"""Clipping auto-post scheduler.

Three background loops, each gated by Artist.is_active so paused artists
don't consume any cycles:

1. Slot planner — every 5 min. Materialises today's `clip_posts` rows per
   active artist, evenly spread across [window_start, window_end] in the
   artist's local timezone.

2. Dispatcher — every 60 s. Flips scheduled rows whose `scheduled_for <= NOW()`
   to `posting`, calls the right platform adapter, records the result.
   After each successful post, re-evaluates pause conditions (view target
   reached OR every clip posted at least once) and auto-pauses the artist.

3. View poller — every 15 min. Re-fetches view counts for posted rows whose
   counts haven't been refreshed in the last 15 minutes. Also checks the
   view-target pause condition every tick so target-reached kicks in
   promptly as views arrive.

All three loops catch per-item exceptions and log them via database.log_error
so a single bad post doesn't kill the scheduler, and admins can see what's
going wrong in `/admin → Errors`.
"""
from __future__ import annotations

import asyncio
import traceback
from datetime import datetime, timedelta, date, time as dtime, timezone
from zoneinfo import ZoneInfo

import database as db
from services import gdrive as gdrive_svc
from services import oauth as oauth_svc
from services.posting import PostingError
from services.posting import tiktok as tiktok_adapter
from services.posting import youtube as youtube_adapter
from services.posting import instagram as instagram_adapter
from services.posting import facebook as facebook_adapter


ADAPTERS = {
    "tiktok": tiktok_adapter,
    "youtube": youtube_adapter,
    "instagram": instagram_adapter,
    "facebook": facebook_adapter,
}


PAUSE_TARGET_REACHED = "target_reached"
PAUSE_DIRECTORY_EXHAUSTED = "directory_exhausted"


def _parse_hhmm(s: str, default: dtime) -> dtime:
    try:
        hh, mm = s.split(":")
        return dtime(int(hh), int(mm))
    except Exception:
        return default


def _today_slots(artist: dict, now_utc: datetime) -> list[datetime]:
    """Return the list of scheduled_for datetimes (UTC) for today, evenly spread."""
    tz_name = artist.get("timezone") or "US/Eastern"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("US/Eastern")

    now_local = now_utc.astimezone(tz)
    today_local = now_local.date()
    ws = _parse_hhmm(artist.get("window_start") or "09:00", dtime(9, 0))
    we = _parse_hhmm(artist.get("window_end") or "21:00", dtime(21, 0))
    n = max(1, int(artist.get("posts_per_day") or 1))

    start_dt = datetime.combine(today_local, ws, tzinfo=tz)
    end_dt = datetime.combine(today_local, we, tzinfo=tz)
    total_seconds = max(0, int((end_dt - start_dt).total_seconds()))
    if n == 1:
        return [start_dt.astimezone(timezone.utc)]
    step = total_seconds / (n - 1) if n > 1 else 0
    return [
        (start_dt + timedelta(seconds=i * step)).astimezone(timezone.utc)
        for i in range(n)
    ]


async def _fresh_variation_token(database, variation: dict, platform: str) -> str | None:
    """Return an access token for (variation, platform), refreshing if near expiry.

    Mirrors the Post Now refresh logic but writes back to artist_accounts.
    Returns None when the platform isn't connected.
    """
    v = dict(variation)
    token = v.get(f"{platform}_token")
    if not token:
        return None
    exp = v.get(f"{platform}_expires_at")
    refresh = v.get(f"{platform}_refresh_token")
    needs = False
    if exp:
        try:
            exp_dt = datetime.fromisoformat(str(exp).replace("Z", "+00:00"))
            if exp_dt <= datetime.now(timezone.utc) + timedelta(minutes=2):
                needs = True
        except Exception:
            pass
    if not needs or not refresh:
        return token
    provider = "meta" if platform in ("instagram", "facebook") else platform
    cfg = await db.get_site_config(database)
    cid = cfg.get(f"oauth_{provider}_client_id", "")
    csec = cfg.get(f"oauth_{provider}_client_secret", "")
    if not cid or not csec:
        return token
    try:
        refreshed = await oauth_svc.refresh_access_token(provider, refresh, cid, csec)
    except Exception:
        return token
    new_token = refreshed.get("access_token")
    if not new_token:
        return token
    updates: dict = {f"{platform}_token": new_token}
    if refreshed.get("refresh_token"):
        updates[f"{platform}_refresh_token"] = refreshed["refresh_token"]
    if refreshed.get("expires_in"):
        new_exp = datetime.now(timezone.utc) + timedelta(seconds=int(refreshed["expires_in"]))
        updates[f"{platform}_expires_at"] = new_exp.isoformat()
    try:
        await db.update_artist_account(database, v["id"], **updates)
    except Exception:
        pass
    return new_token


