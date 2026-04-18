#!/usr/bin/env bash
#
# ICREATEFLOW — one-time VPS setup.
#
# Run ONCE as root on the box (187.124.231.108):
#     curl -fsSL https://... | bash         # or
#     scp deploy/server-setup.sh root@host:/tmp/ && ssh root@host "bash /tmp/server-setup.sh"
#
# Idempotent: re-running is safe; existing steps are skipped.
# Does NOT touch spideybot — only adds new users, DB, ports, and nginx server blocks.
#
set -euo pipefail

echo "==> ICREATEFLOW server-setup — AlmaLinux 9"

# ---------------------------------------------------------------------------
# 1. System packages
# ---------------------------------------------------------------------------
echo "==> Installing system packages"
dnf install -y epel-release
dnf install -y \
    https://mirrors.rpmfusion.org/free/el/rpmfusion-free-release-9.noarch.rpm \
    https://mirrors.rpmfusion.org/nonfree/el/rpmfusion-nonfree-release-9.noarch.rpm || true

# Python 3.12, Postgres 16, FFmpeg, nginx, certbot, rsync, git
dnf module reset -y postgresql || true
dnf module enable -y postgresql:16
dnf module reset -y python3.12 || true

# NOTE: We piggy-back on the existing Apache/httpd that Hostinger's hPanel
# already runs for spideybot.com. We do NOT install nginx — Apache owns :80/:443.
dnf install -y \
    python3.12 python3.12-devel python3.12-pip \
    postgresql-server postgresql-contrib \
    ffmpeg \
    httpd mod_ssl \
    certbot python3-certbot-apache \
    rsync git tar gcc make openssl-devel libffi-devel \
    firewalld policycoreutils-python-utils

# Node.js 20 LTS (NodeSource)
if ! command -v node >/dev/null 2>&1 || [ "$(node -v | cut -d. -f1 | tr -d v)" -lt 20 ]; then
    curl -fsSL https://rpm.nodesource.com/setup_20.x | bash -
    dnf install -y nodejs
fi

# ---------------------------------------------------------------------------
# 2. Postgres 16 init + service
# ---------------------------------------------------------------------------
echo "==> Initializing Postgres"
if [ ! -f /var/lib/pgsql/data/PG_VERSION ]; then
    postgresql-setup --initdb
fi
systemctl enable --now postgresql

# Create app DB + user (idempotent)
sudo -u postgres psql <<'SQL'
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'icreateflow') THEN
        CREATE ROLE icreateflow LOGIN PASSWORD 'OBo8fNSwwkvPmu3qJe7HTPmPoRl7aq1';
    END IF;
END$$;

SELECT 'CREATE DATABASE icreateflow OWNER icreateflow'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'icreateflow')\gexec
SQL

# Tune postgresql.conf for 8 GB box (only if not already tuned)
PGCONF=/var/lib/pgsql/data/postgresql.conf
if ! grep -q "# ICREATEFLOW tuning" "$PGCONF"; then
    cat >> "$PGCONF" <<'EOF'

# ICREATEFLOW tuning — 8 GB box shared with spideybot
shared_buffers = 1GB
effective_cache_size = 4GB
work_mem = 16MB
maintenance_work_mem = 128MB
max_connections = 50
EOF
    systemctl restart postgresql
fi

# Ensure password auth for the app user on localhost
PGHBA=/var/lib/pgsql/data/pg_hba.conf
if ! grep -q "icreateflow" "$PGHBA"; then
    # Insert a rule for the app user BEFORE the default "all" rules
    sed -i '/^host    all.*127.0.0.1/i host    icreateflow     icreateflow     127.0.0.1/32            scram-sha-256' "$PGHBA"
    systemctl reload postgresql
fi

# ---------------------------------------------------------------------------
# 3. App user + directory layout
# ---------------------------------------------------------------------------
echo "==> Creating icreateflow user + directories"
if ! id icreateflow >/dev/null 2>&1; then
    useradd -r -m -d /srv/icreateflow -s /bin/bash icreateflow
fi

install -d -o icreateflow -g icreateflow -m 755 \
    /srv/icreateflow \
    /srv/icreateflow/backend \
    /srv/icreateflow/frontend \
    /srv/icreateflow/logs \
    /srv/icreateflow/data \
    /srv/icreateflow/data/output \
    /srv/icreateflow/data/uploads

# ---------------------------------------------------------------------------
# 4. Python venv + pip upgrade
# ---------------------------------------------------------------------------
echo "==> Creating Python 3.12 venv"
sudo -u icreateflow python3.12 -m venv /srv/icreateflow/venv
sudo -u icreateflow /srv/icreateflow/venv/bin/pip install -U pip setuptools wheel

# ---------------------------------------------------------------------------
# 5. systemd units
# ---------------------------------------------------------------------------
echo "==> Installing systemd units"
cp /tmp/icreateflow-backend.service  /etc/systemd/system/
cp /tmp/icreateflow-frontend.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable icreateflow-backend icreateflow-frontend

# ---------------------------------------------------------------------------
# 6. Apache vhost — new conf.d file, does NOT touch spideybot's vhost
# ---------------------------------------------------------------------------
echo "==> Installing Apache vhost for icreateflow.com"
cp /tmp/icreateflow.apache.conf /etc/httpd/conf.d/icreateflow.conf
# Legacy: remove stale nginx drop-in if a previous run created one
rm -f /etc/nginx/conf.d/icreateflow.conf 2>/dev/null || true
systemctl disable --now nginx 2>/dev/null || true
httpd -t
systemctl enable --now httpd
systemctl reload httpd

# ---------------------------------------------------------------------------
# 7. Firewall — 80/443 (if not already open for spideybot)
# ---------------------------------------------------------------------------
echo "==> Configuring firewall"
if systemctl is-active --quiet firewalld; then
    firewall-cmd --permanent --add-service=http  --quiet || true
    firewall-cmd --permanent --add-service=https --quiet || true
    firewall-cmd --reload --quiet
fi

# SELinux: allow nginx to proxy to localhost ports
setsebool -P httpd_can_network_connect 1 || true

echo
echo "==> server-setup complete."
echo
echo "Next steps (run these in order):"
echo "  1. From your Mac: bash deploy/sync.sh         # rsync code → server"
echo "  2. On server:     bash /srv/icreateflow/deploy/deploy.sh   # install + build"
echo "  3. On server:     certbot --apache -d icreateflow.com -d www.icreateflow.com \\"
echo "                        --non-interactive --agree-tos --email admin@icreateflow.com --redirect"
echo "                    (SSL vhost is pre-baked in apache/icreateflow.conf — certs just plug in)"
echo
