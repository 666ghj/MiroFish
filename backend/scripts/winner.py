#!/usr/bin/env python3
"""Gate 19 winner function for acceptance rubric v15.

Reads variant artifacts (A reference, B tiered, C pure screen, plus optional
bias-control artifacts) and applies the committed, deterministic winner function:

  Step 1 — calibration gate: B and C must pass gate-13 control + gate-20 calibration.
  Step 2 — tiered-quality gate: B is eliminated if it fails gate 18 or gate 21.
  Step 3 — selection: B wins if it survives; otherwise C wins. A never ships.

A is a reference baseline and is never the canonical artifact. Prints the winner
and a per-variant measure table (the gate-26 executable artifact).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

VARIANTS = ("A", "B", "C")


def load(path: str | None) -> dict | None:
    if not path or not Path(path).exists():
        return None
    return json.loads(Path(path).read_text())


def pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 3:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return 0.0
    return num / (dx * dy)


def fisher_rtoz_test(r_b: float, r_a: float, n: int) -> dict:
    """Fisher r-to-z on the difference; significant if 95% CI of (r_b - r_a) excludes 0."""
    if n < 4 or abs(r_b) >= 1 or abs(r_a) >= 1:
        return {"significant": False, "ci95": [0.0, 0.0], "reason": "insufficient n or degenerate r"}
    zb = 0.5 * math.log((1 + r_b) / (1 - r_b))
    za = 0.5 * math.log((1 + r_a) / (1 - r_a))
    se = math.sqrt(2 / (n - 3))  # approx for two independent correlations
    diff = zb - za
    lo, hi = diff - 1.96 * se, diff + 1.96 * se
    return {"z_b": round(zb, 4), "z_a": round(za, 4), "diff_z": round(diff, 4),
            "ci95": [round(lo, 4), round(hi, 4)], "n": n,
            "significant": (lo > 0) or (hi < 0)}


def calibration(variant_art: dict | None) -> dict:
    """Gate 20 + gate 13 control pass flag. Returns pass(bool) and reasons."""
    if not variant_art:
        return {"pass": False, "reason": "artifact missing"}
    # gate 20: agents with confidence > 0.8 must have |score-5| above variant median
    ops = []
    for r in ("r1", "r2"):
        ops.extend(variant_art.get("rounds", {}).get(r, {}).values())
    if not ops:
        ops = variant_art.get("rounds", {}).get("r1", {}).values()
    absd = [abs(float(o["score"]) - 5.0) for o in ops if isinstance(o, dict) and "score" in o]
    if not absd:
        return {"pass": False, "reason": "no opinions"}
    median_absd = sorted(absd)[len(absd) // 2]
    hi_conf = [abs(float(o["score"]) - 5.0) for o in ops
               if isinstance(o, dict) and float(o.get("confidence", 0)) > 0.8]
    violators = sum(1 for d in hi_conf if d < median_absd)
    cal_pass = (violators == 0) or (len(hi_conf) == 0)
    return {"pass": cal_pass, "median_absd": round(median_absd, 4),
            "hi_conf_n": len(hi_conf), "violators": violators,
            "reason": "ok" if cal_pass else f"{violators} high-conf agents not more decisive than median"}


def gate13(control_art: dict | None) -> dict:
    if not control_art:
        return {"pass": False, "reason": "control artifact missing (needs live/bias-control run)"}
    sym = control_art["metrics"]["symmetry"]
    return {"pass": bool(sym["pass"]), "diff": sym["diff"], "ci95": sym["ci95"],
            "n_active": sym["n_active"]}


def deepdive_flip_significance(b: dict, a: dict, dd_tickers: set) -> dict:
    """Two-proportion z-test on per-agent flip rate among deep-dive-company agents."""
    def flips_on(art, tickers):
        r1, r2 = art["rounds"]["r1"], art.get("rounds", {}).get("r2", {})
        agents = art["agents"]
        n = f = 0
        for ag in agents:
            if ag["ticker"] not in tickers:
                continue
            aid = str(ag["agent_id"])
            if aid in r1 and aid in r2:
                n += 1
                if r1[aid].get("view") != r2[aid].get("view"):
                    f += 1
        return n, f
    bn, bf = flips_on(b, dd_tickers)
    an, af = flips_on(a, dd_tickers)
    if bn == 0 or an == 0:
        return {"b_rate": 0, "a_rate": 0, "significant": False, "reason": "no deep-dive agents on A/B"}
    br = bf / bn
    ar = af / an
    # two-proportion z-test
    pooled = (bf + af) / (bn + an) if (bn + an) else 0
    se = math.sqrt(pooled * (1 - pooled) * (1 / bn + 1 / an)) if pooled not in (0, 1) else 0
    z = (br - ar) / se if se > 0 else 0
    # one-sided: B higher than A -> significant if z > 1.645 (95% one-sided)
    significant = (br > ar) and (z > 1.645)
    return {"b_flips": bf, "b_n": bn, "b_rate": round(br, 4),
            "a_flips": af, "a_n": an, "a_rate": round(ar, 4),
            "z": round(z, 4), "significant": significant}


def gate21(b: dict, a: dict, dd_tickers: set) -> dict:
    """Discrimination r = pearson(consensus confidence, consensus decisive_score_distance)."""
    def r_for(art):
        cc = art["company_consensus"]
        xs, ys = [], []
        for t in dd_tickers:
            c = cc.get(t)
            if not c or c.get("n", 0) == 0:
                continue
            xs.append(float(c["confidence"]))
            ys.append(float(c.get("decisive_score_distance", abs(c["score"] - 5))))
        return pearson(xs, ys), len(xs)
    r_b, nb = r_for(b)
    r_a, na = r_for(a)
    sig = fisher_rtoz_test(r_b, r_a, min(nb, na))
    return {"r_b": round(r_b, 4), "r_a": round(r_a, 4), "n": min(nb, na),
            "significant": sig["significant"], "test": sig,
            "pass": (r_b > r_a) and sig["significant"]}


def measure(art: dict) -> dict:
    if not art:
        return {}
    m = art["metrics"]
    return {
        "covered": art["meta"]["covered_companies"],
        "tokens": m["total_tokens"],
        "cost_per_covered": m["cost_per_covered_company"],
        "reinforcement": m["reinforcement_rate"],
        "bal_gap_before": m["balance_gap_before"],
        "flip_rate": m["deepdive_per_agent_flip_rate"],
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Gate 19 winner function (rubric v15)")
    p.add_argument("--A", required=True)
    p.add_argument("--B", required=True)
    p.add_argument("--C", required=True)
    p.add_argument("--control-A", default=None)
    p.add_argument("--control-BC", default=None)
    p.add_argument("--output", default=None)
    args = p.parse_args(argv)

    A, B, C = load(args.A), load(args.B), load(args.C)
    cA, cBC = load(args.control_A), load(args.control_BC)
    if not (A and B and C):
        print("ERROR: missing A/B/C artifact", file=sys.stderr)
        return 2

    dd = set(B["meta"]["tier_meta"]["deepdive_tickers"])

    g13_A = gate13(cA)
    g13_BC = gate13(cBC)
    cal = {v: calibration({"A": A, "B": B, "C": C}[v]) for v in VARIANTS}
    g16 = deepdive_flip_significance(B, A, dd)
    g21 = gate21(B, A, dd)

    # gate 18: B vs A
    reinf_pass = B["metrics"]["reinforcement_rate"] < A["metrics"]["reinforcement_rate"]
    balance_pass = B["metrics"]["balance_gap_before"] < A["metrics"]["balance_gap_before"]
    g18 = {"reinforcement": reinf_pass, "balance": balance_pass,
           "flip": g16["significant"], "pass": reinf_pass and balance_pass and g16["significant"]}

    # ---- winner function ----
    # step 1: calibration gate
    step1 = {
        "B": cal["B"]["pass"] and g13_BC["pass"],
        "C": cal["C"]["pass"] and g13_BC["pass"],
    }
    # step 2: tiered-quality gate (B only)
    step2_B_pass = g18["pass"] and g21["pass"]
    survivors = []
    if step1["B"] and step2_B_pass:
        survivors.append("B")
    if step1["C"]:
        survivors.append("C")
    # step 3: prefer B; else C
    if "B" in survivors:
        winner = "B"
    elif "C" in survivors:
        winner = "C"
    else:
        winner = None

    table = {v: measure(art) for v, art in (("A", A), ("B", B), ("C", C))}
    table["A"]["note"] = "reference baseline, not shippable"
    if winner is None:
        table["verdict"] = "NO SHIP — neither design survived the winner function"

    report = {
        "winner": winner,
        "A_is": "reference baseline, not shippable",
        "gate13_A": g13_A, "gate13_BC": g13_BC,
        "gate20_calibration": cal,
        "gate16_deepdive_flip_vs_A": g16,
        "gate18_B_beats_A": g18,
        "gate21_discrimination": g21,
        "step1_calibration": step1,
        "step2_tiered_quality_B_pass": step2_B_pass,
        "survivors": survivors,
        "measure_table": table,
    }
    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2))

    print("=== GATE 19 WINNER FUNCTION (rubric v15) ===")
    print(f"WINNER: {winner if winner else 'NONE'}")
    print(f"A = reference baseline, never shippable")
    print(f"\n-- Gate 13 (prompt-bias symmetry, control run) --")
    print(f"  A control : pass={g13_A['pass']}  diff={g13_A.get('diff')}  ci95={g13_A.get('ci95')}")
    print(f"  BC control: pass={g13_BC['pass']}  diff={g13_BC.get('diff')}  ci95={g13_BC.get('ci95')}")
    print(f"\n-- Gate 20 (conviction calibration) --")
    for v in VARIANTS:
        print(f"  {v}: pass={cal[v]['pass']}  ({cal[v]['reason']})")
    print(f"\n-- Gate 16 (deep-dive flip rate vs A, significance) --")
    print(f"  B flip={g16['b_rate']} (n={g16['b_n']})  A flip={g16['a_rate']} (n={g16['a_n']})  z={g16['z']}  significant={g16['significant']}")
    print(f"\n-- Gate 18 (B beats A: all three) --")
    print(f"  reinforcement<{A['metrics']['reinforcement_rate']}? {reinf_pass}  balance_gap<{A['metrics']['balance_gap_before']}? {balance_pass}  flip significant? {g16['significant']}  -> G18 pass={g18['pass']}")
    print(f"\n-- Gate 21 (discrimination r, cross-tier, no averaging confound) --")
    print(f"  r_B={g21['r_b']}  r_A={g21['r_a']}  n={g21['n']}  B>A and significant? {g21['pass']}")
    print(f"\n-- Winner-function steps --")
    print(f"  step1 survivors (calibration): B={step1['B']} C={step1['C']}")
    print(f"  step2 B tiered-quality pass: {step2_B_pass}")
    print(f"  survivors: {survivors}")
    print(f"\n-- Measure table --")
    print(f"  {'variant':7} {'covered':>8} {'tokens':>10} {'cost/cov':>9} {'reinf':>7} {'gap_pre':>8} {'flip':>7}")
    for v in ("A", "B", "C"):
        t = table.get(v, {})
        if t:
            print(f"  {v:7} {t.get('covered',0):>8} {t.get('tokens',0):>10} {t.get('cost_per_covered',0):>9} {t.get('reinforcement',0):>7} {t.get('bal_gap_before',0):>8} {t.get('flip_rate',0):>7}")
    print(f"\nCANONICAL ARTIFACT: {winner if winner else 'NONE (no ship)'}")
    return 0 if winner else 1


if __name__ == "__main__":
    sys.exit(main())
