# Project Memory — Zagged / icreateflow.com

> Project memory for future Claude sessions and any dev picking this up
> cold. Heavy on file paths and exact symbol names so neither audience
> has to grep around. Last updated 2026-04-28.

---

## 1. What this is

Multi-account social-media auto-poster for music artists. The product:
each artist has up to N "variations" (per-platform sub-accounts: TikTok,
YouTube, Instagram, Facebook). The user uploads or syncs short clips
from Google Drive; the system schedules them across configurable
posting windows in the artist's local timezone, picks the least-posted
clip for each slot, optionally per-account video-diversifies it
(imperceptible re-encode for cross-account dedup), and uploads to every
connected platform.

Stack: FastAPI + Postgres + asyncpg backend, Next.js 16 (Turbopack)
frontend, gunicorn + uvicorn workers, all on a single VPS at
`icreateflow.com` (`187.124.231.108`).

---

## 1b. Two products in one repo

This repo runs **two distinct pipelines** that share auth, DB, OAuth,
posting adapters, and the frontend shell. They are NOT alternative
descriptions of the same thing — past Claude sessions kept conflating
the two and rewriting one to look like the other. Don't.

| | Brands | Clipping |
|---|---|---|
| Source content | TikTok slideshow URL or uploaded slides | Short video clips (Google Drive sync or upload) |
| Pipeline | OCR → text edits → per-account variation (keep/replace/Flux) → text overlay → 9:16 video → schedule | Plan slots → diversify (or passthrough) → upload → poll views → auto-pause |
| Trigger | User-driven; no auto-dispatcher loop | 3 async loops in `services/clip_scheduler.py` (planner / dispatcher / view poller) |
| Tables | `brands`, `accounts`, `posts`, `slides`, `variations`, `outputs`, `music_tracks` | `artists`, `campaigns`, `artist_accounts`, `clips`, `clip_posts`, `clip_caption_variants` |
| Backend services | `services/{ocr,overlay,generator,video,flux,tiktok_scraper}.py` | `services/{clip_scheduler,variation_processor,gdrive,caption_variants}.py` |
| Frontend dashboard | `frontend/src/app/{brands,posts,posts/new,music,schedule}/` | `frontend/src/app/clipping/[slug]/` |
| Shared | `users`, `settings`, `user_settings`, `site_config`, `meta_pending_assignments`, `error_logs`, `services/{auth,oauth,posting/*}.py` |

§§3–13 below cover the **Clipping** side (the operationally heavy one).
§13b at the end is the **Brands** side.

---

## 2. Repo layout

```
.
├── backend/        FastAPI app, services, posting adapters
├── frontend/       Next.js 16 dashboard
├── deploy/         sync.sh (rsync laptop → server) + deploy.sh (server-side install)
├── output/         local-only render outputs (gitignored)
└── memory.md       this file
```

Top-level `.gitignore` excludes `node_modules/`, `.next/`, `__pycache__/`,
`venv/`, `*.db`, `output/`, `.env*`, `backend/{uploads,output,music}`,
`.claude/scheduled_tasks.lock`, `.claude/settings.local.json`.

---

## 3. Architecture in one diagram

```
                  ┌──────────────────────────────┐
GDrive sync ────▶ │  clips table                 │
or upload         │  (source, gdrive_file_id,    │
                  │   times_posted, ...)         │
                  └──────────────┬───────────────┘
                                 │ picked by `_pick_next_clip`
                                 ▼
                  ┌──────────────────────────────┐
   plan_slots_once│  clip_posts table            │
   (every 5 min)  │  one row per (variation,     │
   ──────────────▶│   platform, slot)            │
                  │  status: scheduled →         │
                  │   posting → posted | failed  │
                  └──────────────┬───────────────┘
                                 │ scheduled_for <= NOW()
                                 ▼
                  ┌──────────────────────────────┐
  dispatch_due_once│ atomic claim (SKIP LOCKED)  │
  (every 60s)     │ → diversify or passthrough  │
   ──────────────▶│ → adapter.upload_video       │
                  │ → status='posted',           │
                  │   platform_post_id, ...      │
                  └──────────────┬───────────────┘
                                 │
                                 ▼
                  ┌──────────────────────────────┐
  poll_views_once │ adapter.get_view_count       │
  (every 180s     │ monotonic max(prev, new)     │
   default)       │ deleted_at on PostDeletedError│
   ──────────────▶└──────────────────────────────┘
```

Three async loops, all in `backend/services/clip_scheduler.py`, kicked
off from FastAPI's lifespan startup hook in `main.py`.

---

## 4. Critical files

