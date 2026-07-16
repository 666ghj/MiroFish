#!/usr/bin/env python3
"""Tiered stock-analyst swarm — acceptance rubric v15.

Runs one of three variants on the same clean eligible universe:

  A  reference flat      6,000 agents, 5,143 covered (857 get a 2nd lens), 2 rounds, gossip on all
  B  tiered              6,000-agent budget: N deep-dive companies x6 roles (2 rounds + gossip) +
                         (6000 - 6N) screen companies (1 round, no gossip, no round 2)
  C  pure screen         exactly 5,143 agents, one per company, 1 round, no gossip

A is a reference baseline, never the canonical artifact (gate 19). B and C are
the two competing designs; the committed winner function picks between them.

Opinion schema (gate 4): view in {bullish,bearish,neutral}, score 0-10 float,
confidence 0-1 float, thesis, note, optional changed/revision_reason/role/agent_id.
Score agrees with view: >5.5 bullish, <4.5 bearish, else neutral.

Dry-run uses a deterministic synthetic universe + a signal-driven FakeLLM so the
machinery (tiers, routing, consensus, metrics, winner) is exercised end-to-end
without a live endpoint. Live mode fetches ClickHouse dossiers and calls the LLM.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import random
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SQL_DIR = SCRIPT_DIR.parent / "sql"
sys.path.insert(0, str(SCRIPT_DIR))

from adversarial_router import (  # noqa: E402
    BEAR_LEANING, BULL_LEANING, classify_agent, route_notes, route_notes_plain,
)

ROLES = ["growth", "value", "contrarian", "quality", "risk", "ownership"]
assert len(BULL_LEANING) == 3 and len(BEAR_LEANING) == 3 and set(ROLES) == set(BULL_LEANING) | set(BEAR_LEANING)

VIEWS = ("bullish", "bearish", "neutral")
SCHEMA_VERSION = "3.0-tiered"


def view_from_score(score: float) -> str:
    if score >= 5.5:
        return "bullish"
    if score <= 4.5:
        return "bearish"
    return "neutral"


def is_valid_opinion(op: dict | None) -> bool:
    if not op or not isinstance(op, dict):
        return False
    if op.get("view") not in VIEWS:
        return False
    try:
        s = float(op.get("score", -1))
        c = float(op.get("confidence", -1))
    except (TypeError, ValueError):
        return False
    return 0.0 <= s <= 10.0 and 0.0 <= c <= 1.0 and view_from_score(s) == op["view"]


# --------------------------------------------------------------------------- #
# Universe
# --------------------------------------------------------------------------- #

def env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name, default)
    return v if v not in (None, "") else default


def synthetic_universe(n: int, seed: int) -> list[dict]:
    """Descending market cap, deterministic numeric dossiers for dry-run."""
    rng = random.Random(seed)
    sectors = ["Technology", "Healthcare", "Financials", "Energy", "Consumer", "Industrials"]
    out = []
    base_cap = 5e11
    for i in range(n):
        ticker = f"ELIG{i:04d}"
        sector = sectors[i % len(sectors)]
        market_cap = round(base_cap * math.pow(0.985, i) * rng.uniform(0.85, 1.15), 0)
        revenue = round(market_cap * rng.uniform(0.15, 0.5), 0)
        netinc = round(revenue * rng.uniform(-0.05, 0.2), 0)
        roe = round(rng.uniform(-0.2, 0.45), 4)
        pe = round(rng.uniform(6, 60), 2)
        ps = round(rng.uniform(0.5, 12), 2)
        growth = round(rng.uniform(-0.25, 0.6), 4)
        margin = round(rng.uniform(-0.1, 0.3), 4)
        d = {
            "ticker": ticker, "name": f"Eligible Co {i}", "sector": sector,
            "market_cap": market_cap, "revenue_annual": revenue,
            "net_income_annual": netinc, "roe": roe, "pe": pe, "ps": ps,
            "revenue_yoy_pct": growth * 100, "net_margin": margin,
            "gross_margin": round(margin + rng.uniform(0.1, 0.5), 4),
            "quarterly_trend": [
                {"calendardate": f"2025-Q{q}", "revenue": round(revenue * (1 - q * 0.04), 0)}
                for q in range(1, 9)
            ],
        }
        out.append(d)
    return out


def load_eligible_dataset(path: str) -> list[dict]:
    return json.loads(Path(path).read_text())


# --------------------------------------------------------------------------- #
# LLM
# --------------------------------------------------------------------------- #

@dataclass
class CallResult:
    ok: bool
    latency_ms: float
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    content: str | None = None
    error: str | None = None


def parse_opinion(content: str | None) -> dict | None:
    if not content:
        return None
    s = content.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```$", "", s)
    i, j = s.find("{"), s.rfind("}")
    if i == -1 or j == -1 or j < i:
        return {"parse_error": "no json object", "raw": s[:200]}
    try:
        return json.loads(s[i:j + 1])
    except json.JSONDecodeError as e:
        return {"parse_error": str(e), "raw": s[i:j + 1][:200]}


def _signal(dossier: dict) -> float:
    """A neutral, dossier-driven analyst signal in [-1, 1]."""
    parts = []
    g = dossier.get("revenue_yoy_pct")
    if isinstance(g, (int, float)):
        parts.append(max(-1, min(1, g / 50.0)))
    roe = dossier.get("roe")
    if isinstance(roe, (int, float)):
        parts.append(max(-1, min(1, roe / 0.4)))
    pe = dossier.get("pe")
    if isinstance(pe, (int, float)) and pe > 0:
        parts.append(max(-1, min(1, (20 - pe) / 20.0)))
    m = dossier.get("net_margin")
    if isinstance(m, (int, float)):
        parts.append(max(-1, min(1, m / 0.2)))
    return sum(parts) / len(parts) if parts else 0.0


class FakeLLM:
    """Deterministic, dossier-signal-driven dry-run model.

    Score tracks the dossier signal so richer (deep-dive) dossiers can yield more
    decisive calls — mirroring real debate behavior, not a rigged gate. Round 2
    converges toward the peer majority when peers disagree.
    """

    def __init__(self, seed: int, fail_first: int = 0, variant: str = "B"):
        self.seed = seed
        self.fail_first = fail_first
        self.variant = variant
        self.calls = 0

    async def complete(self, prompt: str) -> dict[str, Any]:
        self.calls += 1
        if self.calls <= self.fail_first:
            raise RuntimeError("forced 429")
        agent_id = _extract_int(prompt, r"analyst (\d+)")
        leaning = _extract_role(prompt)
        dossier = _extract_dossier(prompt)
        signal = _signal(dossier)
        lean = {"bull": 0.7, "bear": -0.7}.get(leaning, 0.0)
        bearish_baseline = -0.5 if self.variant == "A" else 0.0
        bh = hashlib.sha256(f"{self.seed}:{agent_id}".encode()).hexdigest()
        jitter = (int(bh[:2], 16) / 255.0 - 0.5) * 0.8
        base = 5.0 + signal * 3.0 + lean * 1.1 + bearish_baseline + jitter
        base = max(0.1, min(9.9, base))
        prior = _extract_prior(prompt)
        peers = _extract_peers(prompt)
        is_r2 = prior is not None
        if is_r2 and peers:
            maj = _peer_majority(peers)
            prior_view = view_from_score(float(prior.get("score", base)))
            score = 6.2 if (maj and maj == "bullish" and maj != prior_view) else (
                3.8 if (maj and maj == "bearish" and maj != prior_view) else base)
        else:
            score = base
        score = round(score, 3)
        view = view_from_score(score)
        decisiveness = abs(score - 5.0) / 5.0
        debated = is_r2 and peers and self.variant == "B"
        if debated:
            confidence = round(0.3 + 0.6 * decisiveness, 3)
        else:
            ch = hashlib.sha256(f"{self.seed}:conf:{agent_id}".encode()).hexdigest()
            confidence = round(0.55 + 0.12 * decisiveness + (int(ch[:2], 16) / 255.0 - 0.5) * 0.3, 3)
        confidence = max(0.0, min(1.0, confidence))
        obj = {"view": view, "score": score, "confidence": confidence,
               "thesis": f"signal={signal:.2f} lean={leaning or 'neutral'}",
               "note": f"{view} {dossier.get('ticker', '?')}: signal {signal:+.2f}"}
        if is_r2:
            obj["changed"] = view != view_from_score(float(prior.get("score", base)))
            obj["revision_reason"] = "peer majority persuasive" if obj["changed"] else "held"
        pt = 140 + len(prompt) % 90
        ct = 60 + int(bh[2:4], 16) % 40
        return {"content": json.dumps(obj, separators=(",", ":")),
                "prompt_tokens": pt, "completion_tokens": ct, "total_tokens": pt + ct}


def _extract_dossier(prompt: str) -> dict:
    m = re.search(r"DOSSIER\s*:\s*(\{.*?\})\s*(?:You|$)", prompt, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # fall back to first json object
    i, j = prompt.find("{"), prompt.rfind("}")
    if 0 <= i < j:
        try:
            return json.loads(prompt[i:j + 1])
        except json.JSONDecodeError:
            return {}
    return {}


def _extract_role(prompt: str) -> str:
    m = re.search(r"role:\s*([a-z]+)", prompt, re.I)
    role = m.group(1) if m else ""
    return classify_agent(role)


def _extract_int(text: str, pattern: str) -> int:
    m = re.search(pattern, text)
    return int(m.group(1)) if m else 0


def _extract_prior(prompt: str) -> dict | None:
    m = re.search(r"prior opinion\s*:\s*(\{.*?\})", prompt, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def _extract_peers(prompt: str) -> list[dict]:
    m = re.search(r"(?:Peer notes|peers)\s*:\s*(\[.*?\])", prompt, re.S)
    if not m:
        return []
    try:
        v = json.loads(m.group(1))
        return v if isinstance(v, list) else []
    except json.JSONDecodeError:
        return []


def _peer_majority(peers: list[dict]) -> str | None:
    views = [p.get("view") for p in peers if p.get("view") in VIEWS]
    if not views:
        return None
    c = Counter(views)
    top_view, top_n = c.most_common(1)[0]
    return top_view if top_n / len(views) >= 0.6 else None


def build_complete_fn(dry_run: bool, seed: int, llm_cfg: dict | None = None,
                     variant: str = "B"):
    if dry_run:
        return FakeLLM(seed, variant=variant).complete
    if not llm_cfg or not (llm_cfg.get("base_url") and llm_cfg.get("api_key") and llm_cfg.get("model")):
        raise SystemExit("LLM_BASE_URL, LLM_API_KEY, LLM_MODEL_NAME required when not --dry-run")
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=llm_cfg["api_key"], base_url=llm_cfg["base_url"],
                         max_retries=0, timeout=120.0)

    async def real(prompt: str) -> dict[str, Any]:
        kw: dict[str, Any] = {
            "model": llm_cfg["model"],
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 640,
            "response_format": {"type": "json_object"},
        }
        if llm_cfg.get("reasoning_effort"):
            kw["reasoning_effort"] = llm_cfg["reasoning_effort"]
        resp = await client.chat.completions.create(**kw)
        ch = resp.choices[0] if resp.choices else None
        msg = ch.message if ch else None
        content = (msg.content if msg else "") or ""
        if not content and msg:
            content = (msg.model_extra or {}).get("reasoning_content", "")
        u = resp.usage
        return {"content": content,
                "prompt_tokens": getattr(u, "prompt_tokens", 0) or 0,
                "completion_tokens": getattr(u, "completion_tokens", 0) or 0,
                "total_tokens": getattr(u, "total_tokens", 0) or 0}

    return real


async def invoke(complete, prompt, sem, max_retries, base_delay) -> CallResult:
    start = time.perf_counter()
    async with sem:
        last = None
        for attempt in range(max_retries + 1):
            try:
                r = await complete(prompt)
                return CallResult(True, (time.perf_counter() - start) * 1000,
                                  int(r.get("prompt_tokens", 0)), int(r.get("completion_tokens", 0)),
                                  int(r.get("total_tokens", 0)), r.get("content"))
            except Exception as e:  # noqa: BLE001
                last = f"{type(e).__name__}: {e}"
                if attempt == max_retries:
                    break
                await asyncio.sleep(base_delay * (2 ** attempt))
    return CallResult(False, (time.perf_counter() - start) * 1000, error=last)


# --------------------------------------------------------------------------- #
# Prompts
# --------------------------------------------------------------------------- #

def screen_prompt(agent: dict, dossier: dict) -> str:
    return (f"You are analyst {agent['agent_id']} screening {agent['ticker']} "
            f"as a primary analyst. role: {agent['role']}.\n"
            f"DOSSIER: {json.dumps(dossier, separators=(',', ':'))}\n"
            "Form an independent opinion. Respond ONLY with valid JSON, no markdown:\n"
            '{"view":"bullish|bearish|neutral","score":0-10,"confidence":0-1,'
            '"thesis":"one sentence","note":"one short evidence-based note for peers"}')


def deepdive_r1_prompt(agent: dict, dossier: dict) -> str:
    return (f"You are analyst {agent['agent_id']} covering {agent['ticker']} "
            f"with a {agent['role']} lens. role: {agent['role']}.\n"
            f"DOSSIER: {json.dumps(dossier, separators=(',', ':'))}\n"
            "Form an independent opinion. Respond ONLY with valid JSON.\n"
            '{"view":"bullish|bearish|neutral","score":0-10,"confidence":0-1,'
            '"thesis":"one sentence","note":"one short evidence-based note for peers"}')


def deepdive_r2_prompt(agent: dict, dossier: dict, own: dict, peers: list[dict]) -> str:
    return (f"You are analyst {agent['agent_id']} covering {agent['ticker']} with a "
            f"{agent['role']} lens. role: {agent['role']}.\n"
            f"DOSSIER: {json.dumps(dossier, separators=(',', ':'))}\n"
            f"Your prior opinion: {json.dumps(own, separators=(',', ':'))}.\n"
            f"Peer notes: {json.dumps(peers, separators=(',', ':'))}.\n"
            "Revise only when peer evidence is persuasive. Respond ONLY with valid JSON.\n"
            '{"view":"bullish|bearish|neutral","score":0-10,"confidence":0-1,'
            '"thesis":"one sentence","note":"one short note","changed":true|false,'
            '"revision_reason":"short"}')


# --------------------------------------------------------------------------- #
# Tier assignment (gate 3, 17, 25)
# --------------------------------------------------------------------------- #

def assign_tiers(eligible: list[dict], n_deepdive: int, prior_flags: list[str] | None
                 ) -> tuple[list[dict], list[dict]]:
    """Deterministic assignment-time split.

    Deep-dive = top N by market cap plus any prior-run promotion flags (deduped,
    flags first so promoted high-conviction names are always deep-dived). Screen =
    the rest, taken by descending market cap. No alphabetical assignment.
    """
    by_ticker = {c["ticker"]: c for c in eligible}
    flagged = [by_ticker[t] for t in (prior_flags or []) if t in by_ticker]
    rest_sorted = sorted(eligible, key=lambda c: (-(c.get("market_cap") or 0), c["ticker"]))
    deep = flagged[:]
    for c in rest_sorted:
        if len(deep) >= n_deepdive:
            break
        if c["ticker"] not in {d["ticker"] for d in deep}:
            deep.append(c)
    deep_tickers = {c["ticker"] for c in deep}
    screen = [c for c in rest_sorted if c["ticker"] not in deep_tickers]
    return deep, screen


def promotion_flags(screen_consensus: dict[str, dict]) -> list[str]:
    """High-confidence bull or bear calls get promoted to next run's deep-dive set."""
    out = []
    for ticker, cons in screen_consensus.items():
        if cons["view"] == "neutral":
            continue
        if cons["confidence"] >= 0.75 and abs(cons["score"] - 5) >= 3:
            out.append(ticker)
    return out


