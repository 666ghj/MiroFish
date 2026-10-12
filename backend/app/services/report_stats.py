"""Simulation statistics shown alongside generated reports."""

import json
import os
import sqlite3
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Optional

from .simulation_runner import SimulationRunner

PLATFORMS = ("twitter", "reddit")
NOOP_ACTIONS = {"DO_NOTHING"}
TOP_AGENTS = 5
TOP_QUOTES = 3
QUOTE_MAX_CHARS = 600


def _read_json(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _sim_dir(simulation_id: str) -> str:
    return os.path.join(SimulationRunner.RUN_STATE_DIR, simulation_id)


def _base_stats(simulation_id: str) -> Optional[Dict[str, Any]]:
    sim_dir = _sim_dir(simulation_id)
    run = _read_json(os.path.join(sim_dir, "run_state.json"))
    config = _read_json(os.path.join(sim_dir, "simulation_config.json")) or {}
    state = _read_json(os.path.join(sim_dir, "state.json")) or {}
    if run is None and not config and not state:
        return None
    run = run or {}

    agents = config.get("agent_configs") or []
    platforms: List[Dict[str, Any]] = []
    for key in PLATFORMS:
        enabled = os.path.exists(os.path.join(sim_dir, key, "actions.jsonl")) or bool(
            state.get(f"enable_{key}")
        )
        if not enabled:
            continue
        platforms.append({
            "key": key,
            "actions": run.get(f"{key}_actions_count", 0),
            "rounds": run.get(f"{key}_current_round", 0),
        })

    minutes_per_round = (config.get("time_config") or {}).get("minutes_per_round")
    rounds = run.get("current_round", 0)
    return {
        "agents": len(agents) or state.get("profiles_count", 0),
        "platforms": platforms,
        "rounds": rounds,
        "total_rounds": run.get("total_rounds", 0),
        "total_actions": run.get("total_actions_count", 0),
        "simulated_hours": round(rounds * minutes_per_round / 60, 1) if minutes_per_round else None,
        "model": config.get("llm_model"),
        "_agents": agents,
    }


def get_summary(simulation_id: str) -> Optional[Dict[str, Any]]:
    """Cheap stats for report list cards (no action-log scan)."""
    stats = _base_stats(simulation_id)
    if stats is None:
        return None
    stats.pop("_agents")
    return stats


def _parse_ts(value: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def get_detail(simulation_id: str) -> Optional[Dict[str, Any]]:
    """Full stats: summary plus breakdowns read from the action logs."""
    stats = _base_stats(simulation_id)
    if stats is None:
        return None
    agents = stats.pop("_agents")
    names = {a.get("agent_id"): a.get("entity_name") for a in agents}
    types = {a.get("agent_id"): a.get("entity_type") for a in agents}

    stats["entity_types"] = [
        {"type": t, "count": n}
        for t, n in Counter(a.get("entity_type") or "Unknown" for a in agents).most_common()
    ]

    sim_dir = _sim_dir(simulation_id)
    per_agent: Counter = Counter()
    timestamps: List[datetime] = []
    per_round: Dict[int, Dict[str, int]] = {}
    post_round: Dict[str, Dict[Any, int]] = {}
    for platform in stats["platforms"]:
        post_round[platform["key"]] = {}
        path = os.path.join(sim_dir, platform["key"], "actions.jsonl")
        actions: Counter = Counter()
        active = set()
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                    except ValueError:
                        continue
                    ts = _parse_ts(entry.get("timestamp"))
                    if ts:
                        timestamps.append(ts)
                    if "event_type" in entry:
                        continue
                    action = entry.get("action_type") or "UNKNOWN"
                    actions[action] += 1
                    round_num = entry.get("round")
                    if isinstance(round_num, int):
                        row = per_round.setdefault(round_num, {})
                        row[platform["key"]] = row.get(platform["key"], 0) + 1
                        post_id = (entry.get("action_args") or {}).get("post_id")
                        if action == "CREATE_POST" and post_id is not None:
                            post_round[platform["key"]][post_id] = round_num
                    if action not in NOOP_ACTIONS:
                        active.add(entry.get("agent_id"))
                        per_agent[entry.get("agent_id")] += 1
        except OSError:
            pass
        platform["action_types"] = [
            {"type": t, "count": n} for t, n in actions.most_common()
        ]
        platform["active_agents"] = len(active)

    stats["top_agents"] = [
        {
            "agent_id": agent_id,
            "name": names.get(agent_id) or f"Agent {agent_id}",
            "type": types.get(agent_id),
            "actions": count,
        }
        for agent_id, count in per_agent.most_common(TOP_AGENTS)
    ]
    stats["timeline"] = [
        {"round": r, **{p["key"]: per_round.get(r, {}).get(p["key"], 0) for p in stats["platforms"]}}
        for r in range(1, max([stats["rounds"], *per_round]) + 1)
    ]
    stats["quotes"] = [
        q for p in stats["platforms"]
        for q in _top_quotes(sim_dir, p["key"], agents, post_round[p["key"]])
    ]
    stats["active_agents"] = len(per_agent)
    stats["duration_seconds"] = (
        round((max(timestamps) - min(timestamps)).total_seconds())
        if len(timestamps) > 1 else None
    )
    return stats


def _clip(text: Optional[str]) -> str:
    text = (text or "").strip()
    return text if len(text) <= QUOTE_MAX_CHARS else text[:QUOTE_MAX_CHARS].rstrip() + "…"


def _top_quotes(
    sim_dir: str, platform: str, agents: List[Dict[str, Any]], rounds: Dict[Any, int]
) -> List[Dict[str, Any]]:
    """Most-liked original posts and comments from a platform's SQLite DB."""
    db_path = os.path.join(sim_dir, f"{platform}_simulation.db")
    if not os.path.exists(db_path):
        return []
    names = {a.get("agent_id"): a.get("entity_name") for a in agents}
    types = {a.get("agent_id"): a.get("entity_type") for a in agents}

    quotes: List[Dict[str, Any]] = []
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            queries = (
                ("post", """
                    SELECT p.post_id AS id, u.agent_id, u.user_name, p.content,
                           p.num_likes AS likes, p.num_shares AS shares
                    FROM post p LEFT JOIN user u ON u.user_id = p.user_id
                    WHERE p.original_post_id IS NULL AND COALESCE(p.content, '') != ''
                    ORDER BY p.num_likes + p.num_shares DESC, p.post_id LIMIT ?
                """),
                ("comment", """
                    SELECT c.comment_id AS id, u.agent_id, u.user_name, c.content,
                           c.num_likes AS likes, 0 AS shares
                    FROM comment c LEFT JOIN user u ON u.user_id = c.user_id
                    WHERE COALESCE(c.content, '') != ''
                    ORDER BY c.num_likes DESC, c.comment_id LIMIT ?
                """),
            )
            for kind, sql in queries:
                for row in conn.execute(sql, (TOP_QUOTES,)):
                    if not row["likes"] and not row["shares"]:
                        continue
                    agent_id = row["agent_id"]
                    quotes.append({
                        "platform": platform,
                        "kind": kind,
                        "author": names.get(agent_id) or row["user_name"],
                        "author_type": types.get(agent_id),
                        "content": _clip(row["content"]),
                        "likes": row["likes"],
                        "shares": row["shares"],
                        "round": rounds.get(row["id"]) if kind == "post" else None,
                    })
        finally:
            conn.close()
    except sqlite3.Error:
        return []
    return quotes
