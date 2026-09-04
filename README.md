# ICREATEFLOW

A multi-user SaaS platform for content creators. The platform has **two distinct sides** that share auth, database, OAuth, and the frontend shell:

- **Brands** — TikTok slideshow scaling. Import or upload slides, OCR the text, generate per-account variations (keep / replace / Flux face-swap), assemble 9:16 videos, and schedule across TikTok, YouTube Shorts, Instagram Reels, and Facebook.
- **Clipping** — Music artist auto-poster. Sync short clips from Google Drive, plan posting slots in the artist's local timezone, optionally per-account video-diversify, and auto-post across the same four platforms with view tracking and auto-pause on view-target / directory-exhausted.
- **Audio-to-Video** — Karaoke-style music video creator. Upload a music track, Whisper transcribes it, split into 1/3/5 clips, edit lyrics in the Overlay Studio (4 templates, karaoke/scroll modes), export as 9:16 MP4 with synced lyrics, assign to a variation for posting.
- **Outreach** — Multi-account DM campaigns. Import a list of TikTok profiles, write a `{{variable}}` message template, and let a Postgres-backed job queue hand targets to up to 20 sending accounts, each driven in its own isolated browser session. Live progress, retries, per-account auto-pause, audit log.

Production: **icreateflow.com** (`95.111.228.80`) — Postgres + FastAPI + Next.js 16 on a single VPS, fronted by Apache.

For deep operational internals (background loops, data model, lessons, runbook), see [`memory.md`](memory.md).

---

## Brands — How it works

1. **Import slides** — paste a TikTok slideshow URL, or upload images manually. OCR (`services/ocr.py` via Claude vision) extracts title / body / CTA text per slide.
2. **Edit & customize** — review extracted text, set slide type (`hook` / `content` / `cta`), mark slides containing faces.
3. **Per-account variations** — for each account under a brand, choose `keep` (original image), `replace` (manual upload), or `generate` (Flux face variation via Replicate).
4. **Generate** — `services/overlay.py` applies text overlays; `services/video.py` assembles 9:16 video using `PLATFORM_PROFILES` for per-platform duration caps (YouTube Shorts ≤ 60s; IG / FB Reels ≤ 90s).
5. **Schedule** — `PUT /api/posts/{post_id}/schedule` sets `scheduled_time`. Brand posts are dispatched manually via `POST /api/posts/{post_id}/post-now`.
6. **Emails** — a reminder email fires ~1 hour before `scheduled_time`; a HURRAY result email fires after successful dispatch. Both use `services/email.py`.

Tables: `brands`, `accounts`, `posts`, `slides`, `variations`, `outputs`, `music_tracks`.
Frontend: `frontend/src/app/{brands,posts,posts/new,music,schedule}/`.

## Clipping — How it works

