# Project Memory — icreateflow.com

> Session memory for Claude and any dev picking this up cold.
> Heavy on exact file paths and symbol names so neither audience has to grep.
> Last updated: 2026-09-04.

---

## 1. What this is

Multi-account social-media auto-poster. Two completely separate pipelines:

| | Brands | Clipping | Audio-to-Video |
|---|---|---|---|
| Source content | TikTok slideshow URL or uploaded slides | Short video clips (Google Drive sync or upload) | Uploaded music track (MP3/WAV/M4A) |
| Pipeline | OCR → text edits → per-account variation (keep/replace/Flux) → text overlay → 9:16 video → schedule → post-now | Plan slots → diversify (or passthrough) → upload → poll views → auto-pause | Upload → Whisper transcribe → split clips → edit lyrics → Overlay Studio → export MP4 → assign to variation |
| Dispatch trigger | Manual (`POST /api/posts/{id}/post-now`) | 4 async background loops in `clip_scheduler.py` | Manual assign to variation |
| Emails | ⏰ Reminder 1h before `scheduled_time` + 🎉 HURRAY after dispatch | ⏰ Reminder 1h before `scheduled_for` + 🎉 HURRAY after each post batch | None |
| Tables | `brands`, `accounts`, `posts`, `slides`, `variations`, `outputs`, `music_tracks` | `artists`, `campaigns`, `artist_accounts`, `clips`, `clip_posts`, `clip_caption_variants` | `audio_tracks`, `audio_words`, `audio_clips`, `audio_video_clips` |
| Services | `ocr, overlay, generator, video, flux, tiktok_scraper` | `clip_scheduler, variation_processor, gdrive, caption_variants` | Whisper (OpenAI), ffmpeg split, client-side canvas/MediaRecorder export |
| Frontend | `app/{brands,posts,posts/new,music,schedule}/` | `app/clipping/[slug]/` | `app/clipping/audio-to-video/page.tsx` |
| Shared | `users`, `settings`, `user_settings`, `site_config`, `meta_pending_assignments`, `error_logs`, `services/{auth,oauth,email,posting/*}.py` |

**Do NOT conflate the three pipelines** — they share auth and the artist/variation model but otherwise nothing.

Stack: FastAPI 0.135 + Postgres 16 + asyncpg backend, Next.js 16 (Turbopack) frontend,
gunicorn **`-w 1`** + uvicorn worker, Apache reverse proxy, all on one VPS at `icreateflow.com` (`95.111.228.80`).

---

## 2. Repo layout

```
.
├── backend/        FastAPI app, services, posting adapters
├── frontend/       Next.js 16 dashboard
├── deploy/
│   ├── ship.sh         ★ ONE COMMAND DEPLOY — always use this
│   ├── deploy.sh       Server-side: git archive → pip/npm/restart (no git ops)
│   ├── sync.sh         First-time only: rsync code to server before server-setup
│   ├── server-setup.sh One-time AlmaLinux 9 bootstrap
│   ├── apache/         Apache vhost config
│   ├── systemd/        icreateflow-{backend,frontend}.service
│   └── .env.example    Backend env template
├── README.md
└── memory.md       This file
```

`.gitignore` excludes: `node_modules/`, `.next/`, `__pycache__/`, `venv/`, `*.db`, `output/`, `.env*`, `backend/{uploads,output,music}`.

---

## 3. Architecture — Clipping pipeline

```
GDrive sync / upload
        │
        ▼
  clips table
  (source, gdrive_file_id, artist_account_id, times_posted, …)
        │
        │  _pick_next_clip (least-posted, variation-scoped)
        ▼
  clip_posts table (one row per variation × platform × slot)
  status: scheduled → posting → posted | failed
        │
        │  scheduled_for <= NOW()
        ▼
  dispatch_due_once (every 60s)
  atomic claim SKIP LOCKED → diversify/passthrough → adapter.upload_video
  → status=posted, platform_post_id, send HURRAY email
        │
        ▼
  poll_views_once (every view_poll_interval_seconds, default 180s)
  → send pre-post reminders (Clipping + Brand)
  → adapter.get_view_count (monotonic max)
  → PostDeletedError → deleted_at
```

---

## 4. Audio-to-Video (A2V) pipeline

### Overview

A2V is a 3-step wizard under `/clipping/audio-to-video`. An artist uploads a music track; it gets split into clips with Whisper word timestamps; each clip gets an Overlay Studio where the user picks a template, edits lyrics, and exports a karaoke-style 9:16 MP4 that can be assigned to a variation (clip) in the Clipping pipeline.

### Data model

| Table | Key columns | Notes |
|---|---|---|
| `audio_tracks` | `artist_id`, `local_path`, `duration_s`, `transcription_status` (pending/processing/done/failed), `transcription_error` | One per uploaded track. `local_path` is relative to `/srv/icreateflow/data/`. |
| `audio_words` | `audio_track_id`, `clip_index`, `word`, `start_s`, `end_s` | **Absolute** timestamps from full track start (not clip-relative). `clip_index` matches `audio_clips.clip_index` for the same track. |
| `audio_clips` | `audio_track_id`, `clip_index`, `start_s`, `end_s`, `local_path`, `lyrics_text` | 1, 3, or 5 equal segments created by `POST /api/audio-to-video/{id}/split`. `lyrics_text` = user-edited multi-line text (newline = line break). If NULL/empty → auto-generated from words (5 per line). |
| `audio_video_clips` | `audio_clip_id`, `artist_account_id` (NULL=shared), `template_id`, `lyrics_mode`, `background_image_path`, `album_cover_path`, `video_path`, `status`, `render_progress` | One settings row per clip per variation. `lyrics_mode` ∈ `karaoke\|scroll`. |

