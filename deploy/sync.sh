#!/usr/bin/env bash
#
# Sync ICREATEFLOW source from this Mac → the VPS.
# Run from the repo root on your Mac:
#     bash deploy/sync.sh
#
# Does NOT copy: venv, node_modules, .next, __pycache__, *.db, .git, .env,
# generated /data content. Deletes stale files on server (--delete).
#
set -euo pipefail

HOST="${ICREATE_HOST:-root@187.124.231.108}"
SRC="$(cd "$(dirname "$0")/.." && pwd)/"
DST="/srv/icreateflow/src/"

echo "==> Rsyncing $SRC → $HOST:$DST"

ssh "$HOST" "install -d -o icreateflow -g icreateflow /srv/icreateflow/src"

rsync -az --delete \
    --exclude='.git/' \
    --exclude='.DS_Store' \
    --exclude='node_modules/' \
    --exclude='.next/' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='venv/' \
    --exclude='.venv/' \
    --exclude='backend/icreate.db*' \
    --exclude='backend/zagged.db*' \
    --exclude='backend/output/' \
    --exclude='backend/uploads/' \
    --exclude='backend/.env' \
    --exclude='frontend/.env.local' \
    --exclude='frontend/.env.production' \
    --rsync-path="sudo -u icreateflow rsync" \
    "$SRC" "$HOST:$DST"

# Stage systemd units + apache vhost for server-setup.sh to pick up.
# Use absolute paths so this works regardless of CWD.
scp "${SRC}deploy/systemd/icreateflow-backend.service"  "$HOST:/tmp/icreateflow-backend.service"
scp "${SRC}deploy/systemd/icreateflow-frontend.service" "$HOST:/tmp/icreateflow-frontend.service"
scp "${SRC}deploy/apache/icreateflow.conf"              "$HOST:/tmp/icreateflow.apache.conf"

echo
echo "==> Sync complete."
echo "    On first deploy:  ssh $HOST 'bash /srv/icreateflow/src/deploy/server-setup.sh'"
echo "    Then / after:     ssh $HOST 'bash /srv/icreateflow/src/deploy/deploy.sh'"
