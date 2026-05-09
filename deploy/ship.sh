#!/usr/bin/env bash
#
# One-command deploy: push local main → GitHub, then SSH the server to deploy
# that exact commit. The server retries its git fetch until it sees the SHA,
# so there is no race between the push and the server's pull.
#
# Usage (from repo root):
#     bash deploy/ship.sh
#
set -euo pipefail

HOST="${ICREATE_HOST:-root@187.124.231.108}"
REMOTE_DEPLOY="bash /srv/icreateflow/src/deploy/deploy.sh"

# ---- 1. Make sure we're on main and everything is committed ----------------
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

# ---- 3. SSH deploy, passing the expected SHA so the server waits for it ----
echo "==> Deploying on $HOST (expect SHA=$SHA)"
ssh "$HOST" "EXPECT_SHA=$SHA $REMOTE_DEPLOY"
