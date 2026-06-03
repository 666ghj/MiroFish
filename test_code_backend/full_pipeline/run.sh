#!/usr/bin/env bash
# MiroFish full pipeline runner — calls prepare_input.py then MiroFish API.
#
# Usage:
#   bash run.sh
#   bash run.sh path/to/config.env
#
# Requirements: curl, jq, python3

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
CONFIG_FILE="${1:-$SCRIPT_DIR/config_articles.env}"
BACKEND_URL="http://localhost:5001"

info() { echo "[$(date '+%H:%M:%S')] INFO  $*"; }
err()  { echo "[$(date '+%H:%M:%S')] ERROR $*" >&2; }
die()  { err "$*"; exit 1; }

command -v curl   >/dev/null 2>&1 || die "curl is required"
command -v jq     >/dev/null 2>&1 || die "jq is required (apt install jq)"
command -v python3 >/dev/null 2>&1 || die "python3 is required"

[[ -f "$CONFIG_FILE" ]] || die "Config file not found: $CONFIG_FILE"

# ─── Step 0: Prepare input (Python) ──────────────────────────────────────────
info "=== Step 0: Preparing article input ==="
INPUT_JSON=$(python3 "$SCRIPT_DIR/prepare_input.py" "$CONFIG_FILE") \
    || die "prepare_input.py failed"

# Check for error from prepare_input.py
if echo "$INPUT_JSON" | jq -e '.error' >/dev/null 2>&1; then
    die "Input error: $(echo "$INPUT_JSON" | jq -r '.error')"
fi

COMBINED_FILE=$(echo "$INPUT_JSON" | jq -r '.combined_file')
ARTICLE_COUNT=$(echo "$INPUT_JSON" | jq -r '.article_count')
PROJECT_NAME=$( echo "$INPUT_JSON" | jq -r '.project_name')
SIM_REQ=$(      echo "$INPUT_JSON" | jq -r '.simulation_requirement')

trap 'rm -f "$COMBINED_FILE"' EXIT   # cleanup temp file on exit

info "  articles      : $ARTICLE_COUNT"
info "  project_name  : $PROJECT_NAME"
info "  combined_file : $COMBINED_FILE ($(wc -c < "$COMBINED_FILE" | tr -d ' ') bytes)"

# ─── Start Flask backend (if not already running) ─────────────────────────────
if curl -sf "$BACKEND_URL/health" >/dev/null 2>&1; then
    info "Backend already running at $BACKEND_URL"
else
    info "Starting Flask backend..."
    VENV="$BACKEND_DIR/.venv"
    PYTHON=$( [[ -f "$VENV/bin/python" ]] && echo "$VENV/bin/python" || echo "python3" )

    "$PYTHON" "$BACKEND_DIR/run.py" >/dev/null 2>&1 &

    info "Waiting for backend to be ready..."
    for i in $(seq 1 30); do
        sleep 2
        curl -sf "$BACKEND_URL/health" >/dev/null 2>&1 && { info "Backend ready"; break; }
        [[ $i -eq 30 ]] && die "Backend did not start (check backend/logs/)"
    done
fi

# ─── Helper: assert API response has success=true ─────────────────────────────
ok() { echo "$1" | jq -r '.success // false'; }
assert_ok() { [[ "$(ok "$1")" == "true" ]] || { err "Step '$2' failed:"; echo "$1" | jq . >&2; die "Aborted"; }; }

# ─── Helper: poll GET task until completed/failed ─────────────────────────────
poll_task() {
    local url="$1" label="$2"
    while true; do
        local body; body=$(curl -sf "$url") || { sleep 10; continue; }
        local st msg
        st=$(echo "$body" | jq -r '.data.status   // empty')
        pg=$(echo "$body" | jq -r '.data.progress // 0')
        msg=$(echo "$body"| jq -r '.data.message  // empty')
        info "  [$label] $st ${pg}% — $msg"
        [[ "$st" == "completed" ]] && return 0
        [[ "$st" == "failed"    ]] && { err "$label failed: $msg"; die "Aborted"; }
        sleep 10
    done
}

# ─── Step 1: Generate ontology ────────────────────────────────────────────────
info "=== Step 1/7: Generating ontology ==="
RESP=$(curl -sf "$BACKEND_URL/api/graph/ontology/generate" \
    -F "files=@${COMBINED_FILE};filename=articles.md" \
    -F "simulation_requirement=${SIM_REQ}" \
    -F "project_name=${PROJECT_NAME}")
assert_ok "$RESP" "ontology/generate"

PROJECT_ID=$(echo "$RESP" | jq -r '.data.project_id')
info "  project_id   : $PROJECT_ID"

# ─── Step 2: Build knowledge graph ────────────────────────────────────────────
info "=== Step 2/7: Building Zep knowledge graph ==="
RESP=$(curl -sf "$BACKEND_URL/api/graph/build" \
    -H "Content-Type: application/json" \
    -d "$(jq -n --arg p "$PROJECT_ID" --arg n "$PROJECT_NAME" \
        '{project_id: $p, graph_name: $n}')")
assert_ok "$RESP" "graph/build"

TASK_ID=$(echo "$RESP" | jq -r '.data.task_id')
info "  task_id : $TASK_ID"
poll_task "$BACKEND_URL/api/graph/task/$TASK_ID" "graph/build"

GRAPH_ID=$(curl -sf "$BACKEND_URL/api/graph/task/$TASK_ID" | jq -r '.data.result.graph_id')
info "  graph_id : $GRAPH_ID"

