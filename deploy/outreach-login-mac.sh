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

REMOTE=/srv/icreateflow/src/deploy/outreach-login.sh

# shellcheck source=/dev/null
. "$(dirname "$0")/_vnc-tunnel-mac.sh"

# --- no account given → just list them -------------------------------------
if [ $# -lt 1 ]; then
    ssh "$HOST" "bash $REMOTE"
    echo
    echo "Then run:  bash $0 <ID>"
    exit 0
fi

ACCOUNT_ID=$1
case "$ACCOUNT_ID" in
    ''|*[!0-9]*)
        echo "ERROR: give an account ID (a number). Run with no arguments to list them."
        exit 1 ;;
esac

trap tunnel_close EXIT INT TERM
tunnel_open

echo "==> Starting the browser on the server"
echo

# Screen Sharing goes to "Reconnecting…" the moment the remote side tears
# down its display, which happens on success AND on timeout. Report which
# one it was, so the window's behaviour is never the thing you have to
# interpret.
if ssh -t "$HOST" "bash $REMOTE $ACCOUNT_ID"; then
    echo
    echo "==> Done. Close the Screen Sharing window if it's still up —"
    echo "    \"Reconnecting…\" just means the remote browser has shut down."
    echo "    Check Outreach → Accounts: the account should show a stored session."
else
    echo
    echo "!!  The sign-in did not complete, so nothing was saved."
    echo "!!  Re-run when you're ready:  bash $0 $ACCOUNT_ID"
    exit 1
fi