### Timing critical detail

`audio_words.start_s` / `end_s` are **absolute seconds from the start of the full track** — NOT clip-relative. The RAF tick converts: `tAbs = audio.currentTime + clip.start_s` before binary-searching the word array.

### Karaoke sync algorithm (as of 2026-05-26)

**File:** `frontend/src/app/clipping/audio-to-video/page.tsx`

1. **`activeKaraokeLyrics`** (`useMemo`) — converts `clipLyricsText[clipId]` (or Whisper auto-text) to `string[][]` (lines of words).
2. **`wordTimings`** (`useMemo`) — builds a flat `WordTiming[]` array: `{startAbs, endAbs, lineIdx, wordIdx}` per display word.
   - **1:1 case** (display word count == Whisper word count — the auto-generated default): each display word maps directly to its Whisper word's exact timestamps.
   - **Mismatched case** (user edited lyrics, word count changed): total audio time distributed evenly across display words — smooth, no jumps.
3. **RAF tick** — binary searches `wordTimings` by `tAbs` → `setOverlayLineIndex` / `setOverlayWordIndex`.
4. **Monotonic guard** — `wordIdx` never steps backward within the same line during forward play.

### Key refs and state

```typescript
// Audio
const audioPreviewRef    // hidden <audio> element
const lastAudioTimeRef   // backward-seek detection
const userSeekingRef     // suppresses backward-seek guard during programmatic seeks
const seekAudio = (a, t) => { userSeekingRef.current=true; a.currentTime=t; setTimeout(()=>{userSeekingRef.current=false},150); }

// Editing debounce
const editingLyricsRef   // true while user is typing; freezes RAF setState
const editingTimeoutRef  // clears editingLyricsRef 400ms after last keystroke

// Karaoke
const wordTimingsRef     // ref copy of wordTimings memo
const activeKaraokeLyricsRef  // ref copy of lyrics lines
const lastLineIdxRef, lastWordIdxRef  // gate setState — only fire when changed
```

### Export flow

- **Overlay Studio** renders a live HTML preview in the browser (canvas + CSS).
- **Export** uses `getDisplayMedia` to screen-capture the preview `<div>`, crops to 9:16 via canvas, and records with `MediaRecorder` → WebM → server converts to MP4 via ffmpeg.
- Export progress tracked via `exportProgress` state (0–100), driven from the same RAF loop.

### Lyrics persistence

`PUT /api/audio-to-video/clips/{clip_id}/lyrics` — saves `lyrics_text` (string) and optionally a `words` array. The backend **only replaces words if `data.words` is non-empty** — passing `words=[]` keeps the existing Whisper timestamps intact. The frontend always sends `words=[]` so Whisper data is never overwritten.

### Templates

`template_id` ∈ `minimal | vibrant | cinematic | neon`. Each template drives CSS variables for colors, fonts, and animation style in `<PreviewContent>`.

### Lyrics modes

- `karaoke` — active word highlighted in current line (word-by-word karaoke).
- `scroll` — Apple Music-style: all lines visible, active line centered and full-brightness, others dimmed.

---

## 6. Critical files

