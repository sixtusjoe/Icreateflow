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
- Persistent data: `/srv/icreateflow/data/{output,uploads}` (symlinked into backend dir so deploys don't wipe them)

---

## 0. Prerequisites

- DNS: `icreateflow.com` and `www.icreateflow.com` A records → `187.124.231.108` (confirmed).
- SSH access as `root` to the box.
- This repo cloned on your Mac at `/Users/mac/Desktop/Zagged`.

---

## 1. First-time server setup (run ONCE)

From your Mac:

```bash
cd /Users/mac/Desktop/Zagged
bash deploy/sync.sh                                     # rsync code + stage systemd/nginx files to /tmp
ssh root@187.124.231.108 'bash /srv/icreateflow/src/deploy/server-setup.sh'
```

`server-setup.sh` is idempotent — safe to re-run. It:
- Installs Python 3.12, Postgres 16, FFmpeg, nginx, certbot, Node 20.
- Inits Postgres with 8 GB tuning (shared with spideybot).
- Creates `icreateflow` Linux user, Postgres role + DB.
- Builds the Python 3.12 venv at `/srv/icreateflow/venv`.
- Installs systemd units and the nginx server block.
- Opens firewall 80/443, sets SELinux `httpd_can_network_connect`.

---

## 2. Deploy (every code change)

From your Mac:

```bash
bash deploy/sync.sh                                     # rsync code → /srv/icreateflow/src
ssh root@187.124.231.108 'bash /srv/icreateflow/src/deploy/deploy.sh'
```

`deploy.sh`:
- Rsyncs src → `backend/` + `frontend/` app dirs (preserves `/data`).
- Seeds `.env` on first run from `deploy/.env.example`, leaves it alone after.
- `pip install -r requirements.txt` into the venv.
- Runs `database.init_db()` (idempotent — creates tables if missing).
- `npm ci && npm run build` for Next.js.
- Symlinks `backend/output` → `/srv/icreateflow/data/output` (same for `uploads`).
- `systemctl restart icreateflow-backend icreateflow-frontend`.

---

## 3. Enable SSL (run ONCE after first deploy)

```bash
ssh root@187.124.231.108 'certbot --apache -d icreateflow.com -d www.icreateflow.com \
    --non-interactive --agree-tos --email admin@icreateflow.com --redirect'
```

The apache vhost already has the `:443` block + `SSLCertificateFile` paths baked in, so certbot just issues the cert and Apache picks it up on reload. Auto-renewal is handled by the `certbot-renew.timer` unit already on the box.

---

## 4. Secrets

`/srv/icreateflow/backend/.env` on the server (chmod 600, owned by `icreateflow`). Seeded from `deploy/.env.example` on first deploy.

- `ICREATE_JWT_SECRET` — JWT signing key. Pre-generated; rotate with `openssl rand -hex 48`.
- `ICREATE_DB_DSN` — `postgresql+asyncpg://icreateflow:<password>@127.0.0.1:5432/icreateflow`.
- `ANTHROPIC_API_KEY` / `REPLICATE_API_TOKEN` — **intentionally blank**. Set them in-app via the admin settings panel (stored in the `settings` table).

Postgres password is baked into `.env.example`. If you regenerate it, update `pg_hba.conf`'s `ALTER ROLE` or reset via `psql`.

---

## 5. Ops

```bash
# Logs (follow)
journalctl -u icreateflow-backend  -f
journalctl -u icreateflow-frontend -f

# Status
systemctl status icreateflow-backend icreateflow-frontend
systemctl is-active icreateflow-backend

# Restart after manual config edit
systemctl restart icreateflow-backend

# DB shell
sudo -u postgres psql icreateflow
# or with app role over localhost:
PGPASSWORD=... psql -h 127.0.0.1 -U icreateflow -d icreateflow

# Apache
httpd -t && systemctl reload httpd

# Disk usage (generated content grows here)
du -sh /srv/icreateflow/data/output /srv/icreateflow/data/uploads
```

---

## 6. What's NOT automated (by design)

- `.env` edits — never overwritten after first deploy. Edit directly on the server.
- Postgres schema migrations beyond `init_db()` — run manually when introducing breaking changes.
- Spideybot — fully isolated. These scripts only add new files; nothing is shared.

---

## 7. Future work (explicitly deferred)

- Admin "purge old user content" button (one-click cleanup of stale output/uploads).
- Queued-state animation on the Generate button when FFmpeg workers are saturated, auto-starting when a slot frees.
