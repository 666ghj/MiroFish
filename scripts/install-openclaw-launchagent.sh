#!/bin/zsh

set -euo pipefail

if [[ "$(id -un)" != "airstride" ]]; then
  echo "Run this script as airstride."
  exit 1
fi

RUNTIME_ROOT="/Users/Shared/OpenClaw/mirofish-runtime"
PLIST_SOURCE="$RUNTIME_ROOT/ops/launchd/airshare.mirofish.plist"
PLIST_TARGET="$HOME/Library/LaunchAgents/airshare.mirofish.plist"

mkdir -p "$HOME/Library/LaunchAgents"
cp "$PLIST_SOURCE" "$PLIST_TARGET"

if launchctl print "gui/$(id -u)" >/dev/null 2>&1; then
  DOMAIN="gui/$(id -u)"
else
  DOMAIN="user/$(id -u)"
fi

launchctl bootout "$DOMAIN/airshare.mirofish" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST_TARGET"
launchctl kickstart -k "$DOMAIN/airshare.mirofish"

echo "Installed LaunchAgent at $PLIST_TARGET in $DOMAIN"
