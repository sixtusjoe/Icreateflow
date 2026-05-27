#!/usr/bin/env bash
#
# One-command deploy: commit and push to GitHub.
# The server picks up the change automatically via the systemd timer
# (icreateflow-autodeploy.timer), which polls GitHub every 2 minutes
# and runs deploy.sh when it detects a new commit.
#
# Usage (from repo root):
#     bash deploy/ship.sh
#
set -euo pipefail

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
echo
echo "==> Server will auto-deploy within ~2 minutes."
echo "    Watch:  ssh root@187.124.231.108 'tail -f /var/log/icreateflow-autodeploy.log'"