| Path | What's there |
|------|--------------|
| `backend/main.py` | All endpoints (~7500 lines). Lifespan starts 4 scheduler loops. A2V endpoints at `/api/audio-to-video/*`. |
| `backend/database.py` | ORM models, `init_db()`, all `_migrate_*` functions (idempotent `ALTER TABLE IF NOT EXISTS`). `Connection.execute()` auto-appends `RETURNING id` to INSERTs. A2V models: `AudioTrack`, `AudioWord`, `AudioClip`, `AudioVideoClip`. |
| `backend/services/clip_scheduler.py` | `plan_slots_once`, `dispatch_due_once`, `poll_views_once`, `sweep_clip_caches_once`, `_send_pre_post_reminders`, `_send_brand_pre_post_reminders`, `_pick_next_clip`, `_has_unposted_clip_for_variation`, `evaluate_pause`, `start_background_tasks`. |
| `backend/services/email.py` | `send_post_reminder_email`, `send_post_result_email`, `send_welcome_pending_email`, `send_password_reset_email`. SMTP config from `site_config`. No-op if `smtp_host` unset. |
| `backend/services/variation_processor.py` | `diversify()` (ffmpeg crop+eq+hue, atomic .partial write), `passthrough_download()`, `_transcode_to_h264()`. |
| `backend/services/posting/tiktok.py` | `upload_video` — unaudited client fallback to `INBOX` (draft) post mode if `unaudited_client_can_only_post_to_private_accounts`. |
| `backend/services/posting/{youtube,instagram,facebook}.py` | Upload + `get_view_count` + deletion detection. |
| `backend/services/oauth.py` | OAuth scopes + token refresh per platform. |
| `frontend/src/app/clipping/audio-to-video/page.tsx` | **A2V single-file app** (~2900 lines). 3-step wizard: upload/transcribe → split clips → Overlay Studio. Contains all karaoke sync logic (`wordTimings` memo, RAF tick, `seekAudio`, `editingLyricsRef`), all 4 templates, and both lyrics modes. |
| `frontend/src/app/clipping/[slug]/page.tsx` | Campaign dashboard. ConfirmModal for all destructive actions (stop, reset, delete variation, delete clip, clear failed posts). Variation cards: collapsible clip directory, paused_reason chips, TikTok settings accordion. |
| `frontend/src/components/ConfirmModal.tsx` | Reusable confirm dialog (replaces all `window.confirm` calls). |
| `backend/routers/outreach.py` | The one APIRouter in the codebase. Takes `get_current_user` / `admin_required` as arguments (`build_router`) so it never imports `main.py`, which imports it. `_account_public()` is the only place a sending account is serialized. |
| `backend/services/outreach/queue.py` | `enqueue_campaign`, `claim_job`, `complete_job`, `fail_job`, `reap_stale_jobs`, `start/pause/resume/stop_campaign`, `retry_failed`. All timestamps written as `NOW() AT TIME ZONE 'UTC'`. |
| `backend/services/outreach/accounts.py` | `lease_account` (SKIP LOCKED + cooldown + per-account cap), `record_success`, `record_failure` (auto-pause rule), `release_expired_leases`. |
| `backend/services/outreach/runner.py` | `OutreachWorker.process_one` — the claim → render → send → record cycle. `run_once()` is the seam the tests drive. `_maintenance_loop` is what the API process runs. |
| `backend/services/outreach/browser/` | Driver registry + `MessageResult`. `mock.py` for dry runs and tests, `playwright_tiktok.py` for real sends (selectors with fallbacks in `SELECTORS`). |
| `backend/tests/` | pytest suite for the outreach pipeline. Needs `ICREATE_TEST_DB_DSN`; skips the DB tests without it. Sends nothing — mock driver only. |
| `frontend/src/app/outreach/` | Campaign list, campaign detail (3s live poll), sending accounts, templates. `ui.tsx` holds the shared `StatusPill` / `ProgressBar` / helpers. |
| `deploy/ship.sh` | Local deploy script: git push + SSH server-sync + deploy.sh. Always use this. |
| `deploy/deploy.sh` | Server-side: `git archive HEAD backend/ \| tar -x`, then pip/npm/restart. No git operations — SRC is already correct when this runs. |

---

## 7. Data model

### `artists`
- `timezone` — IANA (e.g. `Africa/Lagos`); falls back to `US/Eastern`.
- `posts_per_day`, `window_start` / `window_end` (HH:MM).
- `paused_reason`: NULL | `manual` | `directory_exhausted` | `target_reached`.
- `is_active`, `current_campaign_id`, `view_target`.

### `artist_accounts` (variations)
Per-platform tokens: `*_token`, `*_refresh_token`, `*_expires_at`, `*_user_id`, `*_handle`, `*_scopes`.
Per-variation extras: `gdrive_folder_url`, `gdrive_folder_id`, `proxy_url`, `paused_reason`.
- `paused_reason`: NULL | `manual` | `directory_exhausted` | `no_clips`.

### `clips`
- `artist_account_id` (nullable FK): NULL = shared pool; set = exclusive to that variation.
- `source` ∈ `gdrive | upload`.
- `times_posted`, `last_posted_at` — bumped post-dispatch (NOT at plan time).

### `clip_posts`
- `status` ∈ `scheduled|posting|posted|failed`.
- `scheduled_for` NAIVE UTC.
- `view_count` MONOTONIC — never decreases.
- `reminder_sent_at` — set when reminder email fires; prevents re-send.
- `deleted_at` — set on `PostDeletedError`.
- Unique partial index on `(artist_account_id, platform, scheduled_for) WHERE status='scheduled'`.

### `posts` (Brands)
- `scheduled_time` TEXT (HH:MM), `date` TEXT (YYYY-MM-DD), `status` ∈ `draft|scheduled|generating|posting|posted|failed`.
- `reminder_sent_at` — set when brand reminder email fires; prevents re-send.

### `meta_pending_assignments`
Multi-asset OAuth handoff stored in DB (not memory — breaks under multi-worker gunicorn). Columns: `id`, `token`, `payload` (JSON), `created_at`.

### Settings tables
| Table | Scope | Contents |
|------|-------|----------|
| `user_settings` | per-user | `clip_diversification_enabled`, `clip_caption_variants_enabled` |
| `site_config` | global admin | SMTP config, `oauth_redirect_base`, `oauth_google_drive_api_key`, `view_poll_interval_seconds`, `tiktok_privacy_level`, `site_logo_url` (PNG, not SVG — email clients block SVG) |
| `settings` | global legacy | Anthropic/Replicate API keys, overlay defaults |

---

## 8b. Outreach pipeline

Fourth pipeline, added after the three above. Multi-account DM outreach:
targets → campaign → job queue → account manager → browser worker → result
processor → dashboard.

### Why Postgres is the queue

Same reason the Clipping dispatcher claims slots with `SKIP LOCKED`: campaign
state and queue state commit in one transaction, so a worker dying mid-send
cannot leave them disagreeing. No Redis, no Celery, no broker to operate.

### Process split (important)