1. **Create artist** — name, slug, IANA timezone, posts/day, posting window (HH:MM start / end), view target.
2. **Add variations** — per-platform sub-accounts (TikTok / YouTube / IG / FB), connected via OAuth.
3. **Sync clips** — paste a Google Drive folder URL; `services/gdrive.py` lists video files using the admin-stored `google_api_key` from the `site_config` table.
4. **Run** — four async loops in `services/clip_scheduler.py` (started from FastAPI's lifespan hook):
   - **Planner** (every 300s) materialises today's slots into `clip_posts`, runs per-variation integrity sweep.
   - **Dispatcher** (every 60s) atomically claims due slots (`SKIP LOCKED`), per-account diversifies via `services/variation_processor.py`, uploads via platform adapters in `services/posting/`.
   - **View poller** (every `view_poll_interval_seconds`, default 180s) sends pre-post reminder emails, refreshes view counts (monotonic), detects deletions.
   - **Cache sweep** (every 24h) prunes old diversifier render files.
5. **Auto-pause** — when the campaign hits its view target, or the clip directory is exhausted, the artist is paused. Resumes manually or on new clip upload.

Tables: `artists`, `campaigns`, `artist_accounts`, `clips`, `clip_posts`, `clip_caption_variants`.
Frontend: `frontend/src/app/clipping/`.
Operational deep dive: [`memory.md`](memory.md).

## Audio-to-Video — How it works

1. **Upload track** — drag in MP3/WAV/M4A. Backend stores it and kicks off an async Whisper (OpenAI) transcription that returns word-level timestamps (`audio_words` table).
2. **Split** — choose 1, 3, or 5 equal segments. Each segment becomes an `audio_clips` row with its own audio file.
3. **Overlay Studio** — for each clip, pick a template (`minimal` / `vibrant` / `cinematic` / `neon`), edit the lyrics textarea, preview karaoke/scroll sync live with the audio, tweak background image and album cover.
4. **Export** — screen-capture the preview panel via `getDisplayMedia`, crop to 9:16 canvas, record with `MediaRecorder`, server remuxes WebM→MP4. Download or assign directly to a variation in the Clipping pipeline.

Tables: `audio_tracks`, `audio_words`, `audio_clips`, `audio_video_clips`.
Frontend: `frontend/src/app/clipping/audio-to-video/page.tsx` (single file, ~2900 lines).

Key technical detail: **Whisper timestamps are absolute** (from track start, not clip start). The karaoke RAF tick converts: `tAbs = audio.currentTime + clip.start_s`. Sync uses a per-display-word `wordTimings` array — 1:1 Whisper timestamps for auto-generated text, even time distribution for user-edited text.

## Outreach — How it works

1. **Add sending accounts** — `/outreach/accounts`, up to 20. Name the account, then sign it in **on the server**:

   ```bash
   bash deploy/outreach-login-mac.sh        # list accounts
   bash deploy/outreach-login-mac.sh 1      # sign in account 1
   ```

   That one command starts a real browser on the server's virtual display, opens the SSH tunnel, and launches macOS Screen Sharing pointed at it. Sign in by hand in the window that appears; the session is detected and encrypted straight into the account row — no file, no copy-paste, nothing left on disk. (`deploy/outreach-login.sh` is the server half, if you'd rather drive it yourself.)

   Doing this on the server matters: the session is created on the machine and IP that will use it. Capturing it on a laptop and importing means the platform watches an established session move to a new IP, which is the usual reason a fresh session gets challenged. The API also accepts a pasted `storage_state` JSON (`POST /api/outreach/accounts/{id}/session`) if you need it. Either way no password reaches the service, and sessions are never readable back out of the API.
2. **Create a campaign** — name, description, and a message template with `{{username}}`, `{{profile_url}}`, `{{campaign_name}}`, `{{account_name}}` plus any campaign variable you define (`{{offer}}`, …).
3. **Import targets** — CSV upload or paste. Accepts `username`, `profile_url`, or both, in any column order. Off-platform URLs, malformed handles and duplicates are rejected *before* insert; the summary reports `imported / duplicates / invalid / ready`.
4. **Start** — a preflight refuses to run without a valid template, queued targets and an enabled account. Starting enqueues one `outreach_jobs` row per queued target.
5. **Workers** — `scripts/outreach_worker.py`, run as one or more processes. Each cycle leases a free sending account, claims a job with `FOR UPDATE SKIP LOCKED`, renders the message, calls the browser driver, records the structured result, and releases the lease.
6. **Monitor** — the campaign page polls every 3 s: progress bar, per-status target list, sending accounts, recent activity, error log, audit trail. Pause / Resume / Stop / Retry failed / Export CSV.

   To watch a send actually happen, run one job with the browser visible:

   ```bash
   bash deploy/outreach-watch-mac.sh          # a real send, watched
   bash deploy/outreach-watch-mac.sh mock     # rehearse, sends nothing
   ```

   Same tunnel and viewer as the login flow. It takes the next queued job off the same queue through the same worker code — the only difference is you can see it load the profile, click Message, type and submit. Background workers are paused for the duration so the job can't be claimed out from under you, and restarted on exit however it ends. When a selector breaks, this is faster than reading logs.
