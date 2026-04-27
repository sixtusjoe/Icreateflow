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
from services import variation_processor as diversify_svc
from services import caption_variants as caption_svc
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
PAUSE_MANUAL = "manual"


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


async def _user_or_site_setting(database, user_id: int | None, key: str, default: str = "1") -> str:
    """Resolve a clipping toggle. Reads `key` from the artist owner's
    user_settings first; falls back to site_config; finally `default`.

    The three clipping toggles (clip_diversification_enabled,
    clip_caption_variants_enabled, catchup_enabled) used to live in
    site_config (admin-only). They moved to per-user settings so each user
    can configure their own posting behaviour. Old site_config values are
    still honoured as a fallback so existing installs keep working without
    a migration step.
    """
    if user_id:
        try:
            us = await db.get_user_settings(database, user_id)
            v = us.get(key) if us else None
            if v is not None and v != "":
                return v
        except Exception:
            pass
    try:
        cfg = await db.get_site_config(database)
        v = cfg.get(key) if cfg else None
        if v is not None and v != "":
            return v
    except Exception:
        pass
    return default


def _toggle_on(value: str, default_on: bool = True) -> bool:
    """Standard truthy parse for toggle strings: '0', 'false', 'False', '' = off."""
    if value is None:
        return default_on
    return value not in ("0", "false", "False", "")


def _clip_video_source(clip: dict) -> str | None:
    """Return a URL or local path suitable for a posting adapter."""
    if clip.get("source") == "gdrive" and clip.get("gdrive_file_id"):
        return gdrive_svc.direct_download_url(clip["gdrive_file_id"])
    return clip.get("local_path")