| Process | Runs | Why |
|---|---|---|
| API (`gunicorn -w 1`) | `runner._maintenance_loop` — reaper only, every 120s | The API must never drive a browser: `-w 1` means one hung Playwright call blocks every request. |
| Worker (`scripts/outreach_worker.py`) | Leases accounts, claims jobs, sends | Separate systemd unit (`icreateflow-outreach-worker@N`); run as many as you like. |

### Exclusivity — the two leases

1. **Job lease** — `claim_job` sets `worker_id` + `lease_expires_at` inside
   `UPDATE … WHERE id = (SELECT … FOR UPDATE SKIP LOCKED)`. A partial unique
   index (`outreach_jobs_one_live_per_target`) additionally makes two live
   jobs for one target impossible, even from hand-written SQL.
2. **Account lease** — `accounts.lease_account` flips `status` to `active` and
   stamps `last_activity_at` under the same SKIP LOCKED pattern. Two workers
   driving one TikTok session is how an account gets flagged, so the lease is
   taken in the database, not in process memory. An expired lease
   (`last_activity_at` older than `outreach_job_lease_seconds`) counts as free.

### Crash recovery

`queue.reap_stale_jobs` requeues any `processing` job whose lease expired, and
fails the ones that crashed on their final attempt. Nothing lives in worker
memory, so that is the whole recovery story. Runs in the API process every
120s and inside each worker every 60s.

### Failure taxonomy (`services/outreach/constants.py`)

| Class | Statuses | Effect |
|---|---|---|
| Terminal for the target | `profile_unavailable`, `messaging_unavailable` | Target → `skipped`, no retry, account not blamed. |
| Account fault | `session_expired`, `rate_limited`, `browser_error` | Counts toward the account's consecutive-error streak. |
| Immediate pause | `session_expired` | Pauses the account at once — retrying an expired session only burns attempts. |
| Everything else | `navigation_timeout`, `unexpected_page`, `unknown_error` | Retried behind `backoff × attempt` until the retry limit. |
| Above the driver | `template_error` | `force_fail=True` — the same template and target fail identically next time. |

### Counters are recomputed, never incremented

`stats.refresh_and_maybe_complete` recomputes the campaign counters from the
target status histogram after every result. A crashed worker, a double-processed
job, or a manual DB fix can therefore never leave the numbers permanently
skewed — and it is what flips a campaign to `completed`.

### Admin controls

All in `site_config`, read per call so a change takes effect on the next worker
tick with no restart (`/admin → Outreach`): `outreach_max_jobs_per_campaign`,
`outreach_max_jobs_per_account`, `outreach_retry_limit`,
`outreach_worker_concurrency`, `outreach_account_error_threshold`,
`outreach_job_lease_seconds`, `outreach_retry_backoff_seconds`,
`outreach_min_send_interval_seconds`, `outreach_worker_idle_seconds`,
`outreach_driver`, `outreach_workers_enabled` (the "stop all workers" switch).
Campaigns override the first three per campaign.

### Browser layer

`services/outreach/browser/` is the only place that knows what a web page is;
nothing outside it imports Playwright. `get_driver(name)` resolves `mock` or
`playwright_tiktok` from a registry. Every driver returns a `MessageResult`
(`success` / `status` / `error` / `timestamp`) — an expected failure is never
an exception. `playwright_tiktok` keeps one `BrowserContext` per account (the
isolation boundary), closes only the *page* after a job, and keeps the context
so the session survives.

### Sessions

Captured on the server by `deploy/outreach-login.sh` → `backend/scripts/outreach_login.py`: Xvfb + x11vnc (localhost-bound, reached through an SSH tunnel) put a real browser on screen, the script polls for the platform's session cookie, and on success writes the encrypted `storage_state` straight into the account row. No file on disk, no copy-paste. Capturing on the server rather than a laptop is deliberate — an imported session moving to a new IP is the usual reason a fresh one gets challenged.

Never a password. The operator signs in themselves and uploads Playwright
`storage_state` JSON; `crypto.py` Fernet-encrypts it with
`ICREATE_OUTREACH_SECRET` (falling back to `ICREATE_JWT_SECRET`).
`routers/outreach.py:_account_public()` is the only serialization of an
account and drops the ciphertext entirely, exposing `has_session: bool`.
Rotating either secret makes stored sessions unreadable — those accounts must
be re-authorized.

---

## 8. Background loops

| Loop | Cadence | Key behaviour |
|------|---------|---------------|
| Planner | 300s | Per-variation integrity sweep first (cancels stale slots). Materialises today's slots. Calls `evaluate_pause` before early-exit. |
| Dispatcher | 60s | Stale-claim recovery (>30m `posting` → `scheduled`). Atomic claim SKIP LOCKED up to 50 rows/tick. Pre-dispatch stale-slot guard. Sends HURRAY email on success. |
| View poller | `view_poll_interval_seconds` (default 180s, clamped 60–3600) | Sends Clipping AND Brand pre-post reminders. Refreshes view counts (monotonic). Deletion detection. YouTube quota backoff (skips all YT until next midnight US/Pacific on 403). |
| Cache sweep | 86400s | Prunes `variation_renders` + `passthrough_clips` older than `cache_ttl_days`. |

| Outreach reaper | 120s | Requeues jobs a crashed worker was holding; frees stranded account leases. Started from `outreach_runner.start_background_tasks()`. Never sends. |

