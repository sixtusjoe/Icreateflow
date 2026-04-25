"""One-off: scan an artist's posted clip_posts, ping each platform to verify the
post still exists, and delete the row when the platform confirms it's gone.

Conservative — anything other than a clear "not found" leaves the row alone so
a transient API hiccup can't wipe history.

Usage:  python -m scripts.cleanup_deleted_posts <artist_id>
"""
from __future__ import annotations

import asyncio
import sys
from typing import Optional

import httpx

import database as dbmod
from services.clip_scheduler import _fresh_variation_token


GRAPH = "https://graph.facebook.com/v19.0"


async def youtube_exists(token: str, video_id: str) -> Optional[bool]:
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={"id": video_id, "part": "id"},
            headers={"Authorization": f"Bearer {token}"},
        )
        if r.status_code == 404:
            return False
        if r.status_code >= 400:
            return None  # uncertain
        items = (r.json() or {}).get("items") or []
        return bool(items)


async def tiktok_exists(token: str, video_id: str) -> Optional[bool]:
    # /v2/video/query/ — empty videos array means the video isn't visible to
    # this user (deleted or unpublished). publish_id placeholders return
    # uncertain; skip.
    if "v_pub_url" in (video_id or ""):
        return None
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(
            "https://open.tiktokapis.com/v2/video/query/",
            params={"fields": "id"},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"filters": {"video_ids": [video_id]}},
        )
        if r.status_code >= 400:
            return None
        videos = ((r.json() or {}).get("data") or {}).get("videos") or []
        return any(v.get("id") == video_id for v in videos)


async def meta_exists(token: str, post_id: str) -> Optional[bool]:
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(
            f"{GRAPH}/{post_id}",
            params={"fields": "id", "access_token": token},
        )
        if r.status_code == 404:
            return False
        if r.status_code == 400:
            err = (r.json() or {}).get("error") or {}
            # code 100 subcode 33 = "Object does not exist"
            # code 803         = "Some of the aliases you requested do not exist"
            if err.get("code") in (100, 803) or err.get("error_subcode") == 33:
                return False
            return None
        if r.status_code >= 400:
            return None
        return bool((r.json() or {}).get("id"))


async def check_post(database, cp: dict) -> Optional[bool]:
    variation = await dbmod.get_artist_account(database, cp["artist_account_id"])
    if not variation:
        return None
    platform = cp["platform"]
    token = await _fresh_variation_token(database, variation, platform)
    if not token:
        return None
    pid = cp.get("platform_post_id")
    if not pid:
        return None
    if platform == "youtube":
        return await youtube_exists(token, pid)
    if platform == "tiktok":
        return await tiktok_exists(token, pid)
    if platform in ("instagram", "facebook"):
        return await meta_exists(token, pid)
    return None


async def resolve_tiktok_placeholders(database, artist_id: int) -> None:
    """Upgrade `v_pub_url~...` TikTok publish IDs to real video IDs so the
    LIVE/GONE check can run, and so the dedupe pass can spot duplicates that
    happen to map to the same video."""
    from services.posting.tiktok import _is_publish_id, resolve_video_id
    cur = await database.execute(
        "SELECT * FROM clip_posts WHERE artist_id = ? AND platform = 'tiktok' "
        "AND status = 'posted' AND platform_post_id LIKE 'v_pub_url%'",
        (artist_id,),
    )
    rows = [dict(r) for r in await cur.fetchall()]
    for cp in rows:
        variation = await dbmod.get_artist_account(database, cp["artist_account_id"])
        if not variation:
            continue
        token = await _fresh_variation_token(database, variation, "tiktok")
        if not token:
            continue
        posted = cp.get("posted_at")
        epoch = int(posted.timestamp()) if posted else None
        try:
            real = await resolve_video_id(token, cp["platform_post_id"], epoch)
        except Exception as e:  # noqa: BLE001
            print(f"  resolve cp={cp['id']} ERROR {e}")
            continue
        if real and real != cp["platform_post_id"]:
            await dbmod.update_clip_post(database, cp["id"], platform_post_id=real)
            print(f"  resolved cp={cp['id']} -> {real}")


async def dedupe_by_platform_post_id(database, artist_id: int) -> list[int]:
    """If multiple clip_posts share the same (account, platform, platform_post_id),
    keep the one with highest view_count (real engagement) and drop the rest."""
    cur = await database.execute(
        """
        SELECT artist_account_id, platform, platform_post_id,
               array_agg(id ORDER BY view_count DESC, id ASC) AS ids
        FROM clip_posts
        WHERE artist_id = ? AND status = 'posted' AND platform_post_id IS NOT NULL
        GROUP BY artist_account_id, platform, platform_post_id
        HAVING count(*) > 1
        """,
        (artist_id,),
    )
    drop_ids: list[int] = []
    for r in await cur.fetchall():
        ids = list(r["ids"])
        drop_ids.extend(ids[1:])  # keep first (highest view_count), drop rest
    if drop_ids:
        ph = ",".join("?" * len(drop_ids))
        await database.execute(
            f"DELETE FROM clip_posts WHERE id IN ({ph})", tuple(drop_ids)
        )
        await database.session.commit()
    return drop_ids


async def main(artist_id: int) -> None:
    database = await dbmod.get_db()
    try:
        # 1. resolve any lingering TikTok publish-id placeholders so dedupe
        #    and LIVE/GONE checks can see the real video ids.
        await resolve_tiktok_placeholders(database, artist_id)
        # 2. drop rows that share an exact platform_post_id with another row
        #    (happens when two scheduler instances posted the same clip and
        #    TikTok replied with the same video id for both attempts, or when
        #    publish-id resolution merged two placeholder rows onto one video).
        merged = await dedupe_by_platform_post_id(database, artist_id)
        if merged:
            print(f"merged exact-id duplicates: {merged}")

        cur = await database.execute(
            "SELECT * FROM clip_posts WHERE artist_id = ? AND status = 'posted' "
            "AND platform_post_id IS NOT NULL ORDER BY id",
            (artist_id,),
        )
        rows = [dict(r) for r in await cur.fetchall()]
        print(f"checking {len(rows)} posted rows for artist {artist_id}")
        deleted_ids: list[int] = []
        uncertain: list[int] = []
        live: list[int] = []
        for cp in rows:
            try:
                exists = await check_post(database, cp)
            except Exception as e:  # noqa: BLE001
                print(f"  cp={cp['id']} {cp['platform']:9s} ERROR {e}")
                uncertain.append(cp["id"])
                continue
            tag = "LIVE" if exists is True else ("GONE" if exists is False else "?? ")
            print(f"  cp={cp['id']:4d} {cp['platform']:9s} pid={cp['platform_post_id']:>40s} {tag}")
            if exists is False:
                deleted_ids.append(cp["id"])
            elif exists is None:
                uncertain.append(cp["id"])
            else:
                live.append(cp["id"])
        if deleted_ids:
            ph = ",".join("?" * len(deleted_ids))
            await database.execute(
                f"DELETE FROM clip_posts WHERE id IN ({ph})", tuple(deleted_ids)
            )
            await database.session.commit()
        print()
        print(f"summary: live={len(live)} deleted={len(deleted_ids)} uncertain={len(uncertain)}")
        if deleted_ids:
            print(f"removed clip_post ids: {deleted_ids}")
        if uncertain:
            print(f"left untouched (uncertain): {uncertain}")
    finally:
        await database.close()


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1])))
