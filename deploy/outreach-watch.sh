#!/usr/bin/env bash
#
# Watch one outreach send happen, live.
#
#     ssh -t root@95.111.228.80 'bash /srv/icreateflow/src/deploy/outreach-watch.sh'
#
# Runs exactly one queued job with the browser visible on a virtual display,
# served over VNC, so you can watch it load the profile, click Message, type
# and send. Prefer `deploy/outreach-watch-mac.sh` — it opens the tunnel and
# the viewer for you.
#
# This is a real send, not a rehearsal: the job comes off the same queue,
# through the same worker code, and its result is recorded normally. The
# only difference is that you can see it.
#
# The background workers are stopped for the duration, so the job you are
# watching cannot be claimed out from under you by one of them, and are
# started again on exit however this ends.
#
set -euo pipefail

APP_DIR=/srv/icreateflow
BACKEND=$APP_DIR/backend
VENV=$APP_DIR/venv
SERVICE_USER=icreateflow
BROWSERS_DIR=$APP_DIR/pw-browsers
DRIVER="${1:-}"

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: run this as root."
    exit 1
fi
if [ ! -f "$BACKEND/scripts/outreach_worker.py" ]; then
    echo "ERROR: outreach code is not on this box — run deploy/ship.sh first."
    exit 1
fi

# shellcheck source=/dev/null
. "$(dirname "$0")/_vnc-session.sh"

set -a
# shellcheck disable=SC1090
. "$BACKEND/.env"
set +a
export PLAYWRIGHT_BROWSERS_PATH="$BROWSERS_DIR"
# The whole point: a browser you can see.
export ICREATE_OUTREACH_HEADLESS=0

# Which workers are running now, so exactly those come back afterwards.
STOPPED_WORKERS=$(systemctl list-units --state=active --plain --no-legend \
    'icreateflow-outreach-worker@*' 2>/dev/null | awk '{print $1}' || true)

restore_workers() {
    if [ -n "$STOPPED_WORKERS" ]; then
        echo "==> Restarting background workers"
        # shellcheck disable=SC2086
        systemctl start $STOPPED_WORKERS || true
    fi
}
trap 'restore_workers; vnc_cleanup' EXIT INT TERM

if [ -n "$STOPPED_WORKERS" ]; then
    echo "==> Pausing background workers so this job is the one you see"
    # shellcheck disable=SC2086
    systemctl stop $STOPPED_WORKERS
fi

vnc_require_deps
vnc_start "$VENV/bin/python"
vnc_banner \
    "A browser will open and run one real send. Watch it load the
   profile, click Message, type, and submit." \
    "It closes itself when the job finishes — that is the end,
   not an error. The result is on the campaign page."

cd "$BACKEND"
echo "==> Running one job with the browser visible"
echo

ARGS=(--once)
[ -n "$DRIVER" ] && ARGS+=(--driver "$DRIVER")

sudo -u "$SERVICE_USER" \
    --preserve-env=ICREATE_DB_DSN,ICREATE_OUTREACH_SECRET,ICREATE_JWT_SECRET,PLAYWRIGHT_BROWSERS_PATH,DISPLAY,ICREATE_OUTREACH_HEADLESS \
    "$VENV/bin/python" "$BACKEND/scripts/outreach_worker.py" "${ARGS[@]}"

echo
echo "==> Finished. Check the campaign page for the recorded result."
