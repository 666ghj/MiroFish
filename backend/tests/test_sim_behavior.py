import copy
import csv
import hashlib
import json
import math
import random

import pytest

import sim_behavior as sb
from sim_behavior import (
    EligibilityTracker,
    PlatformBehavior,
    RoundContext,
    activation_probability,
    build_behavior_directive,
    derive_rng,
    due_scheduled_events,
    plan_seed_follows,
    select_active_agents,
    write_effective_profiles,
)


# --- fixtures ---------------------------------------------------------------

def make_config(*, version=2, n_agents=6, **overrides):
    stances = ["supportive", "opposing", "neutral", "observer", "supportive", "opposing"]
    agents = []
    for i in range(n_agents):
        agents.append({
            "agent_id": i,
            "entity_name": f"Agent {i}",
            "activity_level": 0.7,
            "posts_per_hour": 0.5,
            "comments_per_hour": 1.0,
            "active_hours": list(range(0, 24)),
            "response_delay_min": 5,
            "response_delay_max": 60,
            "sentiment_bias": 0.0,
            "stance": stances[i % len(stances)],
            "influence_weight": 1.0 + i * 0.25,
        })
    config = {
        "simulation_requirement": "Will HEGAM trade higher after the demerger?",
        "time_config": {
            "total_simulation_hours": 120,
            "minutes_per_round": 60,
            "agents_per_hour_min": 1,
            "agents_per_hour_max": 4,
            "peak_hours": [9, 10, 11, 20, 21],
            "peak_activity_multiplier": 1.5,
            "off_peak_hours": [1, 2, 3, 4, 5],
            "off_peak_activity_multiplier": 0.05,
            "morning_hours": [6, 7, 8],
            "morning_activity_multiplier": 0.4,
            "work_hours": [12, 13, 14, 15, 16, 17, 18],
            "work_activity_multiplier": 0.7,
        },
        "agent_configs": agents,
        "event_config": {
            "initial_posts": [],
            "scheduled_events": [],
            "hot_topics": [],
            "narrative_direction": "SECRET-NARRATIVE-HYPOTHESIS",
        },
        "twitter_config": {"platform": "twitter", "echo_chamber_strength": 0.5},
        "reddit_config": {"platform": "reddit", "echo_chamber_strength": 0.6},
    }
    if version is not None:
        config["behavior_version"] = version
    config.update(overrides)
    return config


def schedule(config, seed, platform="twitter", rounds=100, v2=None):
    """The selection sequence a PlatformBehavior produces over ``rounds`` rounds."""
    behavior = PlatformBehavior(config, platform, seed, v2=v2)
    if behavior.v2:
        behavior.initial_posts_published()
    return [behavior.select_active(r, r % 24) for r in range(rounds)]


# The original activation function, verbatim apart from taking the RNG object
# instead of using the global ``random`` module.
def legacy_reference(r, config, current_hour):
    time_config = config.get("time_config", {})
    agent_configs = config.get("agent_configs", [])
    base_min = time_config.get("agents_per_hour_min", 5)
    base_max = time_config.get("agents_per_hour_max", 20)
    peak_hours = time_config.get("peak_hours", [9, 10, 11, 14, 15, 20, 21, 22])
    off_peak_hours = time_config.get("off_peak_hours", [0, 1, 2, 3, 4, 5])
    if current_hour in peak_hours:
        multiplier = time_config.get("peak_activity_multiplier", 1.5)
    elif current_hour in off_peak_hours:
        multiplier = time_config.get("off_peak_activity_multiplier", 0.3)
    else:
        multiplier = 1.0
    target_count = int(r.uniform(base_min, base_max) * multiplier)
    candidates = []
    for cfg in agent_configs:
        agent_id = cfg.get("agent_id", 0)
        active_hours = cfg.get("active_hours", list(range(8, 23)))
        activity_level = cfg.get("activity_level", 0.5)
        if current_hour not in active_hours:
            continue
        if r.random() < activity_level:
            candidates.append(agent_id)
    return r.sample(candidates, min(target_count, len(candidates))) if candidates else []


# --- seeds and determinism ---------------------------------------------------

@pytest.mark.parametrize("version", [None, 2])
def test_same_seed_gives_identical_schedule_over_100_rounds(version):
    config = make_config(version=version)
    assert schedule(config, 1234) == schedule(config, 1234)


