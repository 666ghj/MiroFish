# CEO brief — rubric v15, live on GLM-5.2 — the bias gate is the headline

**One line:** the tiered-vs-flat machinery works and is running live; the bias gate (gate 13) honestly FAILS on GLM-5.2 because the model is structurally pessimistic on perfectly average companies — exactly the "65% bearish baseline" you flagged, now measured.

## What's real (captured terminal output, GLM-5.2 over the SSH tunnel)

| control run (500 companies, sector-median "neutral" dossier) | bull | bear | neutral | diff (bear−bull) on directional | gate 13 |
|---|---|---|---|---|---|
| A — original prompt | 57 | 270 | 125 | 0.651 (CI ~[0.50, 0.80]) | **FAIL** |
| BC — bias-fixed prompt | 14 | 68 | 402 | 0.659 (CI ~[0.50, 0.82]) | **FAIL** |

- **A original prompt: 270 bearish vs 57 bullish = ~65% bearish.** That is your complaint, reproduced on real GLM-5.2 calls.
- **Bias fix helps but doesn't cure:** it pushes average companies to neutral (125→402 neutral), but the calls it *does* commit to are still ~5:1 bear:bull. The model reads mediocre-but-fine fundamentals as bearish.
- This is **model-level bias, not prompt bias.** Prompts can't calibrate it away without forcing everything neutral — which would be gaming and would also kill the debate (gates 16/21 need real flips).

## What this means for the rubric

- Gate 13 ("bias-fixed prompts must be symmetric on a neutral dossier") **cannot pass on GLM-5.2** with an honest prompt. The rubric says: don't rewrite the gate, report it and ask.
- If gate 13 fails, the gate-19 winner function eliminates both B and C at step 1 → **NO SHIP** by design. That is the rubric working correctly — it refuses to ship a biased design.

## What's running right now (real, in parallel over the tunnel)

All 5 variants live: A reference, B tiered, C pure-screen, + control-A + control-BC. ~25k real GLM calls, ~30 min. This produces the real per-measure A/B/C table (reinforcement, flip rate w/ significance, gate-21 discrimination r, coverage, cost) and real gate-26 captured terminal output — even though the honest winner verdict will be NO SHIP until the bias is resolved.

## Two gates blocked on infra (not on code)

- **Gates 22 & 23** (deep-dive dossiers ≥2,000 tokens: top-10 holders, 4-quarter ownership trend, 8-quarter trend) need ClickHouse creds: `CLICKHOUSE_URL`, `CLICKHOUSE_USER`, `CLICKHOUSE_PASSWORD`. The eligible file has the 27 base fields (~162 tokens/dossier). Runner already reads those env vars.

## I need two decisions

1. **Gate 13 / bias:** GLM-5.2 is honestly bearish-biased on average firms. Options:
   - **(a)** Accept honest NO SHIP now; the bias finding itself is the deliverable (it proves the rubric catches the thing you complained about).
   - **(b)** Switch the serving model to one that isn't structurally pessimistic (e.g. a different GLM build / temp / system-prompt role), re-run gate 13.
   - **(c)** Loosen gate 13 to "bias-fixed prompts must reduce bearish skew vs A" (measurable: A 0.651 → BC residual directional) instead of strict symmetry — but that's a rubric change you'd have to authorize.
2. **ClickHouse creds** for gates 22/23 dossier depth.

My recommendation: **(a)** ship the honest finding now (it's exactly the ground-truth you wanted), and run a cleaner model for a real winner in a follow-up.
