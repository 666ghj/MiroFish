"""Tests for the tiered runner + winner function (rubric v15)."""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import run_tiered_swarm as rt  # noqa: E402
import winner as wn  # noqa: E402


# ---- tier assignment (gates 3, 17, 25) ----

def _elig(n):
    return [{"ticker": f"T{i:04d}", "name": f"Co {i}", "sector": "Tech",
             "market_cap": 10_000 - i} for i in range(n)]


def test_assign_tiers_budget_and_no_alpha():
    elig = _elig(20)
    deep, screen = rt.assign_tiers(elig, n_deepdive=3, prior_flags=None)
    assert len(deep) == 3
    # top by market cap (descending) — not alphabetical
    assert [d["ticker"] for d in deep] == ["T0000", "T0001", "T0002"]
    assert all(d["ticker"] not in {s["ticker"] for s in screen} for d in deep)


def test_assign_tires_prior_flags_promoted_first():
    elig = _elig(20)
    deep, screen = rt.assign_tiers(elig, n_deepdive=3, prior_flags=["T0019"])
    assert "T0019" in [d["ticker"] for d in deep]


def test_assign_tiers_deterministic():
    elig = _elig(50)
    d1, s1 = rt.assign_tiers(elig, 5, None)
    d2, s2 = rt.assign_tiers(elig, 5, None)
    assert [d["ticker"] for d in d1] == [d["ticker"] for d in d2]


def test_budget_arithmetic_covered_not_covered():
    n_deepdive = 200
    agents = 6000
    covered_per_b = n_deepdive + (agents - 6 * n_deepdive)  # = 6000 - 5N
    assert covered_per_b == 6000 - 5 * n_deepdive == 5000


# ---- consensus tie-break (gate 7) ----

def test_consensus_tiebreak_confidence_then_agent_id():
    a = {"view": "bullish", "score": 7, "confidence": 0.8, "agent_id": 5}
    b = {"view": "bullish", "score": 7, "confidence": 0.8, "agent_id": 2}
    c = {"view": "bearish", "score": 3, "confidence": 0.9, "agent_id": 9}
    cons = rt.consensus([a, b, c])
    assert cons["view"] == "bullish"  # 2 vs 1
    assert cons["winner_agent_id"] == 2  # higher conf, then smaller id


def test_consensus_view_tiebreak_by_confidence():
    a = {"view": "bullish", "score": 7, "confidence": 0.6, "agent_id": 1}
    b = {"view": "bearish", "score": 3, "confidence": 0.95, "agent_id": 2}
    cons = rt.consensus([a, b])
    # one each -> the view with higher mean confidence wins (bearish)
    assert cons["view"] == "bearish"


def test_consensus_empty_is_neutral():
    cons = rt.consensus([])
    assert cons["view"] == "neutral" and cons["n"] == 0


# ---- promotion (gate 24) ----

def test_promotion_flags_high_conviction_non_neutral():
    cc = {"A": {"view": "bullish", "score": 9, "confidence": 0.9},
          "B": {"view": "neutral", "score": 5, "confidence": 0.5},
          "C": {"view": "bearish", "score": 2, "confidence": 0.7}}  # not sharp enough
    flags = rt.promotion_flags(cc)
    assert "A" in flags and "B" not in flags and "C" not in flags


def test_promotion_rule_does_not_read_own_screen_for_deepdive_set():
    # the assignment-time rule uses market cap + prior flags only — coverage by
    # the assignment function which never sees opinions
    elig = _elig(30)
    deep, _ = rt.assign_tiers(elig, 4, None)
    # determinism + market-cap-driven (not opinion-driven)
    assert deep[0]["market_cap"] == 10000


# ---- balance gap (gate 18) ----

def test_balance_gap():
    ops = [{"view": v, "score": s, "confidence": 0.5} for v, s in
           [("bullish", 8), ("bullish", 8), ("bullish", 8), ("bearish", 2), ("neutral", 5)]]
    assert rt._balance_gap(ops) == 40.0  # |3-1|/5*100


# ---- winner function (gate 19) on fixtures ----

def _op(view, score, conf, aid):
    return {"view": view, "score": score, "confidence": conf, "agent_id": aid}