async def _pick_next_clip(database, artist_id: int) -> dict | None:
    """Round-robin: least-posted clip, tie-broken by oldest last_posted_at.

    Excludes clips that already have a pending (scheduled/posting) clip_post
    so the planner can't queue the same clip twice in the same batch — and so
    a fresh clip added between two plan slots gets preferred over one already
    sitting in the queue."""
    clips = await database.execute(
        """
        SELECT c.* FROM clips c
        WHERE c.artist_id = ?
          AND NOT EXISTS (
            SELECT 1 FROM clip_posts cp
            WHERE cp.clip_id = c.id
              AND cp.status IN ('scheduled', 'posting')
          )
        ORDER BY c.times_posted ASC,
                 COALESCE(c.last_posted_at, '1970-01-01') ASC,
                 c.id ASC
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
    """True if any clip has no successful post yet — meaning the directory
    isn't actually exhausted. Reads from clip_posts (real post status) instead
    of clips.times_posted so a clip that's merely queued doesn't get counted
    as 'already posted' (that misread is what caused the false-pause and
    stalled the dispatcher)."""
    cur = await database.execute(
        """
        SELECT 1 FROM clips c
        WHERE c.artist_id = ?
          AND NOT EXISTS (
            SELECT 1 FROM clip_posts cp
            WHERE cp.clip_id = c.id AND cp.status = 'posted'
          )
        LIMIT 1
        """,
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
    # Never overwrite a manual pause. The user clicked Pause; only an explicit
    # un-pause click (which clears paused_reason) should resume them — not
    # auto-detection of view-target or directory-exhausted.
    if artist.get("paused_reason") == PAUSE_MANUAL:
        return
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
    """Clear directory_exhausted pause if a fresh unposted clip exists.

    Manual pauses are never auto-cleared — the user has to un-pause from the
    dashboard to resume."""
    artist = await db.get_artist(database, artist_id)
    if not artist:
        return
    if artist.get("paused_reason") == PAUSE_MANUAL:
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

                variations = await db.get_artist_accounts(database, artist["id"])
                if not variations:
                    continue

                # Per-slot dedup: figure out which of today's slot times still
                # need rows. Previously this was per-day ("any row for today?")
                # which meant a deleted future slot couldn't be re-planned and
                # any race-inserted row blocked all future slots from being
                # filled. Per-slot is self-healing.
                all_slots = _today_slots(artist, now_utc)
                # Treat a slot as "filled" when ANY clip_post exists at that
                # exact scheduled_for for this artist. The unique index is
                # per-(account, platform, time, clip), so if at least one row
                # for that slot landed, others should follow via re-runs of
                # the per-platform fanout below — but in practice a successful
                # fanout writes all variations × platforms in one tick.
                day_start = datetime.combine(now_utc.date(), dtime(0, 0))
                day_end = day_start + timedelta(days=1)
                existing = await database.execute(
                    """
                    SELECT DISTINCT scheduled_for FROM clip_posts
                    WHERE artist_id = ? AND scheduled_for IS NOT NULL
                      AND scheduled_for >= ? AND scheduled_for < ?
                    """,
                    (artist["id"], day_start, day_end),
                )
                # scheduled_for is stored as naive UTC; _today_slots returns
                # UTC-aware. Normalise to naive UTC on both sides for the set
                # membership check.
                existing_times = {
                    (r["scheduled_for"] if r["scheduled_for"].tzinfo is None
                     else r["scheduled_for"].astimezone(timezone.utc).replace(tzinfo=None))
                    for r in await existing.fetchall()
                }
                def _naive(d: datetime) -> datetime:
                    return d.astimezone(timezone.utc).replace(tzinfo=None) if d.tzinfo else d
                # Remove already-filled slots; only future or catch-up slots
                # for today get planned.
                missing = [s for s in all_slots if _naive(s) not in existing_times]
                future = [s for s in missing if s > now_utc]
                past_missing = [s for s in missing if s <= now_utc]
                now_naive = now_utc.replace(tzinfo=None)
                # Catch-up gate. When the artist resumes after a gap (manual
                # un-pause OR maybe_resume_on_new_clip from a fresh upload),
                # the planner sees today's already-passed slots as "missed"
                # and inserts a now+30s row to fire them. That surprised the
                # user when an upload triggered an immediate fire instead of
                # waiting for tomorrow's 8am slot — and on resume from a long
                # gap it can fire MULTIPLE missed slots back-to-back.
                #
                # Per-user toggle (artist owner's user_settings) with
                # site_config fallback. Default off.
                _catchup_raw = await _user_or_site_setting(
                    database, artist.get("user_id"), "catchup_enabled", "0"
                )
                catchup_on = _toggle_on(_catchup_raw, default_on=False)
                if catchup_on and past_missing and not any(
                    t > now_naive - timedelta(minutes=2)
                    and t <= now_naive + timedelta(minutes=5)
                    for t in existing_times
                ):
                    future = [now_utc + timedelta(seconds=30)] + future
                slots = future
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
                    # Note: times_posted / last_posted_at are bumped by the
                    # dispatcher on successful post, NOT here at plan time.
                    # Bumping at plan time used to mark queued-but-not-fired
                    # clips as "posted", which falsely tripped
                    # `directory_exhausted` and paused the artist before its
                    # evening slot could fire. The picker exclusion of
                    # already-queued clips (in _pick_next_clip) is what now
                    # prevents the same clip being chosen twice in a single
                    # plan run.
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
        # Stale-claim recovery: if a worker crashed mid-upload (OOM, container
        # restart, network drop) the row stays at status='posting' forever.
        # That permanently excludes the clip from `_pick_next_clip` (which
        # skips clips with pending scheduled/posting rows) and stalls the
        # picker. Anything still 'posting' more than 30 min after its
        # scheduled_for is by definition stuck — flip it back to scheduled so
        # this dispatch tick can re-claim it. 30 min is well above any real
        # upload time (typical < 5 min) so we won't race a legitimate worker.
        await database.execute(
            """
            UPDATE clip_posts SET status = 'scheduled'
            WHERE status = 'posting'
              AND scheduled_for IS NOT NULL
              AND scheduled_for < NOW() - INTERVAL '30 minutes'
            """
        )
        await database.commit()

        # Atomic claim: flip status='scheduled' → 'posting' in a single
        # UPDATE so only one worker ever gets each row. Without this, two
        # gunicorn workers both SELECT, both UPDATE, and the clip gets
        # posted twice per variation.
        cur = await database.execute(
            """
            UPDATE clip_posts SET status = 'posting'
            WHERE id IN (
                SELECT cp.id FROM clip_posts cp
                JOIN artists a ON a.id = cp.artist_id
                WHERE cp.status = 'scheduled' AND cp.scheduled_for IS NOT NULL
                  AND cp.scheduled_for <= NOW()
                  AND a.is_active = TRUE
                  AND a.paused_reason IS NULL
                ORDER BY cp.scheduled_for ASC
                LIMIT 50
                FOR UPDATE OF cp SKIP LOCKED
            )
            RETURNING *
            """
        )
        rows = [dict(r) for r in await cur.fetchall()]
        await database.commit()
        for cp in rows:
            try:
                # Row is already status='posting' thanks to the atomic claim.

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

                # Source resolution. Three paths:
                #   1. Diversification ON: per-(clip, variation, platform)
                #      ffmpeg-rendered file under our verified domain.
                #   2. Diversification OFF + remote source (e.g. GDrive):
                #      passthrough — download once into a local cache, serve
                #      from our verified domain. TikTok requires this; raw
                #      GDrive links fail with `url_ownership_unverified`.
                #   3. Diversification OFF + local source: leave as-is.
                cfg = await db.get_site_config(database)
                public_base = (cfg.get("oauth_redirect_base") or "").rstrip("/")
                # Per-user toggle (artist owner's user_settings) with
                # site_config fallback. Default on.
                _artist_for_toggle = await db.get_artist(database, cp["artist_id"]) if cp.get("artist_id") else None
                _owner_id = dict(_artist_for_toggle).get("user_id") if _artist_for_toggle else None
                _div_raw = await _user_or_site_setting(database, _owner_id, "clip_diversification_enabled", "1")
                diversify_on = _toggle_on(_div_raw)
                if diversify_on and public_base:
                    try:
                        local = await diversify_svc.diversify(
                            source=source,
                            clip_id=clip["id"],
                            variation_id=variation["id"],
                            platform=platform,
                        )
                        source = diversify_svc.public_url_for(local, public_base)
                        # Stamp last-success so admin stats survive cache cleanup.
                        try:
                            await db.set_site_config(
                                database,
                                "last_diversify_at",
                                datetime.now(timezone.utc).isoformat(),
                            )
                        except Exception:
                            pass
                    except Exception as de:
                        # Log but fall back to the raw source so a single bad
                        # diversification doesn't block the post.
                        await db.log_error(
                            database, source=f"scheduler.diversify.{platform}",
                            message=str(de), traceback=traceback.format_exc(),
                            context=f"clip_post_id={cp['id']} clip_id={clip['id']} variation_id={variation['id']}",
                        )
                elif public_base and source.startswith(("http://", "https://")):
                    # Passthrough: wrap remote source in our verified domain
                    # without any ffmpeg work.
                    try:
                        local = await diversify_svc.passthrough_download(
                            source=source, clip_id=clip["id"],
                        )
                        source = diversify_svc.public_url_for(local, public_base)
                    except Exception as pe:
                        await db.log_error(
                            database, source=f"scheduler.passthrough.{platform}",
                            message=str(pe), traceback=traceback.format_exc(),
                            context=f"clip_post_id={cp['id']} clip_id={clip['id']}",
                        )

                adapter = ADAPTERS[platform]
                kwargs = {}
                if platform == "instagram":
                    kwargs["ig_user_id"] = dict(variation).get("instagram_user_id")
                if platform == "facebook":
                    kwargs["page_id"] = dict(variation).get("facebook_user_id")
                if platform == "tiktok":
                    cfg_tt = await db.get_site_config(database)
                    kwargs["privacy_level"] = (cfg_tt.get("tiktok_privacy_level") or "SELF_ONLY").upper()

                # Phase 2: per-(clip, variation, platform) caption paraphrase.
                # Kill switch: site-config `clip_caption_variants_enabled`
                # (default on). Falls back to the raw base caption if
                # disabled, if no API key is configured, or on any error.
                base_caption = dict(clip).get("caption") or ""
                _cap_raw = await _user_or_site_setting(database, _owner_id, "clip_caption_variants_enabled", "1")
                caption_on = _toggle_on(_cap_raw)
                caption_to_post = base_caption
                if caption_on and base_caption:
                    try:
                        caption_to_post = await caption_svc.get_variant(
                            database,
                            clip_id=clip["id"],
                            variation_id=variation["id"],
                            platform=platform,
                            base_caption=base_caption,
                        )
                    except Exception as ce:
                        await db.log_error(
                            database, source=f"scheduler.caption.{platform}",
                            message=str(ce), traceback=traceback.format_exc(),
                            context=f"clip_post_id={cp['id']} clip_id={clip['id']} variation_id={variation['id']}",
                        )
                        caption_to_post = base_caption

                # Stamp what we actually posted for audit/debug.
                try:
                    await db.update_clip_post(database, cp["id"], caption_snapshot=caption_to_post)
                except Exception:
                    pass

                result = await adapter.upload_video(
                    access_token=access_token,
                    video_source=source,
                    caption=caption_to_post,
                    **kwargs,
                )
                await db.update_clip_post(
                    database, cp["id"],
                    status="posted",
                    posted_at=datetime.now(timezone.utc),
                    platform_post_id=result.get("platform_post_id"),
                    error=None,
                )

                # Bump clip stats AFTER a successful post (not at plan time).
                # Bumping at plan time made evaluate_pause think the directory
                # was exhausted while clips were merely queued, which paused
                # the artist and stalled the dispatcher.
                try:
                    if clip:
                        await db.update_clip(
                            database, clip["id"],
                            times_posted=int(dict(clip).get("times_posted") or 0) + 1,
                            last_posted_at=datetime.now(timezone.utc),
                        )
                except Exception:
                    pass

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


#: Default cadence for the view poller, in seconds. Admins can override this
#: live via site_config key ``view_poll_interval_seconds`` — see
#: ``get_view_poll_interval``. Floor is 60s so we don't rate-limit ourselves.
DEFAULT_VIEW_POLL_INTERVAL_SECONDS = 180  # 3 minutes
VIEW_POLL_INTERVAL_SECONDS = DEFAULT_VIEW_POLL_INTERVAL_SECONDS  # legacy alias


async def get_view_poll_interval(database) -> int:
    """Read the live poll cadence from site_config; clamp to [60, 3600]."""
    try:
        cfg = await db.get_site_config(database)
        raw = (cfg or {}).get("view_poll_interval_seconds")
        if raw is None or raw == "":
            return DEFAULT_VIEW_POLL_INTERVAL_SECONDS
        n = int(raw)
        if n < 60:
            return 60
        if n > 3600:
            return 3600
        return n
    except Exception:
        return DEFAULT_VIEW_POLL_INTERVAL_SECONDS


async def poll_views_once() -> None:
    """Refresh view counts for posted rows older than VIEW_POLL_INTERVAL_SECONDS,
    then re-check pause."""
    database = await db.get_db()
    try:
        # The loop interval is the rate limiter. The SQL staleness gate only
        # exists to dedupe within a single tick (so we don't re-poll a row
        # we just refreshed seconds ago via a manual trigger). A small fixed
        # gate of 30s is enough — using the full interval here meant that a
        # tick fired right after a process restart, while rows were still
        # young, would skip the entire batch and force the user to wait out
        # the next sleep. Refresh on every tick; the asyncio.sleep below
        # paces things.
        cur = await database.execute(
            """
            SELECT * FROM clip_posts
            WHERE status = 'posted' AND platform_post_id IS NOT NULL
              AND deleted_at IS NULL
              AND (view_count_updated_at IS NULL
                   OR view_count_updated_at < NOW() - INTERVAL '30 seconds')
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

                # Pre-token check: a TikTok row with a never-resolved
                # publish_id and posted_at > 1h ago is dead regardless of
                # whether the token is still attached. Mark deleted now so
                # variations that disconnected their TT token still get
                # their stale rows cleaned up. Real video_ids fall through
                # to the normal poll path below.
                if platform == "tiktok":
                    from services.posting.tiktok import _is_publish_id
                    pid = cp.get("platform_post_id")
                    posted_at = cp.get("posted_at")
                    if pid and _is_publish_id(pid) and posted_at:
                        if posted_at.tzinfo is None:
                            posted_at = posted_at.replace(tzinfo=timezone.utc)
                        if (datetime.now(timezone.utc) - posted_at).total_seconds() > 3600:
                            now = datetime.now(timezone.utc)
                            await db.update_clip_post(
                                database, cp["id"],
                                view_count_updated_at=now,
                                deleted_at=now,
                            )
                            continue

                access_token = await _fresh_variation_token(database, variation, platform)
                if not access_token:
                    continue
                adapter = ADAPTERS[platform]

                # TikTok publish_id → real video_id upgrade. /post/publish/video/init/
                # returns a publish_id we store when `publicly_available_post_id` is
                # empty at post time. That string isn't valid for /video/query/ —
                # resolve it once, persist the upgrade, then stats land correctly
                # from then on.
                post_id = cp["platform_post_id"]
                if platform == "tiktok":
                    from services.posting.tiktok import _is_publish_id, resolve_video_id
                    if _is_publish_id(post_id):
                        posted_at = cp.get("posted_at")
                        posted_epoch = int(posted_at.timestamp()) if posted_at else None
                        resolved = await resolve_video_id(access_token, post_id, posted_epoch)
                        if resolved and resolved != post_id:
                            await db.update_clip_post(
                                database, cp["id"], platform_post_id=resolved,
                            )
                            post_id = resolved
                        else:
                            # Couldn't resolve. If the row has been a
                            # placeholder for >1 hour, the publish never
                            # finalised on TikTok (upload failure, mod
                            # rejection, deleted-during-publish) — mark it
                            # deleted so it drops from the dashboard count.
                            # Within the first hour, just bump updated_at so
                            # the poller retries on the next cycle.
                            now = datetime.now(timezone.utc)
                            stale = posted_at is not None and (
                                (now - (posted_at if posted_at.tzinfo
                                        else posted_at.replace(tzinfo=timezone.utc))).total_seconds() > 3600
                            )
                            if stale:
                                await db.update_clip_post(
                                    database, cp["id"],
                                    view_count_updated_at=now,
                                    deleted_at=now,
                                )
                            else:
                                await db.update_clip_post(
                                    database, cp["id"],
                                    view_count_updated_at=now,
                                )
                            continue

                views = await adapter.get_view_count(access_token, post_id)
                new_views = int(views or 0)
                prev_views = int(cp.get("view_count") or 0)
                # Never let a real, observed view count regress. Platforms
                # occasionally return a lower number (rate-limit glitch,
                # propagation lag, edge-cache stale read, or a 0 when the
                # post is briefly invisible). Take MAX(prev, new) so the
                # dashboard total only ever climbs.
                if new_views < prev_views:
                    # Small regressions are noise (rate-limit glitch, edge-cache
                    # lag, brief propagation hiccup) — keep the previous count
                    # silently and move on.
                    #
                    # Drop-to-zero from a non-zero count is different: it
                    # almost always means the post was deleted/hidden. We log
                    # it once AND accept the 0, so the next poll has prev=0
                    # and the log doesn't re-fire every cycle (which is what
                    # was flooding the error feed with the same message every
                    # 15 min for the same row).
                    if new_views == 0 and prev_views > 0:
                        await db.log_error(
                            database, source=f"posting.{platform}.views",
                            message=(
                                f"adapter returned 0 views but previous was "
                                f"{prev_views}; post may be deleted/hidden"
                            ),
                            context=(
                                f"clip_post_id={cp['id']} "
                                f"platform_post_id={cp.get('platform_post_id')!r}"
                            ),
                        )
                        # Mark the row deleted so the dashboard counts drop
                        # on the next refresh. view_count=0 also stops the
                        # log from re-firing on the next poll.
                        await db.update_clip_post(
                            database, cp["id"],
                            view_count=0,
                            view_count_updated_at=datetime.now(timezone.utc),
                            deleted_at=datetime.now(timezone.utc),
                        )
                    else:
                        # Generic small regression — keep prev, just bump
                        # updated_at so the poller moves on.
                        await db.update_clip_post(
                            database, cp["id"],
                            view_count_updated_at=datetime.now(timezone.utc),
                        )
                else:
                    # Real, non-regressing view_count. Stamp it. Note: we no
                    # longer auto-clear deleted_at when an alive count comes
                    # back. YouTube's stats endpoint flaps — empty items
                    # (deleted) → real count → empty items — and the
                    # auto-recovery let that flap re-fire the
                    # 'may be deleted' log on every flip. Once a row is
                    # marked deleted, only an explicit admin action should
                    # un-mark it.
                    await db.update_clip_post(
                        database, cp["id"],
                        view_count=new_views,
                        view_count_updated_at=datetime.now(timezone.utc),
                    )
                if cp.get("artist_id"):
                    touched_artists.add(cp["artist_id"])
            except Exception as e:  # noqa: BLE001
                # TikTok stats are scope-locked behind the Display API. If
                # that's why the adapter failed, stamp view_count_updated_at
                # so the poller moves past this row and silently skip — no
                # point logging the same 401 every 15 minutes.
                from services.posting.tiktok import TikTokStatsUnavailable
                if isinstance(e, TikTokStatsUnavailable):
                    try:
                        await db.update_clip_post(
                            database, cp["id"],
                            view_count_updated_at=datetime.now(timezone.utc),
                        )
                    except Exception:
                        pass
                    continue
                # Adapter explicitly told us the post is gone (404/empty
                # items/Object-doesn't-exist). Mark deleted so the dashboard
                # count drops on the next refresh, and log once.
                from services.posting import PostDeletedError
                if isinstance(e, PostDeletedError):
                    try:
                        already_deleted = bool(cp.get("deleted_at"))
                        await db.update_clip_post(
                            database, cp["id"],
                            view_count_updated_at=datetime.now(timezone.utc),
                            deleted_at=datetime.now(timezone.utc),
                        )
                        # Dedupe the log: only the first detection writes.
                        if not already_deleted:
                            await db.log_error(
                                database, source=f"posting.{cp.get('platform')}.views",
                                message=f"post deleted on platform: {str(e)[:200]}",
                                context=f"clip_post_id={cp['id']} platform_post_id={cp.get('platform_post_id')!r}",
                            )
                    except Exception:
                        pass
                    continue
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


async def _poll_views_loop() -> None:
    """View-poll loop with per-iteration cadence lookup from site_config.

    Sleeps in 30-second chunks (re-reading the interval each chunk) so an
    admin lowering the cadence — say 1 hour → 15 min — takes effect within
    ~30s instead of waiting out the previous, longer sleep.
    """
    await asyncio.sleep(10)
    while True:
        try:
            await poll_views_once()
        except Exception:
            traceback.print_exc()
        last_run = datetime.now(timezone.utc)
        while True:
            try:
                database = await db.get_db()
                try:
                    delay = await get_view_poll_interval(database)
                finally:
                    await database.close()
            except Exception:
                delay = DEFAULT_VIEW_POLL_INTERVAL_SECONDS
            elapsed = (datetime.now(timezone.utc) - last_run).total_seconds()
            remaining = delay - elapsed
            if remaining <= 0:
                break
            await asyncio.sleep(min(30, remaining))


async def sweep_clip_caches_once() -> None:
    """Delete stale entries from uploads/variation_renders/ and
    uploads/passthrough_clips/ — anything not accessed in the last
    `cache_ttl_days` days (default 30). Disk usage grows slowly otherwise:
    every (clip × variation × platform) leaves an mp4 behind, plus one
    passthrough per clip. After ~6 months on a busy artist that's gigabytes.
    """
    from pathlib import Path as _P
    import time as _time
    database = await db.get_db()
    try:
        cfg = await db.get_site_config(database)
        try:
            ttl_days = int(cfg.get("cache_ttl_days") or 30)
        except Exception:
            ttl_days = 30
        ttl_days = max(1, min(365, ttl_days))
    finally:
        await database.close()

    cutoff = _time.time() - (ttl_days * 86400)
    deleted = 0
    bytes_freed = 0
    for root in (_P("uploads/variation_renders"), _P("uploads/passthrough_clips")):
        if not root.exists():
            continue
        for f in root.rglob("*"):
            if not f.is_file():
                continue
            try:
                st = f.stat()
                # atime falls back to mtime on filesystems that don't track it.
                # Use the larger of the two so a freshly-uploaded file isn't
                # nuked just because nothing read it yet.
                last_used = max(st.st_atime, st.st_mtime)
                if last_used < cutoff:
                    sz = st.st_size
                    f.unlink(missing_ok=True)
                    deleted += 1
                    bytes_freed += sz
            except Exception:
                pass
    if deleted:
        try:
            database = await db.get_db()
            try:
                await db.log_error(
                    database, source="scheduler.cache_sweep",
                    message=(
                        f"deleted {deleted} cached file(s), freed "
                        f"{bytes_freed / (1024 * 1024):.1f} MB "
                        f"(ttl={ttl_days}d)"
                    ),
                )
            finally:
                await database.close()
        except Exception:
            pass


async def start_background_tasks() -> list[asyncio.Task]:
    """Kick off the four loops. Call from FastAPI lifespan startup."""
    return [
        asyncio.create_task(_loop(plan_slots_once, 300, "plan_slots")),
        asyncio.create_task(_loop(dispatch_due_once, 60, "dispatch")),
        asyncio.create_task(_poll_views_loop()),
        # Daily cache sweep — runs once on boot, then every 24h.
        asyncio.create_task(_loop(sweep_clip_caches_once, 86400, "cache_sweep")),
    ]
