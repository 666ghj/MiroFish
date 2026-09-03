#!/bin/zsh

set -euo pipefail

PLIST_SOURCE="/Users/Shared/OpenClaw/mirofish-runtime/ops/launchd/com.openclaw.mirofish.plist"
PLIST_TARGET="/Library/LaunchDaemons/com.openclaw.mirofish.plist"

if [[ ! -f "$PLIST_SOURCE" ]]; then
  echo "Missing source plist: $PLIST_SOURCE"
  exit 1
fi

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run this script with sudo."
  exit 1
fi

cp "$PLIST_SOURCE" "$PLIST_TARGET"
chown root:wheel "$PLIST_TARGET"
chmod 644 "$PLIST_TARGET"
plutil -lint "$PLIST_TARGET"

launchctl bootout system/com.openclaw.mirofish 2>/dev/null || true
launchctl bootstrap system "$PLIST_TARGET"
launchctl kickstart -k system/com.openclaw.mirofish

echo "Installed LaunchDaemon at $PLIST_TARGET"
