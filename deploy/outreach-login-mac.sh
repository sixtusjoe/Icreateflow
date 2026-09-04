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

# Wait for the VNC server to actually answer before opening the viewer.
#
# A fixed delay is wrong: the first run on a box installs Xvfb and x11vnc
# first, which takes far longer than any sensible guess, and connecting
# early just gives "Connection failed to localhost".
#
# `nc -z` is not enough either — the tunnel's local port is bound by ssh
# immediately, so a bare connect succeeds even when nothing is listening on
# the far end. A real VNC server greets us with an "RFB 003.00x" banner, so
# wait for that.
(
    for _ in $(seq 1 150); do   # up to ~5 minutes
        if printf '' | nc -w 2 localhost "$PORT" 2>/dev/null | head -c 3 | grep -q RFB
        then
            sleep 1
            echo
            echo "==> Opening Screen Sharing — sign in to the account in that window."
            open "vnc://localhost:$PORT" 2>/dev/null || {
                echo "!!  Couldn't open Screen Sharing automatically."
                echo "!!  In Finder press Cmd-K and enter:  vnc://localhost:$PORT"
            }
            exit 0
        fi
        sleep 2
    done
    echo
    echo "!!  The server's VNC never came up. Once you see 'Starting VNC' above,"
    echo "!!  press Cmd-K in Finder and enter:  vnc://localhost:$PORT"
) &

echo "==> Starting the browser on the server"
echo
ssh -t "$HOST" "bash $REMOTE $ACCOUNT_ID"
