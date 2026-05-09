# ICREATEFLOW

A multi-user SaaS platform for content creators. The platform has **two distinct sides** that share auth, database, OAuth, and the frontend shell:

- **Brands** — TikTok slideshow scaling. Import or upload slides, OCR the text, generate per-account variations (keep / replace / Flux face-swap), assemble 9:16 videos, and schedule across TikTok, YouTube Shorts, Instagram Reels, and Facebook.
- **Clipping** — Music artist auto-poster. Sync short clips from Google Drive, plan posting slots in the artist's local timezone, optionally per-account video-diversify, and auto-post across the same four platforms with view tracking and auto-pause on view-target / directory-exhausted.

Production: **icreateflow.com** (`187.124.231.108`) — Postgres + FastAPI + Next.js 16 on a single VPS, fronted by Apache.

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

---

## Repo layout

```
.
├── backend/                FastAPI + SQLAlchemy 2.0 (asyncpg) backend
│   ├── main.py             All API endpoints + JWT auth + lifespan startup
│   ├── database.py         ORM models, init_db(), idempotent migrations
│   ├── requirements.txt
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
| AI | Anthropic Claude (OCR, captions), Replicate Flux (image gen) |
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
ssh root@187.124.231.108 'bash /srv/icreateflow/src/deploy/server-setup.sh'
```

Then enable SSL:
```bash
ssh root@187.124.231.108 'certbot --apache -d icreateflow.com -d www.icreateflow.com \
    --non-interactive --agree-tos --email admin@icreateflow.com --redirect'
```

### Logs

```bash
ssh root@187.124.231.108
journalctl -u icreateflow-backend -f
journalctl -u icreateflow-frontend -f
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

### Admin
| Method | Endpoint | Description |
|---|---|---|
| `GET`  | `/api/admin/users` | All users |
| `GET`  | `/api/admin/stats` | Platform-wide stats |
| `GET`  | `/api/admin/variation-health` | Per-variation stale-slot diagnostics |
| `POST` | `/api/admin/clip-posts/audit-deleted` | Force view-poll all posted rows |

---

## License

Private — all rights reserved.
