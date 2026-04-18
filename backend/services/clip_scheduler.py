"""Clipping auto-post scheduler.

Three background loops:

1. Slot planner — every 5 min. Materialises today's `clip_posts` rows per
   artist (one per variation × 4 platforms × posts_per_day), evenly spread
   across [window_start, window_end] in the artist's local timezone.
   Picks the clip with the lowest `times_posted` + oldest `last_posted_at`
   for each slot (round-robin fairness).

2. Dispatcher — every 60 s. Flips scheduled rows whose `scheduled_for <= NOW()`
   to `posting`, calls the right platform adapter, records the result.

3. View poller — every 15 min. Re-fetches view counts for posted rows whose
   counts haven't been refreshed in the last 15 minutes.

All three loops catch per-item exceptions so a single bad post doesn't kill
the scheduler.
"""
from __future__ import annotations

import asyncio
import traceback
from datetime import datetime, timedelta, date, time as dtime, timezone
from zoneinfo import ZoneInfo

import database as db
from services import gdrive as gdrive_svc
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


async def plan_slots_once() -> None:
    """Ensure today's clip_posts rows exist for every artist."""
    database = await db.get_db()
    try:
        artists = await db.get_artists(database)
        now_utc = datetime.now(timezone.utc)
        for a in artists:
            artist = dict(a)
            # Already materialised today? Check by matching any clip_post scheduled today in UTC.
            check = await database.execute(
                """
                SELECT COUNT(*) AS c FROM clip_posts cp
                JOIN clips c ON cp.clip_id = c.id
                WHERE c.artist_id = ? AND cp.scheduled_for IS NOT NULL
                  AND cp.scheduled_for::date = ?::date
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
            slots = [s for s in slots if s > now_utc]  # skip past slots
            if not slots:
                continue

            for slot in slots:
                clip = await _pick_next_clip(database, artist["id"])
                if not clip:
                    break
                for var in variations:
                    for platform in ("tiktok", "youtube", "instagram", "facebook"):
                        # Only schedule where the variation is connected
                        if not (dict(var).get(f"{platform}_token")):
                            continue
                        await db.create_clip_post(
                            database,
                            clip_id=clip["id"],
                            artist_account_id=var["id"],
                            platform=platform,
                            scheduled_for=slot,
                            status="scheduled",
                        )
                # bump round-robin counter so the next slot picks a different clip
                await db.update_clip(
                    database,
                    clip["id"],
                    times_posted=int(clip.get("times_posted") or 0) + 1,
                    last_posted_at=now_utc,
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
            SELECT * FROM clip_posts
            WHERE status = 'scheduled' AND scheduled_for IS NOT NULL AND scheduled_for <= NOW()
            ORDER BY scheduled_for ASC
            LIMIT 50
            """
        )
        rows = [dict(r) for r in await cur.fetchall()]
        for cp in rows:
            try:
                await db.update_clip_post(database, cp["id"], status="posting")

                clip = await db.get_clip(database, cp["clip_id"])
                variation = await db.get_artist_account(database, cp["artist_account_id"])
                if not clip or not variation:
                    await db.update_clip_post(
                        database, cp["id"], status="failed", error="Clip or variation missing"
                    )
                    continue

                platform = cp["platform"]
                access_token = dict(variation).get(f"{platform}_token")
                if not access_token:
                    await db.update_clip_post(
                        database, cp["id"], status="failed",
                        error=f"{platform} not connected",
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
            except PostingError as e:
                await db.update_clip_post(database, cp["id"], status="failed", error=str(e)[:500])
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                await db.update_clip_post(database, cp["id"], status="failed", error=str(e)[:500])
    except Exception:
        traceback.print_exc()
    finally:
        await database.close()


async def poll_views_once() -> None:
    """Refresh view counts for posted rows older than 15 minutes."""
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
        for cp in rows:
            try:
                variation = await db.get_artist_account(database, cp["artist_account_id"])
                if not variation:
                    continue
                platform = cp["platform"]
                access_token = dict(variation).get(f"{platform}_token")
                if not access_token:
                    continue
                adapter = ADAPTERS[platform]
                views = await adapter.get_view_count(access_token, cp["platform_post_id"])
                await db.update_clip_post(
                    database, cp["id"],
                    view_count=int(views or 0),
                    view_count_updated_at=datetime.now(timezone.utc),
                )
            except Exception:  # noqa: BLE001
                # Swallow so one bad row doesn't stall the loop
                traceback.print_exc()
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
