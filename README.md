# ICREATE — Content Scaling Platform

ICREATE is a multi-user SaaS platform that helps content creators scale their TikTok slideshow content across multiple platforms (TikTok, YouTube Shorts, Instagram Reels, Facebook) and multiple accounts — all from a single dashboard.

---

## How It Works

### 1. Import Slides
Paste a TikTok slideshow URL or manually upload slide images. ICREATE automatically extracts text from each slide using OCR (titles, body text, CTAs).

### 2. Edit & Customize
Review and edit the extracted text for each slide. Assign slide types (hook, content, CTA) and mark slides that contain faces.

### 3. Generate Variations
For each social media account under a brand, ICREATE creates unique slide variations. You can:
- **Keep** the original slide image
- **Upload** a replacement image manually
- **AI Generate** a new face/image using Flux AI to avoid duplicate content flags

### 4. Generate & Schedule
ICREATE applies text overlays to all slides, generates 9:16 videos with transitions, and lets you schedule posts across all platforms with timezone-aware timing.

---

## Architecture

```
ICREATE/
├── backend/             # FastAPI Python backend
│   ├── main.py          # API endpoints + auth middleware
│   ├── database.py      # SQLite database + CRUD operations
│   ├── services/
│   │   ├── auth.py      # JWT authentication + bcrypt passwords
│   │   ├── ocr.py       # Text extraction from slide images
│   │   ├── overlay.py   # Text overlay on slide images
│   │   ├── generator.py # Full post generation pipeline
│   │   ├── flux.py      # AI image generation (Flux API)
│   │   ├── video.py     # 9:16 video creation with transitions
│   │   ├── tiktok_scraper.py  # TikTok slideshow import
│   │   └── posting/     # Platform posting integrations
│   └── requirements.txt
│
├── frontend/            # Next.js 16 React frontend
│   ├── src/
│   │   ├── app/         # Pages (App Router)
│   │   │   ├── page.tsx           # Dashboard
│   │   │   ├── login/page.tsx     # Login (split-screen)
│   │   │   ├── register/page.tsx  # Register (split-screen)
│   │   │   ├── landing/page.tsx   # Public landing page
│   │   │   ├── brands/page.tsx    # Brand management
│   │   │   ├── posts/page.tsx     # Posts library
│   │   │   ├── posts/new/page.tsx # Create/edit post (4-step wizard)
│   │   │   ├── schedule/page.tsx  # Schedule calendar
│   │   │   ├── music/page.tsx     # Music library
│   │   │   ├── settings/page.tsx  # API keys & platform tokens
│   │   │   ├── account/page.tsx   # User profile
│   │   │   ├── admin/page.tsx     # Admin panel
│   │   │   ├── layout.tsx         # Root layout + theme init
│   │   │   └── globals.css        # Design system (light/dark)
│   │   ├── components/
│   │   │   ├── Sidebar.tsx        # Collapsible sidebar nav
│   │   │   ├── AppShell.tsx       # Auth gate + layout wrapper
│   │   │   ├── ThemeToggle.tsx    # Light/dark mode toggle
│   │   │   └── ui/               # shadcn/ui components
│   │   └── lib/
│   │       ├── api.ts             # Axios API client + interceptors
│   │       ├── auth.tsx           # AuthProvider context + JWT
│   │       └── utils.ts           # Utility functions
│   └── package.json
│
└── README.md
```

---

## Key Features

- **Multi-User Auth** — JWT-based authentication with admin/user roles
- **Data Isolation** — Each user only sees their own brands, posts, and content
- **Multi-Brand** — Manage unlimited brands, each with multiple social accounts
- **TikTok Import** — Paste a URL to auto-import slideshow images
- **OCR Text Extraction** — AI reads text overlays from slide images
- **AI Image Generation** — Generate unique face variations per account (Flux)
- **Video Generation** — Auto-create 9:16 videos with transitions and music
- **Cross-Platform Scheduling** — Schedule to TikTok, YouTube, IG, Facebook
- **Music Library** — Upload royalty-free tracks for video backgrounds
- **Light/Dark Theme** — Monochrome design with lime accent, toggleable
- **Admin Panel** — User management, platform stats, branding config

---

## Prerequisites

- **Python 3.10+**
- **Node.js 18+**
- **npm** or **yarn**

---

## Setup & Run

### 1. Clone the repository

```bash
git clone https://github.com/sixtusjoe/Icreateflow.git
cd Icreateflow
```

### 2. Backend Setup

```bash
# Install Python dependencies
pip3 install -r backend/requirements.txt

# Start the backend server
cd backend
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

The backend runs at **http://localhost:8000**

On first run, the database is auto-created with a default admin account:
- **Email:** `admin@icreate.com`
- **Password:** `admin123`

### 3. Frontend Setup

```bash
# Open a new terminal tab/window
cd frontend

# Install dependencies
npm install

# Start the dev server
npm run dev
```

The frontend runs at **http://localhost:3000**

### 4. Open the App

Visit **http://localhost:3000** in your browser. You'll see the login page. Use the default admin credentials above to log in.

---

## Running Both Servers (Quick Start)

Open two terminal tabs and run:

**Tab 1 — Backend:**
```bash
cd /Users/mac/Desktop/Zagged/backend
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

**Tab 2 — Frontend:**
```bash
cd /Users/mac/Desktop/Zagged/frontend
npm run dev
```

---

## Environment Variables (Optional)

### Backend
| Variable | Description | Default |
|---|---|---|
| `ICREATE_JWT_SECRET` | JWT signing secret | `dev-secret-change-in-production-icreate-2024` |
| `OPENAI_API_KEY` | OpenAI API key (for OCR) | — |
| `FAL_KEY` | Fal.ai API key (for Flux image generation) | — |

### Frontend
| Variable | Description | Default |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | Backend API URL | `http://localhost:8000` |

Set these in a `.env` file in the respective directories, or export them in your shell.

---

## API Endpoints

All endpoints require JWT authentication via `Authorization: Bearer <token>` header (except auth routes).

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/auth/register` | Register new user |
| `POST` | `/api/auth/login` | Login, returns JWT |
| `GET` | `/api/auth/me` | Get current user |
| `GET` | `/api/brands` | List user's brands |
| `POST` | `/api/brands` | Create brand |
| `GET` | `/api/posts` | List user's posts |
| `POST` | `/api/posts/import` | Import TikTok slideshow |
| `POST` | `/api/posts/upload` | Upload slides manually |
| `POST` | `/api/posts/{id}/generate` | Generate all content |
| `POST` | `/api/posts/{id}/schedule` | Schedule a post |
| `GET` | `/api/schedule` | Get scheduled posts |
| `GET` | `/api/music` | List music tracks |
| `POST` | `/api/music` | Upload music track |
| `GET` | `/api/stats` | Dashboard statistics |
| `GET` | `/api/admin/users` | List all users (admin) |
| `GET` | `/api/admin/stats` | Platform-wide stats (admin) |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 16, React 19, Tailwind CSS v4, TypeScript |
| Backend | Python, FastAPI, SQLite |
| Auth | JWT (python-jose), bcrypt |
| AI | OpenAI (OCR), Fal.ai Flux (image generation) |
| UI Components | shadcn/ui v4 |
| Design | Monochrome (black/white) + lime accent, light/dark theme |

---

## Default Credentials

| Role | Email | Password |
|---|---|---|
| Admin | `admin@icreate.com` | `admin123` |

> Change the admin password after first login via the Account page.

---

## License

Private — All rights reserved.
