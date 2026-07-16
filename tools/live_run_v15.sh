#!/usr/bin/env bash
# Full LIVE GLM-5.2 rubric-v15 swarm over the SSH tunnel (localhost:30000).
# Runs A (reference), B (tiered), control-A, control-BC, C (pure screen)
# sequentially on the same clean 5,143-company eligible universe.
set -uo pipefail
cd "$(dirname "$0")/../backend" || exit 1

export LLM_BASE_URL="http://127.0.0.1:30000/v1"
export LLM_API_KEY="dummy"
export LLM_MODEL_NAME="glm-5.2"
export LLM_REASONING_EFFORT="none"

ELIG="/Users/renanflorez/Documents/mirofish-swarm/artifacts/company-dossiers-eligible.json"
OUT="artifacts/v15"
LOG="$OUT/live_run.log"
SEED=20260716
CONC=${CONC:-128}
N=200
mkdir -p "$OUT"

run() {  # variant promptset outfile extra-args...
  local variant="$1" ps="$2" out="$3"; shift 3
  echo "===[$(date -u +%FT%TZ)] variant=$variant prompt-set=$ps -> $out===" | tee -a "$LOG"
  uv run python scripts/run_tiered_swarm.py \
    --variant "$variant" --prompt-set "$ps" \
    --eligible "$ELIG" --seed "$SEED" --concurrency "$CONC" \
    --n-deepdive "$N" --reasoning-effort none \
    --output "$OUT/$out" "$@" >>"$LOG" 2>&1
  echo "    exit=$? -> $OUT/$out" | tee -a "$LOG"
}

echo "LIVE v15 run start $(date -u +%FT%TZ) conc=$CONC eligible=$ELIG" | tee "$LOG"
run A    A  live_A.json
run B    BC live_B.json
run control A  control_A_live.json
run control BC control_BC_live.json
run C    BC live_C.json
echo "===[$(date -u +%FT%TZ)] LIVE v15 run COMPLETE" | tee -a "$LOG"
echo "now run: uv run python scripts/winner.py --A artifacts/v15/live_A.json --B artifacts/v15/live_B.json --C artifacts/v15/live_C.json --control-A artifacts/v15/control_A_live.json --control-BC artifacts/v15/control_BC_live.json --output artifacts/v15/winner_report_live.json" | tee -a "$LOG"