All Clipping loops started from `clip_scheduler.start_background_tasks()` called in `main.py` lifespan.
**`-w 1` gunicorn worker is mandatory** — multiple workers each run their own scheduler loop, causing duplicate emails and double-posts.

---

## 9. Per-variation fan-out

For each slot, for each non-paused variation:
1. `_pick_next_clip(artist_id, variation_id)` — least-posted for this variation; scope: `clips.artist_account_id = variation_id` OR shared pool (`IS NULL`).
2. Same clip scheduled across **every platform** the variation has tokens for.

5 variations × 4 platforms = up to 20 posts per slot. Same clip across one variation's socials; different clips across variations (dedup). Diversification re-encodes for fingerprint difference.

---

## 10. Diversifier vs passthrough

**Diversification ON** (default):
- ffmpeg: crop 0.97–0.99 + tiny color jitter (≤±0.01 brightness, ≤±0.01 sat, ≤±0.5° hue). No noise filter. Audio passthrough (`af="anull"`).
- Output: `uploads/variation_renders/{clip_id}/v{variation_id}_{platform}.mp4`. H.264 + AAC, CRF 22–26.
- Atomic write: `.partial.<uuid8>` → `os.replace`.
- Cache: `ffprobe` validates before reuse; broken cache auto-re-renders.

**Passthrough** (diversification OFF):
- Downloaded to `uploads/passthrough_clips/{clip_id}.mp4`.
- Transcoded to H.264 if HEVC/VP9 (TikTok player glitches on H.265 despite API accepting it).

Both use `public_url_for()` → `{oauth_redirect_base}/api/files/{encoded-path}` (TikTok requires verified domain).

---

## 11. Deletion detection & view counts

- **Monotonic counts**: every write is `max(new, prev)`. Prevents spurious 0 wipes.
- **Deletion**: only `PostDeletedError` sets `deleted_at`. Dashboard filters it out.

| Platform | Detection |
|----------|-----------|
| TikTok | Empty `data.videos` on `/video/query/`. Stale publish_id >1h flagged. |
| YouTube | Empty `items` on `videos.list`. |
| Instagram | Existence probe `?fields=id`; 4xx with `does not exist` / `code:100`. |
| Facebook | Combined `?fields=id,views`; same Meta error sniffs. |

---

## 12. Platform constraints

### TikTok
- **Unaudited client**: posting only works to private TT accounts. Default `SELF_ONLY`. Fallback to `INBOX` (draft) when `unaudited_client_can_only_post_to_private_accounts` error returned.
- **URL ownership**: source URLs must be on the verified domain (`icreateflow.com/api/files/`).
- **Brand posts**: TikTok post mode for drafts is `INBOX`, NOT `MEDIA_UPLOAD` (MEDIA_UPLOAD is unrecognised).
- **Publish ID ≠ video_id**: must call `resolve_video_id()` before view polling.
- **H.265**: API accepts but player renders glitchy — always transcode to H.264.

### Meta (IG + FB)
- **`code:190` — missing scopes**: consent dialog defaults "read" scopes OFF. Users must manually tick them.
- **IG Business link**: IG account must be linked to an FB Page before posting.
- **Multi-asset OAuth**: pending assignments stored in DB (`meta_pending_assignments`), not memory.

### YouTube
- **Shorts cap**: 60s.
- **Quota**: 10k/day Data API. Process-level backoff clears at midnight US/Pacific.

---

## 13. Deploy runbook

### Every code change — from your Mac:

```bash
bash deploy/ship.sh
```

That's it. ship.sh pushes to GitHub, waits for propagation, updates the server's git checkout to the exact SHA, then runs deploy.sh. **Never** run `deploy.sh` directly on the server without ship.sh having set up SRC first.

### SSH to server

```bash
ssh root@95.111.228.80
```

### View logs

```bash
journalctl -u icreateflow-backend -f
journalctl -u icreateflow-frontend -f
```

### Backend service

```bash
systemctl status icreateflow-backend
systemctl restart icreateflow-backend
```

Runs as `icreateflow` user: `gunicorn main:app -k uvicorn.workers.UvicornWorker -w 1 -b 127.0.0.1:8100`.

### Postgres

```bash
sudo -u postgres psql icreateflow
```

### Persistent data

`/srv/icreateflow/backend/{output,uploads,music}` → symlinks to `/srv/icreateflow/data/*`. `deploy.sh` enforces these on every deploy.

### Disk quota

```bash
sudo repquota /dev/sda4 | grep icreate
sudo setquota -u icreateflow 10485760 10485760 0 0 /dev/sda4   # 10 GB
```

### Force one-shot view audit

Admin UI: `POST /api/admin/clip-posts/audit-deleted`

CLI:
```bash
ssh root@95.111.228.80 'sudo -u icreateflow bash -c "
  set -a; source /srv/icreateflow/backend/.env; set +a
  cd /srv/icreateflow/backend
  /srv/icreateflow/venv/bin/python -c \"
    import asyncio; from services.clip_scheduler import poll_views_once
    asyncio.run(poll_views_once())
  \""'
```

### Browser cache after deploy

If the UI looks unchanged after a deploy — **hard refresh**:
- Chrome/Edge Mac: `Cmd + Shift + R`
- Or: DevTools → right-click refresh → "Empty Cache and Hard Reload"

---

## 14. Open follow-ups

