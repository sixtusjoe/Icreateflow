#!/usr/bin/env bash
#
# One-command deploy: push local main → GitHub, then update the server's
# git checkout and run deploy.sh. All git operations happen here (in ship.sh),
# NOT inside deploy.sh — so deploy.sh always starts with a clean, correct SRC.
#
# Usage (from repo root):
#     bash deploy/ship.sh
#
set -euo pipefail

HOST="${ICREATE_HOST:-root@187.124.231.108}"
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

# ---- 3. Update server SRC to exact SHA (retry until GitHub propagates) -----
echo "==> Updating server SRC to $SHA"
ssh "$HOST" bash -s -- "$SRC_DIR" "$SHA" <<'ENDSSH'
set -euo pipefail
SRC_DIR=$1
WANT_SHA=$2
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
# Force working tree to exactly match HEAD (clears any stale files)
git reset --hard origin/main
rm -f .git/index
git checkout HEAD -- .
echo "  SRC is now at: $(git rev-parse --short HEAD)"
ENDSSH

# ---- 4. Run deploy.sh (no git needed — SRC is already correct) -------------
echo "==> Running deploy on $HOST"
ssh "$HOST" "bash $SRC_DIR/deploy/deploy.sh"
