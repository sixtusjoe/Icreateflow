#!/usr/bin/env bash
#
# Publish a new build of the phone app. Every installed copy picks it up the
# next time it opens (mobile/android/.../update/Updater.kt).
#
# Usage (from repo root):
#     bash deploy/publish-app.sh "What changed, in a line"          # the app people install
#     bash deploy/publish-app.sh --dev "What changed, in a line"    # the review build (….dev)
#
# What it does: bumps mobile/android/version.properties, builds and signs
# the APK, and uploads it with its manifest to /srv/icreateflow/app-releases
# on the server — outside backend/, which every deploy wipes. The manifest
# goes up last, so a phone never sees a version whose file isn't there yet.
#
# Needs ~/.icreateflow/android-signing.properties and the keystore it names.
# Every build must be signed with that same key or no phone will take the
# update — back both up somewhere that survives this Mac.
#
set -euo pipefail

HOST="${ICREATE_HOST:-root@147.93.182.253}"
DEST="/srv/icreateflow/app-releases"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$ROOT/mobile/android"

VARIANT=release
PACKAGE=com.icreateflow.companion
if [ "${1:-}" = "--dev" ]; then
    VARIANT=debug
    PACKAGE=com.icreateflow.companion.dev
    shift
fi
NOTES="${1:-}"

[ -f "$HOME/Library/Android/env.sh" ] && source "$HOME/Library/Android/env.sh"
if [ ! -f "$HOME/.icreateflow/android-signing.properties" ]; then
    echo "ERROR: no signing key (~/.icreateflow/android-signing.properties)."
    echo "       A build signed with any other key can't update the installed app."
    exit 1
fi

# ---- 1. Bump the version ---------------------------------------------------
VP="$APP/version.properties"
CODE=$(( $(sed -n 's/^code=//p' "$VP") + 1 ))
NAME=$(sed -n 's/^name=//p' "$VP")
NAME="${NAME%.*}.$(( ${NAME##*.} + 1 ))"
sed -i '' -e "s/^code=.*/code=$CODE/" -e "s/^name=.*/name=$NAME/" "$VP"
echo "==> Version $NAME ($CODE)"

# ---- 2. Build and sign -----------------------------------------------------
TASK="assemble$(tr '[:lower:]' '[:upper:]' <<< "${VARIANT:0:1}")${VARIANT:1}"
(cd "$APP" && ./gradlew --quiet ":app:$TASK")
APK="$APP/app/build/outputs/apk/$VARIANT/app-$VARIANT.apk"
[ -f "$APK" ] || { echo "ERROR: build produced no APK at $APK"; exit 1; }
SHA=$(shasum -a 256 "$APK" | cut -d' ' -f1)
FILE="$PACKAGE-$CODE.apk"

# ---- 3. Upload: the file first, then the manifest that points at it -------
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
# json.dumps-safe notes without needing python: escape \ and ".
ESC_NOTES=$(printf '%s' "$NOTES" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g')
cat > "$TMP/$PACKAGE.json" <<EOF
{"version_code": $CODE, "version_name": "$NAME", "apk": "$FILE", "sha256": "$SHA", "notes": "$ESC_NOTES"}
EOF

echo "==> Uploading $FILE"
ssh "$HOST" "mkdir -p $DEST"
scp -q "$APK" "$HOST:$DEST/$FILE"
scp -q "$TMP/$PACKAGE.json" "$HOST:$DEST/$PACKAGE.json.new"
# Rename is atomic; then drop builds older than the previous one.
ssh "$HOST" "cd $DEST && chmod 644 '$FILE' '$PACKAGE.json.new' && mv '$PACKAGE.json.new' '$PACKAGE.json' \
    && ls -1t $PACKAGE-*.apk | tail -n +3 | xargs -r rm -f"

echo "==> Published $PACKAGE $NAME. Phones update the next time the app opens."
echo "    Commit mobile/android/version.properties so the next build counts up from here."
