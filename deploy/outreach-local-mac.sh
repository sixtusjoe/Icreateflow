#!/usr/bin/env bash
#
# Run the outreach driver on this Mac, in a real Chrome window.
#
#     bash deploy/outreach-local-mac.sh --login 3   # sign an account in
#     bash deploy/outreach-local-mac.sh             # send one queued job
#     bash deploy/outreach-local-mac.sh --loop       # keep sending
#     bash deploy/outreach-local-mac.sh mock         # rehearse, sends nothing
#
# Why local rather than on the server:
#
#   * The verification puzzle has to be solved by a person, and solving a
#     drag-slider through VNC does not work — the link drops the fast mouse
#     motion and the slider hangs. In a window on your own screen it is an
#     ordinary drag.
#   * `scripts/outreach_login.py` warns that a session captured on one
#     machine and used from another is the most common reason a session gets
#     challenged. Signing in and sending from the same machine removes that
#     mismatch entirely.
#
# What this does NOT do is get messages past TikTok's own refusal. If it
# answers "may be in violation of our Community Guidelines, and has not been
# sent", that is a decision about the message and the account, and no amount
# of moving the browser around changes it.
#
set -euo pipefail

APP_DIR="${ICREATE_LOCAL_DIR:-$HOME/icreateflow-local}"
BACKEND="$APP_DIR/backend"
VENV="$BACKEND/venv"
ENV_FILE="$BACKEND/local-env.sh"

if [ ! -d "$BACKEND" ]; then
    echo "ERROR: no local checkout at $APP_DIR"
    echo "       Set ICREATE_LOCAL_DIR, or create it with:"
    echo "         mkdir -p $APP_DIR && git archive main | tar -x -C $APP_DIR"
    exit 1
fi
if [ ! -x "$VENV/bin/python" ]; then
    echo "ERROR: no virtualenv at $VENV"
    echo "       python3 -m venv $VENV"
    echo "       $VENV/bin/pip install -r $BACKEND/requirements.txt playwright==1.56.0"
    echo "       $VENV/bin/playwright install chromium"
    exit 1
fi
if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: no $ENV_FILE — it needs ICREATE_DB_DSN and ICREATE_OUTREACH_SECRET."
    echo "       Keep it chmod 600 and out of git."
    exit 1
fi

# Read the secrets here, in this shell, and let the child inherit them.
# Never hand them to sudo — it records the environment it is given, which is
# how three of them ended up in the journal and /var/log/auth.log in plain
# text on the server.
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

# The whole point: a browser you can see and click.
export ICREATE_OUTREACH_HEADLESS=0

cd "$BACKEND"

if [ "${1:-}" = "--login" ]; then
    ACCOUNT_ID="${2:-}"
    if [ -z "$ACCOUNT_ID" ]; then
        echo "==> Sending accounts:"
        exec "$VENV/bin/python" scripts/outreach_login.py --list
    fi
    cat <<BANNER

  ─────────────────────────────────────────────────────────────
   A Chrome window will open on TikTok. Sign in by hand.

   Solve any puzzle yourself — it is an ordinary drag here, not
   a laggy one over VNC. The session is encrypted straight into
   the database; nothing is written to disk.
  ─────────────────────────────────────────────────────────────

BANNER
    exec "$VENV/bin/python" scripts/outreach_login.py "$ACCOUNT_ID"
fi

ARGS=()
case "${1:-}" in
    --loop) ;;                      # no --once: keep taking jobs
    mock)   ARGS+=(--once --driver mock) ;;
    "")     ARGS+=(--once) ;;
    *)      echo "ERROR: unknown argument '$1'"; exit 1 ;;
esac

cat <<BANNER

  ─────────────────────────────────────────────────────────────
   A Chrome window will open and run the job on your screen.

   If TikTok shows a verification puzzle, solve it — the driver
   waits ${ICREATE_OUTREACH_CHALLENGE_WAIT_HEADFUL_MS:-300000}ms for you, then
   clicks Message again itself and carries on.

   The window closes when the job finishes. That is the end,
   not an error — the result is on the campaign page.
  ─────────────────────────────────────────────────────────────

BANNER

exec "$VENV/bin/python" scripts/outreach_worker.py "${ARGS[@]}"