7. **Self-healing** — a claimed job carries a lease; if its worker dies, the reaper requeues it. An account that keeps failing (expired session, rate limit, browser crash) auto-pauses with the reason shown to the administrator instead of retrying forever.

The browser layer is isolated behind a driver interface (`services/outreach/browser/`) — `mock` (sends nothing, for dry runs and tests) and `playwright_tiktok` ship today; swapping the automation technology means adding a module there and changing one setting.

Tables: `outreach_campaigns`, `outreach_targets`, `outreach_sending_accounts`, `outreach_jobs`, `outreach_templates`, `outreach_campaign_accounts`, `outreach_audit_logs`.
Frontend: `frontend/src/app/outreach/`. Admin controls: `/admin → Outreach`.

---

## Repo layout

```
.
├── backend/                FastAPI + SQLAlchemy 2.0 (asyncpg) backend
│   ├── main.py             All API endpoints + JWT auth + lifespan startup
│   ├── database.py         ORM models, init_db(), idempotent migrations
│   ├── requirements.txt
│   ├── routers/outreach.py Outreach API (the one router; everything else is in main.py)
│   ├── scripts/outreach_worker.py  Outreach browser worker CLI
│   ├── tests/              pytest suite (outreach pipeline)
│   └── services/
│       ├── auth.py             JWT + bcrypt
│       ├── email.py            SMTP email (reminders + HURRAY results)
│       ├── ocr.py              Claude-vision OCR for Brand slides
│       ├── overlay.py          Pillow text overlay on slide images
│       ├── video.py            ffmpeg 9:16 video assembly + PLATFORM_PROFILES
│       ├── flux.py             Replicate Flux image generation
│       ├── generator.py        Brands post-generation pipeline
│       ├── clip_scheduler.py   Clipping planner + dispatcher + view poller + brand reminders
│       ├── variation_processor.py  Per-variation ffmpeg diversifier + passthrough
│       ├── gdrive.py           Google Drive clip listing
│       ├── oauth.py            Per-platform OAuth flows + token refresh
│       ├── caption_variants.py Caption variation generation
│       ├── outreach/           ★ DM campaign pipeline
│       │   ├── queue.py            Postgres job queue (claim / retry / reap)
│       │   ├── accounts.py         Sending-account leasing + health
│       │   ├── runner.py           Worker loop + in-process reaper
│       │   ├── importer.py         CSV import + validation + dedup
│       │   ├── templates.py        {{variable}} rendering
│       │   ├── config.py           Admin-tunable limits (site_config)
│       │   ├── stats.py            Campaign counter maintenance
│       │   └── browser/            Swappable automation drivers
│       │       ├── mock.py             No browser — dry runs and tests
│       │       └── playwright_tiktok.py Isolated context per account
│       └── posting/            Platform upload adapters
│           ├── __init__.py     PostingError, PostDeletedError
│           ├── tiktok.py
│           ├── youtube.py
│           ├── instagram.py
│           └── facebook.py
│
├── frontend/               Next.js 16 (App Router, Turbopack) + React 19
│   └── src/
│       ├── app/
│       │   ├── brands/         Brand management
│       │   ├── posts/          Posts library + 4-step wizard (posts/new)
│       │   ├── schedule/       Calendar view of scheduled posts
│       │   ├── music/          Music library
│       │   ├── clipping/[slug] Per-artist campaign dashboard
│       │   ├── clipping/audio-to-video/  ★ Audio-to-Video karaoke creator
│       │   ├── settings/       Per-user settings + clipping toggles
│       │   ├── admin/          Admin panel (global config, audit-deleted, errors)
│       │   ├── account/        User profile + email preferences
│       │   └── (auth)          login / register / landing
│       ├── components/         Sidebar, AppShell, OAuthTiles, ConfirmModal, ui/*
│       └── lib/                api.ts (axios + interceptors), auth.tsx (JWT context)
│
├── deploy/
│   ├── ship.sh             ★ ONE COMMAND DEPLOY — use this every time (see below)
│   ├── deploy.sh           Server-side extract + build + restart (called by ship.sh)
│   ├── sync.sh             First-time only: rsync code to server before server-setup
│   ├── server-setup.sh     One-time AlmaLinux 9 bootstrap (Postgres, Apache, systemd, venv)
│   ├── apache/             Apache vhost (proxies :443 → backend:8100 + frontend:3100)
│   ├── systemd/            icreateflow-{backend,frontend}.service
│   └── .env.example        Backend env template
│
├── README.md               This file
└── memory.md               Full internals + ops runbook + lessons learned
```

