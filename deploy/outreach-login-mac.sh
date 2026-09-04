#!/usr/bin/env bash
#
# Sign an outreach sending account in — one command, from your Mac.
#
#     bash deploy/outreach-login-mac.sh        # list your accounts
#     bash deploy/outreach-login-mac.sh 1      # sign in account 1
#
# Does the whole dance for you: starts the browser on the server, opens the
# SSH tunnel, and launches macOS Screen Sharing pointed at it. A window
# appears — sign in normally. The session is captured and encrypted into the
# account the moment you're logged in, then everything is torn down.
#
set -euo pipefail

HOST="${ICREATE_HOST:-root@95.111.228.80}"
REMOTE=/srv/icreateflow/src/deploy/outreach-login.sh
PORT="${ICREATE_LOGIN_VNC_PORT:-5900}"

# --- no account given → just list them -------------------------------------
if [ $# -lt 1 ]; then
    ssh "$HOST" "bash $REMOTE"
    echo
    echo "Then run:  bash $0 <ID>"
    exit 0
fi

ACCOUNT_ID=$1
case "$ACCOUNT_ID" in
    ''|*[!0-9]*) echo "ERROR: give an account ID (a number). Run with no arguments to list them."; exit 1 ;;
esac

# macOS enables its own screen sharing on 5900; step aside if it's in use.
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    PORT=5901
    echo "==> Port 5900 is busy on this Mac, using $PORT instead"
fi

# A control socket makes the background tunnel easy to shut down cleanly.
CTL="/tmp/icreateflow-vnc-$$"
cleanup() {
    ssh -S "$CTL" -O exit "$HOST" 2>/dev/null || true
    rm -f "$CTL"
}
trap cleanup EXIT INT TERM

echo "==> Opening tunnel to $HOST"
ssh -M -S "$CTL" -f -N -L "$PORT:localhost:${ICREATE_LOGIN_VNC_PORT:-5900}" "$HOST"

# The remote side needs a moment to bring up the display and the browser
# before there is anything to look at.
(
    sleep 12
    echo
    echo "==> Opening Screen Sharing — sign in to the account in that window."
    open "vnc://localhost:$PORT" 2>/dev/null || {
        echo "!!  Couldn't open Screen Sharing automatically."
        echo "!!  In Finder press Cmd-K and enter:  vnc://localhost:$PORT"
    }
) &

echo "==> Starting the browser on the server"
echo
ssh -t "$HOST" "bash $REMOTE $ACCOUNT_ID"
