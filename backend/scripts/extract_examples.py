"""Extract curated example blocks from a winning variant artifact (rubric v15, gate 8).

Gate 8 (winner == B) requires, each matching the artifact JSON:
  - >=2 deep-dive examples with 2 opposing roles on the same company
  - >=1 screen example
  - >=1 bullish-to-bearish flip
  - >=1 neutral-to-bearish flip
  - >=1 move toward bullish
  - >=1 confidence tie-break

Each example shows: fundamentals, initial view, peer evidence (where applicable),
final view, reason. Categories with fewer than the required count print the best
available and an honest shortfall note — nothing is fabricated.

Runnable:  python scripts/extract_examples.py --artifact <path> --output <path>
Importable: extract_examples(artifact_dict) -> report dict; main(argv) -> int
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REQUIRED = {
    "deepdive_opposing_roles": 2,
    "screen_example": 1,
    "bullish_to_bearish_flip": 1,
    "neutral_to_bearish_flip": 1,
    "move_toward_bullish": 1,
    "confidence_tie_break": 1,
}


def _signal_from_thesis(thesis: str | None) -> str | None:
    if not thesis:
        return None
    m = re.search(r"signal=([+-]?\d+(?:\.\d+)?)", thesis)
    return m.group(1) if m else None


def _agents_by_ticker(agents: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for a in agents:
        out.setdefault(a.get("ticker", "?"), []).append(a)
    return out


def _opinion(rounds: dict, aid: int | str) -> dict | None:
    r1 = rounds.get("r1", {})
    r2 = rounds.get("r2", {})
    o1 = r1.get(str(aid)) or r1.get(aid)
    o2 = r2.get(str(aid)) or r2.get(aid)
    if o1 is None:
        return None
    return {"r1": o1, "r2": o2}


def _fundamentals(ticker: str, agents_for_co: list[dict], rounds: dict) -> dict:
    """Best fundamentals snapshot available in the artifact.

    The winning artifact carries analyst opinions, not raw financials; the
    dossier-driven signal is captured in each thesis. We surface the ticker,
    roles, and the recorded signal so the example is traceable to the JSON.
    """
    signal = None
    for a in agents_for_co:
        op = _opinion(rounds, a.get("agent_id"))
        if op:
            signal = _signal_from_thesis(op["r1"].get("thesis"))
            if signal is not None:
                break
    return {
        "ticker": ticker,
        "roles": [a.get("role") for a in agents_for_co],
        "dossier_signal": signal,
    }


def _deepdive_opposing(artifact: dict, limit: int) -> list[dict]:
    agents = artifact.get("agents", [])
    rounds = artifact.get("rounds", {})
    consensus = artifact.get("company_consensus", {})
    dd_tickers = (artifact.get("meta", {}).get("tier_meta", {})
                  .get("deepdive_tickers") or [])
    by_ticker = _agents_by_ticker(agents)
    out = []
    for ticker in dd_tickers:
        co_agents = by_ticker.get(ticker, [])
        bulls, bears = [], []
        for a in co_agents:
            op = _opinion(rounds, a.get("agent_id"))
            if not op:
                continue
            v = op["r1"].get("view")
            if v == "bullish":
                bulls.append((a, op["r1"]))
            elif v == "bearish":
                bears.append((a, op["r1"]))
        if not bulls or not bears:
            continue
        b_role, b_op = bulls[0]
        r_role, r_op = bears[0]
        final = consensus.get(ticker, {}).get("view")
        out.append({
            "company": ticker,
            "roles": [b_role.get("role"), r_role.get("role")],
            "fundamentals": _fundamentals(ticker, co_agents, rounds),
            "initial_view": {"bullish_role": b_role.get("role"),
                             "bullish_score": b_op.get("score"),
                             "bearish_role": r_role.get("role"),
                             "bearish_score": r_op.get("score")},
            "peer_evidence": (f"round-1 independent opinions diverged: "
                              f"{b_role.get('role')}=bullish, "
                              f"{r_role.get('role')}=bearish"),
            "final_view": final,
            "reason": (f"two roles on {ticker} disagreed initially; "
                       f"debate resolved to {final}"),
        })
        if len(out) >= limit:
            break
    return out


def _screen_example(artifact: dict, limit: int) -> list[dict]:
    agents = artifact.get("agents", [])
    rounds = artifact.get("rounds", {})
    consensus = artifact.get("company_consensus", {})
    out = []
    for a in agents:
        if a.get("tier") != "screen":
            continue
        op = _opinion(rounds, a.get("agent_id"))
        if not op:
            continue
        ticker = a.get("ticker")
        out.append({
            "company": ticker,
            "roles": [a.get("role")],
            "fundamentals": _fundamentals(ticker, [a], rounds),
            "initial_view": op["r1"].get("view"),
            "peer_evidence": "none (screen runs one round, no gossip)",
            "final_view": consensus.get(ticker, {}).get("view", op["r1"].get("view")),
            "reason": "single-round primary screen call; no round 2",
        })
        if len(out) >= limit:
            break
    return out


def _flip(artifact: dict, from_view: str | None, to_view: str, limit: int,
          name: str) -> list[dict]:
    agents = artifact.get("agents", [])
    rounds = artifact.get("rounds", {})
    consensus = artifact.get("company_consensus", {})
    out = []
    for a in agents:
        if a.get("tier") != "deepdive":
            continue
        op = _opinion(rounds, a.get("agent_id"))
        if not op or op["r2"] is None:
            continue
        v1, v2 = op["r1"].get("view"), op["r2"].get("view")
        if v2 != to_view:
            continue
        if from_view is not None and v1 != from_view:
            continue
        if from_view is None and v1 == to_view:  # "move toward" excludes same
            continue
        ticker = a.get("ticker")
        out.append({
            "company": ticker,
            "roles": [a.get("role")],
            "fundamentals": _fundamentals(ticker, [a], rounds),
            "initial_view": v1,
            "peer_evidence": (op["r2"].get("revision_reason") or
                              "peer notes in round 2"),
            "final_view": v2,
            "reason": (f"{a.get('role')} on {ticker}: {v1} -> {v2}; "
                       f"{op['r2'].get('revision_reason', 'revised after peer evidence')}"),
        })
        if len(out) >= limit:
            break
    return out


def _confidence_tie_break(artifact: dict, limit: int) -> list[dict]:
    consensus = artifact.get("company_consensus", {})
    rounds = artifact.get("rounds", {})
    agents = artifact.get("agents", [])
    dd_tickers = (artifact.get("meta", {}).get("tier_meta", {})
                  .get("deepdive_tickers") or [])
    by_ticker = _agents_by_ticker(agents)
    out = []
    for ticker in dd_tickers:
        cc = consensus.get(ticker, {})
        cc_agents = cc.get("agents", []) or []
        if len(cc_agents) < 2:
            continue
        # rebuild per-company final votes from rounds (r2 then r1) so a real
        # vote tie is visible; the consensus `agents` list holds only winners.
        counts: dict[str, int] = {}
        for a in by_ticker.get(ticker, []):
            op = _opinion(rounds, a.get("agent_id"))
            if not op:
                continue
            final = (op["r2"] or op["r1"]).get("view")
            if final:
                counts[final] = counts.get(final, 0) + 1
        if not counts:
            continue
        top = sorted(counts.values(), reverse=True)
        if len(top) < 2 or top[0] != top[1]:
            continue
        out.append({
            "company": ticker,
            "roles": [a.get("role") for a in by_ticker.get(ticker, [])],
            "fundamentals": _fundamentals(ticker, by_ticker.get(ticker, []), rounds),
            "initial_view": f"tied votes: {counts}",
            "peer_evidence": "tie-break rule applied (confidence then agent_id)",
            "final_view": cc.get("view"),
            "reason": (f"vote tie on {ticker} broken by confidence; "
                       f"winner agent_id={cc.get('winner_agent_id')}"),
        })
        if len(out) >= limit:
            break
    return out


def extract_examples(artifact: dict) -> dict[str, Any]:
    dd_tickers = (artifact.get("meta", {}).get("tier_meta", {})
                  .get("deepdive_tickers") or [])
    deepdive_opposing = _deepdive_opposing(artifact, REQUIRED["deepdive_opposing_roles"])
    screen = _screen_example(artifact, REQUIRED["screen_example"])
    bull_to_bear = _flip(artifact, "bullish", "bearish",
                         REQUIRED["bullish_to_bearish_flip"], "bull_to_bear")
    neut_to_bear = _flip(artifact, "neutral", "bearish",
                         REQUIRED["neutral_to_bearish_flip"], "neut_to_bear")
    move_to_bull = _flip(artifact, None, "bullish",
                         REQUIRED["move_toward_bullish"], "move_to_bull")
    tie_break = _confidence_tie_break(artifact, REQUIRED["confidence_tie_break"])

    found = {
        "deepdive_opposing_roles": deepdive_opposing,
        "screen_example": screen,
        "bullish_to_bearish_flip": bull_to_bear,
        "neutral_to_bearish_flip": neut_to_bear,
        "move_toward_bullish": move_to_bull,
        "confidence_tie_break": tie_break,
    }
    shortfalls = []
    for cat, req in REQUIRED.items():
        have = len(found[cat])
        if have < req:
            shortfalls.append(f"{cat}: have {have}, required {req}")
    return {
        "meta": {
            "variant": artifact.get("meta", {}).get("variant"),
            "deepdive_companies": len(dd_tickers),
            "agent_count": artifact.get("meta", {}).get("agent_count"),
        },
        "categories": {
            cat: {"required": REQUIRED[cat], "found": len(found[cat]),
                  "examples": found[cat]}
            for cat in REQUIRED
        },
        "shortfalls": shortfalls,
    }


def render(report: dict) -> str:
    lines = []
    lines.append(f"variant={report['meta'].get('variant')} "
                 f"deepdive_companies={report['meta'].get('deepdive_companies')} "
                 f"agents={report['meta'].get('agent_count')}")
    for cat, body in report["categories"].items():
        lines.append(f"\n## {cat} (required {body['required']}, found {body['found']})")
        for i, ex in enumerate(body["examples"], 1):
            lines.append(f"  {i}. company={ex.get('company')} roles={ex.get('roles')}")
            lines.append(f"     fundamentals: {ex.get('fundamentals')}")
            lines.append(f"     initial_view: {ex.get('initial_view')}")
            lines.append(f"     peer_evidence: {ex.get('peer_evidence')}")
            lines.append(f"     final_view: {ex.get('final_view')}")
            lines.append(f"     reason: {ex.get('reason')}")
        if body["found"] < body["required"]:
            lines.append(f"  SHORTFALL: only {body['found']} of {body['required']} "
                         f"available; printed best available, none fabricated.")
    if report["shortfalls"]:
        lines.append("\nSHORTFALLS: " + "; ".join(report["shortfalls"]))
    else:
        lines.append("\nAll gate-8 categories satisfied.")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Extract gate-8 example block from a variant artifact")
    p.add_argument("--artifact", required=True, help="path to winning variant JSON")
    p.add_argument("--output", required=True, help="path to write the example block JSON")
    args = p.parse_args(argv)
    artifact = json.loads(Path(args.artifact).read_text())
    report = extract_examples(artifact)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(report, indent=2))
    print(render(report))
    print(f"-> wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