1. **Persist OAuth granted scopes** on the variation row so missing-scope tokens surface up-front.
2. **TLS fingerprint hardening (curl-cffi)** — speculative; only if TikTok escalates beyond IP-based blocking.
3. **YouTube Data API quota raise** — default 10k/day; quota-exhausted backoff prevents log spam but the cure is a quota increase via Google Cloud Console.
4. **View-count undercount** (open since 2026-05-04) — DB values lower than in-app. Don't speculate without a side-by-side DB row + screenshot per platform. Hypotheses:
   - FB: `GET /{video_id}?fields=id,views` may undercount vs `/{video_id}/video_insights?metric=total_video_views`.
   - IG: both `views` and `plays` can 4xx silently if token lost `instagram_manage_insights` after re-OAuth.
   - TikTok: analytics index lags in-app counter by hours. No better API available.
   - YouTube: wrong `platform_post_id` would cause viewing the wrong video's stats.

---

## 15. Common operational recipes

### Artist stuck in `directory_exhausted`
- UI: click the pause chip on the dashboard (clickable for ALL pause reasons).
- DB: `UPDATE artists SET paused_reason=NULL WHERE id=X;`

### Variation stuck in `no_clips`
Set the variation's Drive folder URL on the dashboard and click Sync, or upload an MP4 directly. Planner clears pause within one tick.

### YouTube view polling silently stalled
```bash
journalctl -u icreateflow-backend | grep "quota exhausted; pausing YouTube"
systemctl restart icreateflow-backend   # clears the process-level flag immediately
```

### Stale `posting` row (crash mid-upload)
Auto-recovered within 30 min by the dispatcher. No action needed.

### False bulk deletions (Meta returned 0 spuriously)
```sql
UPDATE clip_posts SET deleted_at=NULL
WHERE platform='facebook' AND deleted_at > '2026-04-27';
```

### Clear diversifier cache to free disk space
```bash
rm -rf /srv/icreateflow/data/uploads/{variation_renders,passthrough_clips}/*
```

### Re-fire specific clip on specific platforms
```sql
INSERT INTO clip_posts (clip_id, artist_account_id, platform, scheduled_for, status, artist_id, campaign_id, clip_filename)
SELECT {clip_id}, aa.id, '{platform}', NOW(), 'scheduled', {artist_id}, {campaign_id}, '{filename}'
FROM artist_accounts aa
WHERE aa.id IN ({var_ids}) AND aa.{platform}_token IS NOT NULL;
UPDATE artists SET paused_reason=NULL WHERE id={artist_id};
```

---

## 16. Lessons / pitfalls (do not relearn the hard way)

- **`-w 1` gunicorn is mandatory for the scheduler.** With `-w 2`, both workers each run the full scheduler loop — duplicate emails, double-posts, HURRAY emails sent twice. The scheduler is stateful (process-level flags for YT quota, async task handles); it must run in exactly one process.

- **`deploy.sh` must NOT do git operations on itself.** The script is bootstrapped from the git working tree; if it resets that tree mid-run, the running bash process keeps executing whatever version was loaded at launch — potentially stale. Solution: `ship.sh` (local) owns ALL git ops (push → fetch-retry → reset → checkout) before calling `deploy.sh`. `deploy.sh` is a pure extract + build + restart script with no self-modifying git work.

- **GitHub CDN propagation lag.** After `git push`, the server's `git fetch` can grab an old `origin/main` if it runs within ~5 seconds. `ship.sh` retries fetch up to 5× (5s gaps) until the server sees the exact pushed SHA. Never call `deploy.sh` immediately after a manual push without this retry.

- **`git reset --hard` alone does NOT clear a corrupted git index.** A corrupt index (e.g. from aborted rsync mid-run) means `git reset --hard` succeeds but the working tree stays unchanged — old files persist on disk even though `git status` looks clean. Fix: `rm -f .git/index && git checkout HEAD -- .`. The deploy pipeline now does this automatically inside `ship.sh`.

- **`database.execute()` shim auto-appends `RETURNING id` to INSERTs.** Tables without an `id` PK fail. `DELETE … RETURNING` is NOT surfaced — use SELECT-then-DELETE.

- **Local imports inside `lifespan` don't escape to module scope.** Always module-import services that endpoints reference (hit this twice on `clip_scheduler`).

- **Multi-worker FastAPI = NO shared in-memory state across workers.** Always persist OAuth handoffs to DB. Hit on `_PENDING_META_ASSIGNMENTS` (~50% miss rate under `-w 2`).

- **TikTok publish_id ≠ video_id.** Must call `resolve_video_id` before `/video/query/`. Until resolved, the row is dead — flagged stale at >1h.

- **TikTok draft mode = `INBOX`, not `MEDIA_UPLOAD`.** `MEDIA_UPLOAD` is not recognised as a post mode. `INBOX` saves to drafts. `DIRECT_POST` posts publicly.

- **SVG in emails is blocked.** Gmail, Outlook, Apple Mail all strip SVG. Use PNG for the site logo in emails. `site_logo_url` in `site_config` must point to a `.png`.

- **Brand reminder emails must group by post, not by platform.** One reminder per scheduled post, not one per platform. Similarly, Clipping reminders group by `(artist_id, scheduled_for_minute)` — one email per batch.

- **Meta consent screens default-uncheck "read" scopes.** Users must manually tick `pages_read_engagement` / `instagram_manage_insights`. Can't grant server-side.