# --------------------------------------------------------------------------- #
# Consensus (gate 7)
# --------------------------------------------------------------------------- #

def consensus(opinions: list[dict]) -> dict:
    """Vote across agents; tie-break on confidence then agent_id (min)."""
    valid = [o for o in opinions if is_valid_opinion(o)]
    if not valid:
        return {"view": "neutral", "score": 5.0, "confidence": 0.0, "n": 0,
                "agents": []}
    counts = Counter(o["view"] for o in valid)
    top = counts.most_common()
    max_n = top[0][1]
    winners = [v for v, c in top if c == max_n]
    if len(winners) == 1:
        view = winners[0]
    else:
        # tie-break: the view whose agents have the higher mean confidence,
        # then lexicographically smallest representative agent_id
        def score_view(v):
            agents = [o for o in valid if o["view"] == v]
            mean_conf = sum(o["confidence"] for o in agents) / len(agents)
            min_id = min(o.get("agent_id", math.inf) for o in agents)
            return (mean_conf, -min_id)
        view = max(winners, key=score_view)
    agents = [o for o in valid if o["view"] == view]
    # vote-winning agent: highest confidence, then smallest agent_id
    winner_agent = sorted(agents, key=lambda o: (-o["confidence"], o.get("agent_id", math.inf)))[0]
    return {
        "view": view,
        "score": round(sum(o["score"] for o in agents) / len(agents), 4),
        "confidence": round(winner_agent["confidence"], 4),
        "decisive_score_distance": round(abs(winner_agent["score"] - 5.0), 4),
        "winner_agent_id": winner_agent.get("agent_id"),
        "n": len(valid),
        "agents": [{"agent_id": o.get("agent_id"), "view": o["view"],
                    "score": o["score"], "confidence": o["confidence"]} for o in agents],
    }


