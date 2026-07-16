"""
Gate 13 — no bearish prompt bias, tested by symmetry.

Builds synthetic "neutral" dossiers (every numeric field pinned to the sector
median) for a deterministic random sample of companies, classifies a prompt
set's view of each dossier as bullish/bearish/neutral, and runs a McNemar-style
symmetry test on (bear_share - bull_share) to detect directional bias.

Pure standard library only.
"""

from __future__ import annotations

import math
import random
import statistics
from typing import Any

NUMERIC_FIELDS = (
    "revenue_annual",
    "net_income_annual",
    "roe",
    "pe",
    "ps",
    "market_cap",
    "gross_margin",
    "net_margin",
)


def sector_median_fundamentals(dossiers: list[dict]) -> dict[str, dict]:
    """Per-sector median of every numeric dossier field; None values ignored."""
    by_sector: dict[str, dict[str, list[float]]] = {}
    for d in dossiers:
        sector = d.get("sector")
        if not sector:
            continue
        bucket = by_sector.setdefault(sector, {f: [] for f in NUMERIC_FIELDS})
        for f in NUMERIC_FIELDS:
            v = d.get(f)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                bucket[f].append(v)

    out: dict[str, dict] = {}
    for sector, bucket in by_sector.items():
        medians = {f: statistics.median(vals) for f, vals in bucket.items() if vals}
        out[sector] = medians
    return out


def synthetic_neutral_dossier(ticker: str, sector: str, medians: dict) -> dict:
    """A dossier pinned to sector medians for every numeric field."""
    sec_medians = medians.get(sector, {})
    d = {"ticker": ticker, "name": ticker, "sector": sector, "synthetic_neutral": True}
    for f in NUMERIC_FIELDS:
        d[f] = sec_medians.get(f)
    return d


def deterministic_sample(items: list, n: int, seed: int) -> list:
    """Seeded shuffle, take n. Enforce minimum 500 (or all if fewer available)."""
    desired = max(n, 500)
    take = min(desired, len(items))
    rng = random.Random(seed)
    pool = list(items)
    rng.shuffle(pool)
    return pool[:take]


def mcnemar_symmetry(views: list[str]) -> dict:
    """Symmetry test on bullish/bearish/neutral views.

    diff = bear_share - bull_share over n_active = n_bull + n_bear.
    95% CI via normal approx; PASS when 0 is inside the CI.
    """
    n_bull = sum(1 for v in views if v == "bullish")
    n_bear = sum(1 for v in views if v == "bearish")
    n_neutral = sum(1 for v in views if v == "neutral")
    n_active = n_bull + n_bear

    if n_active == 0:
        return {
            "n_bull": n_bull,
            "n_bear": n_bear,
            "n_neutral": n_neutral,
            "n_active": 0,
            "diff": 0.0,
            "ci95": [0.0, 0.0],
            "pass": True,
        }

    p_bull = n_bull / n_active
    p_bear = n_bear / n_active
    diff = p_bear - p_bull
    se = math.sqrt((p_bull + p_bear - (p_bull - p_bear) ** 2) / n_active)
    moe = 1.96 * se
    lo, hi = diff - moe, diff + moe
    return {
        "n_bull": n_bull,
        "n_bear": n_bear,
        "n_neutral": n_neutral,
        "n_active": n_active,
        "diff": diff,
        "ci95": [lo, hi],
        "pass": lo <= 0.0 <= hi,
    }


def run_bias_control(
    companies: list[dict],
    views: list[str],
    n: int = 500,
    seed: int = 13,
) -> dict:
    """End-to-end: median fundamentals -> neutral dossiers -> symmetry test.

    companies: real dossiers (used to derive sector medians + as the sampling frame).
    views: parallel list of bullish|bearish|neutral for each sampled dossier.
    """
    medians = sector_median_fundamentals(companies)
    sample = deterministic_sample(companies, n, seed)
    dossiers = [
        synthetic_neutral_dossier(c.get("ticker", c.get("name", "?")), c.get("sector", "?"), medians)
        for c in sample
    ]
    result = mcnemar_symmetry(views)
    return {"n_sampled": len(dossiers), "dossiers": dossiers, "symmetry": result}
