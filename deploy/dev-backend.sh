#!/usr/bin/env bash
#
# Start the local backend by hand.
#
# This used to be a launch.json entry, but the preview launcher refuses to
# start anything when its port is taken — and 8000 is normally taken, by a
# backend already running with a browser session under it that a restart
# would kill. So launch.json attaches to that backend instead, and starting
# one from cold lives here.
#
#     bash deploy/dev-backend.sh
#
set -euo pipefail

BACKEND="${ICREATE_LOCAL_BACKEND:-/Users/mac/icreateflow-local/backend}"

if lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Port 8000 is already serving — nothing started."
    echo "To replace it, stop that process first:  lsof -nP -iTCP:8000 -sTCP:LISTEN"
    exit 0
fi

cd "$BACKEND"
set -a
# shellcheck disable=SC1091
. "$BACKEND/local-env.sh"
set +a
exec "$BACKEND/venv/bin/uvicorn" main:app --host 127.0.0.1 --port 8000