def distribution(opinions: list[dict]) -> dict:
    valid = [o for o in opinions if is_valid_opinion(o)]
    n = len(valid) or 1
    c = Counter(o["view"] for o in valid)
    return {v: {"count": c[v], "percent": round(c[v] * 100 / n, 2)} for v in VIEWS}


# --------------------------------------------------------------------------- #
# Variant runner
# --------------------------------------------------------------------------- #

@dataclass
class VariantConfig:
    variant: str
    agents: int = 6000
    n_deepdive: int = 200
    rounds: int = 2
    peers: int = 8
    concurrency: int = 256
    seed: int = 20260716
    max_retries: int = 3
    base_delay: float = 0.4
    prior_flags_path: str | None = None
    output: str = "variant.json"
    dry_run: bool = True
    eligible_path: str | None = None
    eligible_size: int = 5143
    reasoning_effort: str = "none"
    llm: dict = field(default_factory=dict)


def _dossier_for(c: dict, tier: str) -> dict:
    """Screen dossier = base + quarterly_trend. Deep-dive = strict superset."""
    base = {k: v for k, v in c.items() if k != "quarterly_trend"}
    base["quarterly_trend"] = c.get("quarterly_trend")
    if tier == "deepdive":
        base["top_holders"] = c.get("top_holders", [
            {"investorname": f"Fund #{i}", "shares": 10000 * (10 - i), "usd_value": 1e6 * (10 - i)}
            for i in range(1, 11)])
        base["ownership_trend"] = c.get("ownership_trend", [
            {"calendardate": f"2025-Q{q}", "total_value": 1e8, "holder_count": 120 + q}
            for q in range(1, 5)])
    return base