---

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 16, React 19, TypeScript, Tailwind CSS v4, shadcn/ui |
| Backend | FastAPI 0.135, SQLAlchemy 2.0 (async), asyncpg |
| Database | PostgreSQL 16 |
| Auth | JWT (python-jose) + bcrypt |
| AI | Anthropic Claude (OCR, captions), OpenAI gpt-image-2 (image gen), OpenAI Whisper (A2V transcription) |
| Media | ffmpeg (video), Pillow (overlays), yt-dlp (TikTok import fallback) |
| Email | Python smtplib (SMTP, configured in admin `site_config`) |
| Server | gunicorn + uvicorn worker (`-w 1`), Apache reverse proxy, systemd |
| OS | AlmaLinux 9 (production) — Linux/macOS for development |

---

## Prerequisites

- **Python 3.10+** (3.12 in production)
- **Node.js 20+**
- **PostgreSQL 14+** with a database and role for the app
- **ffmpeg** in `PATH`

---

## Local setup

### 1. Clone

```bash
git clone https://github.com/sixtusjoe/Icreateflow.git
cd Icreateflow
```

### 2. Postgres

```bash
createdb icreateflow
psql -c "CREATE ROLE icreateflow LOGIN PASSWORD 'devpw';"
psql -c "GRANT ALL PRIVILEGES ON DATABASE icreateflow TO icreateflow;"
```

### 3. Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export ICREATE_JWT_SECRET="$(openssl rand -hex 48)"
export ICREATE_DB_DSN="postgresql+asyncpg://icreateflow:devpw@127.0.0.1:5432/icreateflow"

python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Backend runs at **http://localhost:8000**. On first run, `init_db()` creates the schema and seeds a default admin user (credentials in `database.py:_seed()`).

### 4. Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend runs at **http://localhost:3000** and points to `NEXT_PUBLIC_API_URL` (defaults to `http://localhost:8000`).

### 5. Outreach worker (optional)

The API process never drives a browser. To actually send outreach messages, run at least one worker alongside it:

```bash
cd backend
python3 scripts/outreach_worker.py --driver mock     # dry run — sends nothing
python3 scripts/outreach_worker.py                   # driver from the admin panel
python3 scripts/outreach_worker.py --concurrency 3
```

For the real TikTok driver: `pip install playwright && playwright install chromium`, then set `outreach_driver` to `playwright_tiktok` in `/admin → Outreach`.

### 6. Tests

```bash
createdb icreateflow_test
cd backend
pip install pytest pytest-asyncio
ICREATE_TEST_DB_DSN=postgresql+asyncpg://postgres@127.0.0.1:5432/icreateflow_test python3 -m pytest
```

