#!/usr/bin/env bash
#
# One-time server bootstrap for the Outreach browser workers.
#
# Run ON THE SERVER, as root, AFTER a normal `bash deploy/ship.sh` has put the
# outreach code on the box:
#
#     ssh root@95.111.228.80 'bash /srv/icreateflow/src/deploy/outreach-setup.sh'
#     ssh root@95.111.228.80 'bash /srv/icreateflow/src/deploy/outreach-setup.sh 3'   # 3 workers
#
# What it does:
#   1. Installs Playwright into the existing venv.
#   2. Installs Chromium + its system libraries into a shared, app-owned path
#      (NOT root's ~/.cache — the workers run as the `icreateflow` user and
#      could not read it there).
#   3. Installs and enables N `icreateflow-outreach-worker@` units.
#   4. Launches a real headless Chromium as the service user to prove it works.
#
# Safe to re-run: every step is idempotent.
#
# It deliberately does NOT switch the sending driver on. After this finishes,
# the pipeline is still on the `mock` driver until you change it in
# /admin -> Outreach. Rehearse a campaign there first, then switch.
#
set -euo pipefail

APP_DIR=/srv/icreateflow
SRC=$APP_DIR/src
BACKEND=$APP_DIR/backend
ENV_FILE=$BACKEND/.env
VENV=$APP_DIR/venv
SERVICE_USER=icreateflow
BROWSERS_DIR=$APP_DIR/pw-browsers
PLAYWRIGHT_VERSION=1.56.0
WORKERS="${1:-2}"

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: run this as root (it installs system packages and systemd units)."
    exit 1
fi
if [ ! -x "$VENV/bin/python" ]; then
    echo "ERROR: no venv at $VENV — run deploy/server-setup.sh first."
    exit 1
fi
if [ ! -f "$SRC/backend/scripts/outreach_worker.py" ]; then
    echo "ERROR: outreach code is not on this box yet."
    echo "       Run 'bash deploy/ship.sh' from your Mac first, then re-run this."
    exit 1
fi
case "$WORKERS" in
    ''|*[!0-9]*) echo "ERROR: worker count must be a number, got '$WORKERS'"; exit 1 ;;
esac

echo "==> Outreach setup — $WORKERS worker(s)"

# ---------------------------------------------------------------------------
# 0. Session-encryption secret
#
# Sending-account sessions are encrypted at rest with this key. Without it
# the app falls back to ICREATE_JWT_SECRET, which works — but then rotating
# the JWT secret would silently make every stored session unreadable and
# every account would need re-authorizing. Generate a dedicated one so the
# two concerns can be rotated independently.
#
# Generated once and left alone: changing it later has exactly the failure
# mode described above. `deploy.sh` preserves .env across deploys.
# ---------------------------------------------------------------------------
touch "$ENV_FILE"
if grep -q '^ICREATE_OUTREACH_SECRET=' "$ENV_FILE"; then
    echo "==> ICREATE_OUTREACH_SECRET already set — leaving it alone"
    SECRET_ADDED=no
else
    echo "==> Generating ICREATE_OUTREACH_SECRET into $ENV_FILE"
    {
        printf '\n# Encrypts stored outreach sending-account sessions.\n'
        printf '# Written by deploy/outreach-setup.sh. Rotating this makes every\n'
        printf '# stored session unreadable — those accounts must be re-authorized.\n'
        printf 'ICREATE_OUTREACH_SECRET=%s\n' \
            "$("$VENV/bin/python" -c 'import secrets; print(secrets.token_hex(48))')"
    } >> "$ENV_FILE"
    SECRET_ADDED=yes
fi
# The .env holds the DB password and now this key — keep it owner-only.
chown "$SERVICE_USER":"$SERVICE_USER" "$ENV_FILE"
chmod 600 "$ENV_FILE"

# ---------------------------------------------------------------------------
# 1. Playwright in the venv
# ---------------------------------------------------------------------------
echo "==> Installing playwright==$PLAYWRIGHT_VERSION into $VENV"
"$VENV/bin/pip" install --quiet "playwright==$PLAYWRIGHT_VERSION"

# ---------------------------------------------------------------------------
# 2. Chromium + system libraries
#
# PLAYWRIGHT_BROWSERS_PATH puts the browser somewhere both root (installing)
# and the service user (running) can reach. Without it the download lands in
# the invoking user's ~/.cache and the worker cannot start Chromium.
# ---------------------------------------------------------------------------
mkdir -p "$BROWSERS_DIR"

