#!/bin/zsh

set -euo pipefail

ROOT_DIR="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
PID_DIR="$ROOT_DIR/runtime/pids"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
CURL_BIN="${CURL_BIN:-$(command -v curl)}"
LSOF_BIN="${LSOF_BIN:-$(command -v lsof)}"

echo "Backend health:"
"$CURL_BIN" -fsS http://127.0.0.1:5001/health || true
echo
echo
echo "Frontend headers:"
"$CURL_BIN" -fsSI http://127.0.0.1:3000/ || true
echo
echo "Ports:"
"$LSOF_BIN" -nP -iTCP:3000 -sTCP:LISTEN || true
"$LSOF_BIN" -nP -iTCP:5001 -sTCP:LISTEN || true
echo
echo "PID files:"
ls -la "$PID_DIR" 2>/dev/null || true
