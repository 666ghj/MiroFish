#!/bin/zsh

set -euo pipefail

SOURCE_DIR="${1:-/Users/adrianlat/Library/Mobile Documents/com~apple~CloudDocs/BreathWork/Transcribes}"
TARGET_DIR="${2:-/Users/Shared/OpenClaw/transcribes}"

mkdir -p "$TARGET_DIR"
rsync -a --delete --human-readable "$SOURCE_DIR/" "$TARGET_DIR/"
chgrp -R openclawshare "$TARGET_DIR"
chmod -R g+rwX "$TARGET_DIR"
find "$TARGET_DIR" -type d -exec chmod g+s {} +

echo "Transcribes synced to $TARGET_DIR"