- **`asetrate + atempo` audio chains cause A/V drift on TikTok.** Use `af="anull"` (audio passthrough) in the diversifier.

- **GDrive serves HEVC for some uploads.** TikTok player glitches on H.265 even if the API accepts it. Always transcode to H.264 in passthrough.

- **Concurrent ffmpeg on the same cache key races.** Solved by per-run unique `.partial.<uuid8>` then `os.replace`.

- **View-count poll staleness gate must be < loop interval.** If equal, rows polled at T are exactly `interval` old at next tick and hit the `<` boundary — effective cadence doubles. Fixed at 30s buffer.

- **Auto-catchup on resume was removed.** `catchup_enabled` toggle caused surprise `now+30s` posts on every resume. Replaced by explicit "Catch up missed slots" dashboard button.

- **Per-variation pause must evaluate EVERY planner tick.** Once an artist stops posting (exhausted), nothing triggers the pause flip if evaluate_pause only runs post-success. Now hoisted to top of `plan_slots_once` per artist.

- **`directory_exhausted` uses the GLOBAL post log.** "Has this clip been posted?" is global across all variations — not per-variation. One variation posting it counts as posted for everyone.

- **Per-user toggles must NOT fall back to `site_config`.** `_user_setting()` reads `user_settings` only. Admin-set `site_config` rows must not silently override unset user preferences.

- **Per-variation slot dedup must be per-(variation_id, slot_time), not per-artist.** Old artist-level check meant one variation filling both daily slots blocked all other variations from ever getting slots. Fixed with a `(artist_account_id, scheduled_for_naive)` set membership check in the planner.

- **Dashboard "Posts today" must use artist's timezone.** `datetime.now(timezone.utc).date()` makes yesterday's late posts in US/Eastern show as "today" until UTC midnight. Use `ZoneInfo(artist.timezone)`.

- **YouTube quota errors: suppress at source.** Once 10k/day quota is gone, every YT row 403s. Process-level `_yt_quota_exhausted_until` skips all YT polling until midnight US/Pacific; logs once per event.

- **`paused_reason IS NULL` rejects empty strings.** An empty string `""` at that column silently blocks dispatch claims. Detect: `LENGTH(paused_reason) = 0`. Cleanup: `UPDATE artist_accounts SET paused_reason=NULL WHERE paused_reason IS NOT NULL AND LENGTH(TRIM(paused_reason))=0;`

- **Mapper "Unconsumed column names" = model/code drift, NOT DB drift.** Column exists in Postgres but missing from the running ORM class. Usually a deploy gap. `dispatch_due_once` wraps post-success bookkeeping: on this error, logs `scheduler.dispatch.schema_drift`, drops the offending kwarg, retries. Without this, a successful upload lands on the platform but the row gets stamped `failed`.

- **Standalone IG OAuth needs same-window redirect on mobile.** iOS deep-links `instagram.com/oauth` into the IG app, which can't postMessage back to a popup opener. Backend `_oauth_finish` emits 302 to `return_to` for the redirect flow; frontend drives popup or main-window navigation based on `flow` field.

- **IG container ERROR needs `status,error` fields.** `fields=status_code` alone gives nothing useful. Add `status,error` to surface `error_user_msg` / `error.message` — otherwise every IG publish failure looks identical.

- **`window.confirm()` is blocked by some browsers and inconsistent on mobile.** Use `ConfirmModal` (`frontend/src/components/ConfirmModal.tsx`) for all destructive actions. All `window.confirm` calls in the clipping dashboard have been replaced.

- **Whisper `audio_words` timestamps are absolute, not clip-relative.** `start_s` / `end_s` are seconds from the start of the full uploaded track. Clip 2 words may start at ~30s. The RAF tick must do `tAbs = audio.currentTime + clip.start_s` before searching word timestamps. Forgetting this puts the highlight ~30s behind.

- **A2V lyrics save must pass `words=[]`, never the current display words.** The old code merged display text words onto Whisper word objects (replacing 50 timed words with ~10 with bad timestamps). Always pass `words=[]` to `PUT /api/audio-to-video/clips/{id}/lyrics` — the backend only overwrites words when the array is non-empty.

- **Karaoke sync: proportional word-index mapping is wrong.** Mapping `displayPosition / totalDisplayWords * whisperWordCount` to find a Whisper word assumes even distribution, which is false — Whisper words are distributed by when they are spoken. The correct approach: 1:1 mapping when counts match (auto-generated text), even time distribution when mismatched (edited text).

- **A2V `wordTimings` must include `lineIdx`/`wordIdx` per entry.** If you binary-search a flat word timing array and return only a flat index, you still need to map back to `(lineIdx, wordIdx)` for the React state. Build these into each entry at memo time.

- **`loop` attribute on `<audio>` snaps karaoke to word 0 on every repeat.** Remove `loop`; use `onEnded` to pause cleanly and reset time. Add `key={clip.id}` so React unmounts/remounts the element when switching clips — prevents stale audio playing under new lyrics.

- **OpenAI image generation replaced Replicate/Flux.** A2V background images use `gpt-image-2` via OpenAI API. Per-user OpenAI API key stored in `user_settings`. Medium quality is the default (faster).