@pytest.mark.parametrize("version", [None, 2])
def test_different_seed_gives_a_different_schedule(version):
    config = make_config(version=version)
    assert schedule(config, 1234) != schedule(config, 4321)


def test_derive_rng_matches_the_documented_seed_string():
    assert derive_rng(7, "twitter").random() == random.Random("7:twitter").random()
    assert derive_rng(7, "twitter").random() != derive_rng(7, "reddit").random()
    assert derive_rng(7, "twitter", "delay").random() == random.Random("7:twitter:delay").random()


@pytest.mark.parametrize("version", [None, 2])
def test_platform_rngs_are_independent(version):
    config = make_config(version=version)
    reddit_alone = PlatformBehavior(config, "reddit", 99)
    expected = [reddit_alone.select_active(r, r % 24) for r in range(60)]

    reddit = PlatformBehavior(config, "reddit", 99)
    twitter = PlatformBehavior(config, "twitter", 99)
    interleaved = []
    for r in range(60):
        # Twitter keeps consuming randomness between Reddit's rounds.
        for _ in range(3):
            twitter.select_active(r, r % 24)
        interleaved.append(reddit.select_active(r, r % 24))
    assert interleaved == expected


def test_selection_never_touches_the_global_random_module():
    random.seed(2024)
    before = random.getstate()
    config = make_config()
    schedule(config, 5)
    schedule(make_config(version=None), 5)
    plan_seed_follows(config, derive_rng(5, "twitter", "follow"))
    assert random.getstate() == before


# --- legacy equivalence ------------------------------------------------------

def test_legacy_selection_matches_the_original_function():
    config = make_config(version=None)
    for seed in range(25):
        old = random.Random(seed)
        new = random.Random(seed)
        for round_num in range(48):
            hour = round_num % 24
            expected = legacy_reference(old, config, hour)
            actual = select_active_agents(
                config, RoundContext(round_num, hour, 60), new
            )
            assert actual == expected, (seed, round_num)


def test_legacy_path_ignores_eligibility_and_v2_fields():
    config = make_config(version=None)
    for agent in config["agent_configs"]:
        agent["posts_per_hour"] = 0
        agent["comments_per_hour"] = 0
        agent["response_delay_min"] = agent["response_delay_max"] = 10_000
    tracker = EligibilityTracker(config["agent_configs"], 60)
    tracker.on_trigger(0, random.Random(1))
    old, new = random.Random(3), random.Random(3)
    for round_num in range(24):
        assert select_active_agents(
            config, RoundContext(round_num, round_num, 60), new, tracker
        ) == legacy_reference(old, config, round_num)


def test_missing_version_means_legacy_and_the_kill_switch_forces_it(monkeypatch):
    assert sb.behavior_version({}) == 1
    assert sb.behavior_version({"behavior_version": "2"}) == 2
    assert sb.behavior_version({"behavior_version": "garbage"}) == 1
    assert not sb.is_behavior_v2(make_config(version=None))
    assert sb.is_behavior_v2(make_config(version=2))

    monkeypatch.setenv("BEHAVIOR_V2_ENABLED", "false")
    assert not sb.is_behavior_v2(make_config(version=2))
    assert not PlatformBehavior(make_config(version=2), "twitter", 1).v2
    monkeypatch.setenv("BEHAVIOR_V2_ENABLED", "true")
    assert sb.is_behavior_v2(make_config(version=2))


# --- v2 activation -----------------------------------------------------------

def test_activation_probability_formula():
    cfg = {"activity_level": 0.8, "posts_per_hour": 0.5, "comments_per_hour": 1.0}
    tc = {"peak_hours": [20], "peak_activity_multiplier": 1.5}
    expected = 0.8 * (1 - math.exp(-1.5 * 1.0)) * 1.0
    assert activation_probability(cfg, tc, RoundContext(0, 12, 60)) == pytest.approx(expected)
    # A 30 minute round halves the expected number of events.
    half = 0.8 * (1 - math.exp(-1.5 * 0.5))
    assert activation_probability(cfg, tc, RoundContext(0, 12, 30)) == pytest.approx(half)


