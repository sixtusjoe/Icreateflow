# ICREATEFLOW — Deployment Runbook

Host: `root@187.124.231.108` (Hostinger KVM 2, AlmaLinux 9)
Domain: `icreateflow.com` + `www.icreateflow.com`
Coexists with: `spideybot.com` (already on the same box — never touched by these scripts)

Isolation architecture:
- Linux user: `icreateflow` (home `/srv/icreateflow`)
- Postgres: role `icreateflow`, DB `icreateflow` (localhost only)
- Ports: backend `127.0.0.1:8100`, frontend `127.0.0.1:3100`
- Apache: new file `/etc/httpd/conf.d/icreateflow.conf` — shares the existing httpd (hPanel-managed) with spideybot; spideybot's vhost is untouched
- Systemd units: `icreateflow-backend.service`, `icreateflow-frontend.service`
- Background tasks: Clipping scheduler (slot planner / dispatcher / view poller) runs inside the backend process via FastAPI lifespan — no extra systemd unit
- Persistent data: `/srv/icreateflow/data/{output,uploads}` (symlinked into backend dir so deploys don't wipe them)

---

## 0. Prerequisites

- DNS: `icreateflow.com` and `www.icreateflow.com` A records → box IP.
- SSH access as `root` to the box.
- This repo cloned on your Mac.

---

## 1. First-time server setup (run ONCE on a fresh box)

From your Mac:

```bash
cd /path/to/Zagged
bash deploy/sync.sh                                      # rsync code + stage systemd/apache files to /tmp
ssh root@<HOST> 'bash /srv/icreateflow/src/deploy/server-setup.sh'
```

`server-setup.sh` is idempotent — safe to re-run. It:
- Installs Python 3.12, Postgres 16, FFmpeg, Apache, certbot, Node 20.
- Inits Postgres with 8 GB tuning.
- Creates `icreateflow` Linux user, Postgres role + DB with a **randomly generated password**.
- Builds the Python 3.12 venv at `/srv/icreateflow/venv`.
- Installs systemd units and the Apache vhost.
- Opens firewall 80/443, sets SELinux `httpd_can_network_connect`.
- Writes `/srv/icreateflow/backend/.env` with a fresh `ICREATE_JWT_SECRET` and the matching DB DSN.

---

## 2. Deploy (every code change)

From your Mac:

```bash
bash deploy/sync.sh                                      # rsync code → /srv/icreateflow/src
ssh root@<HOST> 'bash /srv/icreateflow/src/deploy/deploy.sh'
```

`deploy.sh`:
- Rsyncs src → `backend/` + `frontend/` app dirs (preserves `.env`, `.env.production`, and `/data`).
- `pip install -r requirements.txt` into the venv.
- Runs `database.init_db()` (idempotent — creates/migrates tables).
- `npm ci && npm run build` for Next.js.
- Symlinks `backend/output` → `/srv/icreateflow/data/output` (same for `uploads`).
- `systemctl restart icreateflow-backend icreateflow-frontend`.

---

## 3. Enable SSL (run ONCE after first deploy)

```bash
ssh root@<HOST> 'certbot --apache -d icreateflow.com -d www.icreateflow.com \
    --non-interactive --agree-tos --email admin@icreateflow.com --redirect'
```

The apache vhost already has the `:443` block + `SSLCertificateFile` paths baked in, so certbot just issues the cert and Apache picks it up on reload. Auto-renewal is handled by the `certbot-renew.timer` unit already on the box.

---

## 4. Bootstrap the first admin (run ONCE)

No UI for self-promotion by design — the first user must be promoted in the DB:

```bash
# Open the app in a browser → /register → create your account (e.g. you@example.com)
ssh root@<HOST> 'sudo -u postgres psql icreateflow -c \
    "UPDATE users SET role='\''admin'\'' WHERE email='\''you@example.com'\'';"'
```

Log out + back in. `/admin` is now accessible.

---

## 5. Secrets & third-party keys

`/srv/icreateflow/backend/.env` on the server (chmod 600, owned by `icreateflow`).

- `ICREATE_JWT_SECRET` — JWT signing key. Rotating it invalidates all sessions.
- `ICREATE_DB_DSN` — `postgresql+asyncpg://icreateflow:<password>@127.0.0.1:5432/icreateflow`.

**Everything else is set in the admin UI** (stored in the `settings` / `site_config` tables, not in `.env`):

| Where | Key | Used for |
|---|---|---|
| `/settings` | Anthropic API Key | Claude Vision OCR (slide text extraction) |
| `/settings` | Replicate API Token | AI face generation for variations |
| `/admin → OAuth Apps` | TikTok client id/secret | per-account TikTok OAuth |
| `/admin → OAuth Apps` | YouTube client id/secret | per-account YouTube OAuth |
| `/admin → OAuth Apps` | Meta client id/secret | per-account IG + Facebook Page OAuth |
| `/admin → OAuth Apps` | Google Drive API key | Clipping — mirror public Drive folders into clip directory |
| `/admin → OAuth Apps` | Redirect base URL | `https://icreateflow.com` — used for all OAuth callback URLs |

For each OAuth app, paste the Redirect URI shown on the card into that platform's developer console before attempting to connect any accounts.

---

## 6. Ops

```bash
# Logs (follow)
journalctl -u icreateflow-backend  -f
journalctl -u icreateflow-frontend -f

# Status
systemctl status icreateflow-backend icreateflow-frontend
systemctl is-active icreateflow-backend

# Restart after manual config edit
systemctl restart icreateflow-backend

# DB shell (superuser)
sudo -u postgres psql icreateflow
# or with app role over localhost:
PGPASSWORD=... psql -h 127.0.0.1 -U icreateflow -d icreateflow

# Apache
httpd -t && systemctl reload httpd

# Disk usage (generated content grows here)
du -sh /srv/icreateflow/data/output /srv/icreateflow/data/uploads
```

---

## 7. What's NOT automated (by design)

- `.env` edits — never overwritten after first run. Edit directly on the server.
- Third-party API keys — admin UI only; never checked into git.
- First admin promotion — manual SQL update (see §4).
- Postgres schema migrations beyond `init_db()` — run manually when introducing breaking changes.
- Spideybot — fully isolated. These scripts only add new files; nothing is shared.

---

## 8. Troubleshooting

**Backend won't start: `asyncpg.InvalidPasswordError`**
The `.env` DSN password doesn't match the Postgres role. Reset both in one shot:
```bash
ssh root@<HOST> 'DBPW=$(openssl rand -hex 24); \
    sudo -u postgres psql -c "ALTER ROLE icreateflow WITH PASSWORD '\''$DBPW'\''"; \
    sed -i "s|icreateflow:[^@]*@|icreateflow:$DBPW@|" /srv/icreateflow/backend/.env; \
    systemctl restart icreateflow-backend'
```

**All users logged out after a deploy**
`ICREATE_JWT_SECRET` got rotated. Not recoverable — users re-login.

**Clipping scheduler not firing**
Check `journalctl -u icreateflow-backend | grep -i scheduler`. Loops catch per-item exceptions, so one bad post won't kill them; a silent failure means the lifespan didn't start the tasks (usually a DB-connect failure on boot).
