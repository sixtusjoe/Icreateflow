# ICREATEFLOW

A multi-user SaaS platform for content creators. The platform has **two distinct sides** that share auth, database, OAuth, and the frontend shell:

- **Brands** — TikTok slideshow scaling. Import or upload slides, OCR the text, generate per-account variations (keep / replace / Flux face-swap), assemble 9:16 videos, and schedule across TikTok, YouTube Shorts, Instagram Reels, and Facebook.
- **Clipping** — Music artist auto-poster. Sync short clips from Google Drive, plan posting slots in the artist's local timezone, optionally per-account video-diversify, and auto-post across the same four platforms with view tracking and auto-pause on view-target / directory-exhausted.

Production: **icreateflow.com** (Postgres + FastAPI + Next.js 16 on a single VPS, fronted by Apache).

For Clipping operational internals (background loops, cache layout, deletion detection, deploy runbook), see [`memory.md`](memory.md).

---

## Brands — How it works

1. **Import slides** — paste a TikTok slideshow URL, or upload images manually. OCR (Claude vision via `services/ocr.py`) extracts title / body / CTA text per slide.
2. **Edit & customize** — review the extracted text, set slide type (`hook` / `content` / `cta`), and mark slides containing faces.
3. **Per-account variations** — for each account under a brand, choose `keep` (original image), `replace` (manual upload), or `generate` (Flux face variation via Replicate).
4. **Generate** — `services/overlay.py` applies text overlays; `services/video.py` assembles 9:16 video using `PLATFORM_PROFILES` for per-platform duration caps (YouTube Shorts ≤ 60s; IG / FB Reels ≤ 90s).
5. **Schedule** — `PUT /api/posts/{post_id}/schedule` sets the post's `scheduled_time` and per-platform sub-times. Posts fire on user action; there is no automated dispatcher loop on the Brands side (separate from Clipping).

Tables: `brands`, `accounts`, `posts`, `slides`, `variations`, `outputs`, `music_tracks`.
Frontend: `frontend/src/app/{brands,posts,posts/new,music,schedule}/`.

## Clipping — How it works