def test_activation_probability_is_zero_for_zero_rate_or_zero_activity():
    tc = {}
    ctx = RoundContext(0, 12, 60)
    assert activation_probability(
        {"activity_level": 0.9, "posts_per_hour": 0, "comments_per_hour": 0}, tc, ctx
    ) == 0
    assert activation_probability(
        {"activity_level": 0, "posts_per_hour": 5, "comments_per_hour": 5}, tc, ctx
    ) == 0


def test_activation_probability_is_clamped_at_095():
    cfg = {"activity_level": 1.0, "posts_per_hour": 50, "comments_per_hour": 50}
    tc = {"peak_hours": [20], "peak_activity_multiplier": 1.5}
    assert activation_probability(cfg, tc, RoundContext(0, 20, 60)) == 0.95


def test_activation_probability_uses_morning_and_work_multipliers_in_v2():
    config = make_config()
    tc = config["time_config"]
    cfg = {"activity_level": 1.0, "posts_per_hour": 1.0, "comments_per_hour": 1.0}
    base = 1 - math.exp(-2.0)
    assert activation_probability(cfg, tc, RoundContext(0, 7, 60)) == pytest.approx(base * 0.4)
    assert activation_probability(cfg, tc, RoundContext(0, 14, 60)) == pytest.approx(base * 0.7)
    assert activation_probability(cfg, tc, RoundContext(0, 23, 60)) == pytest.approx(base)
    # peak wins over work for hours that are both (kept under the 0.95 clamp).
    config["time_config"]["work_hours"] = [10]
    gentle = dict(cfg, activity_level=0.4)
    assert activation_probability(gentle, config["time_config"], RoundContext(0, 10, 60)) == pytest.approx(0.4 * base * 1.5)
    # ... while v1 never applied morning/work multipliers.
    assert sb.hour_multiplier(tc, 7, v2=False) == 1.0
    assert sb.hour_multiplier(tc, 14, v2=False) == 1.0


def test_zero_rate_agents_are_never_woken_and_active_ones_are():
    config = make_config(n_agents=6)
    for agent in config["agent_configs"][:3]:
        agent["posts_per_hour"] = 0
        agent["comments_per_hour"] = 0
    seen = set()
    for round_sets in schedule(config, 11, rounds=200):
        seen.update(round_sets)
    assert seen.isdisjoint({0, 1, 2})
    assert seen >= {3, 4, 5}


def test_agents_per_hour_max_is_an_upper_bound():
    config = make_config(n_agents=6)
    config["time_config"].update(
        agents_per_hour_min=2, agents_per_hour_max=2, peak_hours=[], off_peak_hours=[]
    )
    for agent in config["agent_configs"]:
        agent.update(activity_level=1.0, posts_per_hour=50, comments_per_hour=50)
    for woken in schedule(config, 5, rounds=100):
        assert len(woken) <= 2
    # ... and the cap actually binds when many agents pass their draw.
    assert max(len(w) for w in schedule(config, 5, rounds=100)) == 2


def test_inactive_hours_are_respected():
    config = make_config()
    for agent in config["agent_configs"]:
        agent["active_hours"] = [9]
    for r, woken in enumerate(schedule(config, 8, rounds=72)):
        if r % 24 != 9:
            assert woken == []


def test_selected_ids_are_unique_and_known():
    config = make_config()
    for woken in schedule(config, 3, rounds=100):
        assert len(set(woken)) == len(woken)
        assert set(woken) <= {a["agent_id"] for a in config["agent_configs"]}


# --- reaction delays ---------------------------------------------------------

def _tracker(delays, minutes_per_round=60):
    return EligibilityTracker(
        [
            {"agent_id": i, "response_delay_min": lo, "response_delay_max": hi}
            for i, (lo, hi) in enumerate(delays)
        ],
        minutes_per_round,
    )


def test_agents_without_a_trigger_are_always_eligible():
    tracker = _tracker([(120, 120)])
    assert tracker.is_eligible(0, 0)
    assert tracker.is_eligible(99, 0)  # unknown agents too


