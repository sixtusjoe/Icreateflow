#!/usr/bin/env bash
#
# Watch one outreach send happen, live — one command, from your Mac.
#
#     bash deploy/outreach-watch-mac.sh
#     bash deploy/outreach-watch-mac.sh mock    # rehearse without sending
#
# Opens the tunnel, launches macOS Screen Sharing, and runs a single queued
# job on the server with the browser visible. You watch it load the profile,
# click Message, type, and send.
#
# This is a real send unless you pass `mock`: the job comes off the same
# queue, through the same worker, and its result is recorded normally. The
# background workers are paused for the duration so the job you are watching
# cannot be taken by one of them.
#
set -euo pipefail

REMOTE=/srv/icreateflow/src/deploy/outreach-watch.sh
DRIVER="${1:-}"

# shellcheck source=/dev/null
. "$(dirname "$0")/_vnc-tunnel-mac.sh"

trap tunnel_close EXIT INT TERM
tunnel_open

echo "==> Starting the browser on the server"
echo

if ssh -t "$HOST" "bash $REMOTE $DRIVER"; then
    echo
    echo "==> Done. The result is on the campaign page."
    echo "    \"Reconnecting…\" in Screen Sharing just means the browser closed."
else
    echo
    echo "!!  The run did not finish cleanly. The campaign page and"
    echo "!!  journalctl -u 'icreateflow-outreach-worker@*' have the detail."
    exit 1
fi
