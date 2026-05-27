#!/usr/bin/env bash
# Auto-deploy: run by a systemd timer every 2 minutes.
# Fetches origin/main — if server is behind, deploys automatically.
# Logs to /var/log/icreateflow-autodeploy.log
set -euo pipefail

SRC=/srv/icreateflow/src
LOGFILE=/var/log/icreateflow-autodeploy.log
MAX_LOG=5242880  # 5 MB — rotate when exceeded

cd "$SRC"

# Rotate log if too large
if [ -f "$LOGFILE" ] && [ "$(stat -c%s "$LOGFILE")" -gt "$MAX_LOG" ]; then
    mv "$LOGFILE" "${LOGFILE}.1"
fi

git fetch origin --quiet

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" = "$REMOTE" ]; then
    exit 0  # already up to date — silent exit
fi

echo "──────────────────────────────────────────" >> "$LOGFILE"
echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC')  New commit detected" >> "$LOGFILE"
echo "  old: $LOCAL" >> "$LOGFILE"
echo "  new: $REMOTE" >> "$LOGFILE"

git reset --hard origin/main >> "$LOGFILE" 2>&1

bash "$SRC/deploy/deploy.sh" >> "$LOGFILE" 2>&1 \
    && echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC')  Deploy SUCCESS" >> "$LOGFILE" \
    || echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC')  Deploy FAILED — check log above" >> "$LOGFILE"
