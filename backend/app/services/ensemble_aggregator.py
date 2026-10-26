"""
Aggregation of an ensemble's replicates into distributions.

Pure functions over replicate directories: no LLM calls, no network. Each
replicate contributes

* a *poll result* (``final_poll.json``): every agent's answers to the outcome
  questions, reduced to one number or share per question, and
* *behavioural metrics* from its action logs and platform databases.

Across replicates every scalar becomes a distribution (mean, std, min, p10,
median, p90, max). Conventions worth knowing:

* ``std`` is the sample standard deviation (n-1), 0.0 for a single value.
* Percentiles use linear interpolation between order statistics.
* An agent whose poll reply did not parse (``parse_ok`` false) is excluded from
  every statistic but counted in the parse rate.
* A hot topic is mentioned by a post or comment that contains the phrase, or (for a phrase of
  several words) all of its words: generated topics are phrases like "injectable formulations
  approval" that people rarely repeat word for word.
* Behavioural metrics skip bookkeeping records: the seeded follow graph
  (``phase: setup``), scheduled-event posts (``phase: injected``) and poll
  records (``phase: poll``). Legacy logs that recorded each initial post twice
  are de-duplicated.
* Everything here describes *simulated participants' views*, not real-world
  probabilities. ``summary.md`` always says so (``CAVEAT``).
"""

import json
import math
import os
import re
import sqlite3
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ..utils.atomic_write import write_json_atomic, write_text_atomic

#: Skipped when counting agent behaviour.
EXCLUDED_PHASES = frozenset({"setup", "injected", "poll"})

CAVEAT_TEMPLATE = (
    "These are distributions of *simulated participants' views* across {n} stochastic runs, "
    "not calibrated probabilities of the real-world event. MiroFish has not been backtested "
    "for this domain."
)

STANCES = ("supportive", "opposing", "neutral", "observer")
DRIFT_STANCES = ("supportive", "opposing", "neutral")  # observers have no stated view to drift from

#: Used only when a stance question carries no explicit ``stance_map``.
STANCE_SYNONYMS = {
    "supportive": {"supportive", "support", "supports", "bullish", "positive", "favorable",
                   "favourable", "for", "pro", "yes", "agree", "optimistic"},
    "opposing": {"opposing", "oppose", "opposes", "bearish", "negative", "unfavorable",
                 "unfavourable", "against", "anti", "no", "disagree", "pessimistic"},
    "neutral": {"neutral", "mixed", "undecided", "unsure", "uncertain", "hold", "wait"},
}

POST_ACTIONS = ("CREATE_POST", "QUOTE_POST")
COMMENT_ACTIONS = ("CREATE_COMMENT",)
LIKE_ACTIONS = ("LIKE_POST", "LIKE_COMMENT")
DISLIKE_ACTIONS = ("DISLIKE_POST", "DISLIKE_COMMENT")
REPOST_ACTIONS = ("REPOST",)

PLATFORMS = ("twitter", "reddit")


def caveat(n: int) -> str:
    return CAVEAT_TEMPLATE.format(n=n)


# --- statistics ----------------------------------------------------------------