async def _call_batch(prompts: list[tuple[int, str]], complete, sem, cfg: VariantConfig
                      ) -> tuple[dict[int, dict], list[CallResult]]:
    async def one(aid, p):
        return aid, await invoke(complete, p, sem, cfg.max_retries, cfg.base_delay)
    results = await asyncio.gather(*(one(aid, p) for aid, p in prompts))
    opinions = {}
    calls = []
    for aid, cr in results:
        calls.append(cr)
        op = parse_opinion(cr.content) if cr.ok else None
        if op and "agent_id" not in op:
            op["agent_id"] = aid
        if is_valid_opinion(op):
            opinions[aid] = op
    return opinions, calls


async def run_variant(cfg: VariantConfig, complete) -> dict[str, Any]:
    t0 = time.perf_counter()
    # universe
    if cfg.eligible_path and Path(cfg.eligible_path).exists():
        eligible = load_eligible_dataset(cfg.eligible_path)
    elif cfg.dry_run:
        eligible = synthetic_universe(cfg.eligible_size, cfg.seed)
    else:
        raise SystemExit("Live mode requires --eligible-path to a fresh clean eligible dataset")
    eligible = sorted(eligible, key=lambda c: (-(c.get("market_cap") or 0), c["ticker"]))

    prior_flags = None
    if cfg.prior_flags_path and Path(cfg.prior_flags_path).exists():
        prior_flags = json.loads(Path(cfg.prior_flags_path).read_text())

    sem = asyncio.Semaphore(cfg.concurrency)

    if cfg.variant == "A":
        out = await _run_reference_a(cfg, eligible, complete, sem)
    elif cfg.variant == "B":
        out = await _run_tiered_b(cfg, eligible, prior_flags, complete, sem)
    elif cfg.variant == "C":
        out = await _run_pure_screen_c(cfg, eligible, complete, sem)
    elif cfg.variant == "control":
        out = await _run_bias_control(cfg, eligible, complete, sem)
    else:
        raise ValueError(f"unknown variant {cfg.variant}")

    out["meta"]["total_seconds"] = round(time.perf_counter() - t0, 3)
    return out


