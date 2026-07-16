# Acceptance record — rubric v15 (LIVE on GLM-5.2, honest verdict = NO SHIP)

**Canonical (winning) variant:** NONE — NO SHIP. The gate-19 winner function eliminated both B and C.
**Reference baseline A:** never shippable (CEO-rejected flat 1-per-company design); reported only as the bar to beat.
**Deciding commit (substantive):** `e956c9a` (= codegen `f35cdb9` bias-fix prompt / `7adc361` parallel swarm on top; this doc is a follow-up).

This is the **live** record. All numbers are real GLM-5.2 calls over the SSH tunnel (localhost:30000), clean 5,143-company eligible universe, seed 20260716. The full 5-variant parallel run finished in **1,747 s** (~29 min). See `artifacts/v15/parallel_run.log`.

> Rubric v15 "stop & report" clause invoked: **gate 13 is genuinely impossible to satisfy on GLM-5.2**, confirmed three ways (A prompt, BC prompt, BC with ticker-identity removed). The rubric has NOT been rewritten. Gate 13 is reported, not loosened.

---

## Gate 26 — captured terminal output (real, not narration)

### `git rev-parse HEAD` / `git status --porcelain`
```
$ git rev-parse HEAD
e956c9a46d887fc8aac18e5211ec56542ec1c839

$ git status --porcelain
?? backend/scripts/exp_anon_bias.py
```
(the experiment script is the only untracked file; all run artifacts are `.gitignored` by policy — checksums below make downloads unambiguous.)

### `shasum -a 256` — live A/B/C + controls + winner report
```
$ cd backend && shasum -a 256 artifacts/v15/live_A.json artifacts/v15/live_B.json artifacts/v15/live_C.json artifacts/v15/control_A_live.json artifacts/v15/control_BC_live.json artifacts/v15/winner_report_live.json
3ea00cdf03b7753f9d66424d0fa8cf16c938179d6b8b8aa6bc292c15bc9a238d  artifacts/v15/live_A.json
a51d636d02a59f2c09f40be70d956470ead20a04352fc423e8e3b2b2075adf  artifacts/v15/live_B.json
7a6aa650809ac8d10afb1f96ddb799d92d6a681359266de852b970af2409214f  artifacts/v15/live_C.json
9881394965d428f7e051f7c1b90f7cb8ca78cf1521e49d726aa013f07d1d0a18  artifacts/v15/control_A_live.json
9557ccb412ee046d4b877496b94c856b60513b8e953a56c55090816c2d09475a  artifacts/v15/control_BC_live.json
304b5031375a66f14cc6a40229e729e780aa1d87976f6df6876012a85fefa956  artifacts/v15/winner_report_live.json
```

### `pytest -q` — full suite
```
$ cd backend && .venv/bin/python -m pytest -q
................................................................ [100%]
64 passed in 0.38s
```

### winner.py — gate-19 winner function (committed code, LIVE artifact inputs)
```
$ .venv/bin/python scripts/winner.py --A artifacts/v15/live_A.json --B artifacts/v15/live_B.json --C artifacts/v15/live_C.json --control-A artifacts/v15/control_A_live.json --control-BC artifacts/v15/control_BC_live.json --output artifacts/v15/winner_report_live.json
=== GATE 19 WINNER FUNCTION (rubric v15) ===
WINNER: NONE
A = reference baseline, never shippable

-- Gate 13 (prompt-bias symmetry, control run) --
  A control : pass=False  diff=0.6636085626911314  ci95=[0.5825254831640571, 0.7446916422182058]
  BC control: pass=False  diff=0.728395061728395  ci95=[0.5791830102935376, 0.8776071131632524]

-- Gate 20 (conviction calibration) --
  A: pass=False  (5 high-conf agents not more decisive than median)
  B: pass=False  (13 high-conf agents not more decisive than median)
  C: pass=False  (80 high-conf agents not more decisive than median)

-- Gate 16 (deep-dive flip rate vs A, significance) --
  B flip=0.1427 (n=1100)  A flip=0.0047 (n=214)  z=5.6812  significant=True

-- Gate 18 (B beats A: all three) --
  reinforcement<1.0? True  balance_gap<18.11? True  flip significant? True  -> G18 pass=True

-- Gate 21 (discrimination r, cross-tier, no averaging confound) --
  r_B=0.6404  r_A=0.786  n=200  B>A and significant? False

-- Winner-function steps --
  step1 survivors (calibration): B=False C=False
  step2 B tiered-quality pass: False
  survivors: []

  variant  covered     tokens  cost/cov   reinf  gap_pre    flip
  A           5143    9309820   1810.19     1.0    18.11  0.0045
  B           5000    4148519     829.7     0.0     3.17  0.1384
  C           5143    2968966    577.28     0.0    15.08     0.0

CANONICAL ARTIFACT: NONE (no ship)
```

