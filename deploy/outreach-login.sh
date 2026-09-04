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
DISPLAY_NUM="${ICREATE_LOGIN_DISPLAY:-99}"
VNC_PORT="${ICREATE_LOGIN_VNC_PORT:-5900}"
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

# The DB DSN and the session-encryption key live here.
set -a
# shellcheck disable=SC1090
. "$BACKEND/.env"
set +a
export PLAYWRIGHT_BROWSERS_PATH="$BROWSERS_DIR"

run_capture() {
    # --preserve-env rather than putting secrets on the command line, where
    # they would be visible in `ps` to every user on the box.
    sudo -u "$SERVICE_USER" \
        --preserve-env=ICREATE_DB_DSN,ICREATE_OUTREACH_SECRET,ICREATE_JWT_SECRET,PLAYWRIGHT_BROWSERS_PATH,DISPLAY \
        "$VENV/bin/python" "$BACKEND/scripts/outreach_login.py" "$@"
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

if ! command -v x11vnc >/dev/null 2>&1 || ! command -v Xvfb >/dev/null 2>&1; then
    echo "==> Installing Xvfb + x11vnc (first run only, takes a minute)"
    # NEEDRESTART_MODE=a stops the post-install service scanner from
    # scribbling over this script's own output.
    export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a NEEDRESTART_SUSPEND=1
    apt-get update -qq
    apt-get install -y -qq xvfb x11vnc >/dev/null 2>&1
fi

XVFB_PID=""
VNC_PID=""
PASSFILE=""
cleanup() {
    [ -n "$VNC_PID" ] && kill "$VNC_PID" 2>/dev/null || true
    [ -n "$XVFB_PID" ] && kill "$XVFB_PID" 2>/dev/null || true
    [ -n "$PASSFILE" ] && rm -f "$PASSFILE" 2>/dev/null || true
    rm -f "/tmp/.X${DISPLAY_NUM}-lock" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "==> Starting virtual display :$DISPLAY_NUM"
Xvfb ":$DISPLAY_NUM" -screen 0 1280x900x24 >/dev/null 2>&1 &
XVFB_PID=$!
sleep 2

# A one-time password, regenerated every run and deleted on exit.
#
# The real security boundary is -localhost: the VNC port is not reachable
# from the internet, only through an SSH tunnel by someone who already has
# access to this box. The password exists because macOS Screen Sharing
# refuses to connect to a VNC server that offers no authentication — it
# prompts for a password with nothing valid to type.
#
# VNC passwords are truncated to 8 characters by the protocol, so there is
# no point generating a longer one.
VNC_PASS=$(tr -dc 'a-hjkmnp-z2-9' </dev/urandom | head -c 8)
PASSFILE=$(mktemp /tmp/.icf-vncpw-XXXXXX)
chmod 600 "$PASSFILE"
x11vnc -storepasswd "$VNC_PASS" "$PASSFILE" >/dev/null 2>&1

echo "==> Starting VNC on 127.0.0.1:$VNC_PORT (localhost only)"
x11vnc -display ":$DISPLAY_NUM" -rfbport "$VNC_PORT" -localhost \
       -rfbauth "$PASSFILE" -forever -shared -quiet >/dev/null 2>&1 &
VNC_PID=$!
sleep 2

cat <<BANNER

  ─────────────────────────────────────────────────────────────
   Screen Sharing will ask for a password. Use this one:

           $VNC_PASS

   NOT your Mac password. It is generated for this session
   only and is thrown away when this finishes.

   If the window doesn't open by itself, press Cmd-K in Finder
   and enter:   vnc://localhost:$VNC_PORT
  ─────────────────────────────────────────────────────────────

BANNER

cd "$BACKEND"
export DISPLAY=":$DISPLAY_NUM"
run_capture "$ACCOUNT_ID" --timeout "$TIMEOUT"
