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
from pathlib import Path
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
PAUSE_NO_CLIPS = "no_clips"
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
    # Mirror the main.py OAuth callback logic: standalone IG OAuth accounts
    # store only instagram_token (no facebook_token), so they must refresh
    # via the "instagram" provider, not "meta".
    if platform == "facebook":
        provider = "meta"
    elif platform == "instagram":
        provider = "meta" if v.get("facebook_token") else "instagram"
    else:
        provider = platform
    cfg = await db.get_site_config(database)
    cid = cfg.get(f"oauth_{provider}_client_id", "")
    csec = cfg.get(f"oauth_{provider}_client_secret", "")
    if not cid or not csec:
        return token
    try:
        refreshed = await oauth_svc.refresh_access_token(
            provider, refresh, cid, csec, proxy_url=v.get("proxy_url"),
        )
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


async def _user_setting(database, user_id: int | None, key: str, default: str = "1") -> str:
    """Resolve a per-user clipping toggle from user_settings only.

    No site_config fallback by design — each user controls their own
    posting behaviour, and an admin-set site_config row should NOT
    silently override an unset user toggle. If the user has no row,
    return the hard-coded `default`.
    """
    if user_id:
        try:
            us = await db.get_user_settings(database, user_id)
            v = us.get(key) if us else None
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


async def _instagram_public_url(source: str, clip_post_id: int, proxy_url: str | None = None) -> str:
    """Return a guaranteed-public HTTPS URL for an Instagram container.

    Instagram's media processing servers pull the video from the URL we
    supply in the container-create call.  Google Drive download links often
    fail for Meta's CDN IPs (redirects, consent pages, IP throttling), so
    we always proxy the video through our own server:

    - If source is already a local path  → build /files/uploads/<basename>
    - If source is an http/https URL     → download to uploads/ig_proxy_<id>.mp4
                                           then return our own URL for it.

    The temp file is written once per clip_post_id, so retries are
    idempotent.  It is cleaned up after the container is published.
    """
    import httpx as _httpx
    from pathlib import Path as _Path

    # Read base URL from site_config; fall back to production domain.
    try:
        _db = await db.get_db()
        try:
            _cfg = await db.get_site_config(_db)
            _base = (_cfg.get("oauth_redirect_base") or "https://icreateflow.com").rstrip("/")
        finally:
            await _db.close()
    except Exception:
        _base = "https://icreateflow.com"

    uploads_dir = _Path("uploads")
    uploads_dir.mkdir(exist_ok=True)

    if not source.startswith("http"):
        # Local upload — already on our server. Files are served at
        # /api/files/<basename> by the serve_file endpoint (which looks
        # under uploads/, output/, music/ automatically).
        return f"{_base}/api/files/{_Path(source).name}"

    # HTTP(S) source (e.g. Google Drive) — download to a stable temp file
    # in our uploads dir, then serve it through our own /api/files/ endpoint.
    tmp_name = f"ig_proxy_{clip_post_id}.mp4"
    tmp_path = uploads_dir / tmp_name

    if not tmp_path.exists():
        # Download the source video to a raw temp file first.
        raw_path = uploads_dir / f"ig_raw_{clip_post_id}.mp4"
        try:
            if source.startswith("http"):
                async with _httpx.AsyncClient(
                    timeout=120, follow_redirects=True, proxy=proxy_url
                ) as _client:
                    r = await _client.get(source)
                    r.raise_for_status()
                    raw_path.write_bytes(r.content)
            else:
                import shutil as _shutil
                _shutil.copy2(source, raw_path)
        except Exception as _e:
            raise Exception(
                f"Could not download video for Instagram proxy (source={source!r}): {_e}"
            )

        # Transcode to Instagram-compatible specs:
        #   - 30fps  (IG rejects anything above 60fps; 120fps videos always fail)
        #   - H.264 video + AAC audio  (required by Reels API)
        #   - Copy if already within spec (-vf fps=30 only re-timestamps, ffmpeg
        #     still re-encodes so we use libx264 to guarantee compatibility)
        import subprocess as _sp
        try:
            _sp.run(
                [
                    "ffmpeg", "-y", "-i", str(raw_path),
                    "-vf", "fps=30",
                    "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                    "-c:a", "aac", "-b:a", "128k",
                    "-movflags", "+faststart",
                    str(tmp_path),
                ],
                check=True, capture_output=True,
            )
        except _sp.CalledProcessError as _e:
            raise Exception(
                f"ffmpeg transcode failed for Instagram proxy: {_e.stderr.decode()[-300:]}"
            )
        finally:
            try:
                raw_path.unlink()
            except OSError:
                pass

    # /api/files/<name> is served by serve_file() which searches uploads/ automatically.
    return f"{_base}/api/files/{tmp_name}"