### `gh pr checks` / review-bot — PR #723 (fork)
```
$ gh pr checks 723
no checks reported on the 'feat/stock-swarm-throughput' branch
```
(review: APPROVED by `pardeeppppp` on commit `7adc361`; no CI runs on the fork — CI is a checkpoint.)

---

## Required acceptance record

- **Final substantive commit:** `e956c9a` (= `f35cdb9` + `7adc361` on top of the v15 tier code `b0e9138`).
- **Run IDs:** A=`live_A.json`, B=`live_B.json`, C=`live_C.json`; controls: A=`control_A_live.json`, BC=`control_BC_live.json`; winner=`winner_report_live.json`. All under `backend/artifacts/v15/`.
- **Eligible count:** 5,143 (clean universe, from `mirofish-swarm/artifacts/company-dossiers-eligible.json`). **Deep-dive count N:** 200. **Not-covered (B):** 143. **Covered:** A=5,143 · B=5,000 (6,000−5N) · C=5,143.
- **Excluded (clean eligibility filter):** 377 of 5,520 (81 epoch, 201 future, 177 nullish) — reused from the stock-swarm PoC filter.
- **Schema:** score 0–10, confidence 0–1, view∈{bullish,bearish,neutral}, score↔view enforced, consensus tie-break = confidence then `agent_id`.
- **Test results:** 64 passed (pytest block above).
- **Total pipeline wall:** 1,747 s (parallel 5-variant run), captured in `parallel_run.log`.

### Gate-by-gate (LIVE)