| Path | What's there |
|------|--------------|
| `backend/main.py` | FastAPI app + every endpoint. ~3700 lines. Lifespan starts the 3 scheduler loops. |
| `backend/database.py` | ORM models, helpers, `_TIMESTAMP_COLUMNS`, `_REPLACE_CONFLICT_TARGETS`, `init_db()`, all migrations. The `Connection.execute()` shim auto-appends `RETURNING id` to INSERTs — see Lessons. |
| `backend/services/clip_scheduler.py` | `_today_slots`, `_pick_next_clip`, `_has_unposted_clip`, `evaluate_pause`, `maybe_resume_on_new_clip`, `plan_slots_once`, `dispatch_due_once`, `poll_views_once`, `_user_or_site_setting`, `_toggle_on`. Module-level `from services import clip_scheduler` is required so endpoints can reference it. |
| `backend/services/variation_processor.py` | `diversify()` (per-variation ffmpeg crop+scale+eq+hue, audio passthrough, atomic .partial.<uuid> write) and `passthrough_download()` + `_transcode_to_h264()` for raw HEVC sources. `public_url_for()` builds the verified-domain URL. |
| `backend/services/posting/__init__.py` | `PostingError` + `PostDeletedError` (subclass) — adapters raise this when the platform reports the post is gone. |
| `backend/services/posting/tiktok.py` | `upload_video`, `get_view_count`, `_is_publish_id`, `resolve_video_id`. TikTok upload returns a `publish_id` — must resolve to real `video_id` before view polling works. |
| `backend/services/posting/youtube.py` | YouTube Data API v3 resumable upload for Shorts. Empty `items` → `PostDeletedError`. |
| `backend/services/posting/instagram.py` | IG Reels publish via Graph API v19. Existence probe (`?fields=id`) before insights call so deletions are caught even when token lacks `instagram_manage_insights`. |
| `backend/services/posting/facebook.py` | FB Page video publish. Combined existence + views in one call (`?fields=id,views`). |
| `backend/services/oauth.py` | OAuth scopes per platform. `SCOPES["meta"]` includes `pages_read_engagement,pages_manage_posts,pages_show_list,instagram_basic,instagram_content_publish,instagram_manage_insights`. |
| `backend/services/generator.py` | Brand-side post generator (slides + video). Separate code path from clipping. |
| `backend/services/video.py` | ffmpeg builder for branded videos with platform-specific caps (`PLATFORM_PROFILES`). |
| `frontend/src/app/clipping/[slug]/page.tsx` | Campaign dashboard. `formatInArtistTz` helper at top. Heartbeat in campaign card. Pause/resume chip is clickable for ALL paused reasons. Each variation card has a collapsible "Video directory (N clips)" subsection with edit/delete/caption-edit; the artist-level shared-pool section was removed. |
| `frontend/src/app/admin/page.tsx` | Admin: cache stats, audit-deleted button, view-poll cadence. |
| `frontend/src/app/settings/page.tsx` | Per-user settings: API keys, overlay defaults, AND clipping toggles (diversification, captions). Catch-up toggle was removed — the dashboard "Catch up missed slots" button replaces it. |
| `frontend/src/components/OAuthTiles.tsx` | Connect/disconnect UI. Meta picker shows pages/IG accounts after callback. |
| `deploy/sync.sh` | Rsync laptop → `/srv/icreateflow/src/`. |
| `deploy/deploy.sh` | Server-side: copy src into app dirs, symlink uploads/output/music → `/srv/icreateflow/data/*`, install backend deps, init DB schema, build frontend, `systemctl restart`. |

---

## 5. Data model

### `artists`
- `timezone` — IANA (e.g. `Africa/Lagos`); falls back to `US/Eastern` if unset.
- `posts_per_day` (default 3), `window_start` / `window_end` (HH:MM, 09:00–21:00 default).
- `paused_reason`: NULL | `manual` | `directory_exhausted` | `target_reached`.
  Artist-level rolls up from variations: when EVERY variation is in
  `directory_exhausted` OR `no_clips`, the artist flips to
  `directory_exhausted`. Auto-cleared when any variation becomes
  postable again.
- `is_active` boolean. `current_campaign_id`. `view_target`.

### `artist_accounts` (variations)
Per-platform: `*_token`, `*_refresh_token`, `*_expires_at`, `*_user_id`,
`*_handle`, `*_scopes` (column exists; not yet always persisted on
assign — see "Open follow-ups").
Per-variation extras (added during the per-variation rollout):
- `gdrive_folder_url` / `gdrive_folder_id` — each variation has its own
  Drive folder. Sync via `POST /api/artists/{id}/variations/{vid}/clips/gdrive`
  tags clips with `clips.artist_account_id = vid`.
- `proxy_url` — per-variation residential proxy. Threaded through every
  posting adapter, OAuth refresh, and view-count call.