- **Playwright browsers must not live in root's `~/.cache`.** `playwright install` drops them in the *invoking* user's cache; the workers run as `icreateflow` and cannot read root's. `deploy/outreach-setup.sh` installs to `/srv/icreateflow/pw-browsers` and the unit sets `PLAYWRIGHT_BROWSERS_PATH` to match. A mismatched pip version is the other half of this trap — Playwright only launches the exact Chromium build it shipped with, so `playwright==1.56.0` is pinned in `requirements.txt`, in the setup script, and in the driver tests.

- **Serial selector fallbacks multiply the timeout.** Three fallbacks tried in turn against a page that will never match costs `timeout x 3` — 24s per job at the composer's 8s budget. `_first_visible` races them concurrently instead (full budget each, bounded at one), and `_present` does not wait at all, since every one of its callers is asking "did the page come back broken?" after navigation already settled. That pair took the driver's own test suite from 65s to 40s.

- **A click timing out means something is on top of it.** Playwright's click waits for the target to receive pointer events, so a consent banner over the page produces `Locator.click: Timeout 30000ms` on a button that is plainly visible and correctly found. `_click` clears known overlays and retries, then falls back to force/JS clicks, rather than losing the attempt to a cookie notice. Also: a click timeout is not a navigation timeout — reporting it as one sent us looking at page loading.

- **TikTok builds its controls out of divs.** The Message button on a profile is a `div[role="button"]`, so `button:has-text('Message')` never matches it and the target gets skipped as "does not accept DMs" — indistinguishable, from the dashboard, from a genuine block. Selector groups are tiered (`data-e2e` first, generic role/text second) because `_first_visible` races within a tier and a loose "anything saying Message" would otherwise beat the real control to a nav link.

- **The profile is a client-rendered shell.** `domcontentloaded` fires long before the action buttons exist, so any check that runs immediately is racing an empty page. Wait for `profile_loaded` first, and budget seconds not milliseconds for the button — the original 2.5s was tuned against a stub that rendered instantly.

- **"Is the message text on the page?" is not delivery confirmation.** The composer is part of the page: a send that silently fails leaves the text in the input, the check finds it, and the campaign reports thousands sent having sent none. Confirmation is composer EMPTY *and* the text still present — it moved out of the input into the conversation. Never match the thread's own class names for this; a false negative costs a duplicate DM on retry.

- **"Messages" contains "Message".** TikTok's left nav has a Messages entry, so `:has-text('Message')` matches it, and because `_first_visible` races its selectors the nav link beats a profile button that renders a beat late. The click then navigates to the inbox, and the failure surfaces as "composer never opened" on what looks like the profile URL — the tell is `inbox-title|…` and `All activity / Likes / Mentions` in the logged page actions. The generic tier uses `:text-is` (exact) for this reason; substring matching on a common word is not a fallback, it's a decoy.

- **Clicking Message may hand off to the messages app.** There isn't always an inline composer: TikTok can navigate to its inbox, and if the thread doesn't come with it you are looking at a conversation list with nothing to type into. The driver falls back to opening the target's own row — matched on the label **exactly**, never fuzzily. Those rows are other people's conversations; clicking the nearest-looking one sends a stranger someone else's DM, which is far worse than failing the job.

- **A stub test only proves the direction it exercises.** The verification bug above shipped because the stub cleared its composer on send, so the failing direction was never run. Every driver stub now has a deliberately-broken twin (`/silentfail`, `/swallowed`, `/renamed`, `/divbutton`, `/navmessages`, `/inboxmiss`), and the fix for each was confirmed to fail against the old code before being trusted.

- **Outreach: never let the API process drive a browser.** The backend runs `gunicorn -w 1`; one hung Playwright call there blocks every request on the site. The API runs the DB-only reaper; sending lives in `scripts/outreach_worker.py`.

- **Two leases, not one.** Claiming the job is not enough — the *account* needs its own lease too, or two workers end up driving the same TikTok session concurrently and it gets flagged. Both use `FOR UPDATE … SKIP LOCKED`.

- **`NOW()` writes the DB server's local time.** The outreach TIMESTAMP columns hold UTC, so every write and comparison uses `NOW() AT TIME ZONE 'UTC'`. The older Clipping SQL relies on the server being UTC; don't copy that pattern into new code.

- **`database.Connection.execute()` only takes positional `?` params.** It does `list(params)`, so passing a dict yields the *keys*. New code that needs named binds must go through `db.session.execute(text(sql), {...})` — which is what all of `services/outreach/` does.

- **Retrying an expired session is pure waste.** `session_expired` pauses the account immediately instead of burning the whole consecutive-error budget on the identical failure. A closed inbox is the opposite case: terminal for the *target*, and the account must not be blamed for it at all.

- **A pause must survive the lease release.** `release_account` only touches rows still `active`, so an account auto-paused mid-job is not quietly flipped back to `idle` by the worker's cleanup.

- **Import dedup needs the DB constraint, not just the Python check.** Two simultaneous imports of the same CSV both pass an in-Python "already present?" test. `outreach_targets_campaign_username_uq` plus `ON CONFLICT DO NOTHING` is what actually holds, and the rows the constraint rejects are counted as duplicates in the summary.

- **A2V export: `getDisplayMedia` is the correct path.** Previous attempts using Remotion server-side render, WebGL compositor, and html-to-image all had issues. The working export captures the preview `<div>` via screen recording, crops to 9:16 canvas, records with `MediaRecorder`, then remuxes WebM→MP4 on the server via ffmpeg.