The suite covers the outreach pipeline end to end against a real Postgres (the queue's guarantees are `SKIP LOCKED` and unique indexes, which a stub cannot exercise). Every send goes through the mock driver — no browser, no messages. Without a reachable database the DB-backed tests skip and the pure-logic ones still run.

`tests/test_outreach_playwright_driver.py` additionally drives the real Playwright driver against a local stub site (never TikTok): context-per-account isolation, session loading, typing and submitting, delivery verification, and each bad-page state mapping to the right status. It needs `pip install playwright==1.56.0 && playwright install chromium` and skips without them.

---

## Production deploy

### Every code change — one command from your Mac:

```bash
bash deploy/ship.sh
```

This script:
1. Confirms you're on `main` with nothing uncommitted
2. `git push origin main`
3. SSHes to the server and updates `/srv/icreateflow/src` to the exact pushed SHA (retries `git fetch` up to 5× for GitHub CDN propagation)
4. Runs `deploy.sh` on the server — `git archive` extracts code, installs deps, migrates DB, builds frontend, restarts services

> **Important:** Always use `ship.sh`, not manual SSH + deploy.sh. The ship/deploy split ensures the server always runs exactly what git says — no race conditions, no stale files.

### First-time server setup (once per box)

```bash
bash deploy/sync.sh                          # rsync code to server
ssh root@95.111.228.80 'bash /srv/icreateflow/src/deploy/server-setup.sh'
```

Then enable SSL:
```bash
ssh root@95.111.228.80 'certbot --apache -d icreateflow.com -d www.icreateflow.com \
    --non-interactive --agree-tos --email admin@icreateflow.com --redirect'
```

### Outreach workers (once per box)

After the first `ship.sh` that carries the outreach code:

```bash
ssh root@95.111.228.80 'bash /srv/icreateflow/src/deploy/outreach-setup.sh 2'
```

That generates `ICREATE_OUTREACH_SECRET` into the backend `.env` if it isn't there yet (so session encryption is independent of your JWT secret), installs Playwright, downloads Chromium and its system libraries into `/srv/icreateflow/pw-browsers` (app-owned, so the `icreateflow` service user can read it), installs the `icreateflow-outreach-worker@` template unit, enables the requested number of workers, and launches a real headless Chromium as the service user to prove it works. Re-runnable; pass a different number to scale.

It does **not** switch the sending driver on — the pipeline stays on `mock` until you change `outreach_driver` in `/admin → Outreach`. Rehearse a campaign on `mock` first.

Workers claim jobs and accounts in Postgres, so any number of instances is safe. Restarting one never loses or double-sends a target: an in-flight job keeps its lease and is requeued by the reaper. Later deploys restart the workers automatically (`deploy.sh` picks up any active `icreateflow-outreach-worker@*` units).

### Logs

```bash
ssh root@95.111.228.80
journalctl -u icreateflow-backend -f
journalctl -u icreateflow-frontend -f
journalctl -u 'icreateflow-outreach-worker@*' -f
```

---

## Environment variables

### Backend (`/srv/icreateflow/backend/.env` on the server)

| Variable | Description | Required |
|---|---|---|
| `ICREATE_JWT_SECRET` | JWT signing secret — `openssl rand -hex 48` | **Yes** |
| `ICREATE_DB_DSN` | `postgresql+asyncpg://user:pw@host:5432/db` | **Yes** |
| `ANTHROPIC_API_KEY` | Claude OCR + caption variants | Optional |
| `REPLICATE_API_TOKEN` | Flux image generation | Optional |
| `ICREATE_OUTREACH_SECRET` | Encrypts stored outreach sending-account sessions. Generated into `.env` by `deploy/outreach-setup.sh`; falls back to `ICREATE_JWT_SECRET` if absent. | Auto |
| `ICREATE_OUTREACH_HEADLESS` | `0` runs the Playwright driver with a visible browser (debugging) | Optional |
| `ICREATE_OUTREACH_TIMEOUT_MS` | Per-navigation timeout for the browser driver (default 30000) | Optional |

All OAuth client IDs/secrets, SMTP config, Google Drive API key, and site config are stored in the `settings` / `site_config` tables — edit from `/admin` and `/settings` in the UI.

### Frontend

| Variable | Description | Default |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | Backend base URL | `http://localhost:8000` (dev) / `https://icreateflow.com` (prod) |

---

## Key API endpoints

All endpoints except auth require `Authorization: Bearer <token>`.

### Auth
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/auth/register` | Register — lands in `pending`, admin must approve |
| `POST` | `/api/auth/login` | Login → JWT |
| `GET`  | `/api/auth/me` | Current user |

### Brands
| Method | Endpoint | Description |
|---|---|---|
| `GET/POST` | `/api/brands` | List / create brands |
| `GET` | `/api/posts` | List posts |
| `POST` | `/api/posts/import` | Import TikTok slideshow URL |
| `POST` | `/api/posts/{id}/generate` | Run full generate pipeline |
| `PUT`  | `/api/posts/{id}/schedule` | Set `scheduled_time` |
| `POST` | `/api/posts/{id}/post-now` | Dispatch to platforms + send HURRAY email |

### Clipping
| Method | Endpoint | Description |
|---|---|---|
| `GET/POST` | `/api/artists` | List / create artists |
| `POST` | `/api/artists/{id}/clips/gdrive` | Sync clips from Google Drive |
| `POST` | `/api/artists/{id}/variations` | Add variation (per-platform sub-account) |
| `POST` | `/api/artists/{id}/promotion/start` | Start campaign |
| `POST` | `/api/artists/{id}/promotion/toggle-pause` | Pause / resume |
| `GET`  | `/api/artists/{id}/dashboard` | Live campaign dashboard |

### Audio-to-Video
| Method | Endpoint | Description |
|---|---|---|
| `GET`  | `/api/audio-to-video/tracks` | List tracks for current artist |
| `POST` | `/api/audio-to-video/upload` | Upload track → async Whisper transcription |
| `POST` | `/api/audio-to-video/{id}/retranscribe` | Re-run Whisper on a track |
| `POST` | `/api/audio-to-video/{id}/split` | Split track into N clips |
| `GET`  | `/api/audio-to-video/clips/{id}` | Get clip + words |
| `PUT`  | `/api/audio-to-video/clips/{id}/lyrics` | Save lyrics text (pass `words=[]` to preserve Whisper data) |
| `POST` | `/api/audio-to-video/clips/{id}/upload-asset` | Upload background image / album cover |
| `POST` | `/api/audio-to-video/clips/{id}/settings` | Save template/lyrics_mode settings |
| `POST` | `/api/audio-to-video/clips/{id}/assign` | Assign exported MP4 to a variation clip |
| `POST` | `/api/audio-to-video/convert-to-mp4` | Server-side WebM→MP4 remux |
| `DELETE` | `/api/audio-to-video/{id}` | Delete track + all files |

### Outreach
| Method | Endpoint | Description |
|---|---|---|
| `GET/POST` | `/api/outreach/campaigns` | List / create campaigns |
| `GET` | `/api/outreach/campaigns/{id}` | Campaign detail (targets, accounts, jobs, audit) |
| `GET` | `/api/outreach/campaigns/{id}/progress` | Small payload for the live poll |
| `POST` | `/api/outreach/campaigns/{id}/import` | CSV upload → validated targets |
| `POST` | `/api/outreach/campaigns/{id}/import-text` | Same, from a pasted list |
| `POST` | `/api/outreach/campaigns/{id}/start\|pause\|resume\|stop` | Campaign controls |
| `POST` | `/api/outreach/campaigns/{id}/retry-failed` | Re-queue failed targets |
| `GET` | `/api/outreach/campaigns/{id}/export.csv` | Export results |
| `GET/POST` | `/api/outreach/accounts` | List / add sending accounts (max 20) |
| `POST` | `/api/outreach/accounts/{id}/session` | Store an encrypted browser session |
| `PUT` | `/api/outreach/accounts/{id}` | Rename, enable / disable |
| `GET/POST` | `/api/outreach/templates` | Reusable message templates |
| `POST` | `/api/outreach/templates/preview` | Validate + render with sample data |
| `GET/PUT` | `/api/outreach/settings` | Admin limits, driver, worker kill switch |

### Admin
| Method | Endpoint | Description |
|---|---|---|
| `GET`  | `/api/admin/users` | All users |
| `GET`  | `/api/admin/stats` | Platform-wide stats |
| `GET`  | `/api/admin/variation-health` | Per-variation stale-slot diagnostics |
| `POST` | `/api/admin/clip-posts/audit-deleted` | Force view-poll all posted rows |
| `DELETE` | `/api/admin/audio-to-video` | Clean A2V storage by scope |

---

## License

Private — all rights reserved.
