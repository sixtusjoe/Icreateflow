#!/usr/bin/env bash
#
# Re-runnable ICREATEFLOW deploy.
# Run on the VPS as root AFTER sync.sh has rsynced code to /srv/icreateflow/src/.
#
#     ssh root@187.124.231.108 'bash /srv/icreateflow/src/deploy/deploy.sh'
#
# Installs/updates backend deps, builds frontend, restarts services.
# Does NOT touch spideybot.
#
set -euo pipefail

APP_DIR=/srv/icreateflow
SRC=$APP_DIR/src
BACKEND=$APP_DIR/backend
FRONTEND=$APP_DIR/frontend
VENV=$APP_DIR/venv
USER=icreateflow

echo "==> Syncing code into app dirs"
rsync -a --delete --exclude='.env' "$SRC/backend/"  "$BACKEND/"
rsync -a --delete --exclude='.env.production' --exclude='.env.local' "$SRC/frontend/" "$FRONTEND/"
rsync -a --delete "$SRC/fonts/"    "$APP_DIR/fonts/" 2>/dev/null || true
chown -R $USER:$USER "$BACKEND" "$FRONTEND" "$APP_DIR/fonts" 2>/dev/null || true

# ---------------------------------------------------------------------------
# .env — created on first run if missing, then left alone.
# ---------------------------------------------------------------------------
if [ ! -f "$BACKEND/.env" ]; then
    echo "==> Seeding backend/.env (first run)"
    cp "$SRC/deploy/.env.example" "$BACKEND/.env"
    chown $USER:$USER "$BACKEND/.env"
    chmod 600 "$BACKEND/.env"
fi

# Frontend needs to know the API base (same-origin /api on prod).
cat > "$FRONTEND/.env.production" <<'EOF'
NEXT_PUBLIC_API_URL=https://icreateflow.com
EOF
chown $USER:$USER "$FRONTEND/.env.production"

# ---------------------------------------------------------------------------
# Backend — pip install + init DB schema
# ---------------------------------------------------------------------------
echo "==> Installing backend deps"
sudo -u $USER $VENV/bin/pip install -U pip
sudo -u $USER $VENV/bin/pip install -r "$BACKEND/requirements.txt"

echo "==> Initializing DB schema"
sudo -u $USER bash -c "set -a; . $BACKEND/.env; set +a; cd $BACKEND && $VENV/bin/python -c 'import asyncio, database; asyncio.run(database.init_db())'"

# ---------------------------------------------------------------------------
# Frontend — install + build
# ---------------------------------------------------------------------------
echo "==> Installing frontend deps + building"
sudo -u $USER bash -c "cd $FRONTEND && npm ci --no-audit --no-fund"
sudo -u $USER bash -c "cd $FRONTEND && npm run build"

# ---------------------------------------------------------------------------
# Generated-content directories (persist across deploys)
# ---------------------------------------------------------------------------
install -d -o $USER -g $USER "$APP_DIR/data/output" "$APP_DIR/data/uploads" "$APP_DIR/data/music"
# Symlink backend's expected paths → persistent data dir.
# Each path is removed first in case rsync recreated it as a regular dir
# (ln -sfn won't overwrite an existing directory, only a symlink).
for d in output uploads music; do
    if [ -d "$BACKEND/$d" ] && [ ! -L "$BACKEND/$d" ]; then
        rm -rf "$BACKEND/$d"
    fi
    ln -sfn "$APP_DIR/data/$d" "$BACKEND/$d"
done

# ---------------------------------------------------------------------------
# Restart services
# ---------------------------------------------------------------------------
echo "==> Restarting services"
systemctl restart icreateflow-backend
systemctl restart icreateflow-frontend

sleep 2
echo
echo "==> Service status:"
systemctl is-active icreateflow-backend  && echo "  backend  : active"
systemctl is-active icreateflow-frontend && echo "  frontend : active"
echo
echo "==> Deploy complete."
echo "    Logs:  journalctl -u icreateflow-backend -f"
echo "           journalctl -u icreateflow-frontend -f"