async def _pick_next_clip(database, artist_id: int, artist_account_id: int) -> dict | None:
    """Round-robin within ONE variation's scope, biased toward
    globally-unposted clips.

    Scope = clips assigned to this variation (`clips.artist_account_id = var`)
    PLUS shared-pool clips (`artist_account_id IS NULL`). Excludes any clip
    already queued for this variation (status scheduled/posting), so the
    planner can't queue the same clip twice in a row for the same variation
    — and a fresh upload preempts queued ones in the next slot.

    Order:
      1. `_posts_global` ASC — prefer clips no variation has posted yet,
         so a freshly-uploaded Vid11 beats a previously-posted Vid1 even
         though both have 0 per-variation posts. Matches the global
         `directory_exhausted` semantics: until every clip in the pool
         has been posted somewhere on the campaign, the picker keeps
         finding fresh ones.
      2. `_posts_in_var` ASC — per-variation balance once everything has
         been posted globally at least once.
      3. `_last_in_var` ASC NULLS FIRST — variations that haven't posted
         this clip yet jump ahead of ones that posted it long ago.
      4. `c.id` ASC — final stable tie-break.
    """
    clips = await database.execute(
        """
        SELECT c.*,
               COUNT(cp.id) FILTER (WHERE cp.status = 'posted') AS _posts_in_var,
               MAX(cp.posted_at)  FILTER (WHERE cp.status = 'posted') AS _last_in_var,
               (SELECT COUNT(*) FROM clip_posts cp_g
                WHERE cp_g.clip_id = c.id
                  AND cp_g.status = 'posted') AS _posts_global
        FROM clips c
        LEFT JOIN clip_posts cp
          ON cp.clip_id = c.id AND cp.artist_account_id = ?
        WHERE c.artist_id = ?
          AND (c.artist_account_id = ? OR c.artist_account_id IS NULL)
          AND NOT EXISTS (
            SELECT 1 FROM clip_posts cp2
            WHERE cp2.clip_id = c.id
              AND cp2.artist_account_id = ?
              AND cp2.status IN ('scheduled', 'posting')
          )
        GROUP BY c.id
        ORDER BY _posts_global ASC,
                 _posts_in_var ASC,
                 _last_in_var ASC NULLS FIRST,
                 c.id ASC
        LIMIT 1
        """,
        (artist_account_id, artist_id, artist_account_id, artist_account_id),
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


async def _has_unposted_clip_for_variation(
    database, artist_id: int, artist_account_id: int
) -> bool:
    """True if this variation has any in-scope clip that has never been
    posted by ANY variation. "Posted" is global — once a clip has fired
    once on the campaign, it counts toward "directory used up." That
    matches the user-facing notion: when every video in the directory
    has gone out at least once, the campaign is done.
    """
    cur = await database.execute(
        """
        SELECT 1 FROM clips c
        WHERE c.artist_id = ?
          AND (c.artist_account_id = ? OR c.artist_account_id IS NULL)
          AND NOT EXISTS (
            SELECT 1 FROM clip_posts cp
            WHERE cp.clip_id = c.id
              AND cp.status = 'posted'
          )
        LIMIT 1
        """,
        (artist_id, artist_account_id),
    )
    return bool(await cur.fetchone())


async def _any_clip_for_variation(
    database, artist_id: int, artist_account_id: int
) -> bool:
    cur = await database.execute(
        """
        SELECT 1 FROM clips
        WHERE artist_id = ?
          AND (artist_account_id = ? OR artist_account_id IS NULL)
        LIMIT 1
        """,
        (artist_id, artist_account_id),
    )
    return bool(await cur.fetchone())


async def _any_clip(database, artist_id: int) -> bool:
    cur = await database.execute(
        "SELECT 1 FROM clips WHERE artist_id = ? LIMIT 1", (artist_id,)
    )
    return bool(await cur.fetchone())


async def evaluate_variation_pause(database, variation: dict) -> None:
    """Set/clear the variation's `paused_reason`.

    Three auto states:
      - directory_exhausted: variation has clips in scope and every one
        has already been posted (globally). Pool is used up.
      - no_clips: variation has nothing in scope (no per-variation folder,
        no shared-pool clips). Without this, an empty variation sat
        silently as "Running" while never posting.
      - None: a postable clip exists.

    Never overwrites a manual pause."""
    var_id = variation["id"]
    artist_id = variation["artist_id"]
    current = (variation.get("paused_reason") or None)
    if current == PAUSE_MANUAL:
        return
    has_any = await _any_clip_for_variation(database, artist_id, var_id)
    if not has_any:
        target = PAUSE_NO_CLIPS
    else:
        has_unposted = await _has_unposted_clip_for_variation(database, artist_id, var_id)
        target = None if has_unposted else PAUSE_DIRECTORY_EXHAUSTED
    if current != target:
        await db.update_artist_account(database, var_id, paused_reason=target)
        # When a variation becomes paused, cancel any future scheduled slots
        # immediately so they don't lapse and clutter the failed-posts log.
        if target is not None:
            await database.execute(
                """
                UPDATE clip_posts
                SET status = 'failed',
                    error  = 'Slot lapsed while artist/variation was paused — re-schedule via new clip or manual resume'
                WHERE status = 'scheduled'
                  AND artist_account_id = ?
                  AND scheduled_for > NOW()
                """,
                (var_id,),
            )
            await database.commit()


async def evaluate_pause(database, artist: dict) -> None:
    """Check whether the artist should be paused. Mutates DB if so.

    Two artist-wide pause causes survive here:
    1. `target_reached` — view target hit.
    2. `directory_exhausted` — only applied at the artist level when EVERY
       variation is also exhausted (used for backwards-compat dashboard
       rendering; per-variation pause is the new source of truth)."""
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

    # Per-variation evaluation, then artist-wide rollup.
    variations = await db.get_artist_accounts(database, aid)
    if not variations:
        return
    for v in variations:
        await evaluate_variation_pause(database, dict(v))
    # Re-fetch (paused_reason was just mutated).
    variations = [dict(v) for v in await db.get_artist_accounts(database, aid)]
    # Roll up to artist-level pause when no variation can post anything:
    # every variation is either out of new clips (directory_exhausted) or
    # has no clips at all (no_clips). The artist-level reason is
    # directory_exhausted so the existing dashboard chip / resume flow
    # keeps working uniformly.
    blocking_reasons = {PAUSE_DIRECTORY_EXHAUSTED, PAUSE_NO_CLIPS}
    all_blocked = all(v.get("paused_reason") in blocking_reasons for v in variations)
    if all_blocked and await _any_clip(database, aid):
        if artist.get("paused_reason") != PAUSE_DIRECTORY_EXHAUSTED:
            await db.update_artist(database, aid, paused_reason=PAUSE_DIRECTORY_EXHAUSTED)
    elif artist.get("paused_reason") == PAUSE_DIRECTORY_EXHAUSTED:
        # Some variation is no longer exhausted — clear the artist roll-up.
        await db.update_artist(database, aid, paused_reason=None)


async def maybe_resume_on_new_clip(
    database, artist_id: int, artist_account_id: int | None = None
) -> None:
    """Clear directory_exhausted pause if a fresh unposted clip exists.

    `artist_account_id`:
      - None or NULL clip → re-evaluate every variation (shared-pool addition
        unblocks all of them).
      - Specific variation → only re-evaluate that one.

    Manual pauses are never auto-cleared — the user has to un-pause from the
    dashboard to resume."""
    artist = await db.get_artist(database, artist_id)
    if not artist:
        return
    if artist.get("paused_reason") == PAUSE_MANUAL:
        return
    if artist_account_id is not None:
        v = await db.get_artist_account(database, artist_account_id)
        if v:
            await evaluate_variation_pause(database, dict(v))
    else:
        for v in await db.get_artist_accounts(database, artist_id):
            await evaluate_variation_pause(database, dict(v))
    # Roll the artist-level pause up after per-variation eval.
    artist = await db.get_artist(database, artist_id)
    if artist:
        await evaluate_pause(database, dict(artist))


async def catchup_today_once(database, artist_id: int) -> int:
    """One-shot recovery for missed slots today.

    Plans a single now+30s clip_post for the given artist, distributing
    across every connected, non-paused variation × platform — same shape
    as a normal slot insert from `plan_slots_once`. Returns the number of
    rows inserted. Used by the dashboard "Catch up missed slots" button so
    the user can opt in to recovering today's drops without flipping the
    catchup_enabled toggle on globally.
    """
    artist = await db.get_artist(database, artist_id)
    if not artist:
        return 0
    artist = dict(artist)
    if not artist.get("is_active") or artist.get("paused_reason"):
        return 0
    variations = await db.get_artist_accounts(database, artist_id)
    if not variations:
        return 0
    slot = datetime.now(timezone.utc) + timedelta(seconds=30)
    campaign_id = artist.get("current_campaign_id")
    inserted = 0
    for var in variations:
        var_d = dict(var)
        if var_d.get("paused_reason") in (
            PAUSE_DIRECTORY_EXHAUSTED, PAUSE_NO_CLIPS, PAUSE_MANUAL,
        ):
            continue
        clip = await _pick_next_clip(database, artist_id, var_d["id"])
        if not clip:
            continue
        for platform in ("tiktok", "youtube", "instagram", "facebook"):
            if not var_d.get(f"{platform}_token"):
                continue
            await db.create_clip_post(
                database,
                clip_id=clip["id"],
                artist_account_id=var_d["id"],
                platform=platform,
                scheduled_for=slot,
                status="scheduled",
                artist_id=artist_id,
                campaign_id=campaign_id,
                clip_filename=clip.get("filename"),
                caption_snapshot=clip.get("caption"),
            )
            inserted += 1
    return inserted


async def plan_slots_once() -> None:
    """Ensure today's clip_posts rows exist for every ACTIVE artist."""
    database = await db.get_db()
    try:
        # --- Integrity sweep: reassign stale scheduled slots in place ---
        # A stale slot is a scheduled row whose assigned clip has already been
        # posted globally AND the variation still has unposted clips available.
        # Rather than cancelling (which misses the post if it fires soon), we
        # UPDATE the slot's clip_id to the best available unposted clip using
        # _pick_next_clip. Only if no replacement clip is found is the slot
        # cancelled. Uses the same subquery logic as
        # _has_unposted_clip_for_variation() to avoid semantic drift.
        try:
            stale_cur = await database.execute(
                """
                SELECT cp.id, cp.artist_account_id, aa.artist_id
                FROM clip_posts cp
                JOIN artist_accounts aa ON aa.id = cp.artist_account_id
                WHERE cp.status = 'scheduled'
                  AND EXISTS (
                      SELECT 1 FROM clip_posts cp2
                      WHERE cp2.clip_id = cp.clip_id
                        AND cp2.status = 'posted'
                  )
                  AND EXISTS (
                      SELECT 1 FROM clips c
                      WHERE c.artist_id = aa.artist_id
                        AND (c.artist_account_id = cp.artist_account_id OR c.artist_account_id IS NULL)
                        AND NOT EXISTS (
                            SELECT 1 FROM clip_posts cp3
                            WHERE cp3.clip_id = c.id
                              AND cp3.status = 'posted'
                        )
                  )
                """
            )
            stale_rows = await stale_cur.fetchall()
            reassigned = 0
            for row in stale_rows:
                sid = row["id"]
                var_id = row["artist_account_id"]
                art_id = row["artist_id"]
                # Temporarily exclude this slot's clip from the pick so
                # _pick_next_clip finds the correct unposted clip
                replacement = await _pick_next_clip(database, art_id, var_id)
                if replacement:
                    await database.execute(
                        "UPDATE clip_posts SET clip_id = ?, clip_filename = ? WHERE id = ? AND status = 'scheduled'",
                        (replacement["id"], replacement.get("filename"), sid),
                    )
                    reassigned += 1
                # If no replacement found, leave the slot as-is;
                # evaluate_variation_pause will handle exhaustion on next tick.
            if reassigned:
                await database.commit()
        except Exception:
            pass  # Never let the sweep block the planner
        # --- End integrity sweep ---

        artists = await db.get_artists(database)
        now_utc = datetime.now(timezone.utc)
        for a in artists:
            artist = dict(a)
            try:
                # Per-variation pause flags get refreshed every tick regardless
                # of artist-level pause state. Without this, once the artist is
                # paused (manual, target_reached, or rolled-up directory_exhausted),
                # `evaluate_pause` stops running and any variation that becomes
                # exhausted afterwards stays flagged "Running" on the dashboard
                # while its clip pool is actually empty. The function is a no-op
                # on PAUSE_MANUAL variations and only writes when the target
                # state differs from the current one, so it's safe to call
                # unconditionally.
                try:
                    for v in await db.get_artist_accounts(database, artist["id"]):
                        await evaluate_variation_pause(database, dict(v))
                except Exception:
                    await db.log_error(
                        database, source="scheduler.evaluate_variation_pause",
                        message="failed to refresh per-variation pause flags",
                        traceback=traceback.format_exc(),
                        context=f"artist_id={artist['id']}",
                    )

                if not artist.get("is_active"):
                    continue
                if artist.get("paused_reason"):
                    continue

                variations = await db.get_artist_accounts(database, artist["id"])
                if not variations:
                    continue

                # Re-evaluate pause state on every planner tick. Without this,
                # an artist whose directory has gone fully exhausted between
                # ticks stays `is_active=true` because the only other places
                # evaluate_pause runs (post success, view poll) require a
                # post or a poll to fire — neither happens on an exhausted
                # campaign. Run BEFORE the slot computation so the early
                # `if not slots: continue` below can't skip the eval.
                await evaluate_pause(database, dict(artist))
                # Re-fetch: evaluate_pause may have just paused the artist.
                fresh = await db.get_artist(database, artist["id"])
                if fresh and dict(fresh).get("paused_reason"):
                    continue
                if fresh:
                    artist = dict(fresh)

                all_slots = _today_slots(artist, now_utc)
                # Only plan future slots.
                def _naive(d: datetime) -> datetime:
                    return d.astimezone(timezone.utc).replace(tzinfo=None) if d.tzinfo else d

                future_slots = [s for s in all_slots if s > now_utc]
                if not future_slots:
                    continue

                day_start = datetime.combine(now_utc.date(), dtime(0, 0))
                day_end = day_start + timedelta(days=1)

                # Per-variation dedup: for each (variation, slot_time) pair check
                # independently whether a row already exists. This allows a variation
                # that gained new clips after the initial plan to still get a slot
                # at times that were already filled by other variations.
                existing_cur = await database.execute(
                    """
                    SELECT artist_account_id,
                           scheduled_for
                    FROM clip_posts
                    WHERE artist_id = ? AND scheduled_for IS NOT NULL
                      AND scheduled_for >= ? AND scheduled_for < ?
                      AND status IN ('scheduled','posting','posted')
                    """,
                    (artist["id"], day_start, day_end),
                )
                filled: set[tuple] = set()
                for r in await existing_cur.fetchall():
                    sf = r["scheduled_for"]
                    sf_naive = sf if sf.tzinfo is None else sf.astimezone(timezone.utc).replace(tzinfo=None)
                    filled.add((r["artist_account_id"], sf_naive))

                campaign_id = artist.get("current_campaign_id")
                for slot in future_slots:
                    slot_naive = _naive(slot)
                    # Per-variation picker: each variation pulls from its own
                    # folder + the shared pool, so two variations on the same
                    # slot can post different clips. Skip variations that hit
                    # directory_exhausted independently.
                    any_planned = False
                    for var in variations:
                        var_d = dict(var)
                        if var_d.get("paused_reason") in (
                            PAUSE_DIRECTORY_EXHAUSTED, PAUSE_NO_CLIPS, PAUSE_MANUAL,
                        ):
                            continue
                        # Skip if this variation already has a row at this slot time
                        if (var_d["id"], slot_naive) in filled:
                            any_planned = True  # counts as planned
                            continue
                        clip = await _pick_next_clip(database, artist["id"], var_d["id"])
                        if not clip:
                            continue
                        any_planned = True
                        for platform in ("tiktok", "youtube", "instagram", "facebook"):
                            if not var_d.get(f"{platform}_token"):
                                continue
                            await db.create_clip_post(
                                database,
                                clip_id=clip["id"],
                                artist_account_id=var_d["id"],
                                platform=platform,
                                scheduled_for=slot,
                                status="scheduled",
                                artist_id=artist["id"],
                                campaign_id=campaign_id,
                                clip_filename=clip.get("filename"),
                                caption_snapshot=clip.get("caption"),
                            )
                            filled.add((var_d["id"], slot_naive))
                    if not any_planned:
                        # No variation has a postable clip — stop planning.
                        break
                    # Note: times_posted / last_posted_at are bumped by the
                    # dispatcher on successful post, NOT here at plan time.
                    # Bumping at plan time used to mark queued-but-not-fired
                    # clips as "posted", which falsely tripped
                    # `directory_exhausted` and paused the artist before its
                    # evening slot could fire. The picker exclusion of
                    # already-queued clips (in _pick_next_clip) is what now
                    # prevents the same clip being chosen twice in a single
                    # plan run.
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

        # Lapsed-slot cleanup: when an artist or variation becomes paused
        # AFTER a slot was already scheduled, the dispatcher's paused_reason
        # filter prevents it from ever running — but the row stays at
        # status='scheduled' indefinitely. This causes the dashboard "Next
        # slot" to show a stale past date that never advances and confuses
        # operators. Cancel any scheduled row whose scheduled_for is more than
        # 6 hours old and whose artist or variation is currently paused.
        # 6 h gives a comfortable grace window for short pauses that clear
        # before the slot becomes truly stale.
        await database.execute(
            """
            UPDATE clip_posts
            SET status = 'failed',
                error  = 'Slot lapsed while artist/variation was paused — re-schedule via new clip or manual resume'
            WHERE status = 'scheduled'
              AND scheduled_for IS NOT NULL
              AND scheduled_for < NOW() - INTERVAL '6 hours'
              AND (
                  artist_id IN (SELECT id FROM artists WHERE paused_reason IS NOT NULL)
                  OR artist_account_id IN (
                      SELECT id FROM artist_accounts WHERE paused_reason IS NOT NULL
                  )
              )
            """
        )
        await database.commit()

        # Auto-cleanup: delete failed clip_posts older than 24 hours so
        # the failure queue doesn't grow unboundedly. Posts that failed more
        # than a day ago are stale and not retryable via the UI.
        await database.execute(
            """
            DELETE FROM clip_posts
            WHERE status = 'failed'
              AND scheduled_for < NOW() - INTERVAL '24 hours'
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
                LEFT JOIN artist_accounts aa ON aa.id = cp.artist_account_id
                WHERE cp.status = 'scheduled' AND cp.scheduled_for IS NOT NULL
                  AND cp.scheduled_for <= NOW()
                  AND a.is_active = TRUE
                  AND (cp.force_inbox = TRUE OR a.paused_reason IS NULL OR a.paused_reason = '')
                  AND (cp.force_inbox = TRUE OR aa.id IS NULL OR aa.paused_reason IS NULL OR aa.paused_reason = '')
                ORDER BY cp.scheduled_for ASC
                LIMIT 50
                FOR UPDATE OF cp SKIP LOCKED
            )
            RETURNING *
            """
        )
        rows = [dict(r) for r in await cur.fetchall()]
        await database.commit()
        # Accumulate per-post outcomes so we can send one result email per artist.
        _dispatch_results: list[dict] = []
        # Track which clip IDs have had times_posted incremented this tick so
        # a clip posted across 4 platforms only counts as 1 post, not 4.
        _incremented_clip_ids: set[int] = set()
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

                # --- Pre-dispatch stale-slot guard ---
                # If this clip was already posted on THIS SAME PLATFORM more
                # than 30 minutes ago AND the variation still has unposted clips,
                # this slot was planned against stale state — fail it so the
                # planner picks a fresh clip on the next tick.
                #
                # IMPORTANT: the check is platform-scoped. A clip successfully
                # posted to TikTok/YouTube/Facebook does NOT make the Instagram
                # slot stale — those are independent platform queues. Checking
                # cross-platform was causing user-retried Instagram posts to be
                # incorrectly killed because sibling platforms had already posted
                # the same clip in the same batch.
                platform = cp["platform"]
                _posted_cur = await database.execute(
                    "SELECT COUNT(*) AS cnt FROM clip_posts"
                    " WHERE clip_id = ? AND platform = ? AND status = 'posted' AND deleted_at IS NULL"
                    " AND posted_at < NOW() - INTERVAL '30 minutes'",
                    (clip["id"], platform),
                )
                _posted_row = await _posted_cur.fetchone()
                if _posted_row and _posted_row["cnt"] > 0:
                    _has_unposted = await _has_unposted_clip_for_variation(
                        database, dict(variation)["artist_id"], dict(variation)["id"]
                    )
                    if _has_unposted:
                        await db.update_clip_post(
                            database, cp["id"], status="failed",
                            error="Stale slot — clip already posted globally; a fresh slot will be planned",
                        )
                        continue
                # --- End stale-slot guard ---

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

                # Duplicate-post guard: if this account+platform posted
                # successfully within the last 30 minutes (e.g. brand "Post
                # Now" fired at the same time as the scheduler), skip this
                # slot and requeue 1 hour out rather than double-posting.
                # TikTok and IG detect identical content across rapid posts
                # and silently delete both copies.
                _dup_cur = await database.execute(
                    "SELECT id FROM clip_posts "
                    "WHERE artist_account_id = ? AND platform = ? "
                    "  AND status = 'posted' "
                    "  AND clip_id IS NOT NULL "
                    "  AND posted_at > NOW() - INTERVAL '30 minutes' "
                    "LIMIT 1",
                    (cp["artist_account_id"], platform),
                )
                _recent = await _dup_cur.fetchone()
                if _recent:
                    _requeue_at = datetime.now(timezone.utc) + timedelta(hours=1)
                    await db.update_clip_post(
                        database, cp["id"],
                        status="scheduled",
                        scheduled_for=_requeue_at,
                    )
                    await db.log_error(
                        database, source="scheduler.collision_guard",
                        message=(
                            f"Skipped clip_post {cp['id']} ({platform}) — "
                            f"same account (id={cp['artist_account_id']}) already posted "
                            f"id={dict(_recent)['id']} within the last 30 min. "
                            f"Requeued for {_requeue_at.isoformat()}."
                        ),
                        context=f"clip_post_id={cp['id']} artist_account_id={cp['artist_account_id']}",
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
                # Per-user toggle (artist owner's user_settings only, no
                # site_config fallback). Default on if the user has no row.
                _artist_for_toggle = await db.get_artist(database, cp["artist_id"]) if cp.get("artist_id") else None
                _owner_id = dict(_artist_for_toggle).get("user_id") if _artist_for_toggle else None
                _div_raw = await _user_setting(database, _owner_id, "clip_diversification_enabled", "1")
                diversify_on = _toggle_on(_div_raw)
                if diversify_on and public_base:
                    try:
                        local = await diversify_svc.diversify(
                            source=source,
                            clip_id=clip["id"],
                            variation_id=variation["id"],
                            platform=platform,
                        )
                        # Per-variation seed → per-account remux of the
                        # diversified .mp4 served to the platform.
                        source = diversify_svc.public_url_for(
                            local, public_base, account_seed=variation["id"],
                        )
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
                        source = diversify_svc.public_url_for(
                            local, public_base, account_seed=variation["id"],
                        )
                    except Exception as pe:
                        await db.log_error(
                            database, source=f"scheduler.passthrough.{platform}",
                            message=str(pe), traceback=traceback.format_exc(),
                            context=f"clip_post_id={cp['id']} clip_id={clip['id']}",
                        )
                        # Don't fall through with a raw GDrive URL.
                        # TikTok rejects unverified domains
                        # (`url_ownership_unverified`); other platforms
                        # may accept it but produce inconsistent results.
                        await db.update_clip_post(
                            database, cp["id"], status="failed",
                            error=f"passthrough failed: {pe}",
                        )
                        continue
                elif public_base and not source.startswith(("http://", "https://")):
                    # Diversification OFF + local source. Previously the raw
                    # filesystem path went straight to the adapter — only
                    # YouTube/Facebook accepted it (TikTok and Instagram
                    # require URL sources). Now wrap it via /api/files/ with
                    # the per-account `?for=` knob so:
                    #   - TikTok/IG can use this path at all (URL-based);
                    #   - YT/FB still work (their _fetch_bytes hits our URL);
                    #   - the file gets the per-account container-metadata
                    #     remux even though pixel-level diversification is
                    #     turned off (cheap, no quality loss, breaks the
                    #     identical-bytes-across-accounts cluster).
                    try:
                        source = diversify_svc.public_url_for(
                            Path(source), public_base, account_seed=variation["id"],
                        )
                    except Exception as we:
                        await db.log_error(
                            database, source=f"scheduler.localwrap.{platform}",
                            message=str(we), traceback=traceback.format_exc(),
                            context=f"clip_post_id={cp['id']} clip_id={clip['id']} variation_id={variation['id']}",
                        )
                        # Fall through with raw local path; YT/FB will still
                        # work, TikTok/IG will fail at the adapter.

                # Defense in depth: TikTok will reject any URL not under
                # our verified domain. If neither diversify nor passthrough
                # rewrote `source`, refuse to call the adapter rather than
                # log `url_ownership_unverified` after the fact.
                if platform == "tiktok" and source.startswith(("http://", "https://")):
                    if not public_base or not source.startswith(public_base):
                        err = "tiktok requires verified-domain source (passthrough/diversify off or misconfigured)"
                        await db.update_clip_post(
                            database, cp["id"], status="failed", error=err,
                        )
                        await db.log_error(
                            database, source="scheduler.dispatch.tiktok",
                            message=err,
                            context=f"clip_post_id={cp['id']} source={source}",
                        )
                        continue

                adapter = ADAPTERS[platform]
                kwargs = {}
                # Per-variation residential proxy. None/empty → posts go
                # direct (current behavior); a non-empty string is passed
                # straight to httpx so all platform calls for this variation
                # share one exit IP.
                _proxy = dict(variation).get("proxy_url") or None
                if _proxy:
                    kwargs["proxy_url"] = _proxy
                if platform == "instagram":
                    kwargs["ig_user_id"] = dict(variation).get("instagram_user_id")
                if platform == "facebook":
                    kwargs["page_id"] = dict(variation).get("facebook_user_id")
                if platform == "tiktok":
                    # TikTok per-variation settings live on the artist_accounts
                    # row. User picks them on the variation card; dispatcher
                    # reads them here. No site_config fallback — TikTok
                    # forbids any global default value for privacy.
                    var_d = dict(variation)
                    # force_inbox on the clip_post row overrides variation setting —
                    # set by retry-as-draft so a cap-error post goes to inbox
                    # immediately rather than waiting 6 hours.
                    if cp.get("force_inbox") or var_d.get("tiktok_post_as_draft"):
                        kwargs["post_mode"] = "INBOX"
                    else:
                        privacy = var_d.get("tiktok_privacy_level")
                        if not privacy:
                            err = (
                                "TikTok privacy not set for this variation. "
                                "Open the variation card → expand TikTok "
                                "settings → pick a privacy level (or enable "
                                "Post as draft)."
                            )
                            await db.update_clip_post(
                                database, cp["id"], status="failed", error=err,
                            )
                            await db.log_error(
                                database, source="scheduler.dispatch.tiktok",
                                message=err,
                                context=f"clip_post_id={cp['id']} variation_id={var_d['id']}",
                            )
                            continue
                        branded = bool(var_d.get("tiktok_disclose_branded_content"))
                        if branded and not var_d.get("tiktok_consent_at"):
                            err = (
                                "TikTok branded content selected without "
                                "saving the music usage acknowledgement. "
                                "Re-open variation TikTok settings and Save."
                            )
                            await db.update_clip_post(
                                database, cp["id"], status="failed", error=err,
                            )
                            await db.log_error(
                                database, source="scheduler.dispatch.tiktok",
                                message=err,
                                context=f"clip_post_id={cp['id']} variation_id={var_d['id']}",
                            )
                            continue
                        kwargs.update({
                            "post_mode": "DIRECT_POST",
                            "privacy_level": privacy.upper(),
                            "disable_comment": not bool(var_d.get("tiktok_allow_comment")),
                            "disable_duet":    not bool(var_d.get("tiktok_allow_duet")),
                            "disable_stitch":  not bool(var_d.get("tiktok_allow_stitch")),
                            "brand_content_toggle": branded,
                            "brand_organic_toggle": bool(var_d.get("tiktok_disclose_your_brand")),
                        })

                # Phase 2: per-(clip, variation, platform) caption paraphrase.
                # Per-user toggle: user_settings.clip_caption_variants_enabled
                # (default on, no site_config fallback). Falls back to the
                # raw base caption if disabled, if no API key is configured,
                # or on any error.
                base_caption = dict(clip).get("caption") or ""
                _cap_raw = await _user_setting(database, _owner_id, "clip_caption_variants_enabled", "1")
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
                            user_id=_owner_id,
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

                # Instagram requires a publicly-accessible HTTPS URL that
                # Meta's CDN servers can fetch directly.  Google Drive
                # download URLs are unreliable for this — Google may serve
                # redirects, consent pages, or throttle Meta's IPs, leaving
                # the IG container stuck in IN_PROGRESS until our poller
                # times out.  Serve the video through our own server instead.
                _ig_proxy_path: str | None = None
                post_source = source
                if platform == "instagram":
                    post_source = await _instagram_public_url(
                        source, cp["id"],
                        proxy_url=dict(variation).get("proxy_url") or None,
                    )
                    # Track temp file path for cleanup after publish.
                    if "ig_proxy_" in post_source:
                        from pathlib import Path as _P
                        _ig_proxy_path = str(_P("uploads") / f"ig_proxy_{cp['id']}.mp4")

                result = await adapter.upload_video(
                    access_token=access_token,
                    video_source=post_source,
                    caption=caption_to_post,
                    **kwargs,
                )

                # Clean up the Instagram proxy temp file now that the
                # container has been published successfully.
                if _ig_proxy_path:
                    try:
                        import os as _os
                        _os.remove(_ig_proxy_path)
                    except OSError:
                        pass
                # Stamp posted_as_draft when TikTok inbox/MEDIA_UPLOAD was
                # used so the view poller skips this row (drafts have no
                # public stats until the user publishes from their app)
                # and the dashboard renders a "draft" pill.
                _draft = bool(result.get("draft"))
                # Defense-in-depth: if a model column hasn't been migrated
                # onto the live DB (e.g. service running pre-migration code),
                # SQLAlchemy raises "Unconsumed column names: <col>" and the
                # whole bookkeeping update fails. The platform already has
                # the upload at this point, so we can't lose the row — fall
                # back to the minimum set of columns that's been stable for
                # ages, log the drift, and move on.
                _post_update = dict(
                    status="posted",
                    posted_at=datetime.now(timezone.utc),
                    platform_post_id=result.get("platform_post_id"),
                    error=None,
                    posted_as_draft=_draft,
                    force_inbox=False,  # clear the one-shot override after use
                )
                try:
                    await db.update_clip_post(database, cp["id"], **_post_update)
                except Exception as _upd_err:
                    msg = str(_upd_err)
                    if "Unconsumed column names" in msg:
                        try:
                            await db.log_error(
                                database, source="scheduler.dispatch.schema_drift",
                                message=f"post-success UPDATE rejected: {msg[:200]}",
                                context=f"clip_post_id={cp['id']} platform={cp.get('platform')}",
                            )
                        except Exception:
                            pass
                        _post_update.pop("posted_as_draft", None)
                        await db.update_clip_post(database, cp["id"], **_post_update)
                    else:
                        raise

                # Race-condition cleanup: discovery may have inserted a
                # NULL-clip row for this same video while the platform API
                # call was in flight (discovery sees no platform_post_id yet,
                # queries TikTok/IG, and finds the newly-uploaded video).
                # Soft-delete any such duplicates now that we have the real
                # platform_post_id — prevents the same post counting twice.
                _ppid = result.get("platform_post_id")
                if _ppid and not _draft:
                    try:
                        await database.execute(
                            "UPDATE clip_posts SET deleted_at = NOW(), view_count = 0 "
                            "WHERE artist_account_id = ? AND platform = ? "
                            "  AND platform_post_id = ? "
                            "  AND clip_id IS NULL "
                            "  AND deleted_at IS NULL "
                            "  AND id != ?",
                            (cp["artist_account_id"], platform, _ppid, cp["id"]),
                        )
                        await database.commit()
                    except Exception:
                        pass

                # Bump clip stats AFTER a successful post (not at plan time).
                # Bumping at plan time made evaluate_pause think the directory
                # was exhausted while clips were merely queued, which paused
                # the artist and stalled the dispatcher.
                try:
                    if clip and clip["id"] not in _incremented_clip_ids:
                        _incremented_clip_ids.add(clip["id"])
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
                _dispatch_results.append({
                    "artist_id": cp.get("artist_id"),
                    "platform": cp.get("platform"),
                    "variation_name": str(dict(variation).get("name") or f"#{cp.get('artist_account_id')}"),
                    "status": "posted",
                    "error": None,
                })
            except PostingError as e:
                _err_str = str(e)[:500]
                await db.update_clip_post(database, cp["id"], status="failed", error=_err_str)
                await db.log_error(
                    database, source=f"posting.{cp.get('platform')}",
                    message=str(e), traceback=traceback.format_exc(),
                    context=f"clip_post_id={cp['id']}",
                )
                _dispatch_results.append({
                    "artist_id": cp.get("artist_id"),
                    "platform": cp.get("platform"),
                    "variation_name": "",
                    "status": "failed",
                    "error": str(e)[:200],
                })
            except Exception as e:  # noqa: BLE001
                await db.update_clip_post(database, cp["id"], status="failed", error=str(e)[:500])
                await db.log_error(
                    database, source=f"scheduler.dispatch.{cp.get('platform')}",
                    message=str(e), traceback=traceback.format_exc(),
                    context=f"clip_post_id={cp['id']}",
                )
                _dispatch_results.append({
                    "artist_id": cp.get("artist_id"),
                    "platform": cp.get("platform"),
                    "variation_name": "",
                    "status": "failed",
                    "error": str(e)[:200],
                })

        # Send one post-result email per artist per dispatch batch.
        if _dispatch_results:
            try:
                from services.email import send_post_result_email
                from collections import defaultdict
                by_artist: dict = defaultdict(list)
                for r in _dispatch_results:
                    if r.get("artist_id"):
                        by_artist[r["artist_id"]].append(r)
                for artist_id, results in by_artist.items():
                    try:
                        artist_row = await db.get_artist(database, artist_id)
                        if not artist_row:
                            continue
                        a_d = dict(artist_row)
                        owner_id = a_d.get("user_id")
                        if not owner_id:
                            continue
                        user_row = await db.get_user(database, owner_id)
                        if not user_row:
                            continue
                        u_d = dict(user_row)
                        if not u_d.get("email_notifications", True):
                            continue
                        owner_email = u_d.get("email")
                        if not owner_email:
                            continue
                        await send_post_result_email(
                            owner_email, a_d.get("name", f"Artist #{artist_id}"), results
                        )
                    except Exception:
                        traceback.print_exc()
            except ImportError:
                pass  # email not configured
            except Exception:
                traceback.print_exc()
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


# Process-level backoff for YouTube Data API quota exhaustion. When the
# poller sees a 403 quotaExceeded, it sets this to "next midnight Pacific"
# and skips ALL YouTube rows (batch + per-row fallback) until then. Without
# this, a single quota event spams the error log with one 403 per queued
# YouTube clip every poll cycle (we saw 500+ identical entries in prod).
_yt_quota_exhausted_until: datetime | None = None


def _next_midnight_pacific() -> datetime:
    """Google's Data API daily quota resets at midnight US/Pacific."""
    pacific = ZoneInfo("US/Pacific")
    now_p = datetime.now(pacific)
    tomorrow = (now_p + timedelta(days=1)).date()
    midnight = datetime.combine(tomorrow, dtime(0, 0), tzinfo=pacific)
    return midnight.astimezone(timezone.utc)


async def _send_pre_post_reminders() -> None:
    """Email reminder ~1 hour before a scheduled post. Runs on each poll tick.
    Groups all platforms for the same artist/time into a single email."""
    try:
        from services.email import send_post_reminder_email
    except ImportError:
        return  # email not configured

    database = await db.get_db()
    try:
        cur = await database.execute(
            """
            SELECT cp.id, cp.artist_id, cp.platform, cp.scheduled_for,
                   a.name AS artist_name, a.timezone AS artist_tz,
                   u.email AS user_email, u.email_notifications
            FROM clip_posts cp
            JOIN artists a ON a.id = cp.artist_id
            JOIN users u ON u.id = a.user_id
            WHERE cp.status = 'scheduled'
              AND cp.reminder_sent_at IS NULL
              AND cp.scheduled_for BETWEEN NOW() + INTERVAL '55 minutes'
                                      AND NOW() + INTERVAL '65 minutes'
            ORDER BY cp.artist_id, cp.scheduled_for
            """
        )
        rows = await cur.fetchall()

        # Group rows by (artist_id, scheduled_for minute, user_email) so we
        # send exactly ONE email per artist per upcoming batch time.
        from collections import defaultdict
        groups: dict[tuple, list] = defaultdict(list)
        for row in rows:
            rd = dict(row)
            # Round scheduled_for to the minute so same-batch slots group together
            sf = rd["scheduled_for"]
            if sf.tzinfo is None:
                sf = sf.replace(tzinfo=timezone.utc)
            key = (rd["artist_id"], sf.replace(second=0, microsecond=0), rd.get("user_email", ""))
            groups[key].append(rd)

        for (artist_id, sf, user_email), group_rows in groups.items():
            first = group_rows[0]
            if not first.get("email_notifications", True) or not user_email:
                # Mark as sent so we don't retry each tick
                for rd in group_rows:
                    await database.execute(
                        "UPDATE clip_posts SET reminder_sent_at = NOW() WHERE id = :id AND reminder_sent_at IS NULL",
                        {"id": rd["id"]},
                    )
                await database.commit()
                continue
            try:
                from zoneinfo import ZoneInfo
                tz_str = first.get("artist_tz") or "US/Eastern"
                try:
                    tz = ZoneInfo(tz_str)
                except Exception:
                    tz = ZoneInfo("US/Eastern")
                time_str = sf.astimezone(tz).strftime("%b %d, %Y at %H:%M %Z")
                platforms = list({rd["platform"] for rd in group_rows})
                await send_post_reminder_email(
                    user_email,
                    first["artist_name"],
                    time_str,
                    platforms,
                )
                # Mark all rows in this group as reminded
                for rd in group_rows:
                    await database.execute(
                        "UPDATE clip_posts SET reminder_sent_at = NOW() WHERE id = :id AND reminder_sent_at IS NULL",
                        {"id": rd["id"]},
                    )
                await database.commit()
            except Exception:
                traceback.print_exc()
    except Exception:
        traceback.print_exc()
    finally:
        await database.close()


async def _send_brand_pre_post_reminders() -> None:
    """Email reminder ~1 hour before a brand scheduled post. Runs on each poll tick.
    Sends one email per scheduled post approaching its publish time."""
    try:
        from services.email import send_post_reminder_email
    except ImportError:
        return

    database = await db.get_db()
    try:
        cur = await database.execute(
            """
            SELECT p.id, p.date, p.scheduled_time, p.brand_id,
                   b.name AS brand_name, b.timezone AS brand_tz,
                   u.email AS user_email, u.email_notifications
            FROM posts p
            JOIN brands b ON b.id = p.brand_id
            JOIN users u ON u.id = b.user_id
            WHERE p.status = 'scheduled'
              AND p.scheduled_time IS NOT NULL
              AND p.reminder_sent_at IS NULL
              AND (u.email_notifications IS NULL OR u.email_notifications = TRUE)
            """
        )
        rows = await cur.fetchall()
        if not rows:
            return

        now_utc = datetime.now(timezone.utc)
        window_lo = now_utc + timedelta(minutes=55)
        window_hi = now_utc + timedelta(minutes=65)

        for row in rows:
            rd = dict(row)
            try:
                # Parse date + time in brand's local timezone, then convert to UTC
                tz_str = rd.get("brand_tz") or "US/Eastern"
                try:
                    tz = ZoneInfo(tz_str)
                except Exception:
                    tz = ZoneInfo("US/Eastern")
                date_str = rd.get("date") or ""
                time_str = rd.get("scheduled_time") or ""
                if not date_str or not time_str:
                    continue
                # scheduled_time stored as "HH:MM" or "HH:MM:SS"
                fmt = "%Y-%m-%d %H:%M:%S" if len(time_str) > 5 else "%Y-%m-%d %H:%M"
                local_dt = datetime.strptime(f"{date_str} {time_str}", fmt).replace(tzinfo=tz)
                post_utc = local_dt.astimezone(timezone.utc)
                if not (window_lo <= post_utc <= window_hi):
                    continue

                display_time = local_dt.strftime("%b %d, %Y at %H:%M %Z")
                await send_post_reminder_email(
                    rd["user_email"],
                    rd["brand_name"],
                    display_time,
                    [],
                )
                await database.execute(
                    "UPDATE posts SET reminder_sent_at = NOW() WHERE id = :id AND reminder_sent_at IS NULL",
                    {"id": rd["id"]},
                )
                await database.commit()
            except Exception:
                traceback.print_exc()
    except Exception:
        traceback.print_exc()
    finally:
        await database.close()


async def _fresh_brand_account_token(database, account: dict, platform: str) -> str | None:
    """Return a fresh token for a brand account, refreshing if near expiry.
    Mirrors _fresh_variation_token but writes back to `accounts`, not `artist_accounts`."""
    a = dict(account)
    token = a.get(f"{platform}_token")
    if not token:
        return None
    exp = a.get(f"{platform}_expires_at")
    refresh = a.get(f"{platform}_refresh_token")
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
    if platform == "facebook":
        provider = "meta"
    elif platform == "instagram":
        provider = "meta" if a.get("facebook_token") else "instagram"
    else:
        provider = platform
    cfg = await db.get_site_config(database)
    cid = cfg.get(f"oauth_{provider}_client_id", "")
    csec = cfg.get(f"oauth_{provider}_client_secret", "")
    if not cid or not csec:
        return token
    try:
        refreshed = await oauth_svc.refresh_access_token(
            provider, refresh, cid, csec, proxy_url=a.get("proxy_url"),
        )
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
        await db.update_account(database, a["id"], **updates)
    except Exception:
        pass
    return new_token


async def dispatch_brand_posts_once() -> None:
    """Auto-dispatch brand posts whose scheduled_time has passed.

    Mirrors the POST /api/posts/{id}/post-now endpoint but runs as a background
    loop every 60 seconds. Uses status='posting' as an atomic guard to prevent
    double-dispatch if a previous tick's upload is still in progress.
    """
    from services.posting import tiktok as _tt, youtube as _yt, instagram as _ig, facebook as _fb
    from services.posting import PostingError
    from urllib.parse import quote
    import secrets as _secrets

    database = await db.get_db()
    try:
        # Recover posts stuck in 'posting' for > 15 min (crashed mid-upload).
        # scheduled_at is set when the post transitions to 'scheduled'; it's
        # always in the past by the time dispatch fires, so any post still in
        # 'posting' > 15 min after its scheduled_at slot is definitively stale.
        await database.execute(
            """
            UPDATE posts SET status = 'scheduled'
            WHERE status = 'posting'
              AND scheduled_at IS NOT NULL
              AND scheduled_at < NOW() - INTERVAL '15 minutes'
            """
        )
        await database.commit()

        cur = await database.execute(
            """
            SELECT p.id, p.brand_id, p.date, p.scheduled_time, p.caption,
                   b.timezone AS brand_tz, b.name AS brand_name,
                   u.id AS user_id, u.email, u.email_notifications
            FROM posts p
            JOIN brands b ON b.id = p.brand_id
            JOIN users u ON u.id = b.user_id
            WHERE p.status = 'scheduled'
              AND p.scheduled_time IS NOT NULL
              AND p.date IS NOT NULL
            """
        )
        rows = await cur.fetchall()
        if not rows:
            return

        now_utc = datetime.now(timezone.utc)
        due = []
        for r in rows:
            d = dict(r)
            try:
                tz = ZoneInfo(d.get("brand_tz") or "UTC")
                date_val = d.get("date")
                time_val = d.get("scheduled_time")
                if not date_val or not time_val:
                    continue
                time_str = str(time_val)
                fmt = "%Y-%m-%d %H:%M:%S" if len(time_str) > 5 else "%Y-%m-%d %H:%M"
                local_dt = datetime.strptime(f"{date_val} {time_str}", fmt).replace(tzinfo=tz)
                post_utc = local_dt.astimezone(timezone.utc)
                if post_utc <= now_utc:
                    due.append(d)
            except Exception:
                traceback.print_exc()

        for post_meta in due:
            post_id = post_meta["id"]
            try:
                # Atomic guard: flip to 'posting' so concurrent ticks don't double-dispatch.
                await database.execute(
                    "UPDATE posts SET status = 'posting' WHERE id = ? AND status = 'scheduled'",
                    (post_id,),
                )
                await database.commit()

                # Re-fetch to confirm we won the race.
                post = await db.get_post(database, post_id)
                if not post or dict(post).get("status") != "posting":
                    continue  # Another tick already claimed it.

                cfg = await db.get_site_config(database)
                public_base = (cfg.get("oauth_redirect_base") or "").rstrip("/")
                if not public_base:
                    await db.update_post(database, post_id, status="scheduled")
                    await database.commit()
                    continue

                outputs = await db.get_outputs(database, post_id)
                caption = str(post.get("caption") or "")
                results: list[dict] = []
                any_success = False

                for out in outputs:
                    out = dict(out)
                    account = await db.get_account(database, out["account_id"])
                    if not account:
                        continue
                    account = dict(account)
                    account_proxy = account.get("proxy_url") or None

                    # Build public URL for a given platform-specific path.
                    _video_t = _secrets.token_urlsafe(6)
                    legacy_video_path = out.get("video_path")

                    def _public_video_url(p=None):
                        path = (out.get(f"{p}_video_path") if p else None) or legacy_video_path
                        if not path:
                            return None
                        rel = path.lstrip("./")
                        enc = "/".join(quote(seg, safe="") for seg in rel.split("/") if seg)
                        return f"{public_base}/api/files/{enc}?for={account['id']}&t={_video_t}"

                    # Build TikTok slide URLs if a slides_dir exists.
                    slide_urls: list[str] = []
                    slides_dir = out.get("slides_dir")
                    if slides_dir and Path(slides_dir).exists():
                        _t = _secrets.token_urlsafe(6)
                        for f in sorted(Path(slides_dir).iterdir()):
                            if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp") and "_9x16" not in f.stem:
                                rel = str(f).lstrip("./")
                                enc = "/".join(quote(seg, safe="") for seg in rel.split("/") if seg)
                                slide_urls.append(
                                    f"{public_base}/api/files-jpg/{enc}?for={account['id']}&t={_t}"
                                )

                    targets = [
                        ("tiktok",    _tt, await _fresh_brand_account_token(database, account, "tiktok")),
                        ("youtube",   _yt, await _fresh_brand_account_token(database, account, "youtube")),
                        ("instagram", _ig, await _fresh_brand_account_token(database, account, "instagram")),
                        ("facebook",  _fb, await _fresh_brand_account_token(database, account, "facebook")),
                    ]

                    per_platform: dict = {}
                    for name, adapter, token in targets:
                        if not token:
                            per_platform[name] = {"status": "skipped", "reason": "not connected"}
                            continue
                        try:
                            if name == "tiktok":
                                if out.get("tiktok_post_as_draft"):
                                    tt_kwargs: dict = {"post_mode": "INBOX"}
                                    tt_err = None
                                else:
                                    privacy = out.get("tiktok_privacy_level")
                                    if not privacy:
                                        per_platform[name] = {"status": "failed", "error": "TikTok privacy not set"}
                                        continue
                                    tt_kwargs = {
                                        "post_mode": "DIRECT_POST",
                                        "privacy_level": privacy.upper(),
                                        "disable_comment": not bool(out.get("tiktok_allow_comment")),
                                        "disable_duet":    not bool(out.get("tiktok_allow_duet")),
                                        "disable_stitch":  not bool(out.get("tiktok_allow_stitch")),
                                        "brand_content_toggle": bool(out.get("tiktok_disclose_branded_content")),
                                        "brand_organic_toggle": bool(out.get("tiktok_disclose_your_brand")),
                                    }
                                # Use per-output tiktok_title if set; fall back to
                                # shared scraped caption so other platforms are unaffected.
                                tt_caption = out.get("tiktok_title") or caption
                                if slide_urls:
                                    slideshow_kwargs = {k: v for k, v in tt_kwargs.items()
                                                       if k not in ("disable_duet", "disable_stitch")}
                                    res = await _tt.upload_photo_slideshow(
                                        token, slide_urls, tt_caption,
                                        proxy_url=account_proxy, **slideshow_kwargs,
                                    )
                                else:
                                    plat_url = _public_video_url(None)
                                    if not plat_url:
                                        per_platform[name] = {"status": "skipped", "reason": "no video rendered"}
                                        continue
                                    res = await adapter.upload_video(
                                        token, plat_url, tt_caption,
                                        proxy_url=account_proxy, **tt_kwargs,
                                    )
                            else:
                                plat_url = _public_video_url(name if name in ("youtube", "instagram", "facebook") else None)
                                if not plat_url:
                                    per_platform[name] = {"status": "skipped", "reason": "no video rendered"}
                                    continue
                                plat_kwargs: dict = {}
                                if name == "facebook" and account.get("facebook_user_id"):
                                    plat_kwargs["page_id"] = account["facebook_user_id"]
                                if name == "instagram" and account.get("instagram_user_id"):
                                    plat_kwargs["ig_user_id"] = account["instagram_user_id"]
                                res = await adapter.upload_video(
                                    token, plat_url, caption,
                                    proxy_url=account_proxy, **plat_kwargs,
                                )
                            per_platform[name] = {
                                "status": "posted",
                                "platform_post_id": res.get("platform_post_id"),
                                "permalink": res.get("permalink"),
                                **({"draft": True} if res.get("draft") else {}),
                            }
                            any_success = True
                            try:
                                update_kwargs = {f"{name}_posted": True, f"{name}_error": None}
                                if res.get("draft"):
                                    update_kwargs["posted_as_draft"] = True
                                await db.update_output(database, out["id"], **update_kwargs)
                            except Exception:
                                pass
                        except PostingError as e:
                            err_msg = str(e)[:300]
                            per_platform[name] = {"status": "failed", "error": err_msg}
                            try:
                                await db.update_output(database, out["id"], **{f"{name}_error": err_msg})
                            except Exception:
                                pass
                        except Exception as e:
                            err_msg = f"{type(e).__name__}: {str(e)[:250]}"
                            per_platform[name] = {"status": "failed", "error": err_msg}
                            try:
                                await db.update_output(database, out["id"], **{f"{name}_error": err_msg})
                            except Exception:
                                pass

                    results.append({"account_name": account.get("name"), "platforms": per_platform})

                if any_success:
                    await db.update_post(database, post_id, status="posted")
                    # Send HURRAY result email.
                    try:
                        from services.email import send_post_result_email
                        flat_results = [
                            {"platform": p, "variation_name": r.get("account_name") or p,
                             "status": pd.get("status", "failed"), "error": pd.get("error")}
                            for r in results for p, pd in r.get("platforms", {}).items()
                        ]
                        dash_url = public_base + "/dashboard"
                        asyncio.create_task(send_post_result_email(
                            post_meta["email"], post_meta["brand_name"], flat_results,
                            dashboard_url=dash_url,
                        ))
                    except Exception:
                        pass
                else:
                    await db.update_post(database, post_id, status="failed")

                await database.commit()
            except Exception:
                traceback.print_exc()
                try:
                    await db.update_post(database, post_id, status="failed")
                    await database.commit()
                except Exception:
                    pass

        # ── Delayed TikTok retries ────────────────────────────────────────────
        # Retry outputs whose tiktok_retry_after has elapsed (set by
        # POST /api/outputs/{id}/retry?mode=delayed from the brand retry UI).
        # Only fires if the platform hasn't already posted successfully.
        try:
            retry_cur = await database.execute(
                """
                SELECT o.id AS output_id, o.post_id, o.account_id,
                       o.slides_dir, o.video_path,
                       o.tiktok_post_as_draft, o.tiktok_privacy_level,
                       o.tiktok_allow_comment, o.tiktok_allow_duet,
                       o.tiktok_allow_stitch,
                       o.tiktok_disclose_branded_content, o.tiktok_disclose_your_brand,
                       p.caption
                FROM outputs o
                JOIN posts p ON p.id = o.post_id
                WHERE o.tiktok_retry_after IS NOT NULL
                  AND o.tiktok_retry_after <= NOW()
                  AND (o.tiktok_posted IS NULL OR o.tiktok_posted = FALSE)
                """
            )
            delayed_rows = await retry_cur.fetchall()
            for drow in delayed_rows:
                drow = dict(drow)
                out_id = drow["output_id"]
                # Clear retry_after immediately so we don't re-attempt on next tick
                await database.execute(
                    "UPDATE outputs SET tiktok_retry_after = NULL WHERE id = ?",
                    (out_id,),
                )
                await database.commit()
                try:
                    account = await db.get_account(database, drow["account_id"])
                    if not account:
                        continue
                    account = dict(account)
                    token = await _fresh_brand_account_token(database, account, "tiktok")
                    if not token:
                        continue

                    cfg = await db.get_site_config(database)
                    public_base = (cfg.get("oauth_redirect_base") or "").rstrip("/")
                    if not public_base:
                        continue

                    _t = _secrets.token_urlsafe(6)
                    legacy_path = drow.get("video_path")

                    def _pub_url(p=None):
                        path = (drow.get(f"{p}_video_path") if p else None) or legacy_path
                        if not path:
                            return None
                        rel = path.lstrip("./")
                        enc = "/".join(quote(seg, safe="") for seg in rel.split("/") if seg)
                        return f"{public_base}/api/files/{enc}?for={account['id']}&t={_t}"

                    slide_urls: list[str] = []
                    slides_dir = drow.get("slides_dir")
                    if slides_dir and Path(slides_dir).exists():
                        _st = _secrets.token_urlsafe(6)
                        for f in sorted(Path(slides_dir).iterdir()):
                            if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp") and "_9x16" not in f.stem:
                                rel = str(f).lstrip("./")
                                enc = "/".join(quote(seg, safe="") for seg in rel.split("/") if seg)
                                slide_urls.append(
                                    f"{public_base}/api/files-jpg/{enc}?for={account['id']}&t={_st}"
                                )

                    if drow.get("tiktok_post_as_draft"):
                        tt_kwargs: dict = {"post_mode": "INBOX"}
                    else:
                        privacy = drow.get("tiktok_privacy_level")
                        if not privacy:
                            await db.update_output(database, out_id,
                                                   tiktok_error="TikTok privacy not set")
                            await database.commit()
                            continue
                        tt_kwargs = {
                            "post_mode": "DIRECT_POST",
                            "privacy_level": privacy.upper(),
                            "disable_comment": not bool(drow.get("tiktok_allow_comment")),
                            "disable_duet":    not bool(drow.get("tiktok_allow_duet")),
                            "disable_stitch":  not bool(drow.get("tiktok_allow_stitch")),
                            "brand_content_toggle": bool(drow.get("tiktok_disclose_branded_content")),
                            "brand_organic_toggle": bool(drow.get("tiktok_disclose_your_brand")),
                        }

                    account_proxy = account.get("proxy_url") or None
                    if slide_urls:
                        slideshow_kwargs = {k: v for k, v in tt_kwargs.items()
                                            if k not in ("disable_duet", "disable_stitch")}
                        res = await _tt.upload_photo_slideshow(
                            token, slide_urls, str(drow.get("caption") or ""),
                            proxy_url=account_proxy, **slideshow_kwargs,
                        )
                    else:
                        plat_url = _pub_url(None)
                        if not plat_url:
                            continue
                        res = await _tt.upload_video(
                            token, plat_url, str(drow.get("caption") or ""),
                            proxy_url=account_proxy, **tt_kwargs,
                        )
                    upd: dict = {"tiktok_posted": True, "tiktok_error": None}
                    if res.get("draft"):
                        upd["posted_as_draft"] = True
                    await db.update_output(database, out_id, **upd)
                    await database.commit()
                except Exception:
                    traceback.print_exc()
                    try:
                        err_msg = traceback.format_exc()[-300:]
                        await db.update_output(database, out_id,
                                               tiktok_error=err_msg)
                        await database.commit()
                    except Exception:
                        pass
        except Exception:
            traceback.print_exc()

    finally:
        await database.close()


async def poll_views_once() -> None:
    """Refresh view counts for all posted rows, then re-check pause."""
    # NOTE: External post discovery (TikTok + other platforms) runs in its
    # own separate background loop (_discovery_loop) so it never blocks
    # the view-count pass here.

    # Send pre-post reminders (1 hour ahead) — silently no-op if SMTP not configured.
    try:
        await _send_pre_post_reminders()
    except Exception:
        traceback.print_exc()

    # Send brand-side pre-post reminders.
    try:
        await _send_brand_pre_post_reminders()
    except Exception:
        traceback.print_exc()

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
              AND posted_as_draft = FALSE
              AND (view_count_updated_at IS NULL
                   OR view_count_updated_at < NOW() - INTERVAL '30 seconds')
            ORDER BY view_count_updated_at ASC NULLS FIRST
            LIMIT 30
            """
        )
        rows = [dict(r) for r in await cur.fetchall()]
        touched_artists: set[int] = set()

        # Pre-batch YouTube view-count requests. Per-row `videos.list?id=X`
        # costs 1 quota unit and we get ~14k/day with 30 rows polled every
        # 180s — well over the 10k/day default cap. `videos.list?id=a,b,c`
        # accepts up to 50 IDs for the same 1 unit, dropping daily usage to
        # well under 300. Group by access_token (variations have distinct
        # tokens) and stash results for the inner loop to read instead of
        # making its own per-row API call.
        global _yt_quota_exhausted_until
        yt_views: dict[str, int] = {}  # platform_post_id -> views (from batch)
        yt_attempted: set[str] = set()  # IDs we asked for; missing => deleted
        # Determined per cycle: when the daily quota is gone we skip YT
        # rows entirely in the inner loop (no batch, no fallback, no logs).
        yt_quota_blocked = (
            _yt_quota_exhausted_until is not None
            and datetime.now(timezone.utc) < _yt_quota_exhausted_until
        )
        if yt_quota_blocked:
            # Stamp every YouTube row's view_count_updated_at so the 30s
            # cooldown filter pushes them past the LIMIT 100 — keeps the
            # poller working on TikTok/IG/FB rows instead of spinning on
            # ones we can't refresh anyway.
            now = datetime.now(timezone.utc)
            for cp in rows:
                if cp["platform"] == "youtube":
                    try:
                        await db.update_clip_post(
                            database, cp["id"], view_count_updated_at=now,
                        )
                    except Exception:
                        pass
        try:
            if not yt_quota_blocked:
                from services.posting.youtube import get_view_counts_batch
                from services.posting import YouTubeQuotaExhausted
                yt_groups: dict[str, list[str]] = {}  # access_token -> [video_id...]
                for cp in rows:
                    if cp["platform"] != "youtube":
                        continue
                    pid = cp.get("platform_post_id")
                    if not pid:
                        continue
                    v = await db.get_artist_account(database, cp["artist_account_id"])
                    if not v:
                        continue
                    tok = await _fresh_variation_token(database, v, "youtube")
                    if not tok:
                        continue
                    yt_groups.setdefault(tok, []).append(pid)
                    yt_attempted.add(pid)
                # Capture proxy per token so the batched call goes through the
                # same residential IP as that variation's posts.
                yt_proxy_for_token: dict[str, str | None] = {}
                for cp in rows:
                    if cp["platform"] != "youtube":
                        continue
                    v = await db.get_artist_account(database, cp["artist_account_id"])
                    if not v:
                        continue
                    tok = await _fresh_variation_token(database, dict(v), "youtube")
                    if tok and tok in yt_groups:
                        yt_proxy_for_token.setdefault(tok, dict(v).get("proxy_url") or None)
                for tok, ids in yt_groups.items():
                    try:
                        yt_views.update(await get_view_counts_batch(
                            tok, ids, proxy_url=yt_proxy_for_token.get(tok),
                        ))
                    except YouTubeQuotaExhausted as qe:
                        # Daily Data API quota gone. Set the process-level
                        # backoff to next midnight Pacific (Google's reset)
                        # and treat ALL YouTube rows this cycle as blocked.
                        _yt_quota_exhausted_until = _next_midnight_pacific()
                        yt_quota_blocked = True
                        await db.log_error(
                            database, source="posting.youtube.views_batch",
                            message=(
                                f"YouTube Data API quota exhausted; pausing "
                                f"YouTube view polling until "
                                f"{_yt_quota_exhausted_until.isoformat()}. "
                                f"Original error: {qe}"
                            ),
                        )
                        # Stamp updated_at on the YT rows so they fall out
                        # of the 30s-cooldown window and we don't reselect
                        # them every minute.
                        now = datetime.now(timezone.utc)
                        for cp in rows:
                            if cp["platform"] == "youtube":
                                try:
                                    await db.update_clip_post(
                                        database, cp["id"], view_count_updated_at=now,
                                    )
                                except Exception:
                                    pass
                        yt_attempted.clear()
                        yt_views.clear()
                        break
                    except Exception as be:
                        # Non-quota batch failure (network blip, transient
                        # 5xx): clear attempted set for these IDs so the
                        # inner loop doesn't mis-treat them as deleted, and
                        # let it fall back to per-row.
                        await db.log_error(
                            database, source="posting.youtube.views_batch",
                            message=str(be), traceback=traceback.format_exc(),
                        )
                        for pid in ids:
                            yt_attempted.discard(pid)
        except Exception:
            # Pre-batch setup failed entirely; leave caches empty and let
            # the inner loop run as before (per-row fallback).
            yt_attempted.clear()
            yt_views.clear()

        for cp in rows:
            try:
                # Quota-blocked YouTube rows: skip entirely. The pre-batch
                # block above already stamped view_count_updated_at, so
                # they'll fall outside the 30s cooldown filter on the next
                # selection.
                if yt_quota_blocked and cp["platform"] == "youtube":
                    continue
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
                        resolved = await resolve_video_id(
                            access_token, post_id, posted_epoch,
                            proxy_url=dict(variation).get("proxy_url") or None,
                        )
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

                if platform == "youtube" and post_id in yt_attempted:
                    # Pre-batched above. If the ID came back, use that count;
                    # if it didn't, the video is gone (deleted, private, or
                    # stale ID). Mark deleted_at so it drops from the live
                    # post count. The view_count column is NOT cleared here —
                    # the dashboard sums views from all posted rows (deleted
                    # or not) so the accumulated count never disappears.
                    if post_id in yt_views:
                        views = yt_views[post_id]
                    else:
                        from services.posting import PostDeletedError as _PDE
                        raise _PDE(
                            f"YouTube stats: video id {post_id!r} not found "
                            f"(deleted, private, or stored id is stale)"
                        )
                else:
                    views = await adapter.get_view_count(
                        access_token, post_id,
                        proxy_url=dict(variation).get("proxy_url") or None,
                    )
                new_views = int(views or 0)
                prev_views = int(cp.get("view_count") or 0)
                # Never let a real, observed view count regress. Platforms
                # occasionally return a lower number (rate-limit glitch,
                # propagation lag, edge-cache stale read, or a 0 when the
                # post is briefly invisible). Take MAX(prev, new) so the
                # dashboard total only ever climbs.
                if new_views < prev_views:
                    # MONOTONIC view counts: never write a lower number than
                    # what's stored. Platforms (especially Meta) blip and
                    # return 0 transiently — the previous behaviour treated
                    # any drop-to-zero as a deletion, wiped the count, and
                    # logged a noisy 'may be deleted/hidden' error. The user
                    # then lost all FB views overnight to one bad poll cycle.
                    #
                    # Now: keep the previous count, bump updated_at, no log.
                    # Real deletions are still caught — the adapter raises
                    # PostDeletedError when the platform explicitly says the
                    # post is gone (404, 'does not exist'), and the
                    # exception handler below sets deleted_at.
                    await db.update_clip_post(
                        database, cp["id"],
                        view_count_updated_at=datetime.now(timezone.utc),
                    )
                else:
                    # new_views >= prev_views. Write the new count. Belt-and
                    # -braces guard with max() so we never accidentally
                    # decrease (defensive against future refactors of the
                    # if-branch above).
                    await db.update_clip_post(
                        database, cp["id"],
                        view_count=max(new_views, prev_views),
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
                # Adapter explicitly told us the post is gone (404 / empty
                # items / 'Object with ID does not exist'). Mark deleted_at
                # so the dashboard count drops on the next refresh. NO log
                # entry — the user explicitly asked never to see deletion
                # logs. Dashboard count drop IS the signal.
                from services.posting import PostDeletedError
                if isinstance(e, PostDeletedError):
                    try:
                        await db.update_clip_post(
                            database, cp["id"],
                            view_count_updated_at=datetime.now(timezone.utc),
                            deleted_at=datetime.now(timezone.utc),
                        )
                    except Exception:
                        pass
                    continue
                # TikTok (and other platforms) sometimes return transient
                # 500/429 server errors. These are platform-side outages —
                # nothing we can do. Bump view_count_updated_at so the row
                # is skipped this cycle and retried next poll, but do NOT
                # log to the admin error panel (would flood it every 3 min).
                err_str = str(e).lower()
                is_transient = any(x in err_str for x in (
                    "500", "internal_error", "429", "too many requests",
                    "service unavailable", "503", "502", "bad gateway",
                ))
                if is_transient:
                    try:
                        await db.update_clip_post(
                            database, cp["id"],
                            view_count_updated_at=datetime.now(timezone.utc),
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
            # Hard cap: view poll must complete within 2 minutes.
            # Rows are selected oldest-first so the next cycle picks up
            # where this one left off — all rows are eventually covered.
            await asyncio.wait_for(poll_views_once(), timeout=120)
        except asyncio.TimeoutError:
            print("[view_poll] cycle timed out after 120s — will resume next cycle", flush=True)
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


async def _discover_external_platform_posts(
    platform: str,
    token_col: str,
    extra_col: str | None = None,
) -> None:
    """Generic external-post discovery for Instagram, YouTube, and Facebook.

    Fetches each variation's recent posts via the platform adapter's
    list_videos() and inserts any unknown IDs as status='posted' rows so
    the view poller picks them up automatically. Fully idempotent.
    """
    database = await db.get_db()
    try:
        cols = f"aa.id, aa.artist_id, aa.{token_col}"
        if extra_col:
            cols += f", aa.{extra_col}"
        proxy_col = "aa.proxy_url"
        cur = await database.execute(
            f"""
            SELECT {cols}, {proxy_col}
            FROM artist_accounts aa
            WHERE aa.{token_col} IS NOT NULL
            """
        )
        variations = [dict(r) for r in await cur.fetchall()]
        if not variations:
            return

        # Reset count so the UI ring clears while this run is in progress
        try:
            await db.set_site_config(database, f"{platform}_discovery_count", "0")
            await database.commit()
        except Exception:
            pass

        now_utc = datetime.now(timezone.utc)
        adapter = ADAPTERS[platform]
        total_run_inserted = 0

        for var in variations:
            var_id = var["id"]
            artist_id = var["artist_id"]
            access_token = var[token_col]
            proxy = var.get("proxy_url") or None
            extra_val = var.get(extra_col) if extra_col else None

            try:
                if platform == "instagram":
                    videos = await adapter.list_videos(
                        access_token, ig_user_id=extra_val, proxy_url=proxy
                    )
                elif platform == "youtube":
                    videos = await adapter.list_videos(access_token, proxy_url=proxy)
                else:  # facebook
                    videos = await adapter.list_videos(
                        access_token, page_id=extra_val, proxy_url=proxy
                    )

                if not videos:
                    continue

                existing_cur = await database.execute(
                    f"""
                    SELECT platform_post_id FROM clip_posts
                    WHERE artist_account_id = ? AND platform = ?
                      AND platform_post_id IS NOT NULL
                    """,
                    (var_id, platform),
                )
                known_ids = {
                    str(r["platform_post_id"]).strip()
                    for r in await existing_cur.fetchall()
                }

                inserted = 0
                for video in videos:
                    vid_id = str(video.get("id") or "").strip()
                    if not vid_id or vid_id in known_ids:
                        continue

                    # Parse ISO-8601 create_time (Instagram/Facebook/YouTube all use ISO)
                    create_time_str = video.get("create_time") or ""
                    try:
                        from datetime import datetime as _dt
                        posted_at = _dt.fromisoformat(
                            create_time_str.replace("Z", "+00:00")
                        ).astimezone(timezone.utc).replace(tzinfo=None)
                    except Exception:
                        posted_at = now_utc.replace(tzinfo=None)

                    await database.execute(
                        f"""
                        INSERT INTO clip_posts
                            (clip_id, artist_id, artist_account_id, platform,
                             status, platform_post_id, posted_at,
                             view_count, view_count_updated_at)
                        SELECT NULL, ?, ?, ?,
                               'posted', ?, ?,
                               0, ?
                        WHERE NOT EXISTS (
                            SELECT 1 FROM clip_posts
                            WHERE artist_account_id = ?
                              AND platform = ?
                              AND platform_post_id = ?
                        )
                        """,
                        (
                            artist_id, var_id, platform,
                            vid_id, posted_at,
                            now_utc.replace(tzinfo=None),
                            var_id, platform, vid_id,
                        ),
                    )
                    known_ids.add(vid_id)
                    inserted += 1

                await database.commit()
                total_run_inserted += inserted
                if inserted:
                    print(
                        f"[{platform}_discovery] var={var_id} inserted {inserted} new post(s)",
                        flush=True,
                    )
            except Exception:
                import traceback as _tb
                print(
                    f"[{platform}_discovery] var={var_id} ERROR: {_tb.format_exc()}",
                    flush=True,
                )

        # Stamp final count + timestamp for UI status card
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            await db.set_site_config(database, f"{platform}_discovery_count", str(total_run_inserted))
            await db.set_site_config(database, f"last_{platform}_discovery_at", now_iso)
            await database.commit()
        except Exception:
            pass
    finally:
        await database.close()


async def discover_external_tiktok_posts() -> None:
    """Discover TikTok videos posted outside this platform (e.g. from a phone).

    Calls /v2/video/list/ for every variation that has a tiktok_token (paused
    or not — paused just means no more clips to schedule, not that the account
    is inactive). Any video ID not already in clip_posts is inserted as a
    status='posted' row so the view poller picks it up automatically.

    Safe to run repeatedly — fully idempotent. Only inserts; never touches
    existing rows. Discovered rows have clip_id=NULL so:
      - _pick_next_clip ignores them (clips need clip_id IS NOT NULL)
      - _has_unposted_clip_for_variation ignores them (joins on cp.clip_id=c.id)
      - evaluate_pause / directory_exhausted logic is unaffected
      - view poller DOES poll them — that's the whole point
    """
    import httpx

    database = await db.get_db()
    try:
        # Fetch all variations across all artists that have a TikTok token.
        cur = await database.execute(
            """
            SELECT aa.id, aa.artist_id, aa.tiktok_token, aa.tiktok_user_id
            FROM artist_accounts aa
            WHERE aa.tiktok_token IS NOT NULL
            """
        )
        variations = [dict(r) for r in await cur.fetchall()]
        if not variations:
            return

        # Reset count so UI ring clears while this run is in progress
        try:
            await db.set_site_config(database, "tiktok_discovery_count", "0")
            await database.commit()
        except Exception:
            pass

        now_utc = datetime.now(timezone.utc)
        total_run_inserted = 0
        async with httpx.AsyncClient(timeout=30) as client:
            for var in variations:
                var_id = var["id"]
                artist_id = var["artist_id"]
                access_token = var["tiktok_token"]
                try:
                    # Fetch up to 20 most recent videos from TikTok.
                    # The /video/list/ API caps max_count at 20.
                    videos = await tiktok_adapter.list_videos(
                        client, access_token, max_count=20
                    )
                    if not videos:
                        continue

                    # Load all platform_post_ids already tracked for this
                    # variation so we can skip IDs we already know about.
                    # Include soft-deleted rows so we never re-insert a video
                    # that was cleaned up by the race-condition deduplicator.
                    # Also strip any whitespace so large-integer IDs returned
                    # by TikTok compare correctly against stored strings.
                    existing_cur = await database.execute(
                        """
                        SELECT platform_post_id FROM clip_posts
                        WHERE artist_account_id = ? AND platform = 'tiktok'
                          AND platform_post_id IS NOT NULL
                        """,
                        (var_id,),
                    )
                    known_ids = {
                        str(r["platform_post_id"]).strip()
                        for r in await existing_cur.fetchall()
                    }

                    inserted = 0
                    for video in videos:
                        vid_id = str(video.get("id") or "").strip()
                        if not vid_id or vid_id in known_ids:
                            continue

                        # Derive posted_at from create_time (unix seconds).
                        create_epoch = video.get("create_time")
                        try:
                            posted_at = datetime.fromtimestamp(
                                int(create_epoch), tz=timezone.utc
                            ).replace(tzinfo=None)  # store as naive UTC (DB convention)
                        except Exception:
                            posted_at = now_utc.replace(tzinfo=None)

                        initial_views = int(video.get("view_count") or 0)

                        # Double-check at INSERT time with a WHERE NOT EXISTS so
                        # a concurrent discovery run or a system post that finished
                        # between our known_ids load and now can't cause a dupe.
                        await database.execute(
                            """
                            INSERT INTO clip_posts
                                (clip_id, artist_id, artist_account_id, platform,
                                 status, platform_post_id, posted_at,
                                 view_count, view_count_updated_at)
                            SELECT NULL, ?, ?, 'tiktok',
                                   'posted', ?, ?,
                                   ?, ?
                            WHERE NOT EXISTS (
                                SELECT 1 FROM clip_posts
                                WHERE artist_account_id = ?
                                  AND platform = 'tiktok'
                                  AND platform_post_id = ?
                            )
                            """,
                            (
                                artist_id, var_id,
                                vid_id, posted_at,
                                initial_views, now_utc.replace(tzinfo=None),
                                var_id, vid_id,
                            ),
                        )
                        known_ids.add(vid_id)
                        inserted += 1

                    await database.commit()
                    total_run_inserted += inserted
                    if inserted:
                        print(
                            f"[tiktok_discovery] var={var_id} inserted {inserted} new post(s)",
                            flush=True,
                        )
                except Exception:
                    import traceback as _tb
                    print(
                        f"[tiktok_discovery] var={var_id} ERROR: {_tb.format_exc()}",
                        flush=True,
                    )

        # Stamp final count + timestamp for UI status card
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            await db.set_site_config(database, "tiktok_discovery_count", str(total_run_inserted))
            await db.set_site_config(database, "last_tiktok_discovery_at", now_iso)
            await database.commit()
        except Exception:
            pass
    finally:
        await database.close()


async def _discovery_loop() -> None:
    """Run external post discovery (TikTok + IG/YT/FB) every hour.

    Runs completely independently of the view-poll loop so a hung API call
    never blocks view counting.
    """
    await asyncio.sleep(30)  # brief startup delay
    while True:
        try:
            await discover_external_tiktok_posts()
        except Exception:
            traceback.print_exc()
        for _plat, _tok, _extra in [
            ("instagram", "instagram_token", "instagram_user_id"),
            ("youtube",   "youtube_token",   None),
            ("facebook",  "facebook_token",  "facebook_user_id"),
        ]:
            try:
                await asyncio.wait_for(
                    _discover_external_platform_posts(_plat, _tok, _extra),
                    timeout=30,
                )
            except asyncio.TimeoutError:
                print(f"[{_plat}_discovery] timed out — skipping", flush=True)
            except Exception:
                traceback.print_exc()
        await asyncio.sleep(3600)  # run once per hour


async def start_background_tasks() -> list[asyncio.Task]:
    """Kick off the background loops. Call from FastAPI lifespan startup."""
    return [
        asyncio.create_task(_loop(plan_slots_once, 300, "plan_slots")),
        asyncio.create_task(_loop(dispatch_due_once, 60, "dispatch")),
        asyncio.create_task(_poll_views_loop()),
        asyncio.create_task(_discovery_loop()),
        # Daily cache sweep — runs once on boot, then every 24h.
        asyncio.create_task(_loop(sweep_clip_caches_once, 86400, "cache_sweep")),
        # Brand post auto-dispatcher — checks every 60 s for scheduled posts
        # whose scheduled_time has passed and fires them via platform adapters.
        asyncio.create_task(_loop(dispatch_brand_posts_once, 60, "brand_dispatch")),
    ]
