"""The four verification scenarios of PLAN-behavior-wiring-and-ensembles.md (section 4) as automated tests.

They run on a synthetic scenario shaped like a real prepared simulation (a config without
``behavior_version``, CSV and JSON profiles). They never read ``backend/uploads``: that folder is
untracked user data and does not exist on a fresh checkout.

Anything that needs real processes (the seeded follows landing in the databases and tagged ``setup`` in the
logs, a scheduled event firing inside a running simulation, a replicate's final poll, the same seed twice
giving the same ``active_agent_ids`` in a real run's ``round_start`` records) was checked by hand with the real
run scripts against a fake LLM. The tests here pin the logic those runs rely on.
"""

import csv
import io
import json

import pytest

import sim_behavior as sb
from action_logger import PlatformActionLogger
from sim_behavior import PlatformBehavior, is_behavior_v2, write_effective_profiles

from app.services.ensemble_runner import EnsembleManager

# Fixtures and helpers of the ensemble tests (``env`` is a fixture).
from test_ensemble_manager import BASE_ID, create, drive, env, rid  # noqa: F401

TOPIC = "HEGAM demerger"
NARRATIVE = "ZZ-NARRATIVE: the stock will collapse"

# id, name, entity type, stance, influence, activity, posts/h, comments/h, active hours, delay min/max (minutes), sentiment
AGENTS = [
    (0, "HEG Graphite Limited", "Organization", "supportive", 2.8, 0.2, 0.5, 0.2, range(9, 18), 120, 480, 0.2),
    (1, "Retail Trader", "Person", "supportive", 1.0, 0.8, 1.0, 2.0, range(8, 23), 5, 60, 0.4),
    (2, "Value Fund Manager", "Person", "neutral", 2.0, 0.5, 0.3, 0.5, range(9, 19), 30, 180, 0.0),
    (3, "Short Seller", "Person", "opposing", 1.5, 0.6, 0.6, 1.0, range(8, 23), 5, 90, -0.6),
    (4, "Proxy Advisor", "Organization", "neutral", 1.2, 0.3, 0.2, 0.4, range(9, 18), 60, 240, 0.0),
    (5, "Financial Media", "MediaOutlet", "observer", 3.0, 0.7, 1.5, 0.3, range(6, 24), 10, 45, 0.0),
]


def legacy_config():
    """A prepared simulation as the generator produced it before behavior v2 (no ``behavior_version``)."""
    platform = {"recency_weight": 0.4, "popularity_weight": 0.3, "relevance_weight": 0.3,
                "viral_threshold": 10, "echo_chamber_strength": 0.5}
    return {
        "simulation_id": "sim_reference",
        "simulation_requirement": "How do market participants react to the demerger?",
        "time_config": {
            "total_simulation_hours": 120, "minutes_per_round": 60,
            "agents_per_hour_min": 1, "agents_per_hour_max": 3,
            "peak_hours": [9, 10, 11, 14, 15, 16, 20, 21, 22], "peak_activity_multiplier": 1.5,
            "off_peak_hours": [1, 2, 3, 4, 5], "off_peak_activity_multiplier": 0.05,
            "morning_hours": [6, 7, 8], "morning_activity_multiplier": 0.4,
            "work_hours": list(range(9, 19)), "work_activity_multiplier": 0.7,
        },
        "agent_configs": [
            {"agent_id": agent_id, "entity_name": name, "entity_type": kind, "stance": stance,
             "influence_weight": influence, "activity_level": activity, "posts_per_hour": posts,
             "comments_per_hour": comments, "active_hours": list(hours), "response_delay_min": delay_min,
             "response_delay_max": delay_max, "sentiment_bias": sentiment}
            for agent_id, name, kind, stance, influence, activity, posts, comments, hours,
            delay_min, delay_max, sentiment in AGENTS
        ],
        "event_config": {
            "initial_posts": [{"poster_agent_id": 0, "content": "The demerger is complete."}],
            "scheduled_events": [],
            "hot_topics": ["demerger", "listing"],
            "narrative_direction": NARRATIVE,
        },
        "twitter_config": {"platform": "twitter", **platform},
        "reddit_config": {"platform": "reddit", **platform},
    }


def twitter_csv():
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["user_id", "name", "username", "user_char", "description"])
    for agent_id, name, *_ in AGENTS:
        writer.writerow([agent_id, name, f"user_{agent_id}", f"{name} is a market participant.", f"bio {agent_id}"])
    return out.getvalue()


def reddit_json():
    return json.dumps(
        [{"user_id": agent_id, "username": f"user_{agent_id}", "name": name, "bio": f"bio {agent_id}",
          "persona": f"{name} is a market participant."} for agent_id, name, *_ in AGENTS],
        ensure_ascii=False,
    )


def write_profiles(directory):
    (directory / "twitter_profiles.csv").write_text(twitter_csv(), encoding="utf-8")
    (directory / "reddit_profiles.json").write_text(reddit_json(), encoding="utf-8")


