#!/usr/bin/env bash
#
# Re-runnable ICREATEFLOW deploy.
#
# DO NOT call this script directly on the server.
# Use `bash deploy/ship.sh` from your Mac — it handles git push + server sync
# before calling this script, so the SRC directory is always up-to-date first.
#
# If you must call it manually:
#   ssh root@95.111.228.80 'bash /srv/icreateflow/src/deploy/deploy.sh'
# but only AFTER ensuring /srv/icreateflow/src is at the correct commit.
#
# Installs/updates backend deps, builds frontend, restarts services.
#
set -euo pipefail

APP_DIR=/srv/icreateflow
SRC=$APP_DIR/src
BACKEND=$APP_DIR/backend
FRONTEND=$APP_DIR/frontend
VENV=$APP_DIR/venv
USER=icreateflow

# ---------------------------------------------------------------------------
# Extract code from git — no fetch, no reset. ship.sh already updated SRC.
# Wipe src/ sub-trees first so deleted files don't linger across deploys.
# ---------------------------------------------------------------------------
echo "==> Extracting code from git archive (commit: $(cd $SRC && git rev-parse --short HEAD))"
cd "$SRC"

# Wipe src trees so deleted files don't linger — preserve .env across wipe
[ -f "$BACKEND/.env" ] && cp "$BACKEND/.env" /tmp/_icreateflow_env_bak
rm -rf "$BACKEND" && mkdir -p "$BACKEND"
[ -f /tmp/_icreateflow_env_bak ] && mv /tmp/_icreateflow_env_bak "$BACKEND/.env"

rm -rf "$FRONTEND/src" "$FRONTEND/public" \
       "$FRONTEND/next.config"* "$FRONTEND/package"* \
       "$FRONTEND/tsconfig"* "$FRONTEND/tailwind"* \
       "$FRONTEND/postcss"* "$FRONTEND/.eslint"* 2>/dev/null || true

git archive HEAD backend/  | tar -x -C "$APP_DIR/" --overwrite
git archive HEAD frontend/ | tar -x -C "$APP_DIR/" --overwrite
git archive HEAD fonts/    | tar -x -C "$APP_DIR/" --overwrite 2>/dev/null || true
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

# Outreach workers, if any are enabled on this box. A restart is safe at any
# moment: an in-flight job keeps its lease and is requeued by the reaper, so
# nothing is lost and nothing is sent twice.
OUTREACH_UNITS=$(systemctl list-units --state=active --plain --no-legend \
    'icreateflow-outreach-worker@*' 2>/dev/null | awk '{print $1}')
if [ -n "$OUTREACH_UNITS" ]; then
    echo "==> Restarting outreach workers"
    # shellcheck disable=SC2086
    systemctl restart $OUTREACH_UNITS
fi

sleep 2
echo
echo "==> Service status:"
systemctl is-active icreateflow-backend  && echo "  backend  : active"
systemctl is-active icreateflow-frontend && echo "  frontend : active"
for unit in $OUTREACH_UNITS; do
    systemctl is-active "$unit" >/dev/null && echo "  $unit : active"
done
echo
echo "==> Deploy complete."
echo "    Logs:  journalctl -u icreateflow-backend -f"
echo "           journalctl -u icreateflow-frontend -f"