def _clip_video_source(clip: dict) -> str | None:
    """Return a URL or local path suitable for a posting adapter."""
    if clip.get("source") == "gdrive" and clip.get("gdrive_file_id"):
        return gdrive_svc.direct_download_url(clip["gdrive_file_id"])
    return clip.get("local_path")


async def _pick_next_clip(database, artist_id: int) -> dict | None:
    """Round-robin: least-posted clip, tie-broken by oldest last_posted_at."""
    clips = await database.execute(
        """
        SELECT * FROM clips WHERE artist_id = ?
        ORDER BY times_posted ASC, COALESCE(last_posted_at, '1970-01-01') ASC, id ASC
        LIMIT 1
        """,
        (artist_id,),
    )
    row = await clips.fetchone()
    return dict(row) if row else None


async def _artist_views_total(database, artist_id: int) -> int:
    cur = await database.execute(
        "SELECT COALESCE(SUM(view_count), 0) AS v FROM clip_posts WHERE artist_id = ?",
        (artist_id,),
    )
    r = await cur.fetchone()
    return int(r["v"] or 0) if r else 0


async def _has_unposted_clip(database, artist_id: int) -> bool:
    cur = await database.execute(
        "SELECT 1 FROM clips WHERE artist_id = ? AND times_posted = 0 LIMIT 1",
        (artist_id,),
    )
    return bool(await cur.fetchone())


async def _any_clip(database, artist_id: int) -> bool:
    cur = await database.execute(
        "SELECT 1 FROM clips WHERE artist_id = ? LIMIT 1", (artist_id,)
    )
    return bool(await cur.fetchone())


async def evaluate_pause(database, artist: dict) -> None:
    """Check whether the artist should be paused. Mutates DB if so."""
    aid = artist["id"]
    target = artist.get("view_target")
    if target and int(target) > 0:
        views = await _artist_views_total(database, aid)
        if views >= int(target):
            await db.update_artist(database, aid, is_active=False, paused_reason=PAUSE_TARGET_REACHED)
            cid = artist.get("current_campaign_id")
            if cid:
                await db.update_campaign(
                    database, cid, status="ended",
                    ended_at=datetime.now(timezone.utc),
                    views_total=views,
                )
            return

    # Directory exhaustion: every clip has been posted at least once.
    if await _any_clip(database, aid) and not await _has_unposted_clip(database, aid):
        await db.update_artist(database, aid, paused_reason=PAUSE_DIRECTORY_EXHAUSTED)


async def maybe_resume_on_new_clip(database, artist_id: int) -> None:
    """Clear directory_exhausted pause if a fresh unposted clip exists."""
    artist = await db.get_artist(database, artist_id)
    if not artist:
        return
    if artist.get("paused_reason") == PAUSE_DIRECTORY_EXHAUSTED and await _has_unposted_clip(database, artist_id):
        await db.update_artist(database, artist_id, paused_reason=None)