echo "==> Installing Chromium system libraries"
if command -v apt-get >/dev/null 2>&1; then
    # Debian / Ubuntu — Playwright knows the package list for these.
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    PLAYWRIGHT_BROWSERS_PATH="$BROWSERS_DIR" "$VENV/bin/playwright" install-deps chromium
elif command -v dnf >/dev/null 2>&1; then
    # RHEL / AlmaLinux — `playwright install-deps` does not support RPM
    # distros, so install the shared libraries Chromium links against by hand.
    dnf install -y \
        alsa-lib atk at-spi2-atk at-spi2-core cairo cups-libs dbus-libs \
        expat glib2 gtk3 libX11 libXcomposite libXdamage libXext libXfixes \
        libXrandr libxcb libxkbcommon libdrm mesa-libgbm nspr nss pango \
        liberation-fonts >/dev/null
else
    echo "!!  Unknown package manager — skipping system libraries."
    echo "!!  If Chromium fails to launch below, install its dependencies manually."
fi

echo "==> Downloading Chromium into $BROWSERS_DIR"
PLAYWRIGHT_BROWSERS_PATH="$BROWSERS_DIR" "$VENV/bin/playwright" install chromium

# The workers run as $SERVICE_USER and only need to read the browser.
chown -R "$SERVICE_USER":"$SERVICE_USER" "$BROWSERS_DIR"
chmod -R a+rX "$BROWSERS_DIR"

# ---------------------------------------------------------------------------
# 3. systemd units
# ---------------------------------------------------------------------------
echo "==> Installing systemd unit"
cp "$SRC/deploy/systemd/icreateflow-outreach-worker.service" \
   /etc/systemd/system/icreateflow-outreach-worker@.service
systemctl daemon-reload

for i in $(seq 1 "$WORKERS"); do
    echo "    enabling icreateflow-outreach-worker@$i"
    systemctl enable --now "icreateflow-outreach-worker@$i"
done

# Any worker beyond the requested count is left over from a previous run with
# a higher number — stop it so the box matches what was asked for.
for unit in $(systemctl list-units --all --plain --no-legend \
              'icreateflow-outreach-worker@*' 2>/dev/null | awk '{print $1}'); do
    n=$(echo "$unit" | sed 's/.*@\([0-9]*\)\.service/\1/')
    if [ -n "$n" ] && [ "$n" -gt "$WORKERS" ] 2>/dev/null; then
        echo "    disabling surplus $unit"
        systemctl disable --now "$unit" || true
    fi
done

# Both processes read the secret from .env at startup: the API encrypts a
# session when it is uploaded, the workers decrypt it when they send. A
# freshly-generated secret only takes effect once both have restarted, and
# `enable --now` does not restart a unit that was already running.
if [ "$SECRET_ADDED" = yes ]; then
    echo "==> Restarting backend + workers to pick up the new secret"
    systemctl restart icreateflow-backend
    systemctl restart 'icreateflow-outreach-worker@*' || true
fi

# ---------------------------------------------------------------------------
# 4. Prove Chromium actually launches as the service user
# ---------------------------------------------------------------------------
echo "==> Verifying Chromium launches as $SERVICE_USER"
if sudo -u "$SERVICE_USER" \
     PLAYWRIGHT_BROWSERS_PATH="$BROWSERS_DIR" \
     "$VENV/bin/python" - <<'PYEOF'
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
    )
    page = browser.new_context().new_page()
    page.set_content("<h1>ok</h1>")
    assert page.inner_text("h1") == "ok"
    browser.close()
    print("    Chromium launched, rendered a page, and closed cleanly.")
PYEOF
then
    CHROMIUM_OK=yes
else
    CHROMIUM_OK=no
fi

echo
echo "==> Worker status:"
systemctl --no-pager --plain list-units 'icreateflow-outreach-worker@*' || true
echo
if [ "$CHROMIUM_OK" = yes ]; then
    echo "==> Outreach setup complete."
else
    echo "!!  Outreach setup finished BUT Chromium did not launch — the workers"
    echo "!!  will run on the mock driver only until that is fixed."
fi
echo
echo "    Workers are running on the driver set in /admin -> Outreach"
echo "    (still 'mock' until you change it — nothing is sent yet)."
echo
echo "    Logs:   journalctl -u 'icreateflow-outreach-worker@*' -f"
echo "    Stop:   systemctl stop 'icreateflow-outreach-worker@*'"
echo "            or the 'Stop all workers' button in /admin -> Outreach"