def percentile(sorted_values: Sequence[float], fraction: float) -> float:
    """Linear-interpolation percentile of an ascending list (``fraction`` in [0, 1])."""
    if not sorted_values:
        raise ValueError("percentile of an empty sequence")
    position = (len(sorted_values) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(sorted_values[lower])
    weight = position - lower
    return float(sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight)


def describe(values: Iterable[Optional[float]]) -> Dict[str, Any]:
    """``n, mean, std, min, p10, median, p90, max`` of the non-None values.

    Every statistic is None when there are no values.
    """
    data = sorted(float(v) for v in values if v is not None and not math.isnan(float(v)))
    if not data:
        return {"n": 0, "mean": None, "std": None, "min": None, "p10": None,
                "median": None, "p90": None, "max": None}
    n = len(data)
    mean = sum(data) / n
    std = math.sqrt(sum((v - mean) ** 2 for v in data) / (n - 1)) if n > 1 else 0.0
    return {
        "n": n, "mean": mean, "std": std, "min": data[0],
        "p10": percentile(data, 0.10), "median": percentile(data, 0.50),
        "p90": percentile(data, 0.90), "max": data[-1],
    }


def _mean(values: Sequence[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def _median(values: Sequence[float]) -> Optional[float]:
    return percentile(sorted(values), 0.5) if values else None


# --- reading replicate directories -----------------------------------------------

def _read_json(path: str, default: Any = None) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return default


def read_action_records(sim_dir: str, platform: str) -> List[Dict[str, Any]]:
    """Every agent-action record in a platform's ``actions.jsonl`` (events and blanks skipped)."""
    path = os.path.join(sim_dir, platform, "actions.jsonl")
    records: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict) and "event_type" not in record and "agent_id" in record:
                    records.append(record)
    except OSError:
        pass
    return records


def _drop_replayed_initial_posts(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove the second logging of initial posts that legacy runs produced.

    Legacy logs wrote each initial post at round 0 and then again, from the
    database, in the first round with activity. Each round-0 post is matched to
    at most one later identical post by the same agent.
    """
    pending: Dict[Tuple[Any, Any], int] = {}
    for record in records:
        if record.get("round") == 0 and record.get("action_type") == "CREATE_POST":
            key = (record.get("agent_id"), (record.get("action_args") or {}).get("content"))
            pending[key] = pending.get(key, 0) + 1

    kept = []
    for record in records:
        if record.get("round", 0) >= 1 and record.get("action_type") == "CREATE_POST":
            key = (record.get("agent_id"), (record.get("action_args") or {}).get("content"))
            if pending.get(key):
                pending[key] -= 1
                continue
        kept.append(record)
    return kept


def _behavior_records(sim_dir: str, platform: str) -> List[Dict[str, Any]]:
    records = [r for r in read_action_records(sim_dir, platform) if r.get("phase") not in EXCLUDED_PHASES]
    return _drop_replayed_initial_posts(records)


def _injected_contents(sim_dir: str) -> set:
    contents = set()
    for platform in PLATFORMS:
        for record in read_action_records(sim_dir, platform):
            if record.get("phase") == "injected":
                contents.add((record.get("action_args") or {}).get("content"))
    return contents


# --- stance helpers ----------------------------------------------------------------

def stance_mapping(question: Mapping[str, Any]) -> Optional[Dict[str, str]]:
    """option -> stance for a choice question, or None when it is not a stance question."""
    if question.get("type") != "choice":
        return None
    explicit = question.get("stance_map")
    if explicit:
        return dict(explicit)
    mapping: Dict[str, str] = {}
    for option in question.get("options", []):
        lowered = str(option).strip().lower()
        for stance, words in STANCE_SYNONYMS.items():
            if lowered in words:
                mapping[option] = stance
                break
        else:
            return None  # an unmappable option: do not guess
    return mapping or None


def find_stance_question(questions: Sequence[Mapping[str, Any]]) -> Optional[Tuple[Mapping[str, Any], Dict[str, str]]]:
    for question in questions:
        mapping = stance_mapping(question)
        if mapping:
            return question, mapping
    return None


# --- one replicate: the poll ---------------------------------------------------------

def poll_metrics(
    rows: Sequence[Mapping[str, Any]],
    questions: Sequence[Mapping[str, Any]],
    influence: Mapping[int, float],
) -> Dict[str, Any]:
    """Reduce one replicate's ``final_poll.json`` rows to one value per question."""
    total = len(rows)
    ok_rows = [r for r in rows if r.get("parse_ok")]
    result: Dict[str, Any] = {
        "agents_total": total,
        "agents_ok": len(ok_rows),
        "parse_rate": (len(ok_rows) / total) if total else None,
        "questions": {},
    }

    for question in questions:
        qid = question["id"]
        qtype = question["type"]
        answered = [(r, r["answers"][qid]) for r in ok_rows if qid in (r.get("answers") or {})]
        values = [value for _, value in answered]

        if qtype == "probability":
            weights = [float(influence.get(int(r["agent_id"]), 1.0)) for r, _ in answered]
            weight_sum = sum(weights)
            result["questions"][qid] = {
                "type": qtype,
                "n": len(values),
                "mean": _mean(values),
                "median": _median(values),
                "influence_weighted_mean": (
                    sum(v * w for v, w in zip(values, weights)) / weight_sum if weight_sum > 0 else None
                ),
            }
        elif qtype == "choice":
            counts = {option: 0 for option in question["options"]}
            for value in values:
                if value in counts:
                    counts[value] += 1
            n = len(values)
            result["questions"][qid] = {
                "type": qtype,
                "n": n,
                "counts": counts,
                "shares": {option: (count / n if n else None) for option, count in counts.items()},
            }
        else:
            result["questions"][qid] = {
                "type": qtype,
                "unit": question.get("unit"),
                "n": len(values),
                "median": _median(values),
                "mean": _mean(values),
            }

    stance_question = find_stance_question(questions)
    drift: Dict[str, Any] = {"applicable": False}
    if stance_question:
        question, mapping = stance_question
        qid = question["id"]
        considered = switched = 0
        matrix: Dict[str, Dict[str, int]] = {}
        for row in ok_rows:
            initial = row.get("stance_initial")
            answer = (row.get("answers") or {}).get(qid)
            if initial not in DRIFT_STANCES or answer not in mapping:
                continue
            final = mapping[answer]
            considered += 1
            matrix.setdefault(initial, {}).setdefault(final, 0)
            matrix[initial][final] += 1
            if final != initial:
                switched += 1
        drift = {
            "applicable": True,
            "question": qid,
            "agents_considered": considered,
            "switched": switched,
            "switched_share": (switched / considered) if considered else None,
            "matrix": matrix,
        }
    result["stance_drift"] = drift
    return result


# --- one replicate: behaviour ---------------------------------------------------------

def _engagement_from_db(
    db_path: str, skip_contents: set
) -> Dict[int, int]:
    """Likes + shares + comments received per author, over their own (non-scripted) posts."""
    engagement: Dict[int, int] = {}
    if not os.path.exists(db_path):
        return engagement
    try:
        connection = sqlite3.connect(db_path)
        try:
            comments = dict(connection.execute(
                "SELECT post_id, COUNT(*) FROM comment GROUP BY post_id"
            ).fetchall())
            for post_id, user_id, content, likes, shares in connection.execute(
                "SELECT post_id, user_id, content, num_likes, num_shares FROM post "
                "WHERE original_post_id IS NULL"
            ):
                if content in skip_contents:
                    continue
                score = int(likes or 0) + int(shares or 0) + int(comments.get(post_id, 0))
                engagement[int(user_id)] = engagement.get(int(user_id), 0) + score
        finally:
            connection.close()
    except sqlite3.Error:
        return {}
    return engagement


_TOPIC_WORD = re.compile(r"\w+(?:[-']\w+)*", re.UNICODE)


def topic_matcher(topic: str) -> Callable[[str], bool]:
    """A predicate telling whether a lower-cased text mentions ``topic``.

    It matches the whole phrase, or, for a phrase of several words, every word of it
    (words shorter than three characters are ignored unless they contain a digit).
    A single word or an unspaced phrase (Chinese, say) matches as a plain substring.
    """
    phrase = topic.lower().strip()
    words = [w for w in _TOPIC_WORD.findall(phrase) if len(w) >= 3 or any(ch.isdigit() for ch in w)]

    def mentions(text: str) -> bool:
        if phrase in text:
            return True
        return len(words) >= 2 and all(word in text for word in words)

    return mentions


def behavior_metrics(sim_dir: str, config: Mapping[str, Any], rounds: Optional[int] = None) -> Dict[str, Any]:
    """Counts, per-round series, stance-group shares, engagement and keyword mentions."""
    agents = {
        int(a["agent_id"]): a for a in config.get("agent_configs", []) if a.get("agent_id") is not None
    }
    stance_of = {agent_id: (a.get("stance") or "neutral") for agent_id, a in agents.items()}
    name_of = {agent_id: a.get("entity_name", f"Agent_{agent_id}") for agent_id, a in agents.items()}

    records: List[Dict[str, Any]] = []
    for platform in PLATFORMS:
        records.extend(_behavior_records(sim_dir, platform))

    max_round = max((int(r.get("round", 0)) for r in records), default=0)
    total_rounds = max(int(rounds or 0), max_round)
    per_round = [0] * total_rounds

    totals = {"total_actions": 0, "active_actions": 0, "posts": 0, "comments": 0,
              "likes": 0, "dislikes": 0, "reposts": 0, "follows": 0}
    posts_by_group = {stance: 0 for stance in STANCES}

    hot_topics = [str(t) for t in ((config.get("event_config") or {}).get("hot_topics") or []) if str(t).strip()]
    mentions = {topic: [0] * total_rounds for topic in hot_topics}
    matchers = {topic: topic_matcher(topic) for topic in hot_topics}

    for record in records:
        action = record.get("action_type")
        round_num = int(record.get("round", 0))
        totals["total_actions"] += 1
        if action != "DO_NOTHING":
            totals["active_actions"] += 1
        if round_num >= 1:
            per_round[round_num - 1] += 1

        if action in POST_ACTIONS:
            totals["posts"] += 1
            group = stance_of.get(record.get("agent_id"), "neutral")
            posts_by_group[group] = posts_by_group.get(group, 0) + 1
        elif action in COMMENT_ACTIONS:
            totals["comments"] += 1
        elif action in LIKE_ACTIONS:
            totals["likes"] += 1
        elif action in DISLIKE_ACTIONS:
            totals["dislikes"] += 1
        elif action in REPOST_ACTIONS:
            totals["reposts"] += 1
        elif action == "FOLLOW":
            totals["follows"] += 1

        if hot_topics and action in POST_ACTIONS + COMMENT_ACTIONS and round_num >= 1:
            args = record.get("action_args") or {}
            text = " ".join(str(args.get(k) or "") for k in ("content", "quote_content")).lower()
            for topic in hot_topics:
                if matchers[topic](text):
                    mentions[topic][round_num - 1] += 1

    total_posts = totals["posts"]
    skip = _injected_contents(sim_dir)
    engagement: Dict[int, int] = {}
    for platform in PLATFORMS:
        platform_engagement = _engagement_from_db(os.path.join(sim_dir, f"{platform}_simulation.db"), skip)
        for agent_id, score in platform_engagement.items():
            engagement[agent_id] = engagement.get(agent_id, 0) + score

    total_engagement = sum(engagement.values())
    engagement_by_group = {stance: 0 for stance in STANCES}
    for agent_id, score in engagement.items():
        group = stance_of.get(agent_id, "neutral")
        engagement_by_group[group] = engagement_by_group.get(group, 0) + score

    ranked = sorted(
        ((agent_id, score) for agent_id, score in engagement.items() if score > 0),
        key=lambda pair: (-pair[1], pair[0]),
    )[:3]

    return {
        **totals,
        "actions_per_round": per_round,
        "stance_group_post_share": {
            stance: (count / total_posts if total_posts else None) for stance, count in posts_by_group.items()
        },
        "stance_group_engagement_share": {
            stance: (count / total_engagement if total_engagement else None)
            for stance, count in engagement_by_group.items()
        },
        "engagement_total": total_engagement,
        "top_agents": [
            {"agent_id": agent_id, "agent_name": name_of.get(agent_id, f"Agent_{agent_id}"), "engagement": score}
            for agent_id, score in ranked
        ],
        "hot_topic_mentions": {
            topic: {"total": sum(series), "by_round": series} for topic, series in mentions.items()
        },
    }


# --- replicates -----------------------------------------------------------------------

def replicate_metrics(
    replicate: Mapping[str, Any],
    questions: Sequence[Mapping[str, Any]],
    simulations_dir: str,
) -> Dict[str, Any]:
    """All metrics for one finished replicate (``status`` ``ok`` or ``missing``)."""
    sim_dir = os.path.join(simulations_dir, replicate["simulation_id"])
    config = _read_json(os.path.join(sim_dir, "simulation_config.json"))
    entry: Dict[str, Any] = {
        "index": replicate.get("index"),
        "simulation_id": replicate["simulation_id"],
        "seed": replicate.get("seed"),
    }
    if config is None:
        return {**entry, "status": "missing", "error": "simulation_config.json not found"}

    influence = {
        int(a["agent_id"]): float(a.get("influence_weight", 1.0) or 0.0)
        for a in config.get("agent_configs", []) if a.get("agent_id") is not None
    }
    rounds = (config.get("run") or {}).get("max_rounds")

    poll_rows = _read_json(os.path.join(sim_dir, "final_poll.json"))
    entry["poll"] = (
        poll_metrics(poll_rows, questions, influence) if isinstance(poll_rows, list) and questions else None
    )
    entry["behavior"] = behavior_metrics(sim_dir, config, rounds)
    entry["status"] = "ok"
    return entry


# --- across replicates ------------------------------------------------------------------

def summarize(
    ensemble: Mapping[str, Any],
    questions: Sequence[Mapping[str, Any]],
    metrics: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Combine per-replicate metrics into the ensemble summary (``summary.json``)."""
    ok = [m for m in metrics if m.get("status") == "ok"]
    polled = [m for m in ok if m.get("poll")]

    polls: Dict[str, Any] = {}
    for question in questions:
        qid = question["id"]
        qtype = question["type"]
        per_run = [m["poll"]["questions"].get(qid) for m in polled]
        per_run = [p for p in per_run if p and p.get("n")]
        entry: Dict[str, Any] = {"type": qtype, "text": question["text"], "replicates_with_data": len(per_run)}
        if qtype == "probability":
            means = [p["mean"] for p in per_run]
            entry.update(
                agent_mean=describe(means),
                agent_median=describe([p["median"] for p in per_run]),
                influence_weighted_mean=describe([p["influence_weighted_mean"] for p in per_run]),
                share_of_replicates_mean_above_50=(
                    sum(1 for v in means if v > 50) / len(means) if means else None
                ),
            )
        elif qtype == "choice":
            entry["options"] = {}
            modal: Dict[str, int] = {option: 0 for option in question["options"]}
            for option in question["options"]:
                entry["options"][option] = describe([p["shares"][option] for p in per_run])
            for p in per_run:
                best = max(question["options"], key=lambda o: (p["counts"][o], -question["options"].index(o)))
                if p["counts"][best] > 0:
                    modal[best] += 1
            entry["most_common_in_replicates"] = modal
        else:
            entry["unit"] = question.get("unit")
            entry["median"] = describe([p["median"] for p in per_run])
            entry["mean"] = describe([p["mean"] for p in per_run])
        polls[qid] = entry

    drift_runs = [m["poll"]["stance_drift"] for m in polled if m["poll"]["stance_drift"].get("applicable")]
    stance_drift: Dict[str, Any] = {"applicable": bool(drift_runs)}
    if drift_runs:
        stance_drift.update(
            question=drift_runs[0]["question"],
            switched_agents=describe([d["switched"] for d in drift_runs]),
            switched_share=describe([d["switched_share"] for d in drift_runs]),
        )

    behaviors = [m["behavior"] for m in ok]
    scalar_keys = ("total_actions", "active_actions", "posts", "comments", "likes",
                   "dislikes", "reposts", "follows", "engagement_total")
    behavior: Dict[str, Any] = {key: describe([b.get(key) for b in behaviors]) for key in scalar_keys}
    behavior["stance_group_post_share"] = {
        stance: describe([b["stance_group_post_share"].get(stance) for b in behaviors]) for stance in STANCES
    }
    behavior["stance_group_engagement_share"] = {
        stance: describe([b["stance_group_engagement_share"].get(stance) for b in behaviors]) for stance in STANCES
    }

    series = [b["actions_per_round"] for b in behaviors if b.get("actions_per_round")]
    length = max((len(s) for s in series), default=0)
    behavior["actions_per_round_mean"] = [
        _mean([s[i] if i < len(s) else 0 for s in series]) for i in range(length)
    ]

    top_counts: Dict[int, Dict[str, Any]] = {}
    for b in behaviors:
        for top in b.get("top_agents", []):
            slot = top_counts.setdefault(top["agent_id"], {"agent_name": top["agent_name"], "replicates": 0})
            slot["replicates"] += 1
    behavior["top_agents"] = [
        {"agent_id": agent_id, "agent_name": slot["agent_name"], "replicates": slot["replicates"],
         "share_of_replicates": slot["replicates"] / len(behaviors) if behaviors else None}
        for agent_id, slot in sorted(top_counts.items(), key=lambda kv: (-kv[1]["replicates"], kv[0]))
    ][:5]

    topics = sorted({t for b in behaviors for t in b.get("hot_topic_mentions", {})})
    hot_topics = {
        topic: describe([b.get("hot_topic_mentions", {}).get(topic, {}).get("total") for b in behaviors])
        for topic in topics
    }

    n_ok = len(ok)
    return {
        "ensemble_id": ensemble.get("ensemble_id"),
        "base_simulation_id": ensemble.get("base_simulation_id"),
        "generated_at": datetime.now().isoformat(),
        "caveat": caveat(n_ok),
        "n_replicates_requested": ensemble.get("n_replicates", len(metrics)),
        "n_replicates_ok": n_ok,
        "n_replicates_with_poll": len(polled),
        "max_rounds": ensemble.get("max_rounds"),
        "base_seed": ensemble.get("base_seed"),
        "questions": list(questions),
        "polls": polls,
        "parse_rate": describe([m["poll"]["parse_rate"] for m in polled]),
        "stance_drift": stance_drift,
        "behavior": behavior,
        "hot_topics": hot_topics,
        "replicates": [
            {
                "index": m.get("index"), "simulation_id": m.get("simulation_id"), "seed": m.get("seed"),
                "status": m.get("status"),
                "parse_rate": (m.get("poll") or {}).get("parse_rate"),
                "poll": {
                    qid: {k: v for k, v in data.items() if k in ("mean", "median", "shares", "n")}
                    for qid, data in ((m.get("poll") or {}).get("questions") or {}).items()
                },
                "total_actions": (m.get("behavior") or {}).get("total_actions"),
                "error": m.get("error"),
            }
            for m in metrics
        ],
    }


# --- rendering ----------------------------------------------------------------------------

def _fmt(value: Optional[float], digits: int = 2) -> str:
    if value is None:
        return "–"
    if abs(value - round(value)) < 1e-9 and abs(value) >= 1:
        return str(int(round(value)))
    return f"{value:.{digits}f}"


def _pct(value: Optional[float]) -> str:
    return "–" if value is None else f"{value * 100:.0f}%"


def _stat_row(label: str, stats: Mapping[str, Any], percent: bool = False) -> str:
    fmt = _pct if percent else _fmt
    cells = [fmt(stats.get(key)) for key in ("mean", "std", "min", "p10", "median", "p90", "max")]
    return f"| {label} | " + " | ".join(cells) + f" | {stats.get('n', 0)} |"


STAT_HEADER = "| | mean | std | min | p10 | median | p90 | max | n |\n|---|---|---|---|---|---|---|---|---|"


def render_markdown(summary: Mapping[str, Any]) -> str:
    """The human-readable ``summary.md`` (it opens with the caveat)."""
    lines: List[str] = [
        f"# Ensemble summary: {summary.get('ensemble_id')}",
        "",
        f"> {summary['caveat']}",
        "",
        f"- Base simulation: `{summary.get('base_simulation_id')}`",
        f"- Replicates: {summary['n_replicates_ok']} completed of {summary['n_replicates_requested']} requested"
        f" ({summary['n_replicates_with_poll']} with a final poll)",
        f"- Rounds per run: {summary.get('max_rounds')} · base seed: {summary.get('base_seed')}",
        "",
    ]

    if summary["polls"]:
        lines += ["## Outcome questions", ""]
    for qid, poll in summary["polls"].items():
        lines += [f"### {qid}: {poll['text']}", ""]
        if poll["replicates_with_data"] == 0:
            lines += ["_No replicate produced a usable answer._", ""]
            continue
        if poll["type"] == "probability":
            lines += [
                "Distribution across runs (each run contributes one value):", "", STAT_HEADER,
                _stat_row("agents' mean", poll["agent_mean"]),
                _stat_row("agents' median", poll["agent_median"]),
                _stat_row("influence-weighted mean", poll["influence_weighted_mean"]),
                "",
                f"Share of runs where the agents' mean is above 50: {_pct(poll['share_of_replicates_mean_above_50'])}",
                "",
            ]
        elif poll["type"] == "choice":
            lines += ["Share of agents choosing each option, across runs:", "", STAT_HEADER]
            for option, stats in poll["options"].items():
                lines.append(_stat_row(option, stats, percent=True))
            lines += ["", "Runs in which each option was the most common answer: "
                      + ", ".join(f"{o}: {n}" for o, n in poll["most_common_in_replicates"].items()), ""]
        else:
            unit = f" ({poll['unit']})" if poll.get("unit") else ""
            lines += [f"Median answer{unit} across runs:", "", STAT_HEADER, _stat_row("median", poll["median"]), ""]

    parse = summary["parse_rate"]
    if parse["n"]:
        lines += [f"Poll parse rate: mean {_pct(parse['mean'])}, worst run {_pct(parse['min'])}.", ""]

    drift = summary["stance_drift"]
    if drift["applicable"]:
        lines += [
            "## Stance drift", "",
            f"Agents whose answer to {drift['question']} differs from the stance they started with:", "",
            STAT_HEADER, _stat_row("switched agents", drift["switched_agents"]),
            _stat_row("share of agents", drift["switched_share"], percent=True), "",
        ]

    behavior = summary["behavior"]
    lines += ["## Behaviour", "", STAT_HEADER]
    for key in ("total_actions", "active_actions", "posts", "comments", "likes", "reposts", "follows"):
        lines.append(_stat_row(key.replace("_", " "), behavior[key]))
    lines.append("")
    lines += ["Share of posts by starting stance:", "", STAT_HEADER]
    for stance in STANCES:
        lines.append(_stat_row(stance, behavior["stance_group_post_share"][stance], percent=True))
    lines.append("")
    if behavior["top_agents"]:
        lines += ["Agents most often among the top 3 by engagement received:", ""]
        for top in behavior["top_agents"]:
            lines.append(f"- {top['agent_name']} (agent {top['agent_id']}): {top['replicates']} of {summary['n_replicates_ok']} runs")
        lines.append("")

    if summary["hot_topics"]:
        lines += ["## Hot-topic mentions", "", STAT_HEADER]
        for topic, stats in summary["hot_topics"].items():
            lines.append(_stat_row(topic, stats))
        lines.append("")

    lines += ["## Replicates", "", "| # | simulation | seed | status | poll parsed | actions |", "|---|---|---|---|---|---|"]
    for rep in summary["replicates"]:
        lines.append(
            f"| {rep['index']} | `{rep['simulation_id']}` | {rep['seed']} | {rep['status']} | "
            f"{_pct(rep['parse_rate'])} | {rep['total_actions'] if rep['total_actions'] is not None else '–'} |"
        )
    lines.append("")
    return "\n".join(lines)


# --- reading the summary (report agent tool) ------------------------------------------------------

#: Top-level summary sections the ``ensemble_stats`` tool can return (besides the question ids).
SUMMARY_SECTIONS = ("overview", "polls", "stance_drift", "behavior", "hot_topics", "parse_rate",
                    "replicates", "questions")


def _round_floats(value: Any, digits: int = 3) -> Any:
    """Round every float in a nested structure, to keep tool results compact."""
    if isinstance(value, float):
        return round(value, digits)
    if isinstance(value, dict):
        return {k: _round_floats(v, digits) for k, v in value.items()}
    if isinstance(value, list):
        return [_round_floats(v, digits) for v in value]
    return value


def select_summary_section(summary: Mapping[str, Any], key: Optional[str] = "overview") -> Dict[str, Any]:
    """One section of ``summary.json`` by name, for the report agent's ``ensemble_stats`` tool.

    ``key`` is ``overview`` (run counts, parse rate and the caveat), one of the
    top-level sections (``polls``, ``stance_drift``, ``behavior``, ``hot_topics``,
    ``parse_rate``, ``replicates``, ``questions``) or a question id such as
    ``q1``. An unknown key returns an ``error`` listing what is available.
    Floats are rounded to three decimals.
    """
    polls = summary.get("polls") or {}
    available = list(SUMMARY_SECTIONS) + list(polls)
    name = (str(key).strip() if key is not None else "") or "overview"
    lowered = name.lower()

    if lowered == "overview":
        selected: Dict[str, Any] = {
            field: summary.get(field)
            for field in ("ensemble_id", "base_simulation_id", "caveat", "n_replicates_requested",
                          "n_replicates_ok", "n_replicates_with_poll", "max_rounds", "base_seed", "parse_rate")
        }
        selected["available_sections"] = available
    elif lowered in {s for s in SUMMARY_SECTIONS if s != "overview"}:
        selected = {lowered: summary.get(lowered)}
    else:
        match = next((qid for qid in polls if qid.lower() == lowered), None)
        if match is None:
            selected = {"error": f"unknown section '{name}'", "available_sections": available}
        else:
            selected = {"question": match, **polls[match]}
    return _round_floats(selected)


# --- entry points -----------------------------------------------------------------------------

def build_summary(
    ensemble: Mapping[str, Any],
    questions: Sequence[Mapping[str, Any]],
    simulations_dir: str,
) -> Dict[str, Any]:
    """Aggregate the ensemble's completed replicates (reads files, writes nothing)."""
    finished = [r for r in ensemble.get("replicates", []) if r.get("status") == "completed"]
    metrics = [replicate_metrics(r, questions, simulations_dir) for r in finished]
    return summarize(ensemble, questions, metrics)


def write_summary(ensemble_dir: str, summary: Mapping[str, Any]) -> None:
    """Write ``summary.json`` and ``summary.md`` into the ensemble directory."""
    write_json_atomic(os.path.join(ensemble_dir, "summary.json"), summary)
    write_text_atomic(os.path.join(ensemble_dir, "summary.md"), render_markdown(summary))