async def plan_slots_once() -> None:
    """Ensure today's clip_posts rows exist for every ACTIVE artist."""
    database = await db.get_db()
    try:
        artists = await db.get_artists(database)
        now_utc = datetime.now(timezone.utc)
        for a in artists:
            artist = dict(a)
            try:
                if not artist.get("is_active"):
                    continue
                if artist.get("paused_reason"):
                    continue
                # Already materialised today?
                check = await database.execute(
                    """
                    SELECT COUNT(*) AS c FROM clip_posts
                    WHERE artist_id = ? AND scheduled_for IS NOT NULL
                      AND scheduled_for::date = ?::date
                    """,
                    (artist["id"], now_utc.date().isoformat()),
                )
                row = await check.fetchone()
                if row and int(row["c"] or 0) > 0:
                    continue

                variations = await db.get_artist_accounts(database, artist["id"])
                if not variations:
                    continue

                slots = _today_slots(artist, now_utc)
                slots = [s for s in slots if s > now_utc]
                if not slots:
                    continue

                campaign_id = artist.get("current_campaign_id")
                for slot in slots:
                    clip = await _pick_next_clip(database, artist["id"])
                    if not clip:
                        break
                    for var in variations:
                        for platform in ("tiktok", "youtube", "instagram", "facebook"):
                            if not dict(var).get(f"{platform}_token"):
                                continue
                            await db.create_clip_post(
                                database,
                                clip_id=clip["id"],
                                artist_account_id=var["id"],
                                platform=platform,
                                scheduled_for=slot,
                                status="scheduled",
                                artist_id=artist["id"],
                                campaign_id=campaign_id,
                                clip_filename=clip.get("filename"),
                                caption_snapshot=clip.get("caption"),
                            )
                    await db.update_clip(
                        database, clip["id"],
                        times_posted=int(clip.get("times_posted") or 0) + 1,
                        last_posted_at=now_utc,
                    )
                await evaluate_pause(database, artist)
            except Exception as e:
                await db.log_error(
                    database, source="scheduler.plan",
                    message=f"artist {artist.get('id')}: {e}",
                    traceback=traceback.format_exc(),
                )
    except Exception as e:
        try:
            await db.log_error(
                database, source="scheduler.plan",
                message=str(e), traceback=traceback.format_exc(),
            )
        except Exception:
            traceback.print_exc()
    finally:
        await database.close()


async def dispatch_due_once() -> None:
    """Post any clip_posts rows whose scheduled_for has passed."""
    database = await db.get_db()
    try:
        cur = await database.execute(
            """
            SELECT cp.* FROM clip_posts cp
            JOIN artists a ON a.id = cp.artist_id
            WHERE cp.status = 'scheduled' AND cp.scheduled_for IS NOT NULL
              AND cp.scheduled_for <= NOW()
              AND a.is_active = TRUE
              AND a.paused_reason IS NULL
            ORDER BY cp.scheduled_for ASC
            LIMIT 50
            """
        )
        rows = [dict(r) for r in await cur.fetchall()]
        for cp in rows:
            try:
                await db.update_clip_post(database, cp["id"], status="posting")

                clip = await db.get_clip(database, cp["clip_id"]) if cp.get("clip_id") else None
                variation = await db.get_artist_account(database, cp["artist_account_id"])
                if not clip or not variation:
                    await db.update_clip_post(
                        database, cp["id"], status="failed", error="Clip or variation missing"
                    )
                    continue

                platform = cp["platform"]
                access_token = await _fresh_variation_token(database, variation, platform)
                if not access_token:
                    err = f"{platform} not connected on variation #{variation['id']}"
                    await db.update_clip_post(database, cp["id"], status="failed", error=err)
                    await db.log_error(
                        database, source=f"scheduler.dispatch.{platform}", message=err,
                    )
                    continue

                source = _clip_video_source(dict(clip))
                if not source:
                    await db.update_clip_post(
                        database, cp["id"], status="failed", error="No video source",
                    )
                    continue

                adapter = ADAPTERS[platform]
                kwargs = {}
                if platform == "instagram":
                    kwargs["ig_user_id"] = dict(variation).get("instagram_user_id")
                if platform == "facebook":
                    kwargs["page_id"] = dict(variation).get("facebook_user_id")
                if platform == "tiktok":
                    cfg_tt = await db.get_site_config(database)
                    kwargs["privacy_level"] = (cfg_tt.get("tiktok_privacy_level") or "SELF_ONLY").upper()
                result = await adapter.upload_video(
                    access_token=access_token,
                    video_source=source,
                    caption=dict(clip).get("caption") or "",
                    **kwargs,
                )
                await db.update_clip_post(
                    database, cp["id"],
                    status="posted",
                    posted_at=datetime.now(timezone.utc),
                    platform_post_id=result.get("platform_post_id"),
                    error=None,
                )

                # Re-evaluate pause after each successful post.
                artist = await db.get_artist(database, cp["artist_id"])
                if artist:
                    await evaluate_pause(database, dict(artist))
            except PostingError as e:
                await db.update_clip_post(database, cp["id"], status="failed", error=str(e)[:500])
                await db.log_error(
                    database, source=f"posting.{cp.get('platform')}",
                    message=str(e), traceback=traceback.format_exc(),
                    context=f"clip_post_id={cp['id']}",
                )
            except Exception as e:  # noqa: BLE001
                await db.update_clip_post(database, cp["id"], status="failed", error=str(e)[:500])
                await db.log_error(
                    database, source=f"scheduler.dispatch.{cp.get('platform')}",
                    message=str(e), traceback=traceback.format_exc(),
                    context=f"clip_post_id={cp['id']}",
                )
    except Exception as e:
        try:
            await db.log_error(
                database, source="scheduler.dispatch",
                message=str(e), traceback=traceback.format_exc(),
            )
        except Exception:
            traceback.print_exc()
    finally:
        await database.close()


