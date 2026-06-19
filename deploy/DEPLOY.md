# ICREATEFLOW — Deployment Runbook

Host: `root@95.111.228.80` (Contabo VPS, Ubuntu 24.04, Virtualmin)
Domain: `icreateflow.com` + `www.icreateflow.com`
Coexists with: `spideybot.com` (already on the same box — never touched by these scripts)

Isolation architecture:
- Linux user: `icreateflow` (home `/srv/icreateflow`)
- Postgres: role `icreateflow`, DB `icreateflow` (localhost only)
- Ports: backend `127.0.0.1:8100`, frontend `127.0.0.1:3100`
- Apache: `/etc/httpd/conf.d/icreateflow.conf` — shares existing httpd with spideybot; spideybot's vhost untouched
- Systemd units: `icreateflow-backend.service` (gunicorn `-w 1`), `icreateflow-frontend.service`
- Background tasks: Clipping scheduler (planner / dispatcher / view poller / cache sweep) runs inside the backend process via FastAPI lifespan — no extra systemd unit
- Persistent data: `/srv/icreateflow/data/{output,uploads,music}` (symlinked into backend dir so deploys don't wipe them)

---

## 0. Prerequisites

- DNS: `icreateflow.com` and `www.icreateflow.com` A records → box IP.
- SSH access as `root` to the box.
- This repo cloned on your Mac, on the `main` branch.

---

## 1. First-time server setup (run ONCE on a fresh box)

```bash
cd /path/to/Zagged
bash deploy/sync.sh                          # rsync code to /srv/icreateflow/src + stage systemd/apache files
ssh root@95.111.228.80 'bash /srv/icreateflow/src/deploy/server-setup.sh'
```

`server-setup.sh` is idempotent. It:
- Installs Python 3.12, Postgres 16, FFmpeg, Apache, certbot, Node 20.
- Inits Postgres with tuning.
- Creates `icreateflow` Linux user, Postgres role + DB with a randomly generated password.
- Builds the Python 3.12 venv at `/srv/icreateflow/venv`.
- Installs systemd units and the Apache vhost.
- Opens firewall 80/443, sets SELinux `httpd_can_network_connect`.
- Writes `/srv/icreateflow/backend/.env` with a fresh `ICREATE_JWT_SECRET` and the matching DB DSN.

After first setup, switch to `ship.sh` for all future deploys.

---

## 2. Deploy every code change — ONE command from your Mac

```bash
bash deploy/ship.sh
```

`ship.sh`:
1. Verifies you're on `main` with nothing uncommitted.
2. `git push origin main`.
3. SSHes to server — retries `git fetch` up to 5× until server sees the exact pushed SHA (handles GitHub CDN propagation lag).
4. `git reset --hard` + `rm -f .git/index && git checkout HEAD -- .` to guarantee working tree matches HEAD.
5. Runs `deploy.sh` on the server.

`deploy.sh` (server-side, called by ship.sh):
- `git archive HEAD backend/ | tar -x` into `/srv/icreateflow/backend/`
- `git archive HEAD frontend/ | tar -x` into `/srv/icreateflow/frontend/`
- `pip install -r requirements.txt`
- `database.init_db()` — creates/migrates tables (idempotent)
- `npm ci && npm run build` for Next.js
- Symlinks `backend/{output,uploads,music}` → `/srv/icreateflow/data/*`
- `systemctl restart icreateflow-{backend,frontend}`

> **Why git archive, not rsync?**
> rsync copies from the working tree — vulnerable to stale staged changes or a corrupt git index.
> `git archive` reads directly from git objects — always exactly what's in HEAD.

> **Why ship.sh, not manual deploy.sh?**
> `deploy.sh` is a pure "extract and restart" script. If you call it directly on the server without ship.sh having first updated SRC to the correct commit, it will deploy whatever commit SRC currently points to — which may be old.

---

## 3. Enable SSL (run ONCE after first deploy)

```bash
ssh root@95.111.228.80 'certbot --apache -d icreateflow.com -d www.icreateflow.com \
    --non-interactive --agree-tos --email admin@icreateflow.com --redirect'
```

Auto-renewal handled by `certbot-renew.timer` on the box.

---

## 4. Bootstrap the first admin (run ONCE)

```bash
# Register via the app UI at /register, then:
ssh root@95.111.228.80 'sudo -u postgres psql icreateflow -c \
    "UPDATE users SET role='\''admin'\'' WHERE email='\''you@example.com'\'';"'
```

Log out + back in. `/admin` is now accessible.

---

## 5. Secrets & third-party keys

`/srv/icreateflow/backend/.env` (chmod 600, owned by `icreateflow`) holds only:
- `ICREATE_JWT_SECRET` — JWT signing key
- `ICREATE_DB_DSN` — Postgres DSN

**Everything else is set in the admin UI** (stored in `settings` / `site_config` tables):

| Where | Key | Used for |
|---|---|---|
| `/settings` | Anthropic API Key | Claude Vision OCR |
| `/settings` | Replicate API Token | Flux image generation |
| `/admin → Site Config` | SMTP host/port/user/password | Email notifications |
| `/admin → Site Config` | `site_logo_url` | Logo in emails — must be a PNG URL (SVG blocked by email clients) |
| `/admin → OAuth Apps` | TikTok client id/secret | TikTok OAuth |
| `/admin → OAuth Apps` | YouTube client id/secret | YouTube OAuth |
| `/admin → OAuth Apps` | Meta client id/secret | IG + Facebook OAuth |
| `/admin → OAuth Apps` | Google Drive API key | Clipping clip sync |
| `/admin → OAuth Apps` | Redirect base URL | `https://icreateflow.com` — used for all OAuth callbacks and video source URLs |

---

## 6. Ops commands

```bash
# Logs (follow)
journalctl -u icreateflow-backend  -f
journalctl -u icreateflow-frontend -f

# Status / restart
systemctl status icreateflow-backend icreateflow-frontend
systemctl restart icreateflow-backend

# DB shell
sudo -u postgres psql icreateflow

# Apache config check + reload
httpd -t && systemctl reload httpd

# Disk usage (generated content)
du -sh /srv/icreateflow/data/output /srv/icreateflow/data/uploads
```

---

## 7. What's NOT automated (by design)

- `.env` edits — never overwritten after first run.
- Third-party API keys — admin UI only; never in git.
- First admin promotion — manual SQL (§4).
- Postgres schema beyond `init_db()` — add a `_migrate_*` function to `database.py`.
- Spideybot — fully isolated. These scripts only add new files.

---

## 8. Troubleshooting

**Backend won't start: `asyncpg.InvalidPasswordError`**
```bash
ssh root@95.111.228.80 'DBPW=$(openssl rand -hex 24); \
    sudo -u postgres psql -c "ALTER ROLE icreateflow WITH PASSWORD '\''$DBPW'\''"; \
    sed -i "s|icreateflow:[^@]*@|icreateflow:$DBPW@|" /srv/icreateflow/backend/.env; \
    systemctl restart icreateflow-backend'
```

**All users logged out after a deploy**
`ICREATE_JWT_SECRET` got rotated. Not recoverable — users must re-login.

**Clipping scheduler not firing**
```bash
journalctl -u icreateflow-backend | grep -i "scheduler\|plan_slots\|dispatch"
```
Loops catch per-item exceptions; a silent failure means the lifespan didn't start tasks (usually a DB-connect failure on boot). Restart the service.

**UI looks unchanged after a deploy**
Browser cache. Hard refresh: `Cmd + Shift + R` (Chrome/Edge Mac).

**Code change not on server after ship.sh**
```bash
ssh root@95.111.228.80 'cd /srv/icreateflow/src && git log --oneline -1'
# Compare with: git log --oneline -1
# If behind: cd /Users/mac/Desktop/Zagged && bash deploy/ship.sh
```

**YouTube quota exhausted (view polling stopped)**
```bash
journalctl -u icreateflow-backend | grep "quota exhausted"
systemctl restart icreateflow-backend   # clears process-level flag immediately
```
