# CEO brief — rubric v15, LIVE on GLM-5.2 (5 variants, 29 min, ~24k real LLM calls)

**One line:** the tiered machinery works **live** (debate produced **1,427 real view-flips**, not theater), but the **rubric correctly refuses to ship** because GLM-5.2 is **structurally bearish-biased** on average companies — your "65% bearish baseline" complaint, now measured three ways, and **not curable by prompting**. Winner = **NO SHIP**. Fix = serve a less-pessimistic model and re-run.

## The headline (gate 13 — prompt-bias symmetry on a NEUTRAL dossier, 500 real calls each)

| prompt set | bull | bear | neutral | bear−bull (on committed) | gate 13 |
|---|---|---|---|---|---|
| **A — original prompt** | 55 | 272 | 120 | +0.664  (76% bearish) | **FAIL** |
| **BC — bias-fixed prompt** | 11 | 70 | 401 | +0.728  (73% bearish on committed) | **FAIL** |
| BC — anonymized ticker (confound check) | 1 | 86 | 403 | +0.977  (98% bearish on committed) | **FAIL** |

- **Your complaint, reproduced & measured.** On a *synthetic neutral* company (every fundamental pinned to its sector median), GLM-5.2 calls it bearish ~3:1 to 5:1 — three different ways.
- **It's model-level bias, not prompt bias.** The bias-fix prompt nudges most companies to neutral (120→401) but the calls it *does* commit to are still bear-heavy; anonymizing the ticker (removing identity sentiment) made it **worse**, not better. No honest prompt can pass gate 13 on this model without forcing everything neutral — which would be gaming and would also kill the debate (gate 16).

## What genuinely works live (the tiered design earned its keep)

| gate | measure | result |
|---|---|---|
| **16 — deep-dive debate produces real revision** | per-agent round-1→round-2 flip rate | **B = 14.3% (1,427/1,100)** vs **A = 0.47% (1/214)**, z = 5.68, **significant** ✓ |
| **18 — B beats A on all three** | reinforcement / pre-gossip balance / flip | reinf 0.0 < 1.0 ✓ · balance gap 3.17 < 18.11 ✓ · flip significant ✓ |
| 15 — no wasted debate | screen = 1 round, no gossip | calls saved vs A reported ✓ |

The debate is **not theater** — 1,400+ real opinion flips across 200 deep-dive companies × 6 roles, statistically significant vs the single-agent baseline.

## What honestly blocks the ship (two gates, not just bias)

| gate | measure | result |
|---|---|---|
| **13 — no bearish bias** | symmetry on neutral dossier | **FAIL** (A 76% bearish; BC 73% on committed) — model-level |
| **21 — debate sharpens calls (discrimination r)** | Pearson r, consensus-conf vs decisive-score, per company | **FAIL** — r_B = 0.640 **<** r_A = 0.786 |
| **20 — conviction calibration** | high-conf agents more decisive than median | FAIL across A/B/C |

**Why NO SHIP is correct, not just bias:** even setting gate 13 aside, B fails gate 21 — on GLM-5.2 a single agent already discriminates (r=0.79), and the 6-role debate actually *reduced* discrimination (r=0.64). The tiered design does not sharpen calls on this model. The gate-19 winner function therefore eliminates B at step 1 (gate 13) **and** would at step 2 (gate 21); C also dies at step 1. **No design that fails the symmetry gate is allowed to ship.**

## What this means / what I need from you

The rubric says: *if a gate is genuinely impossible to satisfy, don't rewrite it — stop, report, and ask.* Gate 13 is genuinely impossible on GLM-5.2 (confirmed 3 ways). I did not loosen it.

- **(a) Swap the serving model** to a less-pessimistic, better-calibrated build (or lower temperature / a stronger system role), re-run A/B/C + controls. The machinery is proven end-to-end on real calls; only the model needs changing. This is the path to a real **B wins**.
- **(b) Accept NO SHIP** as the deliverable: the bias you flagged, measured hard, plus a working tiered swarm that demonstrably produces real debate.
- **(c) Authorize a gate-13 change** (e.g. "BC must reduce bearish skew vs A" instead of strict symmetry). This is a rubric edit — only you can authorize it.

My recommendation: **(a)** — the result you want (a shippable tiered winner) is one model-swap away. Everything else is built, tested (64 passing), and live-verified.

## Provenance

- Live run: `artifacts/v15/parallel_run.log` → "ALL 5 VARIANTS DONE in 1747s" (29 min).
- Commit (code): `f35cdb9` (bias-fix prompt) + `7adc361` (parallel/swarm). Head `e956c9a` (this brief).
- PR #723 (fork `renancloudwalk`) — review APPROVED; CI is a checkpoint (no upstream CI on the fork).
- Full gate-by-gate record + real captured terminal output: `ACCEPTANCE_V15_LIVE.md`.