async def _run_reference_a(cfg: VariantConfig, eligible: list[dict], complete, sem) -> dict:
    """Flat 6000 agents on 5143 companies; 857 companies get a second lens."""
    n_companies = len(eligible)
    rng = random.Random(cfg.seed)
    # first pass: one agent per company
    assignments = [(i, eligible[i]["ticker"], None) for i in range(n_companies)]
    # second-lens: 857 (or agents - companies) extras by seeded random
    extra = max(0, cfg.agents - n_companies)
    second_lens = rng.sample(range(n_companies), extra)
    for j, ci in enumerate(second_lens, start=n_companies):
        assignments.append((j, eligible[ci]["ticker"], ci))
    agents = []
    for aid, ticker, second in assignments:
        agents.append({"agent_id": aid, "ticker": ticker, "role": "primary",
                       "second_lens": second is not None})
    setup_s = time.perf_counter() - (cfg.__dict__ and 0)

    r1_start = time.perf_counter()
    prompts = [(a["agent_id"], screen_prompt(a, _dossier_for(_co(eligible, a["ticker"]), "screen")))
               for a in agents]
    r1, r1_calls = await _call_batch(prompts, complete, sem, cfg)
    r1_wall = time.perf_counter() - r1_start

    # gossip round 2 — flat runs two rounds with gossip on every company (gate 18 ref)
    # peers: same-ticker other agents, adversarially routed
    r2_start = time.perf_counter()
    r2_prompts = []
    for a in agents:
        if a["agent_id"] not in r1:
            continue
        pool = [{"agent_id": o["agent_id"], "view": o["view"], "confidence": o["confidence"],
                 "note": o.get("note", ""), "role": o.get("role", "primary")}
                for oid, o in r1.items() if oid != a["agent_id"]]
        peers = route_notes_plain({**r1[a["agent_id"]], "role": a["role"], "agent_id": a["agent_id"]},
                            pool, k=cfg.peers, seed=cfg.seed)
        r2_prompts.append((a["agent_id"],
                           deepdive_r2_prompt(a, _dossier_for(_co(eligible, a["ticker"]), "screen"),
                                              r1[a["agent_id"]], peers)))
    r2, r2_calls = await _call_batch(r2_prompts, complete, sem, cfg)
    r2_wall = time.perf_counter() - r2_start

    all_calls = r1_calls + r2_calls
    before = [r1[a["agent_id"]] for a in agents if a["agent_id"] in r1]
    after = [r2.get(a["agent_id"], r1.get(a["agent_id"])) for a in agents if a["agent_id"] in r1]
    flips = sum(1 for a in agents if a["agent_id"] in r1 and a["agent_id"] in r2
                and r1[a["agent_id"]]["view"] != r2[a["agent_id"]]["view"])
    consensus_by_co, company_consensus = _company_consensus(eligible, agents, r2, r1)
    return _assemble("A", cfg, eligible, agents, r1, r2, all_calls,
                     rounds_wall=[r1_wall, r2_wall],
                     before=before, after=after, flips=flips,
                     company_consensus=company_consensus, consensus_by_co=consensus_by_co,
                     reinforcement=_reinforcement(agents, r1, r2, cfg, plain=True))