- `paused_reason`: NULL | `manual` | `directory_exhausted` | `no_clips`.
  `no_clips` = variation has nothing in scope (no own folder, shared
  pool empty). Surfaces an amber chip on the dashboard so the user
  notices instead of seeing the campaign run silently with no posts.

### `clips`
- `source` ∈ `gdrive` | `upload`.
- `artist_account_id` (nullable FK to `artist_accounts`). NULL = shared
  pool (every variation can draw from it). Set = exclusive to that
  variation. Legacy artist-level clips are backfilled to the artist's
  lowest-id variation by `_migrate_per_variation_columns` — the
  backfill is idempotent and intentionally locks legacy clips to a
  single variation rather than the shared pool (per user request).
- `gdrive_file_id`, `local_path`, `filename`, `caption`.
- `times_posted`, `last_posted_at` — bumped post-dispatch only (not at
  plan time; bumping at plan time previously caused false
  `directory_exhausted` mid-day).

### `clip_posts`
- `status` ∈ `scheduled|posting|posted|failed`.
- `scheduled_for` (NAIVE UTC; planner converts artist-local → UTC).
- `posted_at`, `platform_post_id`, `error`.
- `view_count` (MONOTONIC — never decreases).
- `view_count_updated_at`, `deleted_at`.
- Unique partial index `clip_posts_no_dup_slot` on
  `(artist_account_id, platform, scheduled_for) WHERE status='scheduled'`.
  Slot-level (NOT per-clip_id) — replaced the older per-clip_id index
  because that allowed duplicate-slot inserts when planner picked a
  different clip on a second tick.

### `meta_pending_assignments`
Short-lived (~15 min) handoff between Meta OAuth callback and
`POST /api/oauth/meta/assign`. Was an in-memory dict, broke under `-w 2`
gunicorn workers (50% miss rate). Columns: `id`, `token`, `payload`
(JSON), `created_at`. Has `id` PK because the DB wrapper auto-appends
`RETURNING id` to INSERTs.

### Settings tables (3, by purpose)
| Table | Scope | What's in it |
|------|-------|--------------|
| `user_settings` | per-user | `clip_diversification_enabled`, `clip_caption_variants_enabled`. Read in scheduler via `_user_setting()` — user_settings ONLY, no site_config fallback (admin-set rows must not silently override unset user toggles). |
| `site_config` | global, admin-only | `view_poll_interval_seconds`, `cache_ttl_days`, `tiktok_privacy_level`, `oauth_redirect_base`, `oauth_google_drive_api_key`. Old `clip_diversification_enabled` / `clip_caption_variants_enabled` / `catchup_enabled` rows here are inert — no longer read. |
| `settings` | global, legacy | API keys (`anthropic_api_key`, `replicate_api_token`), overlay defaults, video defaults. Read by `/settings` page. |

---

## 6. Settings & toggles

Read pattern in scheduler (works for any clipping toggle):
```python
raw = await _user_setting(database, artist.user_id, "clip_diversification_enabled", "1")
on = _toggle_on(raw)
```
Resolution order: `user_settings(artist.user_id, key)` → hard-coded default.
**No site_config fallback** for these per-user toggles by design —
admin-set rows must not silently override an unset user toggle.
`_toggle_on()` returns False for `"0"|"false"|"False"|""`, True otherwise.

Removed toggles (do not re-add):
- `catchup_enabled` — replaced by the explicit dashboard "Catch up
  missed slots" button (`POST /promotion/catchup`). Auto-catchup on
  resume was a footgun that fired surprise `now+30s` posts.

UI placement:
- Per-user toggles: `frontend/src/app/settings/page.tsx`.
- Admin-only / global: `frontend/src/app/admin/page.tsx`.

---

## 7. Background loops cadence

| Loop | Cadence | What it does |
|------|---------|--------------|
| Planner | 300s | Materializes today's slots per active artist. Skips if `paused_reason` set. **Calls `evaluate_pause` BEFORE the early-exit when there are no slots** — so an artist whose pool went exhausted between ticks gets paused on the next planner cycle (no post needed). Auto-catchup is gone; missed slots stay missed unless the user clicks "Catch up missed slots". |
| Dispatcher | 60s | Stale-claim recovery flips `posting` rows >30m old back to `scheduled`. Atomic claim (`SKIP LOCKED`) up to 50 rows/tick. After each successful post calls `evaluate_pause`. |
| View poller | `view_poll_interval_seconds` (default 180, clamped 60–3600) | Refreshes view counts. Sleeps in 30s chunks so admin changes propagate fast. Staleness gate fixed at 30s — decoupled from interval to avoid 2x cadence drift. SKIPS rows where `deleted_at IS NOT NULL`. **YouTube quota backoff**: on 403 `quotaExceeded`, sets a process-level `_yt_quota_exhausted_until = next midnight US/Pacific` and skips ALL YouTube rows (batch + per-row fallback) until then — prevents the 100+ identical-error log spam we saw in prod. Other platforms keep refreshing. |

