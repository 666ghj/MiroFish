#!/usr/bin/env bash
# Parallel live GLM-5.2 rubric-v15 swarm over the SSH tunnel (localhost:30000).
# Runs A (reference), B (tiered), C (pure screen), control-A, control-BC
# CONCURRENTLY on the same clean 5,143-company eligible universe, with a
# shared total-concurrency budget (~256) split across the 5 runs.
#
# Total wall ~= one big variant instead of 5 sequential big variants (~2.7x faster).
# Each run writes its own log + output; winner.py fuses them at the end.
set -uo pipefail
cd "$(dirname "$0")/../backend" || exit 1

export LLM_BASE_URL="http://127.0.0.1:30000/v1"
export LLM_API_KEY="dummy"
export LLM_MODEL_NAME="glm-5.2"
export LLM_REASONING_EFFORT="none"

ELIG="/Users/renanflorez/Documents/mirofish-swarm/artifacts/company-dossiers-eligible.json"
OUT="artifacts/v15"
SEED=20260716
N=200
mkdir -p "$OUT"

# Per-variant concurrency. A/B/C are the big ~12k-call variants; controls are tiny.
CONC_A=${CONC_A:-64}
CONC_B=${CONC_B:-64}
CONC_C=${CONC_C:-64}
CONC_CTRL=${CONC_CTRL:-32}

start=$(date -u +%s)
echo "PARALLEL v15 run start $(date -u +%FT%TZ) conc A=$CONC_A B=$CONC_B C=$CONC_C ctrl=$CONC_CTRL eligible=$ELIG" | tee "$OUT/parallel_run.log"

# launch(variant, promptset, outfile, conc, logtag)
launch() {
  local variant="$1" ps="$2" out="$3" c="$4" tag="$5"
  local lf="$OUT/${tag}.log"
  : > "$lf"
  uv run python scripts/run_tiered_swarm.py \
    --variant "$variant" --prompt-set "$ps" \
    --eligible "$ELIG" --seed "$SEED" --concurrency "$c" \
    --n-deepdive "$N" --reasoning-effort none \
    --output "$OUT/$out" >"$lf" 2>&1 &
  echo "$! $tag $OUT/$out" >> "$OUT/pids.txt"
  echo "  launched $tag (PID $!) variant=$variant conc=$c -> $OUT/$out"
}

: > "$OUT/pids.txt"
launch A         A  live_A.json      "$CONC_A"    run_A
launch B         BC live_B.json      "$CONC_B"    run_B
launch C         BC live_C.json      "$CONC_C"    run_C
launch control   A  control_A_live.json   "$CONC_CTRL" run_ctrlA
launch control   BC control_BC_live.json "$CONC_CTRL" run_ctrlBC

echo "waiting on all 5 variants..." | tee -a "$OUT/parallel_run.log"
wait
dur=$(( $(date -u +%s) - start ))
echo "===[$(date -u +%FT%TZ)] ALL 5 VARIANTS DONE in ${dur}s ===" | tee -a "$OUT/parallel_run.log"

echo "now run: uv run python scripts/winner.py --A $OUT/live_A.json --B $OUT/live_B.json --C $OUT/live_C.json --control-A $OUT/control_A_live.json --control-BC $OUT/control_BC_live.json --output $OUT/winner_report_live.json" | tee -a "$OUT/parallel_run.log"