# ─── Step 3: Create simulation ────────────────────────────────────────────────
info "=== Step 3/7: Creating simulation ==="
RESP=$(curl -sf "$BACKEND_URL/api/simulation/create" \
    -H "Content-Type: application/json" \
    -d "$(jq -n --arg p "$PROJECT_ID" \
        '{project_id: $p, enable_twitter: true, enable_reddit: true}')")
assert_ok "$RESP" "simulation/create"

SIM_ID=$(echo "$RESP" | jq -r '.data.simulation_id')
info "  simulation_id : $SIM_ID"

# ─── Step 4: Prepare simulation ───────────────────────────────────────────────
info "=== Step 4/7: Preparing simulation (agent profiles + config) ==="
RESP=$(curl -sf "$BACKEND_URL/api/simulation/prepare" \
    -H "Content-Type: application/json" \
    -d "$(jq -n --arg s "$SIM_ID" \
        '{simulation_id: $s, use_llm_for_profiles: true, parallel_profile_count: 5}')")
assert_ok "$RESP" "simulation/prepare"

if [[ "$(echo "$RESP" | jq -r '.data.already_prepared')" == "true" ]]; then
    info "  Already prepared, skipping poll"
else
    TASK_ID=$(echo "$RESP" | jq -r '.data.task_id')
    info "  task_id : $TASK_ID"

    while true; do
        RESP=$(curl -sf "$BACKEND_URL/api/simulation/prepare/status" \
            -H "Content-Type: application/json" \
            -d "$(jq -n --arg t "$TASK_ID" --arg s "$SIM_ID" \
                '{task_id: $t, simulation_id: $s}')")
        st=$(echo "$RESP"  | jq -r '.data.status   // empty')
        pg=$(echo "$RESP"  | jq -r '.data.progress // 0')
        msg=$(echo "$RESP" | jq -r '.data.message  // empty')
        info "  [prepare] $st ${pg}% — $msg"
        [[ "$st" == "completed" || "$st" == "ready" ]] && break
        [[ "$st" == "failed" ]] && { err "Prepare failed: $msg"; die "Aborted"; }
        sleep 15
    done
fi

# ─── Step 5: Start simulation ─────────────────────────────────────────────────
info "=== Step 5/7: Starting simulation (platform: parallel) ==="
RESP=$(curl -sf "$BACKEND_URL/api/simulation/start" \
    -H "Content-Type: application/json" \
    -d "$(jq -n --arg s "$SIM_ID" '{simulation_id: $s, platform: "parallel"}')")
assert_ok "$RESP" "simulation/start"

RUNNER_STATUS=$(echo "$RESP" | jq -r '.data.runner_status')
TOTAL_ROUNDS=$(echo "$RESP"  | jq -r '.data.total_rounds')
info "  runner_status : $RUNNER_STATUS"
info "  total_rounds  : $TOTAL_ROUNDS"

# ─── Step 6: Wait for simulation to finish ──────────────────────────────────
info "=== Step 6/7: Waiting for simulation to finish ==="
info "  (monitoring $SIM_ID — Ctrl-C to detach and let it run in background)"
while true; do
    RESP=$(curl -sf "$BACKEND_URL/api/simulation/$SIM_ID/run-status") || { sleep 15; continue; }
    RS=$(echo "$RESP"  | jq -r '.data.runner_status // empty')
    CR=$(echo "$RESP"  | jq -r '.data.current_round // 0')
    TR=$(echo "$RESP"  | jq -r '.data.total_rounds  // 0')
    info "  runner_status=$RS  round=$CR/$TR"
    [[ "$RS" == "completed" || "$RS" == "stopped" ]] && break
    [[ "$RS" == "failed"    ]] && { err "Simulation failed"; die "Aborted"; }
    sleep 30
done

# ─── Step 7: Generate report ─────────────────────────────────────────────────
info "=== Step 7/7: Generating report ==="
RESP=$(curl -sf "$BACKEND_URL/api/report/generate" \
    -H "Content-Type: application/json" \
    -d "$(jq -n --arg s "$SIM_ID" '{simulation_id: $s}')")
assert_ok "$RESP" "report/generate"

REPORT_ID=$(echo "$RESP" | jq -r '.data.report_id')
info "  report_id : $REPORT_ID"

if [[ "$(echo "$RESP" | jq -r '.data.already_generated')" == "true" ]]; then
    info "  Report already exists, skipping poll"
else
    TASK_ID=$(echo "$RESP" | jq -r '.data.task_id')
    info "  task_id : $TASK_ID"
    while true; do
        RESP=$(curl -sf "$BACKEND_URL/api/report/generate/status" \
            -H "Content-Type: application/json" \
            -d "$(jq -n --arg t "$TASK_ID" '{task_id: $t}')") || { sleep 10; continue; }
        st=$(echo "$RESP"  | jq -r '.data.status   // empty')
        pg=$(echo "$RESP"  | jq -r '.data.progress // 0')
        msg=$(echo "$RESP" | jq -r '.data.message  // empty')
        info "  [report] $st ${pg}% — $msg"
        [[ "$st" == "completed" ]] && break
        [[ "$st" == "failed"    ]] && { err "Report failed: $msg"; die "Aborted"; }
        sleep 15
    done
fi

# ─── Summary ──────────────────────────────────────────────────────────────────
echo ""
info "============================================================"
info "Pipeline complete"
info "  project_id    : $PROJECT_ID"
info "  graph_id      : $GRAPH_ID"
info "  simulation_id : $SIM_ID"
info "  report_id     : $REPORT_ID"
info "============================================================"
info "Download report: curl $BACKEND_URL/api/report/$REPORT_ID/download -o report.md"