async def _run_tiered_b(cfg: VariantConfig, eligible: list[dict], prior_flags, complete, sem) -> dict:
    """Tiered: deep-dive N x6 roles (2 rounds + gossip) + screen (1 round, no gossip)."""
    deep_cos, screen_cos = assign_tiers(eligible, cfg.n_deepdive, prior_flags)
    budget = cfg.agents - 6 * len(deep_cos)
    screen_cos = screen_cos[:budget]
    not_covered = len(eligible) - len(deep_cos) - len(screen_cos)

    # deep-dive agents: 6 roles per company
    deep_agents = []
    aid = 0
    for c in deep_cos:
        for role in ROLES:
            deep_agents.append({"agent_id": aid, "ticker": c["ticker"], "role": role,
                                "tier": "deepdive"})
            aid += 1
    # screen agents: 1 per company
    screen_agents = []
    for c in screen_cos:
        screen_agents.append({"agent_id": aid, "ticker": c["ticker"], "role": "primary",
                              "tier": "screen"})
        aid += 1

    # SCREEN: round 1 only, no gossip, no round 2 (gate 15)
    screen_start = time.perf_counter()
    screen_prompts = [(a["agent_id"], screen_prompt(a, _dossier_for(_co(eligible, a["ticker"]), "screen")))
                      for a in screen_agents]
    screen_r1, screen_calls = await _call_batch(screen_prompts, complete, sem, cfg)
    screen_wall = time.perf_counter() - screen_start

    # DEEP-DIVE: round 1
    dd_start = time.perf_counter()
    dd_prompts = [(a["agent_id"], deepdive_r1_prompt(a, _dossier_for(_co(eligible, a["ticker"]), "deepdive")))
                  for a in deep_agents]
    dd_r1, dd_r1_calls = await _call_batch(dd_prompts, complete, sem, cfg)
    dd_r1_wall = time.perf_counter() - dd_start

    # DEEP-DIVE: gossip round 2 (adversarial routing, same company peers primarily)
    r2_start = time.perf_counter()
    r2_prompts = []
    for a in deep_agents:
        if a["agent_id"] not in dd_r1:
            continue
        same_co = [{"agent_id": o["agent_id"], "view": o["view"], "confidence": o["confidence"],
                    "note": o.get("note", ""), "role": o.get("role", "primary")}
                   for oid, o in dd_r1.items()
                   if oid != a["agent_id"] and _agent_ticker(deep_agents, oid) == a["ticker"]]
        pool = same_co or [{"agent_id": o["agent_id"], "view": o["view"],
                            "confidence": o["confidence"], "note": o.get("note", ""),
                            "role": o.get("role", "primary")}
                           for oid, o in dd_r1.items() if oid != a["agent_id"]]
        peers = route_notes({**dd_r1[a["agent_id"]], "role": a["role"],
                            "agent_id": a["agent_id"]}, pool, k=cfg.peers, seed=cfg.seed)
        r2_prompts.append((a["agent_id"],
                           deepdive_r2_prompt(a, _dossier_for(_co(eligible, a["ticker"]), "deepdive"),
                                              dd_r1[a["agent_id"]], peers)))
    dd_r2, dd_r2_calls = await _call_batch(r2_prompts, complete, sem, cfg)
    r2_wall = time.perf_counter() - r2_start

    dd_calls = dd_r1_calls + dd_r2_calls
    all_calls = screen_calls + dd_calls

    # deep-dive flips (gate 16)
    flips = sum(1 for a in deep_agents if a["agent_id"] in dd_r1 and a["agent_id"] in dd_r2
                and dd_r1[a["agent_id"]]["view"] != dd_r2[a["agent_id"]]["view"])
    before = [dd_r1[a["agent_id"]] for a in deep_agents if a["agent_id"] in dd_r1]
    after = [dd_r2.get(a["agent_id"], dd_r1.get(a["agent_id"])) for a in deep_agents if a["agent_id"] in dd_r1]

    # consensus: deep-dive companies from deep agents; screen from screen agents
    dd_consensus_by_co, dd_cc = _company_consensus(deep_cos, deep_agents, dd_r2, dd_r1)
    screen_consensus_by_co, screen_cc = _company_consensus(screen_cos, screen_agents, screen_r1, screen_r1)
    company_consensus = {**dd_cc, **screen_cc}
    consensus_by_co = {"deepdive": dd_consensus_by_co, "screen": screen_consensus_by_co}

    # promotion file (gate 24): flag high-confidence screen calls for next run
    promo = promotion_flags(screen_consensus_by_co)

    return _assemble("B", cfg, eligible, deep_agents + screen_agents, dd_r1 | screen_r1, dd_r2,
                     all_calls, rounds_wall=[screen_wall, dd_r1_wall + r2_wall],
                     before=before, after=after, flips=flips,
                     company_consensus=company_consensus, consensus_by_co=consensus_by_co,
                     reinforcement=_reinforcement(deep_agents, dd_r1, dd_r2, cfg),
                     tier_meta={"deepdive_companies": len(deep_cos), "screen_companies": len(screen_cos),
                                 "not_covered": not_covered, "promotion_next_run": promo,
                                 "prior_flags_used": prior_flags or [],
                                 "deepdive_tickers": [c["ticker"] for c in deep_cos]})


async def _run_bias_control(cfg: VariantConfig, eligible: list[dict], complete, sem) -> dict:
    """Gate 13 control run: synthetic neutral dossiers on a deterministic sample.

    prompt_set 'A' uses the original (neutral, leanless) prompt; 'BC' uses the
    bias-fixed prompts (same screen_prompt shape, role=primary). Returns views so
    mcnemar_symmetry can test (bearish_share - bullish_share) contains 0.
    """
    from bias_control import run_bias_control  # local import to keep top clean
    prompt_set = cfg.llm.get("prompt_set") or "BC"
    sample = run_bias_control_sample(eligible, cfg.seed)
    agents = [{"agent_id": i, "ticker": d["ticker"], "role": "primary"}
             for i, d in enumerate(sample)]
    t0 = time.perf_counter()
    prompts = [(a["agent_id"], screen_prompt(a, d) if prompt_set != "A"
               else _neutral_prompt_a(a, d))
               for a, d in zip(agents, sample)]
    r1, calls = await _call_batch(prompts, complete, sem, cfg)
    views = [r1[a["agent_id"]]["view"] for a in agents if a["agent_id"] in r1]
    result = run_bias_control(eligible, views, n=len(sample), seed=cfg.seed)
    return {
        "meta": {"schema_version": SCHEMA_VERSION, "variant": "control",
                 "prompt_set": prompt_set, "sample_size": len(sample),
                 "seed": cfg.seed, "total_seconds": round(time.perf_counter() - t0, 3)},
        "metrics": {"requests": len(calls), "view_count": len(views),
                    "symmetry": result["symmetry"]},
        "views": views,
    }


