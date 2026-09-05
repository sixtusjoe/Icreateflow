#!/usr/bin/env bash
#
# Sign a sending account into its platform, from the server.
#
#     ssh root@95.111.228.80 'bash /srv/icreateflow/src/deploy/outreach-login.sh'      # list accounts
#     ssh -t root@95.111.228.80 'bash /srv/icreateflow/src/deploy/outreach-login.sh 3' # sign in account 3
#
# Opens a real browser on a virtual display, exposes it over VNC bound to
# localhost, and waits for you to sign in. Once it sees you're logged in it
# encrypts the session straight into the account row — no file, no
# copy-paste, nothing left on disk.
#
# Why on the server and not on your laptop: the session is created on the
# machine, IP and browser build that will actually use it. Capturing it
# elsewhere and importing means the platform watches an established session
# move to a new IP, which is what gets a fresh session challenged.
#
# To reach the browser, open a second terminal ON YOUR MAC and run:
#
#     ssh -N -L 5900:localhost:5900 root@95.111.228.80
#     open vnc://localhost:5900
#
# (macOS Screen Sharing is built in — no software to install.)
#
set -euo pipefail

APP_DIR=/srv/icreateflow
BACKEND=$APP_DIR/backend
VENV=$APP_DIR/venv
SERVICE_USER=icreateflow
BROWSERS_DIR=$APP_DIR/pw-browsers
TIMEOUT="${ICREATE_LOGIN_TIMEOUT:-600}"

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: run this as root."
    exit 1
fi
if [ ! -x "$VENV/bin/python" ]; then
    echo "ERROR: no venv at $VENV — run deploy/server-setup.sh first."
    exit 1
fi
if [ ! -f "$BACKEND/scripts/outreach_login.py" ]; then
    echo "ERROR: outreach code is not on this box — run deploy/ship.sh first."
    exit 1
fi

export PLAYWRIGHT_BROWSERS_PATH="$BROWSERS_DIR"

run_capture() {
    # The DB DSN and the session-encryption key are read by the child, from
    # .env, and never enter this script environment.
    #
    # Handing them to sudo keeps them out of `ps`, which was the point, but
    # sudo logs the environment it was given — so every capture wrote all
    # three secrets to the journal and /var/log/auth.log in plain text.
    # Sourcing .env inside the child leaks nothing but paths.
    sudo -u "$SERVICE_USER" \
        PLAYWRIGHT_BROWSERS_PATH="$BROWSERS_DIR" \
        DISPLAY="${DISPLAY:-}" \
        bash -c '
            set -a
            . "$1/.env"
            set +a
            cd "$1"
            shift
            exec "$@"
        ' _ "$BACKEND" "$VENV/bin/python" "$BACKEND/scripts/outreach_login.py" "$@"
}

# No account given → just list them. No display needed for that.
if [ $# -lt 1 ]; then
    cd "$BACKEND"
    DISPLAY="" run_capture --list
    echo
    echo "Pick an ID and re-run:  bash $0 <account_id>"
    exit 0
fi

ACCOUNT_ID=$1

# --- display + VNC ---------------------------------------------------------
#
# Shared with outreach-watch.sh: see deploy/_vnc-session.sh.

# shellcheck source=/dev/null
. "$(dirname "$0")/_vnc-session.sh"

trap vnc_cleanup EXIT INT TERM

vnc_require_deps
vnc_start "$VENV/bin/python"
vnc_banner \
    "Sign in to the account in the window that appears. This
   captures the session by itself — no copy-paste." \
    "Once signed in, the window drops out and says
   \"Reconnecting…\". That is the finish, not an error. Watch
   THIS terminal for the result."

cd "$BACKEND"
run_capture "$ACCOUNT_ID" --timeout "$TIMEOUT"
