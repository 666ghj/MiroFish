#!/usr/bin/env python3
"""EXPERIMENT: does anonymizing the synthetic-neutral dossier's ticker/name
remove a bias-control confound (real-ticker identity sentiment), letting the
bias-fixed prompt pass gate 13 while the original still fails?

Anonymized neutral dossier = sector-median fundamentals + a neutral placeholder
name (no real ticker identity). This is arguably a MORE faithful "synthetic
neutral dossier" (gate 13) than one carrying real-ticker sentiment.
"""
from __future__ import annotations
import asyncio, json, os, sys, time
sys.path.insert(0, "scripts")
import run_tiered_swarm as rt
from bias_control import (sector_median_fundamentals, deterministic_sample,
                          mcnemar_symmetry, synthetic_neutral_dossier)

ELIG = "/Users/renanflorez/Documents/mirofish-swarm/artifacts/company-dossiers-eligible.json"
eligible = json.load(open(ELIG))
medians = sector_median_fundamentals(eligible)
sample = deterministic_sample(eligible, 500, 20260716)

# anon neutral dossier: strip ticker identity, keep sector + sector-median numbers
def anon(d):
    return {"ticker": "ANON", "name": "Anonymized Company", "sector": d["sector"],
            "synthetic_neutral": True, **{k: d.get(k) for k in
            ("revenue_ttm","net_income","roe","pe","ps","market_cap","gross_margin","net_margin")}}

dossiers = [anon(synthetic_neutral_dossier(c.get("ticker"), c.get("sector","Other"), medians)) for c in sample]
agents = [{"agent_id": i, "ticker": d["ticker"], "role": "primary"} for i, d in enumerate(dossiers)]

async def run_set(prompt_fn, tag):
    prompts = [(a["agent_id"], prompt_fn(a, d)) for a, d in zip(agents, dossiers)]
    llm_cfg = {"base_url": os.environ["LLM_BASE_URL"],
               "api_key": os.environ.get("LLM_API_KEY","dummy"),
               "model": os.environ.get("LLM_MODEL_NAME","glm-5.2"),
               "reasoning_effort": "none"}
    complete = rt.build_complete_fn(dry_run=False, seed=20260716, llm_cfg=llm_cfg, variant="control")
    sem = asyncio.Semaphore(48)
    t0 = time.perf_counter()
    r1, calls = await rt._call_batch(prompts, complete, sem,
                                     rt.VariantConfig(variant="control", agents=len(agents),
                                       n_deepdive=0, eligible_size=len(eligible), seed=20260716,
                                       concurrency=48, reasoning_effort="none", llm=llm_cfg))
    views = [r1[a["agent_id"]]["view"] for a in agents if a["agent_id"] in r1]
    sym = mcnemar_symmetry(views)
    print(f"\n=== ANON control {tag} ({len(views)} views, {len(calls)} calls, {time.perf_counter()-t0:.0f}s) ===")
    print(f"  bull={sym['n_bull']} bear={sym['n_bear']} neutral={sym['n_neutral']} active={sym['n_active']}")
    print(f"  diff(bear-bull)={sym['diff']:.3f}  ci95=[{sym['ci95'][0]:.3f},{sym['ci95'][1]:.3f}]  GATE13={'PASS' if sym['pass'] else 'FAIL'}")
    return views

async def main():
    a = await run_set(rt.screen_prompt, "A")
    b = await run_set(rt.bias_fixed_prompt, "BC")
    json.dump({"A_anon": a, "BC_anon": b}, open("artifacts/v15/exp_anon_bias.json","w"))

asyncio.run(main())
