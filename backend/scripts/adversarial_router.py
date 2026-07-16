#!/usr/bin/env python3
"""Adversarial peer-note routing for a tiered stock-analyst swarm.

Bull-leaning analysts receive bearish peer notes, bear-leaning analysts receive
bullish notes, and neutral-leaning analysts rotate through neutral notes first.
Same-view notes are returned only when no opposite/neutral note exists. Gate 14.
"""
from __future__ import annotations

import hashlib
import random
from typing import Optional

BULL_LEANING = ["growth", "value", "contrarian"]
BEAR_LEANING = ["quality", "risk", "ownership"]

_VIEWS = ("bullish", "bearish", "neutral")
_OPP_OF = {"bullish": "bearish", "bearish": "bullish", "neutral": None}


def classify_agent(role: str) -> str:
    """Map a role to a leaning: 'bull', 'bear', or 'neutral'."""
    if role in BULL_LEANING:
        return "bull"
    if role in BEAR_LEANING:
        return "bear"
    return "neutral"


def _opposite_view(leaning: str, own_view: str) -> Optional[str]:
    if leaning == "bull":
        return "bearish"
    if leaning == "bear":
        return "bullish"
    return _OPP_OF.get(own_view)


def _tier_order(leaning: str, own_view: str) -> list[str]:
    """Preferred note-view order. Biased agents: [opposite, neutral, same];
    neutral-leaning agents: [neutral, opposite-of-own, same]."""
    same = own_view
    opp = _opposite_view(leaning, own_view)
    if leaning == "neutral":
        tiers = ["neutral"]
        if opp and opp not in tiers:
            tiers.append(opp)
        if same and same not in tiers:
            tiers.append(same)
        return tiers
    tiers = []
    if opp:
        tiers.append(opp)
    if "neutral" not in tiers:
        tiers.append("neutral")
    if same not in tiers:
        tiers.append(same)
    return tiers


def route_notes(agent: dict, note_pool: list[dict], k: int = 8,
               seed: int = 0, rng: Optional[random.Random] = None) -> list[dict]:
    """Return up to k adversarial peer notes for `agent`.

    Same-view notes are excluded unless no opposite/neutral note exists. The
    agent's own note (matched by agent_id) is never returned; results are
    deduplicated by agent_id and are deterministic for a fixed seed + agent_id.
    """
    leaning = classify_agent(agent.get("role", ""))
    own_view = agent.get("view", "neutral")
    self_id = agent.get("agent_id")
    tiers = _tier_order(leaning, own_view)

    buckets: dict[str, list[dict]] = {v: [] for v in _VIEWS}
    for note in note_pool:
        if self_id is not None and note.get("agent_id") == self_id:
            continue
        v = note.get("view")
        if v in buckets:
            buckets[v].append(note)

    adv_views = [t for t in tiers if t != own_view]
    chosen = adv_views if any(buckets[v] for v in adv_views) else [own_view]

    if rng is None:
        h = hashlib.sha256(f"{seed}:{self_id}".encode()).hexdigest()
        rng = random.Random(int(h[:8], 16))

    seen: set = set()
    out: list[dict] = []
    for v in chosen:
        block = list(buckets[v])
        rng.shuffle(block)
        for note in block:
            nid = note.get("agent_id")
            key = nid if nid is not None else id(note)
            if key in seen:
                continue
            seen.add(key)
            out.append(note)
            if len(out) >= k:
                return out
    return out


def reinforcement_rate(assignments: list[list[dict]]) -> float:
    """Fraction of routed notes whose view matches the receiver's own view.

    Each assignment is a list whose first element is the receiving agent dict
    and whose remaining elements are that agent's routed notes (a single nested
    list of notes is also accepted). Self-notes are excluded from both counts.
    """
    total = 0
    reinforcing = 0
    for assignment in assignments:
        if not assignment:
            continue
        agent = assignment[0]
        own = agent.get("view")
        self_id = agent.get("agent_id")
        notes: list[dict] = []
        for item in assignment[1:]:
            if isinstance(item, list):
                notes.extend(item)
            elif isinstance(item, dict):
                notes.append(item)
        for note in notes:
            if self_id is not None and note.get("agent_id") == self_id:
                continue
            total += 1
            if note.get("view") == own:
                reinforcing += 1
    return reinforcing / total if total else 0.0


def route_notes_plain(agent: dict, note_pool: list[dict], k: int = 8,
                           seed: int = 0, rng: Optional[random.Random] = None) -> list[dict]:
    """Plain (non-adversarial) routing favouring the agent's OWN view first.

    This is the pre-fix 'reinforcing' baseline used by variant A: peers tend to
    echo the agent's prior. Same agent_id never returned; deterministic for seed.
    """
    own_view = agent.get("view", "neutral")
    self_id = agent.get("agent_id")
    buckets: dict[str, list[dict]] = {v: [] for v in _VIEWS}
    for note in note_pool:
        if self_id is not None and note.get("agent_id") == self_id:
            continue
        v = note.get("view")
        if v in buckets:
            buckets[v].append(note)
    order = [own_view, "neutral"] + [v for v in _VIEWS if v not in (own_view, "neutral")]
    if rng is None:
        h = hashlib.sha256(f"plain:{seed}:{self_id}".encode()).hexdigest()
        rng = random.Random(int(h[:8], 16))
    seen: set = set()
    out: list[dict] = []
    for v in order:
        block = list(buckets[v])
        rng.shuffle(block)
        for note in block:
            nid = note.get("agent_id")
            key = nid if nid is not None else id(note)
            if key in seen:
                continue
            seen.add(key)
            out.append(note)
            if len(out) >= k:
                return out
    return out


def synthetic_bear_market_pool(n_bull: int, n_bear: int, n_neutral: int,
                              seed: int) -> list[dict]:
    """Build a synthetic opinion pool with the requested view mix."""
    rng = random.Random(seed)
    pool: list[dict] = []
    idx = 0
    for view, n in (("bullish", n_bull), ("bearish", n_bear), ("neutral", n_neutral)):
        for _ in range(n):
            pool.append({
                "agent_id": f"syn-{idx}",
                "view": view,
                "score": round(rng.uniform(0, 10), 3),
                "confidence": round(rng.uniform(0, 1), 3),
                "thesis": f"{view} thesis {idx}",
                "note": f"{view} note {idx}",
                "role": rng.choice(BULL_LEANING + BEAR_LEANING),
            })
            idx += 1
    return pool