async def poll_views_once() -> None:
    """Refresh view counts for posted rows older than 15 minutes, then re-check pause."""
    database = await db.get_db()
    try:
        cur = await database.execute(
            """
            SELECT * FROM clip_posts
            WHERE status = 'posted' AND platform_post_id IS NOT NULL
              AND (view_count_updated_at IS NULL OR view_count_updated_at < NOW() - INTERVAL '15 minutes')
            ORDER BY view_count_updated_at ASC NULLS FIRST
            LIMIT 100
            """
        )
        rows = [dict(r) for r in await cur.fetchall()]
        touched_artists: set[int] = set()
        for cp in rows:
            try:
                variation = await db.get_artist_account(database, cp["artist_account_id"])
                if not variation:
                    continue
                platform = cp["platform"]
                access_token = await _fresh_variation_token(database, variation, platform)
                if not access_token:
                    continue
                adapter = ADAPTERS[platform]
                views = await adapter.get_view_count(access_token, cp["platform_post_id"])
                await db.update_clip_post(
                    database, cp["id"],
                    view_count=int(views or 0),
                    view_count_updated_at=datetime.now(timezone.utc),
                )
                if cp.get("artist_id"):
                    touched_artists.add(cp["artist_id"])
            except Exception as e:  # noqa: BLE001
                await db.log_error(
                    database, source=f"posting.{cp.get('platform')}.views",
                    message=str(e), traceback=traceback.format_exc(),
                    context=f"clip_post_id={cp['id']}",
                )

        for aid in touched_artists:
            artist = await db.get_artist(database, aid)
            if artist and artist.get("is_active") and not artist.get("paused_reason"):
                await evaluate_pause(database, dict(artist))
    except Exception as e:
        try:
            await db.log_error(
                database, source="scheduler.poll_views",
                message=str(e), traceback=traceback.format_exc(),
            )
        except Exception:
            traceback.print_exc()
    finally:
        await database.close()


async def _loop(fn, every_seconds: int, label: str) -> None:
    # Small initial delay so uvicorn startup logs flush first
    await asyncio.sleep(10)
    while True:
        try:
            await fn()
        except Exception:
            traceback.print_exc()
        await asyncio.sleep(every_seconds)


async def start_background_tasks() -> list[asyncio.Task]:
    """Kick off the three loops. Call from FastAPI lifespan startup."""
    return [
        asyncio.create_task(_loop(plan_slots_once, 300, "plan_slots")),
        asyncio.create_task(_loop(dispatch_due_once, 60, "dispatch")),
        asyncio.create_task(_loop(poll_views_once, 900, "poll_views")),
    ]