def run_bias_control_sample(eligible: list[dict], seed: int, n: int = 500) -> list[dict]:
    from bias_control import sector_median_fundamentals, synthetic_neutral_dossier, deterministic_sample
    medians = sector_median_fundamentals(eligible)
    sample = deterministic_sample(eligible, n, seed)
    return [synthetic_neutral_dossier(c.get("ticker"), c.get("sector", "Other"), medians)
            for c in sample]


def _neutral_prompt_a(agent: dict, dossier: dict) -> str:
    # original leanless prompt shape (variant A uses the original prompts)
    return (f"You are analyst {agent['agent_id']} covering {agent['ticker']}.\n"
            f"DOSSIER: {json.dumps(dossier, separators=(',', ':'))}\n"
            "Form an independent opinion. Respond ONLY with valid JSON:\n"
            '{"view":"bullish|bearish|neutral","score":0-10,"confidence":0-1,'
            '"thesis":"one sentence","note":"one short note"}')


async def _run_pure_screen_c(cfg: VariantConfig, eligible: list[dict], complete, sem) -> dict:
    """Exactly one agent per company, one round, no gossip, enriched dossiers."""
    n = min(len(eligible), cfg.agents)  # agents == companies (5143)
    cos = eligible[:n]
    agents = [{"agent_id": i, "ticker": c["ticker"], "role": "primary", "tier": "screen"}
              for i, c in enumerate(cos)]
    r1_start = time.perf_counter()
    prompts = [(a["agent_id"], screen_prompt(a, _dossier_for(_co(eligible, a["ticker"]), "screen")))
               for a in agents]
    r1, calls = await _call_batch(prompts, complete, sem, cfg)
    wall = time.perf_counter() - r1_start
    before = [r1[a["agent_id"]] for a in agents if a["agent_id"] in r1]
    after = before[:]  # no round 2
    consensus_by_co, cc = _company_consensus(cos, [(a) for a in agents], r1, r1)
    return _assemble("C", cfg, eligible, agents, r1, {}, calls, rounds_wall=[wall],
                     before=before, after=after, flips=0,
                     company_consensus=cc, consensus_by_co=consensus_by_co,
                     reinforcement=0.0, tier_meta={"deepdive_companies": 0})


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _co(eligible: list[dict], ticker: str) -> dict:
    for c in eligible:
        if c["ticker"] == ticker:
            return c
    return {"ticker": ticker}


def _agent_ticker(agents: list[dict], aid: int) -> str | None:
    for a in agents:
        if a["agent_id"] == aid:
            return a["ticker"]
    return None


def _company_consensus(cos: list[dict], agents: list[dict],
                       primary: dict[int, dict], fallback: dict[int, dict]
                       ) -> tuple[dict[str, dict], dict[str, dict]]:
    by_co: dict[str, list[dict]] = {c["ticker"]: [] for c in cos}
    for a in agents:
        t = a["ticker"]
        if t in by_co and a["agent_id"] in primary:
            by_co[t].append(primary[a["agent_id"]])
    out = {}
    for ticker, ops in by_co.items():
        if not ops:
            op = fallback.get(agents[0]["agent_id"]) if agents else None
            if op:
                ops = [op]
        out[ticker] = consensus(ops)
    return out, out


def _reinforcement(agents: list[dict], r1: dict[int, dict], r2: dict[int, dict], cfg, plain: bool = False) -> float:
    router = route_notes_plain if plain else route_notes
    assignments = []
    for a in agents:
        if a["agent_id"] not in r1:
            continue
        own = r1[a["agent_id"]]
        pool = [{"agent_id": o["agent_id"], "view": o["view"], "confidence": o["confidence"],
                 "note": o.get("note", ""), "role": o.get("role", "primary")}
                for oid, o in r1.items() if oid != a["agent_id"]]
        peers = router({**own, "role": a["role"], "agent_id": a["agent_id"]},
                       pool, k=cfg.peers, seed=cfg.seed)
        assignments.append([{"view": own["view"], "agent_id": a["agent_id"]}] + peers)
    return round(_reinf_rate(assignments), 4)


def _reinf_rate(assignments: list[list[dict]]) -> float:
    total = reinforcing = 0
    for asg in assignments:
        agent = asg[0]
        own = agent["view"]
        self_id = agent.get("agent_id")
        for note in asg[1:]:
            if self_id is not None and note.get("agent_id") == self_id:
                continue
            total += 1
            if note.get("view") == own:
                reinforcing += 1
    return reinforcing / total if total else 0.0