---

## 7b. Per-variation fan-out (planner shape)

For each slot, for each variation that isn't paused
(`directory_exhausted` / `no_clips` / `manual`):

1. `_pick_next_clip(artist_id, variation_id)` returns ONE clip from the
   variation's scope: `clips.artist_account_id = variation_id` OR
   `clips.artist_account_id IS NULL` (shared pool). Order:
   least-posted-by-this-variation first, tie-broken by oldest
   `last_posted_at` for this variation, then `c.id` ASC. Excludes
   clips already queued (status in `scheduled|posting`) for the same
   variation.
2. That same clip is scheduled across **every platform** the variation
   has tokens for — TikTok, YouTube, Instagram, Facebook.

So a 5-variation artist with all 4 platforms connected per variation
fires up to **5 unique clips × 4 platforms = 20 posts per slot**. Same
clip across one variation's 4 socials (the "brand identity" idea);
different clips across different variations (look like independent
accounts to platform reuse-detection). Diversification adds a
re-encoding layer on top so the same clip on a different variation
fingerprints differently to the platform.

---

## 8. Diversifier vs passthrough

**Diversification ON** (default; per-user toggle):
- Source: GDrive direct URL → downloaded to a temp file.
- ffmpeg: `crop=trunc(iw*p/2)*2:trunc(ih*p/2)*2,scale=trunc(iw/p/2)*2:trunc(ih/p/2)*2,eq=...,hue=...`. Crop pct 0.97–0.99 random per (clip, var, platform). Color jitter is INTENTIONALLY tiny (≤±0.01 brightness, ≤±0.01 sat, ≤±0.5° hue) — earlier wider values plus a `noise=alls=N` filter caused visible grain on TikTok's player. Noise filter dropped entirely.
- **Audio passthrough** (`af="anull"`). Earlier `asetrate*pitch+atempo` chain caused TT A/V drift ("pausing and playing" the user reported).
- Output: `uploads/variation_renders/{clip_id}/v{variation_id}_{platform}.mp4`. H.264 + AAC, libx264 veryfast, CRF 22–26 random.
- **Atomic write**: render to `out.with_suffix(out.suffix + f".partial.{uuid4().hex[:8]}")` then `os.replace`. Per-run unique partial path so concurrent renders don't race on the same partial.
- Cache reuse: `ffprobe -show_format` validates the cached file before reuse — leftover broken cache from crashes is auto-detected and re-rendered.

**Passthrough mode** (diversification OFF):
- Source downloaded once to `uploads/passthrough_clips/{clip_id}.mp4`.
- Probe codec via `_probe_video_codec()`. If H.264 → keep. Anything else (HEVC, VP9) → `_transcode_to_h264()`. **TikTok accepts H.265 at the upload API but its player renders it glitchy** — always transcode.
- Served via `icreateflow.com/api/files/...` so TikTok sees the verified domain.

Both modes go through `public_url_for(local_path, public_base)` which
builds `{public_base}/api/files/{url-encoded-rel-path}`. The
`/api/files/{file_path:path}` endpoint in `main.py` resolves first by
literal path then by prepending `uploads/`, `output/`, `music/`.

---

## 9. Deletion detection / monotonic view counts

### Monotonic counts
Every view_count write is `max(new, prev)`. Belt-and-braces guard so a
spurious 0 from any platform API never wipes a real number. This rule
fixed an incident where Meta returned 0 transiently for working FB
posts and we lost ~1,373 views in one bad poll cycle.

### Deletion detection
Only `PostDeletedError` from an adapter sets `deleted_at`. No more
"may be deleted/hidden" log entries — silenced entirely. Dashboard
count drop is the only signal.

| Platform | Detection signal |
|----------|------------------|
| TikTok | `data.videos = []` (empty) on `/video/query/?fields=view_count`. Plus 1h staleness for unresolved publish_ids — pre-token check so it fires even for variations that lost their TT token. |
| YouTube | Empty `items` on `/youtube/v3/videos?id=...`. |
| Instagram | Existence probe `?fields=id` before insights. 4xx with `does not exist` / `unsupported get request` / `code:100` → deleted. |
| Facebook | Combined `?fields=id,views`. Same Meta error sniffs as IG. |

Dashboard count queries (in `main.py`):
- `/api/artists/{id}/dashboard` — filters `deleted_at IS NOT NULL`.
- `/api/artists` (artist list) — same filter on `posts_count` AND `views_total`.
- `/api/admin/artists` — same.

