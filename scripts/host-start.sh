#!/bin/zsh

set -euo pipefail

ROOT_DIR="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
LOG_DIR="$ROOT_DIR/runtime/logs"
PID_DIR="$ROOT_DIR/runtime/pids"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
UV_BIN="${UV_BIN:-$(command -v uv)}"
NPM_BIN="${NPM_BIN:-$(command -v npm)}"
NPX_BIN="${NPX_BIN:-$(command -v npx)}"
CURL_BIN="${CURL_BIN:-$(command -v curl)}"
LSOF_BIN="${LSOF_BIN:-$(command -v lsof)}"

mkdir -p "$LOG_DIR" "$PID_DIR" "$ROOT_DIR/backend/uploads/reports" "$ROOT_DIR/backend/uploads/simulations"

monitor_existing_runtime() {
  echo "MiroFish already running"
  while true; do
    if ! "$CURL_BIN" -fsS http://127.0.0.1:5001/health >/dev/null 2>&1; then
      echo "Backend health check failed"
      exit 1
    fi
    if ! "$CURL_BIN" -fsS http://127.0.0.1:3000/ >/dev/null 2>&1; then
      echo "Frontend health check failed"
      exit 1
    fi
    sleep 30
  done
}

if "$LSOF_BIN" -nP -iTCP:3000 -sTCP:LISTEN >/dev/null 2>&1; then
  if "$CURL_BIN" -fsS http://127.0.0.1:3000/ >/dev/null 2>&1 && \
     "$CURL_BIN" -fsS http://127.0.0.1:5001/health >/dev/null 2>&1; then
    monitor_existing_runtime
  fi
  echo "Port 3000 already in use by an unhealthy process"
  exit 1
fi

if "$LSOF_BIN" -nP -iTCP:5001 -sTCP:LISTEN >/dev/null 2>&1; then
  if "$CURL_BIN" -fsS http://127.0.0.1:3000/ >/dev/null 2>&1 && \
     "$CURL_BIN" -fsS http://127.0.0.1:5001/health >/dev/null 2>&1; then
    monitor_existing_runtime
  fi
  echo "Port 5001 already in use by an unhealthy process"
  exit 1
fi

cd "$ROOT_DIR/backend"
env FLASK_DEBUG=False PYTHONUNBUFFERED=1 "$UV_BIN" run --no-sync python run.py < /dev/null > "$LOG_DIR/backend.log" 2>&1 &
BACKEND_PID=$!
echo "$BACKEND_PID" > "$PID_DIR/backend.pid"

for _ in {1..30}; do
  if "$CURL_BIN" -fsS http://127.0.0.1:5001/health >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! "$CURL_BIN" -fsS http://127.0.0.1:5001/health >/dev/null 2>&1; then
  echo "Backend failed to start"
  exit 1
fi

cd "$ROOT_DIR/frontend"
"$NPM_BIN" run build >/dev/null
"$NPX_BIN" vite preview --host 0.0.0.0 --port 3000 --strictPort < /dev/null > "$LOG_DIR/frontend.log" 2>&1 &
FRONTEND_PID=$!
echo "$FRONTEND_PID" > "$PID_DIR/frontend.pid"

for _ in {1..30}; do
  if "$CURL_BIN" -fsS http://127.0.0.1:3000/ >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! "$CURL_BIN" -fsS http://127.0.0.1:3000/ >/dev/null 2>&1; then
  echo "Frontend failed to start"
  exit 1
fi

echo "MiroFish started"
wait "$BACKEND_PID" "$FRONTEND_PID"