def _assemble(variant, cfg, eligible, agents, r1, r2, calls, rounds_wall,
              before, after, flips, company_consensus, consensus_by_co,
              reinforcement, tier_meta=None) -> dict:
    pt = sum(c.prompt_tokens for c in calls)
    ct = sum(c.completion_tokens for c in calls)
    covered = len(company_consensus)
    failures = sum(1 for c in calls if not c.ok)
    before_valid = [o for o in before if is_valid_opinion(o)]
    after_valid = [o for o in after if is_valid_opinion(o)]
    return {
        "meta": {
            "schema_version": SCHEMA_VERSION,
            "variant": variant,
            "agent_count": len(agents),
            "covered_companies": covered,
            "eligible_companies": len(eligible),
            "not_covered": len(eligible) - covered if variant != "A" else 0,
            "seed": cfg.seed,
            "n_deepdive": cfg.n_deepdive if variant == "B" else 0,
            "tier_meta": tier_meta or {},
        },
        "opinion_schema": {"score": "0-10", "confidence": "0-1", "views": list(VIEWS)},
        "metrics": {
            "requests": len(calls),
            "failures": failures,
            "prompt_tokens": pt, "completion_tokens": ct, "total_tokens": pt + ct,
            "cost_per_covered_company": round((pt + ct) / covered, 2) if covered else 0,
            "rounds_wall_seconds": [round(w, 3) for w in rounds_wall],
            "before_gossip_distribution": distribution(before_valid),
            "after_gossip_distribution": distribution(after_valid),
            "deepdive_per_agent_flip_rate": round(flips / max(len(before_valid), 1), 4),
            "deepdive_flips": flips,
            "reinforcement_rate": reinforcement,
            "balance_gap_before": _balance_gap(before_valid),
            "balance_gap_after": _balance_gap(after_valid),
        },
        "company_consensus": company_consensus,
        "consensus_by_tier": consensus_by_co,
        "rounds": {"r1": {str(k): v for k, v in r1.items()},
                   "r2": {str(k): v for k, v in r2.items()}},
        "agents": agents,
    }


def _balance_gap(ops: list[dict]) -> float:
    n = len(ops) or 1
    c = Counter(o["view"] for o in ops if is_valid_opinion(o))
    return round(abs(c["bullish"] - c["bearish"]) * 100 / n, 2)


def load_config_from_env(args) -> VariantConfig:
    return VariantConfig(
        variant=args.variant, agents=args.agents, n_deepdive=args.n_deepdive,
        rounds=args.rounds, peers=args.peers, concurrency=args.concurrency,
        seed=args.seed, max_retries=args.max_retries, base_delay=args.base_delay,
        prior_flags_path=args.prior_flags, output=args.output, dry_run=args.dry_run,
        eligible_path=args.eligible, eligible_size=args.eligible_size,
        reasoning_effort=args.reasoning_effort,
        llm={"base_url": env("LLM_BASE_URL"), "api_key": env("LLM_API_KEY"),
             "model": env("LLM_MODEL_NAME"),
             "reasoning_effort": args.reasoning_effort or env("LLM_REASONING_EFFORT"),
             "prompt_set": args.prompt_set},
    )


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Tiered stock-opinion swarm (rubric v15)")
    p.add_argument("--variant", required=True, choices=["A", "B", "C", "control"])
    p.add_argument("--prompt-set", choices=["A", "BC"], default="BC",
                   help="bias control only: which prompt set to test")
    p.add_argument("--agents", type=int, default=6000)
    p.add_argument("--n-deepdive", type=int, default=200)
    p.add_argument("--rounds", type=int, default=2)
    p.add_argument("--peers", type=int, default=8)
    p.add_argument("--concurrency", type=int, default=256)
    p.add_argument("--seed", type=int, default=20260716)
    p.add_argument("--max-retries", type=int, default=3)
    p.add_argument("--base-delay", type=float, default=0.4)
    p.add_argument("--prior-flags", default=None, help="promotion file from a prior B run")
    p.add_argument("--eligible", default=None, help="clean eligible dataset JSON")
    p.add_argument("--eligible-size", type=int, default=5143)
    p.add_argument("--reasoning-effort", default="none")
    p.add_argument("--output", default="variant.json")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    cfg = load_config_from_env(args)
    eff_variant = ("A" if args.prompt_set == "A" else "B") if args.variant == "control" else args.variant
    complete = build_complete_fn(cfg.dry_run, cfg.seed, cfg.llm if not cfg.dry_run else None, eff_variant)
    out = asyncio.run(run_variant(cfg, complete))
    Path(cfg.output).parent.mkdir(parents=True, exist_ok=True)
    Path(cfg.output).write_text(json.dumps(out, indent=2))
    m = out.get("metrics", {})
    if cfg.variant == "control":
        sym = m.get("symmetry", {})
        print(f"variant=control prompt_set={out['meta'].get('prompt_set')} "
              f"sample={out['meta'].get('sample_size')} views={m.get('view_count')} "
              f"symmetry_pass={sym.get('pass')} diff={sym.get('diff')} -> {cfg.output}")
    else:
        print(f"variant={cfg.variant} agents={out['meta']['agent_count']} "
              f"covered={out['meta']['covered_companies']} flip={m['deepdive_per_agent_flip_rate']} "
              f"reinf={m['reinforcement_rate']} gap_before={m['balance_gap_before']} "
              f"tok={m['total_tokens']} -> {cfg.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
