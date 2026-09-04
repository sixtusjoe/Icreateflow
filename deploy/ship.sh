#!/usr/bin/env bash
#
# One-command deploy: push to GitHub then update + deploy on the server.
#
# Usage (from repo root):
#     bash deploy/ship.sh
#
set -euo pipefail

HOST="${ICREATE_HOST:-root@95.111.228.80}"
SRC_DIR="/srv/icreateflow/src"

# ---- 1. Must be on main with nothing uncommitted ---------------------------
BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$BRANCH" != "main" ]; then
    echo "ERROR: not on main (you are on '$BRANCH'). Checkout main before shipping."
    exit 1
fi
if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "ERROR: uncommitted changes — commit or stash before shipping."
    git status --short
    exit 1
fi

# ---- 2. Push to GitHub -----------------------------------------------------
echo "==> Pushing main → origin"
git push origin main
SHA=$(git rev-parse HEAD)
echo "==> Pushed $SHA"

# ---- 3. Update server SRC to exact SHA -------------------------------------
echo "==> Updating server SRC to $SHA"
ssh "$HOST" bash -s -- "$SRC_DIR" "$SHA" <<'ENDSSH'
set -euo pipefail
SRC_DIR=$1
WANT_SHA=$2

# Git refuses to operate on a repo owned by another user ("detected dubious
# ownership"): we SSH in as root, but /srv/icreateflow/src is owned by the
# icreateflow service user. Whitelist it once — checked first so repeated
# deploys don't append the same line to ~/.gitconfig forever.
if ! git config --global --get-all safe.directory 2>/dev/null | grep -qx "$SRC_DIR"; then
    echo "  whitelisting $SRC_DIR as a safe.directory for $(whoami)"
    git config --global --add safe.directory "$SRC_DIR"
fi

cd "$SRC_DIR"
for attempt in 1 2 3 4 5; do
    git fetch origin
    GOT=$(git rev-parse origin/main)
    if [ "$GOT" = "$WANT_SHA" ]; then
        break
    fi
    echo "  fetch attempt $attempt: got $GOT, want $WANT_SHA — retrying in 5s"
    sleep 5
done
git reset --hard origin/main
# Force the working tree to exactly match the commit. Without git clean,
# untracked/stale files (e.g. an api.ts left behind by an aborted deploy)
# can survive and get rsynced into the app dir, breaking the build.
git clean -fd
echo "  SRC is now at: $(git rev-parse --short HEAD)"
echo "  Verifying tree is clean:"
git status --short | head
ENDSSH

# ---- 4. Run deploy.sh on server --------------------------------------------
echo "==> Running deploy on $HOST"
ssh "$HOST" "bash $SRC_DIR/deploy/deploy.sh"