One-shot audit endpoint: `POST /api/admin/clip-posts/audit-deleted`.
Bypasses staleness gate by clearing `view_count_updated_at` on every
alive posted row, runs a single `poll_views_once()`, returns
`{alive, deleted}` counts.

---

## 10. Platform constraints we've hit

### TikTok
- **`unaudited_client_can_only_post_to_private_accounts`** — until
  TikTok approves the app, posting only works to TT accounts that are
  set to private (NOT the post privacy — the user account must be
  private). We default `tiktok_privacy_level=SELF_ONLY` per
  `site_config`.
- **`url_ownership_unverified`** — source URLs must be on a domain
  verified in the TikTok Developer Portal (icreateflow.com). Raw
  GDrive URLs are rejected. Diversifier and passthrough both wrap
  source in `icreateflow.com/api/files/`.
- **PULL_FROM_URL spec** (per
  https://developers.tiktok.com/doc/content-sharing-guidelines):
  unaudited clients limited to ~5 users per 24h, SELF_ONLY only.
  Audited clients ~15 posts/day per creator. No watermarks/promo
  logos. Commercial content disclosure required.
- **HEVC**: API accepts H.265 but the player renders it glitchy.
  Always transcode to H.264. Diversifier uses libx264; passthrough
  probes codec and transcodes if non-H.264.
- **Publish ID flow**: `/post/publish/video/init/` returns a
  `publish_id` (e.g. `v_pub_url~v2-1.7633...`). Not a valid video_id
  for `/video/query/`. `resolve_video_id()` upgrades it via the user's
  recent uploads. Until resolved, the row is effectively dead — we
  flag stale at >1h via the pre-token check in `poll_views_once`.

### Meta (IG + FB)
- **`code:190` — missing scopes**. Requires `pages_read_engagement`
  (FB) / `instagram_manage_insights` (IG). Re-OAuth users sometimes
  silently lose these because Meta's consent dialog DEFAULTS the
  "read" scopes to OFF. Users must expand "Edit access" and tick every
  permission. We can't grant them server-side.
- **IG Business link**: an IG account must be linked to an FB Page
  via Page Settings → Linked accounts before our adapter can post.
  Container errors with `status_code=ERROR` on first publish typically
  mean missing link OR the IG account is still on Personal mode.
- **Meta pending assignments** (multi-asset OAuth): a single FB OAuth
  grant can authorize multiple Pages + IG accounts. Our flow stashes
  the pending asset list under a `meta_pending_assignments` token and
  asks the admin which to assign. **Stored in DB** (not memory) since
  multi-worker deployment.

### YouTube
- **Shorts cap**: 60s. Brand-side video builder uses `PLATFORM_PROFILES`
  in `services/video.py` to compute per-slide dwell that fits. For
  clipping pipeline we trust the source is short enough (no automatic
  trim).
- **Empty items = deleted/private/stale-id** — caught explicitly.

### IG / FB Reels
- 90s cap.

---

## 11. Deploy & runbook

### Deploy (always run from laptop)
```bash
git push && bash deploy/sync.sh && \
  ssh root@187.124.231.108 'bash /srv/icreateflow/src/deploy/deploy.sh'
```

### SSH access
```bash
ssh root@187.124.231.108
```

### Postgres
```bash
sudo -u postgres psql icreateflow
```

### Backend service
```bash
systemctl status icreateflow-backend
journalctl -u icreateflow-backend -f
```
Runs as `icreateflow` user via:
`gunicorn main:app -k uvicorn.workers.UvicornWorker -w 2 -b 127.0.0.1:8100`.
`PrivateTmp=true` (own /tmp namespace under /var/tmp).
`EnvironmentFile=/srv/icreateflow/backend/.env`.

### Frontend service
```bash
systemctl status icreateflow-frontend
```

### Persistent data
`/srv/icreateflow/backend/{output,uploads,music}` are SYMLINKS to
`/srv/icreateflow/data/*`. The `deploy.sh` script enforces this so
`rsync --delete` doesn't wipe persistent state across deploys.

### Quotas
Filesystem quota on `/dev/sda4` for the `icreateflow` user is **10GB**
(was 2GB — raised after EDQUOT errors during diversifier).
```bash
sudo repquota /dev/sda4 | grep icreate
sudo setquota -u icreateflow 10485760 10485760 0 0 /dev/sda4
```

### Force one-shot view audit
- HTTP: `POST /api/admin/clip-posts/audit-deleted` (admin auth).
- CLI:
  ```bash
  ssh root@187.124.231.108 'sudo -u icreateflow bash -c "
    set -a; source /srv/icreateflow/backend/.env; set +a
    cd /srv/icreateflow/backend
    /srv/icreateflow/venv/bin/python -c \"
      import asyncio
      from services.clip_scheduler import poll_views_once
      asyncio.run(poll_views_once())
    \"
  "'
  ```
  The `set -a; source .env` is required — DB password isn't in the
  user's environment by default.

---

## 12. Open follow-ups

1. **Residential proxy per variation** — IMPLEMENTED. `proxy_url`
   column on `artist_accounts`, threaded through every
   `httpx.AsyncClient` in posting adapters + OAuth refresh + view
   poller. Per-variation UI on the campaign dashboard. Provider choice
   still up to operator (Smartproxy / IPRoyal etc.). Sticky session per
   account is the operational requirement.
2. **Persist OAuth granted scopes** on the variation row reliably so
   we can flag missing-scope tokens up-front instead of silently
   returning 0 views.
3. **TLS fingerprint hardening (curl-cffi)** — speculative, only
   needed if TikTok escalates beyond IP-based blocking.
4. **YouTube Data API quota raise** — default 10k/day works while the
   batched poll keeps daily usage <300, but a multi-artist deploy will
   hit the wall. The quota-exhausted backoff prevents log spam, but
   the cure is a quota increase request via Google Cloud Console.

---

## 13. Common operational recipes

### Stale `posting` row (worker crash mid-upload)
Auto-recovered within 30 minutes by the dispatcher's stale-claim
recovery (top of `dispatch_due_once`). No action needed.

### Artist stuck in `directory_exhausted` but you want to fire
- UI: click the chip on the dashboard (clickable for ALL paused
  reasons as of recent fix).
- DB: `UPDATE artists SET paused_reason=NULL WHERE id=X;`

### Variation stuck in `no_clips`
The variation has no per-variation Drive folder AND the shared pool is
empty. Two ways out:
- Set the variation's Drive folder URL on the dashboard and click Sync.
- Or upload an MP4 directly via the per-variation Upload button.
The planner clears the pause within one tick once a postable clip
appears (via `maybe_resume_on_new_clip` → `evaluate_variation_pause`).

### YouTube view polling silently stalled
Check the process-level backoff:
```bash
journalctl -u icreateflow-backend | grep "quota exhausted; pausing YouTube"
```
The flag lives in process memory and clears at the next midnight US/Pacific
or on a backend restart. To force-clear before reset:
```bash
sudo systemctl restart icreateflow-backend
```

### False bulk deletions (e.g. Meta returned 0 spuriously)
```sql
UPDATE clip_posts SET deleted_at=NULL
WHERE platform='facebook' AND deleted_at > '2026-04-27';
```
Going forward, monotonic counts prevent this entirely. Old data is
gone unless the platform API returns the historical numbers.

### Duplicate fires (planner double-picked a slot)
Not possible anymore — slot-level unique partial index. If you see
duplicates, check the index: `\d clip_posts` in psql, look for
`clip_posts_no_dup_slot`.

### EDQUOT during diversifier
1. Clear regenerable caches:
   ```bash
   rm -rf /srv/icreateflow/data/uploads/{variation_renders,passthrough_clips}/*
   ```
2. Bump quota:
   ```bash
   sudo setquota -u icreateflow 10485760 10485760 0 0 /dev/sda4
   ```

### TikTok upload glitches / unsupported on download
Verify the variation_render is H.264 + AAC:
```bash
ffprobe -v error -show_streams /srv/icreateflow/data/uploads/variation_renders/{clip_id}/v{var}_tiktok.mp4
```
Should be `codec_name=h264`, `codec_name=aac`. If HEVC, the source
came in HEVC — check that the diversifier fired (it always re-encodes
to H.264) or that passthrough's HEVC→H.264 transcode ran.

### Re-fire specific clip on specific platforms
```sql
-- Stage: insert N scheduled rows at NOW
INSERT INTO clip_posts (clip_id, artist_account_id, platform, scheduled_for, status, artist_id, campaign_id, clip_filename)
SELECT {clip_id}, aa.id, '{platform}', NOW(), 'scheduled', {artist_id}, {campaign_id}, '{filename}'
FROM artist_accounts aa
WHERE aa.id IN ({var_ids}) AND aa.{platform}_token IS NOT NULL;
-- Unpause for dispatch
UPDATE artists SET paused_reason=NULL WHERE id={artist_id};
-- Wait 60-300s for dispatcher; then verify and re-pause
```

---

## 13b. Brands-side reference

The slideshow-scaling pipeline. Independent code path from Clipping —
no shared schema, no shared scheduler.

### Pipeline

```
TikTok URL ──▶ tiktok_scraper.py ──┐
   OR                               ├──▶ slides table (master_image_path)
   manual upload ──▶ /upload-slides ┘
                                     │
                                     ▼
                          services/ocr.py (Claude vision)
                          → title_text / body_text / cta_text
                                     │
                                     ▼
                  user edits slide type (hook/content/cta) + has_face
                                     │
                                     ▼
                  per (slide × account) → variations table:
                      action = keep | replace | generate
                      generate → services/flux.py (Replicate Flux)
                                     │
                                     ▼
                  POST /api/posts/{id}/generate
                      → services/generator.py
                          → services/overlay.py  (Pillow text overlay)
                          → services/video.py    (ffmpeg 9:16 + music)
                              uses PLATFORM_PROFILES per platform
                      writes outputs.{video_path,youtube_video_path,...}
                                     │
                                     ▼
                  PUT /api/posts/{id}/schedule
                      sets posts.scheduled_time + per-platform sub-times
                                     │
                                     ▼
                  user fires posts manually (no Brands dispatcher loop)
                  → adapter.upload_video() in services/posting/{tt,yt,ig,fb}.py
```

**Key difference vs Clipping**: there is NO automated background loop
that picks up `posts.status='scheduled'` and fires them. Brands posts
are dispatched via direct user action / endpoint calls. If you need
auto-dispatch for Brands later, add it to the lifespan in `main.py:31`
alongside the existing `clip_scheduler.start_background_tasks()`.

### Critical files

| Path | What's there |
|------|--------------|
| `backend/services/ocr.py` | Claude-vision OCR. Reads `ANTHROPIC_API_KEY` env var. Returns title/body/cta per slide. |
| `backend/services/overlay.py` | Pillow text overlay. Reads overlay defaults from the `settings` table. |
| `backend/services/video.py` | ffmpeg 9:16 video assembly. `PLATFORM_PROFILES` caps per platform (YT Shorts ≤60s, IG/FB Reels ≤90s, TT no hard cap). |
| `backend/services/flux.py` | Replicate Flux face-replacement. Reads `REPLICATE_API_TOKEN` env var. |
| `backend/services/generator.py` | Orchestrates the full post-generation pipeline (overlay → video for all variations). |
| `backend/services/tiktok_scraper.py` | TikTok slideshow URL → slide images. yt-dlp fallback. |
| `frontend/src/app/brands/page.tsx` | Brand + account management. |
| `frontend/src/app/posts/page.tsx` | Posts library. |
| `frontend/src/app/posts/new/page.tsx` | 4-step create/edit wizard (import → edit → variations → generate+schedule). |
| `frontend/src/app/music/page.tsx` | Music library upload + listing. |
| `frontend/src/app/schedule/page.tsx` | Calendar view of scheduled posts. |

### Data model

| Table | Notes |
|------|-------|
| `brands` | `(id, user_id, name, slug, background_color, timezone, default_post_times)`. `slug` is unique. `default_post_times` is comma-sep HH:MM. |
| `accounts` | Per-brand sub-account, one row per platform handle. `role ∈ ('master','variation')`. Holds OAuth tokens + scopes per platform. |
| `posts` | `(brand_id, date, post_number, caption, scheduled_time, scheduled_at, status)`. `status ∈ ('draft','scheduled','generating','posting','posted','failed')`. Per-platform `*_music_track_id` FKs. |
| `slides` | `(post_id, slide_number, type, has_face, title_text, body_text, cta_text, master_image_path)`. `type ∈ ('hook','content','cta')`. |
| `variations` | `(slide_id, account_id, action, replacement_image_path, generated_prompt, status)`. `action ∈ ('keep','replace','generate')`. `status ∈ ('pending','generated','approved')`. |
| `outputs` | `(post_id, account_id, slides_dir, video_path, youtube_video_path, instagram_video_path, facebook_video_path, posting_status, *_posted)`. One row per (post × account). |
| `music_tracks` | `(user_id, name, genre, file_path, duration, is_custom, is_public, platforms_allowed)`. |

### Brands ≠ Clipping notes

- **No FK overlap.** Brands lives in `brands/accounts/posts/slides/variations/outputs`; Clipping lives in `artists/artist_accounts/clips/clip_posts/campaigns`. Both reference `users.id` — that's the only join.
- **OAuth tokens live in two parallel column sets** — `accounts.tiktok_token` etc. for Brands, `artist_accounts.tiktok_token` etc. for Clipping. Connecting a platform on the Brands side does NOT auto-connect it on the Clipping side and vice versa. Same OAuth code path (`services/oauth.py`), separate persistence.
- **Posting adapters are shared.** `services/posting/{tiktok,youtube,instagram,facebook}.py` are called by both sides. `PostingError` / `PostDeletedError` are the common error types.
- **Scheduler reach is one-sided.** `services/clip_scheduler.py` only reads the Clipping tables. It will never plan, dispatch, or poll views for a Brands `Post`.
- **Music library is Brands-only** — `music_tracks` is referenced by `posts.*_music_track_id`. The Clipping pipeline doesn't touch it; clips bring their own audio.
- **Settings split is the same on both sides.** Per-user toggles in `user_settings`; global in `site_config`; legacy API keys / overlay defaults in `settings`. See §6.

---

## 14. Lessons / pitfalls (do not relearn the hard way)

- **`database.execute()` shim auto-appends `RETURNING id` to INSERTs.**
  Tables without an `id` PK fail. Tables with `id` work. `DELETE …
  RETURNING` is NOT surfaced — wrapper silently drops the rows. Use
  SELECT-then-DELETE.
- **Local imports inside `lifespan` don't escape to module scope.**
  Always module-import services that endpoints reference. We hit this
  twice (`clip_scheduler` NameError in `toggle_pause` and in
  `maybe_resume_on_new_clip` callsites).
- **Multi-worker FastAPI under gunicorn = NO in-memory state shared
  across workers.** Always persist OAuth handoffs and similar to DB.
  Hit this on `_PENDING_META_ASSIGNMENTS` (~50% miss rate under -w 2).
- **TikTok publish_id ≠ video_id.** Must call `resolve_video_id`
  before any `/video/query/`. Until resolved, the row is effectively
  dead — flag stale at >1h via pre-token check.
- **Meta consent screens default-uncheck "read" scopes.** Users must
  manually tick them. We can't grant them server-side.
- **`asetrate * pitch + atempo`** audio chains create A/V drift on
  TikTok's player even if ffmpeg accepts the math. Either skip audio
  mods entirely or use only sample-accurate filters.
- **GDrive serves HEVC for some uploads.** TikTok's player can't
  decode H.265 cleanly even if the API accepts it. Always transcode
  to H.264 when passing through.
- **Concurrent ffmpeg renders on the same cache key race.** Solved by
  per-run unique `.partial.<uuid8>` so each ffmpeg has its own
  scratch file; whichever `os.replace` wins is fine since the seed is
  deterministic.
- **View-count poll loop and staleness gate must be decoupled.** If
  staleness threshold == loop interval, rows last polled at T are
  exactly `interval` old at the next tick and get excluded by the
  strict `<` comparison — effective cadence becomes 2× configured.
  Fixed at 30s buffer.
- **Auto-catchup on resume was removed.** Earlier we had a
  `catchup_enabled` toggle that inserted a `now+30s` row when the
  planner saw today's slots as "missed". It surprised users on every
  resume (manual unpause OR fresh-clip auto-resume). Replaced by the
  explicit dashboard "Catch up missed slots" button — opt-in per click,
  not a global toggle.
- **Per-variation pause must be evaluated EVERY planner tick, not just
  after a post.** `evaluate_pause` used to run only post-success and
  post-poll. Once a campaign was exhausted (no posts firing), nothing
  triggered the pause flip — the dashboard sat on "Running" forever.
  Now hoisted to the top of `plan_slots_once` per artist.
- **`directory_exhausted` uses the GLOBAL post log, not per-variation.**
  `_has_unposted_clip_for_variation` previously asked "has THIS
  variation posted this clip?" — which kept Vibesofmoon "running"
  even when every clip had been posted by SOME variation. The user-
  facing notion of "directory used up" is global across the campaign.
- **A variation with no in-scope clips needs an explicit `no_clips`
  pause.** Previously it just sat silently as "Running" while never
  posting. Now flagged with an amber chip; rolls up to artist-level
  `directory_exhausted` alongside actually-exhausted variations.
- **Per-user toggles must NOT fall back to site_config.** The old
  `_user_or_site_setting` helper let admin-set site_config rows
  silently override unset user toggles. Renamed to `_user_setting`,
  user_settings only, hard-coded default if unset.
- **Dashboard "Posts today" must use the artist's timezone.** Computing
  `today` as `datetime.now(timezone.utc).date()` made yesterday's late
  posts in US/Eastern show up as "today" until UTC midnight rolled
  over. Use `ZoneInfo(artist.timezone)`.
- **YouTube quota errors must be suppressed at the source, not by
  log-volume gating.** Once the daily 10k Data API quota is gone, the
  view poller hits 403 on every queued YT row. Solution: a dedicated
  `YouTubeQuotaExhausted` exception + process-level
  `_yt_quota_exhausted_until` set to next midnight US/Pacific. Skips
  ALL YouTube polling until reset; logs ONCE per quota event.
- **Meta APIs sometimes return 0 for working posts.** Never wipe a
  view_count on drop-to-zero — keep the previous higher value. Real
  deletions are caught via the existence probe (`?fields=id`) before
  insights, which 4xx's cleanly when the post is gone.
- **`/admin` is for global config; `/settings` is per-user.** Don't
  put per-user toggles in admin or vice versa.
