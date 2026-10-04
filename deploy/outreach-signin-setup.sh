#!/usr/bin/env bash
#
# Turn on browser sign-in for outreach accounts on the server.
#
#     ssh root@147.93.182.253 'bash /srv/icreateflow/src/deploy/outreach-signin-setup.sh'
#
# "Sign in here" opens a real browser on the server, on a virtual screen of
# its own (services/outreach/display_pool.py), and streams it into the page
# over a websocket. Five things have to be in place, and before this script
# none of them were set up by anything — the 2026-10 server move lost all of
# them and the dialog just said "switched off":
#
#   1. Xvfb + x11vnc installed.
#   2. The local-browser flag in the backend's .env (local_browser.py). The
#      same flag also turns on lead discovery and watching a send.
#   3. PLAYWRIGHT_BROWSERS_PATH in .env, so the *backend* finds Chromium —
#      only the worker units set it, and the backend's own default path
#      (~/.cache) has no browser in it.
#   4. The VNC password file display_pool.py hands to x11vnc. Without it
#      x11vnc runs without a password, reachable by anything on the box.
#   5. Apache carrying the websocket upgrade on /api/. Without it the stream
#      answers 404 and the page shows nothing.
#   6. A writable settings folder for the visible browser (see below).
#
# Backs up what it edits to /root/config-backups/. Safe to re-run.
#
set -euo pipefail

APP_DIR=/srv/icreateflow
ENV_FILE=$APP_DIR/backend/.env
VHOST=${ICREATE_VHOST:-/etc/apache2/sites-enabled/icreateflow.com.conf}
PWFILE=/etc/icreateflow/vncpw.plain
SERVICE_USER=icreateflow

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: run this as root."
    exit 1
fi

TS=$(date +%Y%m%d-%H%M%S)
mkdir -p /root/config-backups
cp -p "$ENV_FILE" "/root/config-backups/backend.env.$TS"
cp -p "$VHOST" "/root/config-backups/$(basename "$VHOST").$TS"
echo "==> Backed up .env and the Apache site to /root/config-backups/ ($TS)"

# --- 1. display tools ------------------------------------------------------
if ! command -v Xvfb >/dev/null 2>&1 || ! command -v x11vnc >/dev/null 2>&1; then
    echo "==> Installing Xvfb + x11vnc"
    export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a NEEDRESTART_SUSPEND=1
    apt-get update -qq
    apt-get install -y -qq xvfb x11vnc >/dev/null
fi

# --- 2 + 3. backend environment -------------------------------------------
if ! grep -q '^ICREATE_OUTREACH_LOCAL_BROWSER=' "$ENV_FILE"; then
    printf '\n# Browser sign-in, lead discovery and watching a send in the web app\nICREATE_OUTREACH_LOCAL_BROWSER=1\n' >> "$ENV_FILE"
    echo "==> Switched browser sign-in on"
fi
if ! grep -q '^PLAYWRIGHT_BROWSERS_PATH=' "$ENV_FILE"; then
    echo "PLAYWRIGHT_BROWSERS_PATH=$APP_DIR/pw-browsers" >> "$ENV_FILE"
    echo "==> Pointed the backend at the installed Chromium"
fi

# A visible Chromium writes its settings and crash database under $HOME,
# and the backend unit makes home read-only (ProtectHome). It crashes at
# launch with "chrome_crashpad_handler: --database is required" (SIGTRAP).
# The hidden browser the workers use never touches it, which is why sends
# worked while sign-in did not.
CHROME_HOME=$APP_DIR/.chrome-home
mkdir -p "$CHROME_HOME/config" "$CHROME_HOME/cache"
chown -R "$SERVICE_USER:$SERVICE_USER" "$CHROME_HOME"
if ! grep -q '^XDG_CONFIG_HOME=' "$ENV_FILE"; then
    printf 'XDG_CONFIG_HOME=%s/config\nXDG_CACHE_HOME=%s/cache\n' "$CHROME_HOME" "$CHROME_HOME" >> "$ENV_FILE"
    echo "==> Gave the browser a writable settings folder"
fi

# --- 4. viewer password ----------------------------------------------------
mkdir -p "$(dirname "$PWFILE")"
if [ ! -s "$PWFILE" ]; then
    (umask 027; openssl rand -hex 4 > "$PWFILE")
    echo "==> Created the viewer password file"
fi
chown root:"$SERVICE_USER" "$(dirname "$PWFILE")" "$PWFILE"
chmod 750 "$(dirname "$PWFILE")"
chmod 640 "$PWFILE"

# --- 5. Apache websocket ---------------------------------------------------
# Apache 2.4.47+ upgrades a websocket on an ordinary http ProxyPass with
# `upgrade=websocket`, so the stream rides the existing /api/ line and the
# rewrite DEPLOY.md describes is not needed.
if ! grep -q '8100/api/ upgrade=websocket' "$VHOST"; then
    sed -i 's|^\(\s*ProxyPass\s\+/api/ http://127\.0\.0\.1:8100/api/\)\s*$|\1 upgrade=websocket|' "$VHOST"
fi
if ! grep -q '8100/api/ upgrade=websocket' "$VHOST"; then
    echo "!!  Could not find 'ProxyPass /api/ http://127.0.0.1:8100/api/' in $VHOST."
    echo "!!  Add ' upgrade=websocket' to the end of that line by hand."
    exit 1
fi
apache2ctl configtest

# --- restart ---------------------------------------------------------------
echo "==> Restarting the backend and reloading Apache"
systemctl restart icreateflow-backend
systemctl reload apache2

# --- check -----------------------------------------------------------------
# 403 = the request reached the websocket route and was refused for having
# no ticket, which is right. 404 = Apache is not carrying the upgrade.
for _ in $(seq 1 30); do
    curl -s -o /dev/null http://127.0.0.1:8100/api/auth/me && break
    sleep 1
done
# --http1.1: browsers open websockets over HTTP/1.1; over HTTP/2 Apache
# cannot upgrade and answers 404 even when everything is right.
code=$(curl --http1.1 -s -o /dev/null -w '%{http_code}' \
    -H 'Connection: Upgrade' -H 'Upgrade: websocket' \
    -H 'Sec-WebSocket-Version: 13' -H 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==' \
    https://icreateflow.com/api/outreach/accounts/1/session/stream)
if [ "$code" = "403" ]; then
    echo "==> Done. The sign-in stream answers 403 without a ticket, as it should."
else
    echo "!!  The sign-in stream answered $code, expected 403. Check the Apache site."
    exit 1
fi
