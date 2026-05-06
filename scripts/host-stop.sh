#!/bin/zsh

set -euo pipefail

ROOT_DIR="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
PID_DIR="$ROOT_DIR/runtime/pids"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
PKILL_BIN="${PKILL_BIN:-$(command -v pkill)}"

stop_pid_file() {
  local pid_file="$1"
  if [[ -f "$pid_file" ]]; then
    local pid
    pid="$(cat "$pid_file")"
    if kill -0 "$pid" >/dev/null 2>&1; then
      kill "$pid" >/dev/null 2>&1 || true
      for _ in {1..20}; do
        if ! kill -0 "$pid" >/dev/null 2>&1; then
          break
        fi
        sleep 1
      done
      kill -9 "$pid" >/dev/null 2>&1 || true
    fi
    rm -f "$pid_file"
  fi
}

stop_pid_file "$PID_DIR/frontend.pid"
stop_pid_file "$PID_DIR/backend.pid"

"$PKILL_BIN" -f "vite preview --host 0.0.0.0 --port 3000" >/dev/null 2>&1 || true
"$PKILL_BIN" -f "uv run --no-sync python run.py" >/dev/null 2>&1 || true

echo "MiroFish stopped"