def test_delay_blocks_until_trigger_round_plus_ceil_delay():
    # 90 minutes at 60 minute rounds -> ceil(1.5) = 2 rounds.
    tracker = _tracker([(90, 90), (30, 30), (0, 0), (120, 120)])
    tracker.on_trigger(5, random.Random(0))
    assert [tracker.is_eligible(0, r) for r in (5, 6, 7)] == [False, False, True]
    assert [tracker.is_eligible(1, r) for r in (5, 6)] == [False, True]
    assert tracker.is_eligible(2, 5)  # zero delay: same round
    assert [tracker.is_eligible(3, r) for r in (6, 7)] == [False, True]


def test_delays_are_drawn_inside_the_configured_range():
    tracker = _tracker([(10, 200)] * 40)
    tracker.on_trigger(0, random.Random(1))
    ready = [min(r for r in range(10) if tracker.is_eligible(a, r)) for a in range(40)]
    assert min(ready) >= 1 and max(ready) <= math.ceil(200 / 60)
    assert len(set(ready)) > 1


def test_a_new_trigger_overrides_the_previous_one():
    tracker = _tracker([(240, 240)])
    tracker.on_trigger(0, random.Random(0))
    assert not tracker.is_eligible(0, 3)
    assert tracker.is_eligible(0, 4)
    # The latest trigger wins, even though it pushes eligibility further out.
    tracker.on_trigger(3, random.Random(0))
    assert not tracker.is_eligible(0, 4)
    assert tracker.is_eligible(0, 7)


def test_triggers_are_deterministic_for_a_seed():
    def ready(seed):
        tracker = _tracker([(5, 600)] * 10)
        tracker.on_trigger(0, random.Random(seed))
        return [min(r for r in range(20) if tracker.is_eligible(a, r)) for a in range(10)]

    assert ready(1) == ready(1)
    assert ready(1) != ready(2)


def test_ineligible_agents_are_not_selected_but_still_consume_their_draw():
    config = make_config()
    for agent in config["agent_configs"]:
        agent.update(activity_level=1.0, posts_per_hour=5, comments_per_hour=5)
    tracker = _tracker([(600, 600)] * 6)
    tracker.on_trigger(0, random.Random(0))  # everybody waits 10 rounds

    blocked = random.Random(9)
    reference = random.Random(9)
    tc = config["time_config"]
    for round_num in range(10):
        ctx = RoundContext(round_num, 12, 60)
        assert select_active_agents(config, ctx, blocked, tracker) == []
        # Nobody is eligible, so the only consumption is the cap draw and one
        # draw for each of the six in-hour agents.
        reference.uniform(tc["agents_per_hour_min"], tc["agents_per_hour_max"])
        for _ in range(6):
            reference.random()
    assert blocked.random() == reference.random()


def test_initial_posts_trigger_delays_only_when_published():
    config = make_config()
    for agent in config["agent_configs"]:
        agent.update(response_delay_min=600, response_delay_max=600)
    behavior = PlatformBehavior(config, "twitter", 1)
    assert behavior.eligibility.is_eligible(0, 0)
    behavior.initial_posts_published()
    assert not behavior.eligibility.is_eligible(0, 5)
    assert behavior.eligibility.is_eligible(0, 10)
    assert PlatformBehavior(make_config(version=None), "twitter", 1).eligibility is None


# --- seeded follows ----------------------------------------------------------

def _follow_config(stances, echo, influence=None):
    agents = [
        {
            "agent_id": i,
            "stance": s,
            "influence_weight": (influence or {}).get(i, 1.0),
        }
        for i, s in enumerate(stances)
    ]
    return {
        "agent_configs": agents,
        "twitter_config": {"echo_chamber_strength": echo},
        "reddit_config": {"echo_chamber_strength": echo},
    }


def test_no_self_follows_and_deterministic_per_seed():
    config = make_config()
    first = plan_seed_follows(config, derive_rng(4, "twitter", "follow"))
    again = plan_seed_follows(config, derive_rng(4, "twitter", "follow"))
    other = plan_seed_follows(config, derive_rng(5, "twitter", "follow"))
    assert first == again
    assert first != other
    assert all(follower != followee for follower, followee in first)
    assert len(set(first)) == len(first)


def test_fewer_than_two_agents_follow_nobody():
    assert plan_seed_follows(_follow_config(["supportive"], 0.5), random.Random(0)) == []
    assert plan_seed_follows({"agent_configs": []}, random.Random(0)) == []