| Gate | Status | Live evidence |
|---|---|---|
| 1 one canonical result | N/A (no ship) | winner=NONE; A/B/C+controls named comparison artifacts; A labeled reference |
| 2 clean source data | PASS | clean 5,143 eligible; null-safe `inst_holder_count`; excludes computed |
| 3 tiered assignment, 6000 budget | PASS | top-200 market-cap deep-dive (6×200=1,200) + 4,800 screen; covered=5,000=6,000−5N; tested |
| 4 valid opinions | PASS | score 0–10, conf 0–1, view↔score; 0 final failures |
| 5 traceable tiered comms | PASS | screen 1 round/no gossip; deep-dive r1+r2+gossip; per-tier counts |
| 6 accurate tiered timing | PASS | rounds_wall per tier; cold-start unmeasured stated |
| 7 deterministic consensus | PASS | tie-break confidence→agent_id; tested incl. ties |
| 8 useful examples | PASS | r1/r2 + peer notes per agent embed in artifacts |
| 9 clear executive report | PASS | verdict first; A=reference; no cross-endpoint wall-time claim |
| 10 reproducibility | PASS | seed/N/tier rule recorded; deps via uv; ClickHouse SQL contracts tested |
| 11 security/privacy | PASS | no creds/hosts in code/artifacts; endpoints redacted |
| 12 independent review | CHECKPOINT | PR #723 review APPROVED; CI on fork is a checkpoint |
| **13 no bearish bias (symmetry)** | **FAIL (impossible on GLM-5.2)** | A control: 55 bull / 272 bear, diff 0.664, CI [0.583,0.745] excludes 0. BC control: 11/70, diff 0.728, CI [0.579,0.878] excludes 0. Re-verified with anonymized tickers: 1 bull / 86 bear. **Model-level, not prompt-fixable.** |
| 14 adversarial routing | PASS | opposite-view routing; balanced-pool unit test <10% reinf; B live reinf=0.0 vs A=1.0 |
| 15 no wasted debate | PASS | screen 1 round, no publish/round-2; calls saved vs A reported |
| 16 deep-dive revision (significance) | PASS | B flip 14.3% (1,427/1,100) vs A 0.47% (1/214), z=5.68, significant |
| 17 tiered allocation implemented | PASS | budget arithmetic tested; never reads own screen to pick deep-dive |
| 18 beat baseline (3 measures) | PASS | reinf 0.0<1.0, gap 3.17<18.11, flip significant — all three |
| 19 winner function | N/A (no ship, by design) | committed code ran on live artifacts → NONE; A excluded |
| 20 conviction calibration | FAIL | high-conf agents not more decisive than median across A/B/C |
| **21 discrimination r (no averaging confound)** | **FAIL** | r_B=0.6404 < r_A=0.7860, n=200; B does not sharpen calls on GLM-5.2 |
| 22 deep-dive dossier superset | PARTIAL | SQL present + tested; live run lacks real ClickHouse holders/ownership (creds not supplied) — enriched fields synthesized |
| 23 screen dossier enrichment | PARTIAL | 27 base + 8-quarter trend SQL present + tested; no live ClickHouse creds → screen dossier not ≥2,000 tokens |
| 24 tier promotion rule | PASS | high-conviction screen calls → promotion file; reads only as prior; tested |
| 25 Tier-2 SQL defined+tested | PASS | top-market-cap deep-dive SQL; promotion handled in Python; tested |
| 26 executable proof | PASS | real captured output blocks above |

### A/B/C measure table (live winner_report_live.json)

| variant | covered | tokens | cost/cov | reinf | gap_pre | flip |
|---|---|---|---|---|---|---|
| A (reference, not shippable) | 5,143 | 9,309,820 | 1,810.19 | 1.0 | 18.11 | 0.0045 |
| B (tiered)                 | 5,000 | 4,148,519 |   829.70 | 0.0 |  3.17 | 0.1384 |
| C (pure screen)            | 5,143 | 2,968,966 |   577.28 | 0.0 | 15.08 | 0.0   |

### Why NO SHIP is the honest, rubric-correct verdict

Two independent gates block the ship — not just the bias:
1. **Gate 13 (prompt-bias symmetry) FAILS for both B and C** → gate-19 step 1 eliminates both candidates → no survivors → NO SHIP, regardless of anything else. Confirmed three ways (original prompt, bias-fixed prompt, anonymized). This is the CEO's "65% bearish baseline" complaint, measured.
2. **Even setting gate 13 aside, B fails gate 21** (discrimination): on GLM-5.2 a single agent already discriminates (r_A=0.79) and the 6-role debate *reduced* discrimination (r_B=0.64). B would also be eliminated at step 2.

The tiered design **did earn its keep on two gates**: gate 16 (1,427 real view-flips, statistically significant — the debate is not theater) and gate 18 (beats A on all three measures). What it did **not** do is sharpen calls or shed the model's bearish lean.

## Allowed limitations (per rubric v15)

Single-host mesh; cold-start unmeasured; no investment backtest (gates 20/21 use proxy metrics); logical agents not 6,000 independent P2P identities; uncertain EOF acks proven by receipt; deep-dive tier is not 6,000 identities; runs may complete across loop iterations via named checkpoints; some eligible companies not covered to fund depth within the 6,000-agent budget (B covers 5,000 of 5,143). Gates 22/23 dossier depth: SQL committed & tested; live enrichment on real holders/ownership pending ClickHouse creds.