def _write_artifact(tmp, name, deepdive_tickers=None, r1=None, r2=None,
                    agents=None, company_consensus=None, metrics=None):
    deepdive_tickers = deepdive_tickers or []
    r1 = r1 or {}
    r2 = r2 or {}
    agents = agents or []
    company_consensus = company_consensus or {}
    metrics = metrics or {"total_tokens": 1000, "cost_per_covered_company": 10,
                           "balance_gap_before": 0.0, "reinforcement_rate": 0.0,
                           "deepdive_per_agent_flip_rate": 0.0,
                           "balance_gap_after": 0.0}
    art = {
        "meta": {"covered_companies": len(company_consensus),
                 "agent_count": len(agents),
                 "tier_meta": {"deepdive_tickers": deepdive_tickers}},
        "metrics": metrics,
        "company_consensus": company_consensus,
        "rounds": {"r1": {str(k): v for k, v in r1.items()},
                   "r2": {str(k): v for k, v in r2.items()}},
        "agents": agents,
    }
    p = tmp / name
    p.write_text(json.dumps(art))
    return str(p)


def _control(pass_, diff):
    p = {
        "meta": {"prompt_set": "X", "sample_size": 500},
        "metrics": {"requests": 500, "view_count": 500,
                    "symmetry": {"pass": pass_, "diff": diff, "ci95": [0, 0],
                                 "n_active": 500}},
        "views": [],
    }
    return p