def _rates_by_relation(config, seeds):
    stances = {a["agent_id"]: a["stance"] for a in config["agent_configs"]}
    counts = {"same": [0, 0], "opposite": [0, 0], "other": [0, 0]}
    ids = list(stances)
    for seed in seeds:
        follows = set(plan_seed_follows(config, random.Random(seed)))
        for i in ids:
            for j in ids:
                if i == j:
                    continue
                relation = sb._stance_relation(stances[i], stances[j])
                key = {1: "same", -1: "opposite", 0: "other"}[relation]
                counts[key][1] += 1
                counts[key][0] += (i, j) in follows
    return {k: v[0] / v[1] for k, v in counts.items() if v[1]}


def test_with_no_echo_chamber_stance_does_not_matter():
    config = _follow_config(["supportive"] * 4 + ["opposing"] * 4, echo=0.0)
    rates = _rates_by_relation(config, range(300))
    assert rates["same"] == pytest.approx(rates["opposite"], abs=0.04)
    assert rates["same"] == pytest.approx(sb.FOLLOW_BASE_PROBABILITY, abs=0.04)


def test_with_a_full_echo_chamber_same_stance_follows_far_more_than_opposite():
    config = _follow_config(["supportive"] * 4 + ["opposing"] * 4, echo=1.0)
    rates = _rates_by_relation(config, range(300))
    assert rates["opposite"] == 0.0
    assert rates["same"] > 0.5
    assert rates["same"] == pytest.approx(0.6, abs=0.05)


def test_neutral_and_observer_count_as_neither_same_nor_opposite():
    config = _follow_config(["neutral", "observer", "supportive", "opposing"], echo=1.0)
    rates = _rates_by_relation(config, range(400))
    # Every pair involving a neutral/observer uses the plain base probability.
    assert rates["other"] == pytest.approx(sb.FOLLOW_BASE_PROBABILITY, abs=0.04)


def test_more_influential_accounts_gain_more_followers():
    config = _follow_config(
        ["neutral"] * 5, echo=0.0, influence={0: 5.0, 1: 1.0, 2: 1.0, 3: 1.0, 4: 0.1}
    )
    followers = {i: 0 for i in range(5)}
    for seed in range(300):
        for _, followee in plan_seed_follows(config, random.Random(seed)):
            followers[followee] += 1
    assert followers[0] > followers[1] > followers[4]


def test_follow_probability_is_capped():
    config = _follow_config(["supportive", "supportive"], echo=1.0)
    follows = [len(plan_seed_follows(config, random.Random(s))) for s in range(400)]
    # base 0.3 * norm 1.0 * (1 + 1.0) = 0.6 per ordered pair, well under the cap
    assert 0.5 < sum(follows) / (400 * 2) < 0.7


def test_follow_planning_uses_the_platform_echo_strength():
    config = _follow_config(["supportive"] * 3 + ["opposing"] * 3, echo=0.0)
    config["reddit_config"]["echo_chamber_strength"] = 1.0
    twitter = _rates_by_relation(config, range(200))  # default platform: twitter
    assert twitter["opposite"] > 0
    reddit_follows = sum(
        len(plan_seed_follows(config, random.Random(s), "reddit")) for s in range(200)
    )
    twitter_follows = sum(
        len(plan_seed_follows(config, random.Random(s), "twitter")) for s in range(200)
    )
    assert reddit_follows != twitter_follows


# --- persona directive -------------------------------------------------------

def test_directive_contains_the_not_a_script_sentence_and_the_topic():
    directive = build_behavior_directive(
        {"stance": "supportive", "sentiment_bias": 0.6}, "HEGAM demerger", "en"
    )
    assert 'On "HEGAM demerger"' in directive
    assert "lean supportive" in directive
    assert "clearly positive" in directive
    assert "not a script" in directive
    assert "update it if you see convincing evidence" in directive


def test_directive_never_contains_the_narrative_direction():
    config = make_config()
    for agent in config["agent_configs"]:
        directive = build_behavior_directive(agent, sb.resolve_topic(config), "en")
        assert "SECRET-NARRATIVE-HYPOTHESIS" not in directive


