import math

import bias_control as bc


def _dossiers():
    return [
        {"ticker": "AAA", "sector": "tech", "revenue_ttm": 100, "roe": 0.1, "pe": 20, "ps": 4},
        {"ticker": "BBB", "sector": "tech", "revenue_ttm": 300, "roe": 0.3, "pe": 40, "ps": 8},
        {"ticker": "CCC", "sector": "tech", "revenue_ttm": 200, "roe": 0.2, "pe": 30, "ps": 6},
        {"ticker": "DDD", "sector": "energy", "revenue_ttm": 50, "roe": None, "pe": 10, "ps": 2},
        {"ticker": "EEE", "sector": "energy", "revenue_ttm": 150, "roe": 0.15, "pe": 15, "ps": 3},
    ]


def test_sector_median_ignores_none_and_returns_medians():
    medians = bc.sector_median_fundamentals(_dossiers())
    assert set(medians) == {"tech", "energy"}
    # tech sorted revenue 100,200,300 -> median 200; roe 0.1,0.2,0.3 -> 0.2
    assert medians["tech"]["revenue_ttm"] == 200
    assert medians["tech"]["roe"] == 0.2
    # energy roe had one None -> only 0.15 survives -> median 0.15
    assert medians["energy"]["roe"] == 0.15


def test_synthetic_neutral_dossier_pins_medians_and_marks_flag():
    medians = bc.sector_median_fundamentals(_dossiers())
    d = bc.synthetic_neutral_dossier("ZZZ", "tech", medians)
    assert d["ticker"] == "ZZZ"
    assert d["sector"] == "tech"
    assert d["synthetic_neutral"] is True
    assert d["revenue_ttm"] == medians["tech"]["revenue_ttm"] == 200
    assert d["roe"] == 0.2
    # field absent from medians stays None
    assert d["net_margin"] is None


def test_deterministic_sample_reproducible():
    items = list(range(1000))
    a = bc.deterministic_sample(items, 500, 7)
    b = bc.deterministic_sample(items, 500, 7)
    assert a == b
    assert len(a) == 500


def test_deterministic_sample_clamps_to_min_500():
    items = list(range(600))
    assert len(bc.deterministic_sample(items, 10, 1)) == 500


def test_deterministic_sample_returns_all_when_fewer_than_500():
    items = list(range(30))
    out = bc.deterministic_sample(items, 10, 1)
    assert len(out) == 30
    assert sorted(out) == items


def test_mcnemar_symmetric_passes_and_ci_contains_zero():
    views = ["bullish"] * 100 + ["bearish"] * 100 + ["neutral"] * 50
    r = bc.mcnemar_symmetry(views)
    assert r["n_bull"] == 100 and r["n_bear"] == 100 and r["n_neutral"] == 50
    assert r["n_active"] == 200
    assert r["diff"] == 0.0
    lo, hi = r["ci95"]
    assert lo < 0 < hi
    assert r["pass"] is True


def test_mcnemar_skewed_fails():
    views = ["bullish"] * 300 + ["bearish"] * 10
    r = bc.mcnemar_symmetry(views)
    assert r["n_active"] == 310
    assert r["diff"] < 0
    lo, hi = r["ci95"]
    assert hi < 0
    assert r["pass"] is False


def test_run_bias_control_end_to_end():
    companies = [
        {"ticker": f"T{i}", "sector": "tech", "revenue_annual": i * 10, "roe": i / 100}
        for i in range(600)
    ]
    # balanced views -> no bearish bias detected
    views = (["bullish", "bearish"] * 250) + ["neutral"] * 100
    out = bc.run_bias_control(companies, views, n=500, seed=13)
    assert out["n_sampled"] == 500
    assert out["symmetry"]["pass"] is True
    assert all(d["synthetic_neutral"] for d in out["dossiers"][:5])