def event(event_id, at_sim_hour, enabled=True):
    return {"id": event_id, "at_sim_hour": at_sim_hour, "poster_agent_id": 1,
            "content": f"Scheduled news {event_id}", "enabled": enabled}


# --- Scenario 1: a simulation prepared before this change keeps the legacy behavior -------------------

def test_scenario_1_a_legacy_simulation_keeps_the_legacy_behavior():
    config = legacy_config()
    config["event_config"]["scheduled_events"] = [event("evt_ignored", 2)]  # inert without behavior v2

    assert "behavior_version" not in config and sb.behavior_version(config) == 1
    assert is_behavior_v2(config, environ={}) is False

    # the run scripts write the *.effective profile copies only when this is true
    assert is_behavior_v2(dict(config, behavior_version=2), environ={}) is True
    assert is_behavior_v2(dict(config, behavior_version=2), environ={"BEHAVIOR_V2_ENABLED": "false"}) is False

    for platform in ("twitter", "reddit"):
        behavior = PlatformBehavior(config, platform, seed=100)
        assert behavior.v2 is False and behavior.eligibility is None
        assert behavior.planned_follows() == []  # no seeded follow graph
        assert all(behavior.events_due(round_num) == [] for round_num in range(0, 30))  # events never fire


def test_scenario_1_the_kill_switch_turns_a_v2_simulation_back_into_a_legacy_one(monkeypatch):
    config = dict(legacy_config(), behavior_version=2)
    config["event_config"]["scheduled_events"] = [event("evt_ignored", 2)]
    monkeypatch.setenv("BEHAVIOR_V2_ENABLED", "false")
    behavior = PlatformBehavior(config, "twitter", seed=100)
    assert behavior.v2 is False
    assert behavior.planned_follows() == [] and behavior.events_due(2) == []


# --- Scenario 2: a v2 simulation: directives, seeded follows, scheduled events -------------------------

def test_scenario_2_a_v2_simulation_gets_directives_seeded_follows_and_scheduled_events(tmp_path):
    config = dict(legacy_config(), behavior_version=2)
    config["event_config"].update(
        topic=TOPIC, scheduled_events=[event("evt_news", 2), event("evt_off", 3, enabled=False)]
    )
    write_profiles(tmp_path)
    originals = {name: (tmp_path / name).read_bytes() for name in ("twitter_profiles.csv", "reddit_profiles.json")}
    assert is_behavior_v2(config, environ={})

    written = write_effective_profiles(str(tmp_path), config)
    assert set(written) == {"twitter", "reddit"}

    # every agent's profile carries the starting disposition, built from its own stance
    twitter_rows = list(csv.DictReader(io.StringIO((tmp_path / "twitter_profiles.effective.csv").read_text(encoding="utf-8"))))
    reddit_rows = json.loads((tmp_path / "reddit_profiles.effective.json").read_text(encoding="utf-8"))
    assert len(twitter_rows) == len(reddit_rows) == len(AGENTS)
    for row in twitter_rows:
        assert TOPIC in row["user_char"] and "starting view, not a script" in row["user_char"]
    for profile in reddit_rows:
        assert TOPIC in profile["persona"] and "starting view, not a script" in profile["persona"]
    assert "lean opposing" in twitter_rows[3]["user_char"]
    assert "lean supportive" in twitter_rows[1]["user_char"]
    assert "mostly read" in twitter_rows[5]["user_char"]  # the observer

    # the generator's guess at the outcome never reaches an agent, and the originals are untouched
    effective_text = "".join((tmp_path / name).read_text(encoding="utf-8") for name in
                             ("twitter_profiles.effective.csv", "reddit_profiles.effective.json"))
    assert "ZZ-NARRATIVE" not in effective_text
    assert {name: (tmp_path / name).read_bytes() for name in originals} == originals

    # the seeded follow graph: deterministic per seed, no self-follows, only known agents
    behavior = PlatformBehavior(config, "twitter", seed=42)
    follows = behavior.planned_follows()
    ids = {agent[0] for agent in AGENTS}
    assert follows and all(a != b and a in ids and b in ids for a, b in follows)
    assert PlatformBehavior(config, "twitter", seed=42).planned_follows() == follows
    assert PlatformBehavior(config, "twitter", seed=43).planned_follows() != follows

    # the user's scheduled event fires in the round of its hour (60-minute rounds); disabled ones never do
    assert behavior.events_due(0) == [] and behavior.events_due(1) == []
    due = behavior.events_due(2)
    assert [e["id"] for e in due] == ["evt_news"] and due[0]["content"] == "Scheduled news evt_news"
    assert behavior.events_due(3) == []

    # ... and it starts every agent's reaction delay: the slow organisation reacts later than the fast trader
    assert not behavior.eligibility.is_eligible(1, 2) and behavior.eligibility.is_eligible(1, 3)  # 5-60 minutes
    assert not behavior.eligibility.is_eligible(0, 3) and behavior.eligibility.is_eligible(0, 10)  # 2-8 hours