def test_winner_picks_B_when_B_proves_quality(tmp_path, monkeypatch):
    # 5 deep-dive companies with varying decisive score distance.
    scores = [6, 7, 8, 9, 10]
    decisive = [abs(s - 5) for s in scores]  # [1,2,3,4,5]
    dd = [f"CO{i}" for i in range(5)]

    # A: naive single agents — confidence ~constant regardless of decisiveness (low r)
    A_cc = {t: {"view": "bullish", "score": s, "confidence": 0.55,
                "decisive_score_distance": d, "n": 1}
            for t, s, d in zip(dd, scores, decisive)}
    a_agents = [{"agent_id": i, "ticker": dd[i]} for i in range(5)]
    a_r1 = {i: _op("bullish", scores[i], 0.55, i) for i in range(5)}
    a_r2 = a_r1  # no flips for A
    A = _write_artifact(tmp_path, "A.json", dd, a_r1, a_r2, a_agents, A_cc,
                        metrics={"total_tokens": 2000, "cost_per_covered_company": 400,
                                 "balance_gap_before": 50.0, "reinforcement_rate": 0.9,
                                 "deepdive_per_agent_flip_rate": 0.0,
                                 "balance_gap_after": 50.0})
    # B: debated agents — confidence tracks decisiveness (high r, not exactly 1.0);
    # agents flip r1->r2. r2 confidence per company tracks decisive so gate 20 holds.
    b_conf = [0.42, 0.54, 0.66, 0.78, 0.85]  # increases with decisive
    B_cc = {t: {"view": "bullish", "score": s, "confidence": c,
                "decisive_score_distance": d, "n": 1}
            for t, s, c, d in zip(dd, scores, b_conf, decisive)}
    b_agents = [{"agent_id": 100 + i, "ticker": dd[i // 6]} for i in range(30)]  # 6 per company
    b_r1 = {100 + i: _op("bearish", 5 - decisive[i // 6], 0.5, 100 + i) for i in range(30)}
    b_r2 = {100 + i: _op("bullish", scores[i // 6], b_conf[i // 6], 100 + i) for i in range(30)}
    B = _write_artifact(tmp_path, "B.json", dd, b_r1, b_r2, b_agents, B_cc,
                        metrics={"total_tokens": 1500, "cost_per_covered_company": 300,
                                 "balance_gap_before": 2.0, "reinforcement_rate": 0.05,
                                 "deepdive_per_agent_flip_rate": 1.0,
                                 "balance_gap_after": 2.0})
    Ccc = {t: {"view": "bullish", "score": s, "confidence": 0.55,
              "decisive_score_distance": d, "n": 1} for t, s, d in zip(dd, scores, decisive)}
    c_agents = [{"agent_id": i, "ticker": dd[i]} for i in range(5)]
    c_r1 = {i: _op("bullish", scores[i], 0.55, i) for i in range(5)}
    C = _write_artifact(tmp_path, "C.json", dd, c_r1, {}, c_agents, Ccc,
                        metrics={"total_tokens": 800, "cost_per_covered_company": 160,
                                 "balance_gap_before": 0.0, "reinforcement_rate": 0.0,
                                 "deepdive_per_agent_flip_rate": 0.0,
                                 "balance_gap_after": 0.0})
    cA = tmp_path / "cA.json"; cA.write_text(json.dumps(_control(False, 1.0)))
    cBC = tmp_path / "cBC.json"; cBC.write_text(json.dumps(_control(True, 0.0)))
    out = tmp_path / "out.json"
    rc = wn.main(["--A", A, "--B", B, "--C", C, "--control-A", str(cA),
                  "--control-BC", str(cBC), "--output", str(out)])
    report = json.loads(out.read_text())
    assert rc == 0
    assert report["winner"] == "B"
    assert report["gate18_B_beats_A"]["pass"] is True
    assert report["gate21_discrimination"]["r_b"] > report["gate21_discrimination"]["r_a"]
    assert report["gate21_discrimination"]["pass"] is True


def test_winner_falls_back_to_C_when_B_fails_quality(tmp_path):
    dd = ["CO1"]
    A_cc = {"CO1": {"view": "bearish", "score": 2, "confidence": 0.55,
                    "decisive_score_distance": 3.0, "n": 1}}
    a = [{"agent_id": 0, "ticker": "CO1"}]
    r1 = {0: _op("bearish", 2, 0.55, 0)}
    A = _write_artifact(tmp_path, "A.json", dd, r1, r1, a, A_cc,
                        metrics={"total_tokens": 1000, "cost_per_covered_company": 1000,
                                 "balance_gap_before": 10.0, "reinforcement_rate": 0.1,
                                 "deepdive_per_agent_flip_rate": 0.5,
                                 "balance_gap_after": 10.0})
    # B fails gate 21: r_B not > r_A (same correlation)
    B_cc = {"CO1": {"view": "bullish", "score": 8, "confidence": 0.9,
                    "decisive_score_distance": 3.0, "n": 1}}
    B = _write_artifact(tmp_path, "B.json", dd, r1, r1, a, B_cc,
                        metrics={"total_tokens": 1000, "cost_per_covered_company": 500,
                                 "balance_gap_before": 1.0, "reinforcement_rate": 0.0,
                                 "deepdive_per_agent_flip_rate": 0.9,
                                 "balance_gap_after": 1.0})
    C = _write_artifact(tmp_path, "C.json", dd, r1, {}, a, B_cc,
                        metrics={"total_tokens": 500, "cost_per_covered_company": 250,
                                 "balance_gap_before": 0.0, "reinforcement_rate": 0.0,
                                 "deepdive_per_agent_flip_rate": 0.0,
                                 "balance_gap_after": 0.0})
    cA = tmp_path / "cA.json"; cA.write_text(json.dumps(_control(False, 1.0)))
    cBC = tmp_path / "cBC.json"; cBC.write_text(json.dumps(_control(True, 0.0)))
    out = tmp_path / "out.json"
    rc = wn.main(["--A", A, "--B", B, "--C", C, "--control-A", str(cA),
                  "--control-BC", str(cBC), "--output", str(out)])
    report = json.loads(out.read_text())
    assert report["winner"] == "C"
    assert "B" not in report["survivors"]


def test_winner_no_ship_when_both_fail_calibration(tmp_path):
    dd = ["CO1"]
    a = [{"agent_id": 0, "ticker": "CO1"}]
    r1 = {0: _op("bearish", 2, 0.99, 0)}  # high conf but score close-ish -> calibration fail
    cc = {"CO1": {"view": "bearish", "score": 2, "confidence": 0.99,
                  "decisive_score_distance": 3.0, "n": 1}}
    A = _write_artifact(tmp_path, "A.json", dd, r1, r1, a, cc,
                        metrics={"total_tokens": 1, "cost_per_covered_company": 1,
                                 "balance_gap_before": 50, "reinforcement_rate": 0.9,
                                 "deepdive_per_agent_flip_rate": 0,
                                 "balance_gap_after": 50})
    B = _write_artifact(tmp_path, "B.json", dd, r1, r1, a, cc,
                        metrics={"total_tokens": 1, "cost_per_covered_company": 1,
                                 "balance_gap_before": 1, "reinforcement_rate": 0,
                                 "deepdive_per_agent_flip_rate": 0.9,
                                 "balance_gap_after": 1})
    C = _write_artifact(tmp_path, "C.json", dd, r1, {}, a, cc,
                        metrics={"total_tokens": 1, "cost_per_covered_company": 1,
                                 "balance_gap_before": 0, "reinforcement_rate": 0,
                                 "deepdive_per_agent_flip_rate": 0,
                                 "balance_gap_after": 0})
    # both controls fail -> B and C eliminated at step 1
    cA = tmp_path / "cA.json"; cA.write_text(json.dumps(_control(False, 1.0)))
    cBC = tmp_path / "cBC.json"; cBC.write_text(json.dumps(_control(False, 1.0)))
    out = tmp_path / "out.json"
    rc = wn.main(["--A", A, "--B", B, "--C", C, "--control-A", str(cA),
                  "--control-BC", str(cBC), "--output", str(out)])
    report = json.loads(out.read_text())
    assert report["winner"] is None
    assert rc == 1
