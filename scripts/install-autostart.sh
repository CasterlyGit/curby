#!/usr/bin/env bash
# Install curby as a LaunchAgent so it starts on login (claude-meter pattern).
#
# Idempotent: re-running unloads any prior copy first, then loads fresh.
# Logs go to /tmp/curby.log.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$REPO/scripts/com.casterly.curby.plist"
DST="$HOME/Library/LaunchAgents/com.casterly.curby.plist"

if [[ ! -x "$REPO/.venv/bin/python" ]]; then
  echo "error: $REPO/.venv/bin/python not found." >&2
  echo "create the venv first:  python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

cp "$SRC" "$DST"

if launchctl list | grep -q com.casterly.curby; then
  launchctl unload "$DST" >/dev/null 2>&1 || true
fi
launchctl load "$DST"

echo "curby installed as LaunchAgent. logs: /tmp/curby.log"
echo "uninstall:  launchctl unload $DST && rm $DST"
