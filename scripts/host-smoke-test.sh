#!/bin/zsh

set -euo pipefail

ROOT_DIR="${1:-/Users/Shared/OpenClaw/mirofish-runtime}"
TRANSCRIBES_DIR="${2:-/Users/Shared/OpenClaw/transcribes}"
DAEMON_LABEL="${3:-com.openclaw.mirofish}"

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

CURL_BIN="${CURL_BIN:-$(command -v curl)}"
LSOF_BIN="${LSOF_BIN:-$(command -v lsof)}"
NC_BIN="${NC_BIN:-$(command -v nc || true)}"
PLUTIL_BIN="${PLUTIL_BIN:-$(command -v plutil)}"

pass() {
  printf '[PASS] %s\n' "$1"
}

fail() {
  printf '[FAIL] %s\n' "$1" >&2
  exit 1
}

run_with_optional_sudo() {
  "$@" 2>/tmp/mirofish-command.err || sudo -n "$@" 2>/tmp/mirofish-command.err
}

check_port() {
  local port="$1"
  local output_file="/tmp/mirofish-port${port}.txt"

  if run_with_optional_sudo "$LSOF_BIN" -nP "-iTCP:$port" -sTCP:LISTEN >"$output_file"; then
    cat "$output_file"
    pass "Port $port is listening"
    return 0
  fi

  if [[ -n "$NC_BIN" ]] && "$NC_BIN" -z 127.0.0.1 "$port" >/dev/null 2>&1; then
    pass "Port $port accepts TCP connections"
    return 0
  fi

  cat /tmp/mirofish-command.err >&2 || true
  fail "Port $port is not listening"
}

printf 'MiroFish smoke test\n'
printf 'runtime=%s\n' "$ROOT_DIR"
printf 'transcribes=%s\n' "$TRANSCRIBES_DIR"
printf 'daemon=%s\n\n' "$DAEMON_LABEL"

if run_with_optional_sudo launchctl print "system/$DAEMON_LABEL" >/tmp/mirofish-daemon.txt; then
  sed -n '1,40p' /tmp/mirofish-daemon.txt
  if grep -Eq 'state = (running|spawn scheduled)' /tmp/mirofish-daemon.txt; then
    pass "LaunchDaemon is installed and active in launchd"
  else
    fail "LaunchDaemon is not active in launchd"
  fi
else
  cat /tmp/mirofish-command.err >&2 || true
  fail "LaunchDaemon is not installed or not readable"
fi

if "$CURL_BIN" -fsS http://127.0.0.1:5001/health >/tmp/mirofish-backend.json; then
  cat /tmp/mirofish-backend.json
  pass "Backend health endpoint responds"
else
  fail "Backend health endpoint failed"
fi

if "$CURL_BIN" -fsSI http://127.0.0.1:3000/ >/tmp/mirofish-frontend.headers; then
  sed -n '1,8p' /tmp/mirofish-frontend.headers
  pass "Frontend root responds"
else
  fail "Frontend root failed"
fi

if "$CURL_BIN" -fsS http://127.0.0.1:3000/api/graph/project/list >/tmp/mirofish-proxy.json; then
  cat /tmp/mirofish-proxy.json
  pass "Frontend proxy to backend responds"
else
  fail "Frontend proxy failed"
fi

check_port 3000
check_port 5001

if [[ -r "$ROOT_DIR/runtime/logs/backend.log" && -r "$ROOT_DIR/runtime/logs/frontend.log" ]]; then
  tail -n 5 "$ROOT_DIR/runtime/logs/backend.log" || true
  printf '\n'
  tail -n 5 "$ROOT_DIR/runtime/logs/frontend.log" || true
  pass "Logs are present"
else
  fail "Runtime logs are missing"
fi

if [[ -d "$TRANSCRIBES_DIR" ]]; then
  transcribe_count="$(find "$TRANSCRIBES_DIR" -type f 2>/dev/null | wc -l | tr -d ' ')"
  transcribe_size="$(du -sh "$TRANSCRIBES_DIR" 2>/dev/null | awk '{print $1}')"
  printf 'transcribes_files=%s\n' "$transcribe_count"
  printf 'transcribes_size=%s\n' "$transcribe_size"
  if [[ "$transcribe_count" -gt 0 ]]; then
    pass "Transcribes path is populated"
  else
    fail "Transcribes path is empty"
  fi
else
  fail "Transcribes path does not exist"
fi

if [[ -f "/Library/LaunchDaemons/$DAEMON_LABEL.plist" ]]; then
  "$PLUTIL_BIN" -lint "/Library/LaunchDaemons/$DAEMON_LABEL.plist"
  pass "Installed LaunchDaemon plist is valid"
else
  fail "Installed LaunchDaemon plist is missing"
fi

printf '\nMiroFish smoke test completed successfully.\n'