@pytest.mark.parametrize(
    "value,expected",
    [
        (-1.0, "clearly negative"), (-0.5, "clearly negative"),
        (-0.4999, "slightly negative"), (-0.15, "slightly negative"),
        (-0.1499, "balanced"), (0.0, "balanced"), (0.1499, "balanced"),
        (0.15, "slightly positive"), (0.4999, "slightly positive"),
        (0.5, "clearly positive"), (1.0, "clearly positive"),
    ],
)
def test_sentiment_buckets(value, expected):
    directive = build_behavior_directive({"stance": "neutral", "sentiment_bias": value}, "t", "en")
    assert f"tone tends to be {expected}." in directive


def test_directive_handles_out_of_range_and_garbage_values():
    assert "clearly positive" in build_behavior_directive({"sentiment_bias": 9}, "t")
    assert "clearly negative" in build_behavior_directive({"sentiment_bias": -9}, "t")
    assert "balanced" in build_behavior_directive({"sentiment_bias": "nope"}, "t")
    assert "lean neutral" in build_behavior_directive({"stance": "gibberish"}, "t")


def test_observer_stance_says_the_agent_mostly_reads():
    directive = build_behavior_directive({"stance": "observer"}, "t", "en")
    assert "neutral" in directive and "mostly read and rarely post" in directive


def test_directive_is_localised_with_an_english_fallback():
    zh = build_behavior_directive({"stance": "opposing", "sentiment_bias": -0.8}, "话题", "zh")
    assert "话题" in zh and "反对" in zh and "不是剧本" in zh
    assert build_behavior_directive({"stance": "opposing"}, "t", "zh-CN") == build_behavior_directive({"stance": "opposing"}, "t", "zh")
    assert "not a script" in build_behavior_directive({"stance": "opposing"}, "t", "fr")


def test_topic_falls_back_to_the_requirement_prefix():
    config = make_config()
    config["simulation_requirement"] = "x" * 500
    assert sb.resolve_topic(config) == "x" * 120
    config["event_config"]["topic"] = "  HEGAM demerger  "
    assert sb.resolve_topic(config) == "HEGAM demerger"


# --- effective profiles ------------------------------------------------------