# --- Scenario 3: an ensemble: clones, final polls, aggregation, the caveat, no Zep writes -----------------

def test_scenario_3_an_ensemble_clones_replicates_polls_and_aggregates_with_the_caveat(env):
    questions = [
        {"id": "q1", "text": "Will HEGAM trade above its 7 Oct close?", "type": "probability"},
        {"id": "q2", "text": "What is your stance on HEGAM?", "type": "choice", "options": ["bullish", "neutral", "bearish"]},
    ]
    ensemble = create(env, n_replicates=3, max_rounds=12, concurrency=1, outcome_questions=questions)
    ens_id = ensemble["ensemble_id"]
    assert len(ensemble["replicates"]) == 3

    answers = [(65, "bullish"), (75, "bullish"), (45, "bearish")]
    for index, (probability, stance) in enumerate(answers, start=1):
        sim_dir = env.sims / rid(ensemble, index)
        run = json.loads((sim_dir / "simulation_config.json").read_text(encoding="utf-8"))["run"]
        assert run["ensemble_id"] == ens_id and run["replicate_index"] == index and run["max_rounds"] == 12
        assert run["outcome_questions"] == questions
        # what a finished replicate leaves behind: the real runner writes it after the last round
        poll = [{"agent_id": 0, "agent_name": "Retail Trader", "stance_initial": "neutral",
                 "answers": {"q1": probability, "q2": stance}, "reason": "momentum", "raw": "{}", "parse_ok": True}]
        (sim_dir / "final_poll.json").write_text(json.dumps(poll), encoding="utf-8")

    EnsembleManager.start(ens_id)
    drive(env, ens_id, {})

    # one replicate after the other, never writing to the knowledge graph, exiting instead of waiting for commands
    assert [call["simulation_id"] for call in env.runner.started] == [rid(ensemble, i) for i in (1, 2, 3)]
    assert env.runner.max_active == 1
    for call in env.runner.started:
        assert call["enable_graph_memory_update"] is False and call["wait_for_commands"] is False

    assert EnsembleManager.get(ens_id)["status"] == "completed"
    summary = EnsembleManager.summary(ens_id)
    assert summary["n_replicates_ok"] == 3 and summary["n_replicates_with_poll"] == 3

    q1 = summary["polls"]["q1"]
    assert (q1["agent_mean"]["min"], q1["agent_mean"]["median"], q1["agent_mean"]["max"]) == (45, 65, 75)
    assert q1["agent_mean"]["n"] == 3 and q1["share_of_replicates_mean_above_50"] == pytest.approx(2 / 3)
    bullish = summary["polls"]["q2"]["options"]["bullish"]
    assert (bullish["min"], bullish["median"], bullish["max"]) == (0, 1, 1)

    # the caveat opens both the machine-readable and the readable summary
    assert summary["caveat"].startswith("These are distributions of")
    opening = EnsembleManager.summary_markdown(ens_id).split("##")[0].replace("\n", " ")
    assert "not calibrated probabilities of the real-world event" in opening
    assert "has not been backtested" in opening


# --- Scenario 4: the same seed twice gives the same activation schedule --------------------------------

def schedule(config, platform, seed, rounds=48):
    behavior = PlatformBehavior(config, platform, seed)
    return [behavior.select_active(round_num, round_num % 24) for round_num in range(rounds)]


def test_scenario_4_the_same_seed_gives_the_same_activation_schedule_on_both_platforms():
    config = dict(legacy_config(), behavior_version=2)
    for platform in ("twitter", "reddit"):
        first = schedule(config, platform, seed=778899)
        assert first == schedule(config, platform, seed=778899)  # reproducible
        assert first != schedule(config, platform, seed=12345)  # and the seed matters
        assert any(first)  # a schedule that wakes nobody would prove nothing


def test_scenario_4_the_activation_schedule_can_be_compared_from_the_round_start_log(tmp_path):
    """Each ``round_start`` record carries the woken agents, so two runs are comparable from their logs alone."""
    config = dict(legacy_config(), behavior_version=2)

    def logged_schedule(run_dir, seed):
        logger = PlatformActionLogger("reddit", str(run_dir))
        behavior = PlatformBehavior(config, "reddit", seed)
        for round_num in range(24):
            logger.log_round_start(round_num + 1, round_num % 24, active_agent_ids=behavior.select_active(round_num, round_num % 24))
        records = [json.loads(line) for line in (run_dir / "reddit" / "actions.jsonl").read_text(encoding="utf-8").splitlines()]
        return {r["round"]: r["active_agent_ids"] for r in records if r["event_type"] == "round_start"}

    first = logged_schedule(tmp_path / "run_a", seed=7)
    assert first == logged_schedule(tmp_path / "run_b", seed=7)
    assert first != logged_schedule(tmp_path / "run_c", seed=8)
    assert set(first) == set(range(1, 25))