1. **Create artist** — name, slug, IANA timezone, posts/day, posting window (HH:MM start / end), view target.
2. **Add variations** — per-platform sub-accounts (TikTok / YouTube / IG / FB), connected via OAuth.
3. **Sync clips** — paste a Google Drive folder URL; `services/gdrive.py` lists video files using the admin-stored `google_api_key` from the `settings` table.
4. **Run** — three async loops in `services/clip_scheduler.py` (started from FastAPI's lifespan hook):
   - **Planner** (every 300s) materializes today's slots into `clip_posts`.
   - **Dispatcher** (every 60s) atomically claims due slots (`SKIP LOCKED`), per-account diversifies via `services/variation_processor.py` (or passthroughs if diversification is off), and uploads via the platform adapters in `services/posting/`.
   - **View poller** (every `view_poll_interval_seconds`, default 180) refreshes view counts (monotonic; never drops) and detects deletions via per-platform existence probes.
5. **Auto-pause** — when the campaign hits its view target, or the clip directory is exhausted, the artist is paused. Resumes on new clip upload (if `catchup_enabled` is on) or manual unpause.

Tables: `artists`, `campaigns`, `artist_accounts`, `clips`, `clip_posts`, `clip_caption_variants`.
Frontend: `frontend/src/app/clipping/`.
Operational deep dive: [`memory.md`](memory.md).

---

## Repo layout

```
.
├── backend/                FastAPI + SQLAlchemy 2.0 (asyncpg) backend
│   ├── main.py             API endpoints + JWT auth + lifespan
│   ├── database.py         ORM models, init_db, migrations, Connection wrapper
│   ├── requirements.txt
│   └── services/
│       ├── auth.py             JWT + bcrypt
│       ├── ocr.py              Claude-vision OCR for slides
│       ├── overlay.py          Pillow text overlay on slide images
│       ├── video.py            ffmpeg 9:16 video assembly + PLATFORM_PROFILES
│       ├── flux.py             Replicate Flux image generation
│       ├── generator.py        Brands post-generation pipeline
│       ├── clip_scheduler.py   Clipping planner + dispatcher + view poller
│       ├── variation_processor.py  Per-variation ffmpeg diversifier + passthrough
│       ├── gdrive.py           Google Drive clip listing
│       ├── oauth.py            Per-platform OAuth flows + scopes
│       ├── caption_variants.py Caption variation generation
│       └── posting/            Platform adapters
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
│       │   ├── posts/          Posts library + 4-step wizard (`posts/new`)
│       │   ├── schedule/       Calendar view
│       │   ├── music/          Music library
│       │   ├── clipping/[slug] Per-artist campaign dashboard
│       │   ├── settings/       Per-user settings + clipping toggles
│       │   ├── admin/          Admin panel (global config, audit-deleted)
│       │   ├── account/        User profile
│       │   └── (auth pages)    login / register / landing
│       ├── components/         Sidebar, AppShell, OAuthTiles, ui/* (shadcn)
│       └── lib/                api.ts (axios + interceptors), auth.tsx (JWT context)
│
├── deploy/                 VPS deployment
│   ├── server-setup.sh     One-time AlmaLinux 9 bootstrap (Postgres, Apache, systemd, venv)
│   ├── sync.sh             Laptop → VPS rsync
│   ├── deploy.sh           Server-side install/build/restart
│   ├── apache/             Apache vhost (proxies :443 → backend:8100 + frontend:3100)
│   ├── systemd/            icreateflow-{backend,frontend}.service
│   └── .env.example        Backend env template
│
├── README.md               This file
└── memory.md               Clipping internals + ops runbook + lessons
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
| Server | gunicorn + uvicorn workers (`-w 2`), Apache reverse proxy, systemd |
| OS | AlmaLinux 9 (production) — Linux/macOS for development |

---

## Prerequisites

- **Python 3.10+** (3.12 in production)
- **Node.js 20+**
- **PostgreSQL 14+** with a database and role for the app
- **ffmpeg** in `PATH` (required for video generation)

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

The backend runs at **http://localhost:8000**. On first run, `init_db()` creates the schema and seeds an admin user — see **First-run admin** below.

### 4. Frontend

In a separate terminal:

```bash
cd frontend
npm install
npm run dev
```

The frontend runs at **http://localhost:3000** and reads `NEXT_PUBLIC_API_URL` (defaults to `http://localhost:8000`).

### First-run admin

`backend/database.py:_seed()` creates a default admin row when the `users` table is empty. **Change the password immediately on first login** via the Account page. The default credentials are not published here for security; if you've inherited a fresh deployment, check `database.py` or ask whoever bootstrapped the box.

> **TODO** (tracked separately): replace the hardcoded default with an `ICREATE_ADMIN_EMAIL` / `ICREATE_ADMIN_PASSWORD` env-var bootstrap, falling back to a one-time random password printed to stdout.

---

## Production deploy

The VPS runs AlmaLinux 9 with Postgres 16, Apache (shared with another tenant on the same box), and systemd-managed `icreateflow-backend` (gunicorn, port 8100) + `icreateflow-frontend` (Next.js, port 3100). Code lives under `/srv/icreateflow/`.

**One-time bootstrap** (per-VPS, run as root):
```bash
ssh root@icreateflow.com 'bash /srv/icreateflow/src/deploy/server-setup.sh'
```
See `deploy/server-setup.sh` for the full set of steps (DB init, app user, venv, systemd units, Apache vhost, firewall, certbot pointers).

**Iterative deploy** (every code change, run from your laptop):
```bash
bash deploy/sync.sh                                      # rsync → /srv/icreateflow/src/
ssh root@icreateflow.com 'bash /srv/icreateflow/src/deploy/deploy.sh'
```
`deploy.sh` re-syncs into `/srv/icreateflow/{backend,frontend}/`, installs deps, runs `init_db()`, builds the frontend, symlinks persistent dirs (`uploads`, `output`, `music`) to `/srv/icreateflow/data/*`, and restarts both services.

**Logs**:
```bash
journalctl -u icreateflow-backend -f
journalctl -u icreateflow-frontend -f
```

---

## Environment variables

### Backend (read at process start)

| Variable | Description | Required |
|---|---|---|
| `ICREATE_JWT_SECRET` | JWT signing secret. Generate with `openssl rand -hex 48`. | **Yes** in production |
| `ICREATE_DB_DSN` | Postgres DSN, e.g. `postgresql+asyncpg://user:pw@host:5432/db` | **Yes** |
| `ANTHROPIC_API_KEY` | Anthropic API key for OCR + caption variants | Optional (features no-op without it) |
| `REPLICATE_API_TOKEN` | Replicate token for Flux image generation | Optional |
| `TIKTOK_SCOPES` / `YOUTUBE_SCOPES` / `META_SCOPES` / `INSTAGRAM_SCOPES` | Override default OAuth scopes | Optional |

OAuth client IDs/secrets and the Google Drive API key are **not** env vars — they're stored in the `settings` / `site_config` tables and edited from the admin panel and per-user settings page.

### Frontend

| Variable | Description | Default |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | Backend base URL | `http://localhost:8000` (dev), `https://icreateflow.com` (prod, set by `deploy.sh`) |

Production env files:
- Backend: `/srv/icreateflow/backend/.env` (seeded by `server-setup.sh`, chmod 600)
- Frontend: `/srv/icreateflow/frontend/.env.production` (regenerated each `deploy.sh` run)

---

## API endpoints (summary)

All endpoints (except auth) require `Authorization: Bearer <token>`.

### Auth
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/auth/register` | Register new user (status defaults to `pending` — admin must approve) |
| `POST` | `/api/auth/login` | Login → JWT |
| `GET`  | `/api/auth/me` | Current user |

### Brands
| Method | Endpoint | Description |
|---|---|---|
| `GET`  | `/api/brands` | List user's brands |
| `POST` | `/api/brands` | Create brand |
| `GET`  | `/api/posts` | List posts |
| `POST` | `/api/posts/import` | Import TikTok slideshow URL |
| `POST` | `/api/posts/upload-slides` | Upload slides manually |
| `POST` | `/api/posts/{id}/generate` | Run full generate pipeline |
| `POST` | `/api/posts/{id}/regenerate-slide` | Re-render a single slide |
| `POST` | `/api/posts/{id}/regenerate-video` | Re-render the video only |
| `PUT`  | `/api/posts/{id}/schedule` | Set scheduled_time + per-platform sub-times |
| `GET`  | `/api/music` / `POST` | Music library |

### Clipping
| Method | Endpoint | Description |
|---|---|---|
| `GET`  | `/api/artists` | List artists |
| `POST` | `/api/artists` | Create artist |
| `POST` | `/api/artists/{id}/clips/gdrive` | Sync clips from Google Drive folder |
| `POST` | `/api/artists/{id}/variations` | Add a per-platform variation account |
| `POST` | `/api/artists/{id}/promotion/start` | Activate the artist (planner + dispatcher pick it up) |
| `POST` | `/api/artists/{id}/promotion/toggle-pause` | Pause / resume |
| `GET`  | `/api/artists/{id}/dashboard` | Live campaign dashboard data |

### Admin
| Method | Endpoint | Description |
|---|---|---|
| `GET`  | `/api/admin/users` | List all users |
| `GET`  | `/api/admin/stats` | Platform-wide stats |
| `POST` | `/api/admin/clip-posts/audit-deleted` | One-shot view-poll bypassing the staleness gate |

---

## License

Private — all rights reserved.