def _write_profiles(sim_dir, n=3):
    rows = [
        {"user_id": str(i), "name": f"Name {i}", "username": f"user_{i}",
         "user_char": f"Persona of {i}, with a comma, and\nnewline", "description": f"Bio {i}"}
        for i in range(n)
    ]
    with open(sim_dir / "twitter_profiles.csv", "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["user_id", "name", "username", "user_char", "description"])
        for row in rows:
            writer.writerow([row["user_id"], row["name"], row["username"], row["user_char"], row["description"]])
    reddit = [
        {"user_id": i, "username": f"user_{i}", "name": f"Name {i}", "bio": f"Bio {i}",
         "persona": f"Persona of {i}", "age": 30, "gender": "male", "mbti": "INTJ", "country": "IN"}
        for i in range(n)
    ]
    (sim_dir / "reddit_profiles.json").write_text(
        json.dumps(reddit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return rows, reddit


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_effective_profiles_extend_personas_and_never_touch_the_originals(tmp_path):
    rows, reddit = _write_profiles(tmp_path, n=3)
    config = make_config(n_agents=3)
    before = {p.name: _digest(p) for p in tmp_path.iterdir()}

    outputs = write_effective_profiles(str(tmp_path), config)

    assert {p.name: _digest(p) for p in tmp_path.iterdir() if p.name in before} == before
    assert outputs == {
        "twitter": str(tmp_path / "twitter_profiles.effective.csv"),
        "reddit": str(tmp_path / "reddit_profiles.effective.json"),
    }

    with open(outputs["twitter"], encoding="utf-8", newline="") as handle:
        effective = list(csv.DictReader(handle))
    assert [list(r.keys()) for r in effective] == [["user_id", "name", "username", "user_char", "description"]] * 3
    for i, row in enumerate(effective):
        assert row["user_char"].startswith(rows[i]["user_char"])
        assert "[Starting disposition]" in row["user_char"]
        assert "not a script" in row["user_char"]
        assert {k: v for k, v in row.items() if k != "user_char"} == {
            k: v for k, v in rows[i].items() if k != "user_char"
        }

    profiles = json.loads((tmp_path / "reddit_profiles.effective.json").read_text(encoding="utf-8"))
    assert len(profiles) == 3
    for i, profile in enumerate(profiles):
        assert profile["persona"].startswith(reddit[i]["persona"])
        assert "[Starting disposition]" in profile["persona"]
        assert {k: v for k, v in profile.items() if k != "persona"} == {
            k: v for k, v in reddit[i].items() if k != "persona"
        }


def test_effective_profiles_use_each_agents_own_stance_and_the_config_locale(tmp_path):
    _write_profiles(tmp_path, n=2)
    config = make_config(n_agents=2)
    config["agent_configs"][0].update(stance="supportive", sentiment_bias=0.8)
    config["agent_configs"][1].update(stance="opposing", sentiment_bias=-0.8)
    outputs = write_effective_profiles(str(tmp_path), config)
    with open(outputs["twitter"], encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert "lean supportive" in rows[0]["user_char"] and "clearly positive" in rows[0]["user_char"]
    assert "lean opposing" in rows[1]["user_char"] and "clearly negative" in rows[1]["user_char"]

    config["locale"] = "zh"
    outputs = write_effective_profiles(str(tmp_path), config)
    with open(outputs["twitter"], encoding="utf-8", newline="") as handle:
        assert "初始倾向" in list(csv.DictReader(handle))[0]["user_char"]


def test_effective_profiles_never_leak_the_narrative_direction(tmp_path):
    _write_profiles(tmp_path, n=3)
    outputs = write_effective_profiles(str(tmp_path), make_config(n_agents=3))
    for path in outputs.values():
        text = open(path, encoding="utf-8").read()
        assert "SECRET-NARRATIVE-HYPOTHESIS" not in text


def test_effective_profiles_skip_missing_files_and_unknown_agents(tmp_path):
    assert write_effective_profiles(str(tmp_path), make_config()) == {}
    rows, _ = _write_profiles(tmp_path, n=3)
    config = make_config(n_agents=2)  # agent 2 has no config
    outputs = write_effective_profiles(str(tmp_path), config)
    with open(outputs["twitter"], encoding="utf-8", newline="") as handle:
        effective = list(csv.DictReader(handle))
    assert effective[2]["user_char"] == rows[2]["user_char"]


def test_effective_twitter_csv_is_readable_by_the_oasis_loader(tmp_path):
    pd = pytest.importorskip("pandas")
    _write_profiles(tmp_path, n=2)
    outputs = write_effective_profiles(str(tmp_path), make_config(n_agents=2))
    frame = pd.read_csv(outputs["twitter"])
    assert list(frame.columns) == ["user_id", "name", "username", "user_char", "description"]
    assert "[Starting disposition]" in frame["user_char"][0]


# --- scheduled events --------------------------------------------------------

def _events(*events, minutes_per_round=60):
    config = make_config()
    config["time_config"]["minutes_per_round"] = minutes_per_round
    config["event_config"]["scheduled_events"] = list(events)
    return config


def test_events_fire_in_the_round_containing_their_hour():
    config = _events({"id": "a", "at_sim_hour": 26, "poster_agent_id": 1, "content": "x"})
    assert [r for r in range(60) if due_scheduled_events(config, r)] == [26]
    config = _events({"id": "a", "at_sim_hour": 26, "content": "x"}, minutes_per_round=30)
    assert [r for r in range(120) if due_scheduled_events(config, r)] == [52]
    config = _events({"id": "a", "at_sim_hour": 1.5, "content": "x"}, minutes_per_round=60)
    assert [r for r in range(10) if due_scheduled_events(config, r)] == [1]


def test_disabled_and_malformed_events_are_skipped():
    config = _events(
        {"id": "off", "at_sim_hour": 3, "content": "x", "enabled": False},
        {"id": "on", "at_sim_hour": 3, "content": "y", "enabled": True},
        {"id": "default", "at_sim_hour": 3, "content": "z"},
        {"id": "bad", "at_sim_hour": "later", "content": "w"},
        {"id": "none", "content": "v"},
    )
    assert [e["id"] for e in due_scheduled_events(config, 3)] == ["default", "on"]


def test_events_in_the_same_round_are_ordered_deterministically():
    config = _events(
        {"id": "b", "at_sim_hour": 3, "content": "x"},
        {"id": "a", "at_sim_hour": 3, "content": "y"},
    )
    assert [e["id"] for e in due_scheduled_events(config, 3)] == ["a", "b"]


def test_behavior_fires_events_only_in_v2_and_each_event_triggers_delays():
    config = _events({"id": "a", "at_sim_hour": 4, "content": "x"})
    for agent in config["agent_configs"]:
        agent.update(response_delay_min=120, response_delay_max=120)
    behavior = PlatformBehavior(config, "twitter", 1)
    assert behavior.events_due(3) == []
    assert behavior.eligibility.is_eligible(0, 4)
    assert [e["id"] for e in behavior.events_due(4)] == ["a"]
    assert not behavior.eligibility.is_eligible(0, 5)
    assert behavior.eligibility.is_eligible(0, 6)

    legacy = PlatformBehavior(copy.deepcopy(dict(config, behavior_version=1)), "twitter", 1)
    assert legacy.events_due(4) == []
    assert legacy.planned_follows() == []


# --- run settings ------------------------------------------------------------

def test_run_settings_cli_overrides_config():
    config = {"run": {"seed": 5, "max_rounds": 12, "replicate_index": 2, "ensemble_id": "ens_x"}}
    assert sb.resolve_run_settings(config)["seed"] == 5
    assert sb.resolve_run_settings(config, cli_seed=9)["seed"] == 9
    assert sb.resolve_run_settings(config, cli_seed=0)["seed"] == 0  # 0 is a valid seed
    assert sb.resolve_run_settings(config)["max_rounds"] == 12
    assert sb.resolve_run_settings(config, cli_max_rounds=3)["max_rounds"] == 3
    settings = sb.resolve_run_settings({})
    assert settings["seed"] is None and settings["max_rounds"] is None
    assert settings["outcome_questions"] == []


# --- round_start logging and schedule determinism ----------------------------

def test_action_logger_records_active_agent_ids_on_round_start(tmp_path):
    from action_logger import PlatformActionLogger
    logger = PlatformActionLogger("twitter", str(tmp_path))
    logger.log_round_start(1, 9, active_agent_ids=[0, 3, 5])
    logger.log_round_start(2, 10)  # optional argument omitted

    log_path = tmp_path / "twitter" / "actions.jsonl"
    assert log_path.exists()
    lines = [json.loads(line) for line in log_path.read_text(encoding="utf-8").strip().split("\n")]
    assert len(lines) == 2
    assert lines[0]["event_type"] == "round_start"
    assert lines[0]["round"] == 1
    assert lines[0]["simulated_hour"] == 9
    assert lines[0]["active_agent_ids"] == [0, 3, 5]

    assert lines[1]["event_type"] == "round_start"
    assert lines[1]["round"] == 2
    assert lines[1]["simulated_hour"] == 10
    assert "active_agent_ids" not in lines[1]


def test_platform_behavior_schedule_determinism_across_platforms():
    config = make_config(n_agents=8)
    config["event_config"]["scheduled_events"] = [
        {"id": "evt_1", "at_sim_hour": 6, "poster_agent_id": 0, "content": "News", "enabled": True}
    ]

    tw1 = PlatformBehavior(config, "twitter", seed=42)
    tw2 = PlatformBehavior(config, "twitter", seed=42)
    rd1 = PlatformBehavior(config, "reddit", seed=42)
    rd2 = PlatformBehavior(config, "reddit", seed=42)
    tw_diff = PlatformBehavior(config, "twitter", seed=99)

    tw1_schedule = []
    tw2_schedule = []
    rd1_schedule = []
    rd2_schedule = []
    tw_diff_schedule = []

    for round_num in range(24):
        hour = round_num % 24
        tw1.events_due(round_num)
        tw2.events_due(round_num)
        rd1.events_due(round_num)
        rd2.events_due(round_num)
        tw_diff.events_due(round_num)

        tw1_schedule.append(tw1.select_active(round_num, hour))
        tw2_schedule.append(tw2.select_active(round_num, hour))
        rd1_schedule.append(rd1.select_active(round_num, hour))
        rd2_schedule.append(rd2.select_active(round_num, hour))
        tw_diff_schedule.append(tw_diff.select_active(round_num, hour))

    assert tw1_schedule == tw2_schedule
    assert rd1_schedule == rd2_schedule
    assert tw1_schedule != rd1_schedule
    assert tw1_schedule != tw_diff_schedule

