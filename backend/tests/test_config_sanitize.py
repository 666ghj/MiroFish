import json
import math

import pytest

from app.services import simulation_config_generator as gen
from app.services.simulation_config_generator import (
    AgentActivityConfig,
    EventConfig,
    PlatformConfig,
    SimulationConfigGenerator,
    SimulationParameters,
    _sanitize_agent_config,
    assign_poster_agents,
    clean_topic,
    sanitize_suggested_events,
)
from app.services.zep_entity_reader import EntityNode
from app.utils.locale import set_locale


# --- _sanitize_agent_config --------------------------------------------------

def test_valid_values_pass_through_unchanged():
    cfg = {
        "activity_level": 0.4, "posts_per_hour": 0.7, "comments_per_hour": 1.5,
        "active_hours": [9, 10, 20], "response_delay_min": 10, "response_delay_max": 90,
        "sentiment_bias": -0.3, "stance": "opposing", "influence_weight": 2.5,
    }
    assert _sanitize_agent_config(cfg) == cfg


@pytest.mark.parametrize("stance", ["", None, "bullish", "SUPPORT", 5, "supportive!"])
def test_unknown_stance_becomes_neutral(stance):
    assert _sanitize_agent_config({"stance": stance})["stance"] == "neutral"


def test_stance_is_normalised():
    assert _sanitize_agent_config({"stance": "  Opposing "})["stance"] == "opposing"
    assert _sanitize_agent_config({"stance": "OBSERVER"})["stance"] == "observer"


@pytest.mark.parametrize(
    "raw,expected",
    [(5, 1.0), (-5, -1.0), (0.25, 0.25), ("0.5", 0.5), ("bad", 0.0), (None, 0.0), (True, 0.0),
     (float("nan"), 0.0), (float("inf"), 0.0)],
)
def test_sentiment_bias_is_clamped_to_unit_interval(raw, expected):
    assert _sanitize_agent_config({"sentiment_bias": raw})["sentiment_bias"] == expected


@pytest.mark.parametrize(
    "raw,expected",
    [(0, 0.1), (-3, 0.1), (100, 5.0), (2.0, 2.0), ("x", 1.0), (None, 1.0)],
)
def test_influence_weight_is_clamped(raw, expected):
    assert _sanitize_agent_config({"influence_weight": raw})["influence_weight"] == expected


@pytest.mark.parametrize("raw,expected", [(2, 1.0), (-1, 0.0), (0.0, 0.0), ("high", 0.5), (None, 0.5)])
def test_activity_level_is_clamped(raw, expected):
    assert _sanitize_agent_config({"activity_level": raw})["activity_level"] == expected


def test_rates_are_never_negative():
    out = _sanitize_agent_config({"posts_per_hour": -2, "comments_per_hour": -0.1})
    assert out["posts_per_hour"] == 0.0 and out["comments_per_hour"] == 0.0
    out = _sanitize_agent_config({"posts_per_hour": "n/a", "comments_per_hour": None})
    assert out["posts_per_hour"] == 0.5 and out["comments_per_hour"] == 1.0
    assert _sanitize_agent_config({"posts_per_hour": 10 ** 9})["posts_per_hour"] == gen.MAX_RATE_PER_HOUR


@pytest.mark.parametrize(
    "lo,hi,exp_lo,exp_hi",
    [(5, 60, 5, 60), (60, 5, 60, 60), (-10, 20, 0, 20), (-10, -5, 0, 0),
     (1.6, 9.4, 2, 9), (None, None, 5, 60), ("x", "y", 5, 60), (30, None, 30, 60)],
)
def test_response_delays_are_ordered_and_non_negative(lo, hi, exp_lo, exp_hi):
    out = _sanitize_agent_config({"response_delay_min": lo, "response_delay_max": hi})
    assert (out["response_delay_min"], out["response_delay_max"]) == (exp_lo, exp_hi)
    assert 0 <= out["response_delay_min"] <= out["response_delay_max"]
    assert isinstance(out["response_delay_min"], int) and isinstance(out["response_delay_max"], int)


def test_active_hours_are_filtered_deduplicated_and_sorted():
    assert _sanitize_agent_config({"active_hours": [22, 9, 9, 24, -1, "x", 3.5, 23, True, "7"]})["active_hours"] == [7, 9, 22, 23]
    for bad in (None, [], "9-17", 12, [99], ["x"]):
        assert _sanitize_agent_config({"active_hours": bad})["active_hours"] == gen.DEFAULT_ACTIVE_HOURS


def test_empty_or_missing_config_gets_all_defaults():
    out = _sanitize_agent_config({})
    assert out == _sanitize_agent_config(None)
    assert out["stance"] == "neutral" and out["activity_level"] == 0.5
    assert set(out) == {
        "activity_level", "posts_per_hour", "comments_per_hour", "active_hours",
        "response_delay_min", "response_delay_max", "sentiment_bias", "stance", "influence_weight",
    }
    assert all(not (isinstance(v, float) and math.isnan(v)) for v in out.values())


def test_sanitizer_does_not_mutate_its_input():
    cfg = {"stance": "BAD", "sentiment_bias": 9, "active_hours": [1, 99]}
    snapshot = json.dumps(cfg, sort_keys=True)
    _sanitize_agent_config(cfg)
    assert json.dumps(cfg, sort_keys=True) == snapshot


def test_the_rule_based_defaults_survive_sanitising_unchanged():
    generator = SimulationConfigGenerator(api_key="k", base_url="http://127.0.0.1:1/v1", model_name="m")
    for entity_type in ("University", "MediaOutlet", "Professor", "Student", "Alumni", "Person", "Other"):
        entity = EntityNode(uuid="u", name="n", labels=["Entity", entity_type], summary="", attributes={})
        rule = generator._generate_agent_config_by_rule(entity)
        assert _sanitize_agent_config(rule) == {
            **rule,
            "response_delay_min": rule["response_delay_min"],
        }, entity_type


# --- topic -------------------------------------------------------------------

def test_topic_is_capped_at_fifteen_words():
    topic = " ".join(f"w{i}" for i in range(30))
    assert clean_topic(topic, "requirement").split() == [f"w{i}" for i in range(15)]


def test_topic_whitespace_is_normalised_and_chars_capped():
    assert clean_topic("  HEGAM \n demerger  ", "req") == "HEGAM demerger"
    assert len(clean_topic("x" * 500, "req")) == 120


@pytest.mark.parametrize("bad", [None, "", "   ", 7, ["a"], {"a": 1}])
def test_unusable_topic_falls_back_to_requirement_prefix(bad):
    assert clean_topic(bad, "r" * 300) == "r" * 120
    assert clean_topic(bad, "  short requirement  ") == "short requirement"


# --- suggested events --------------------------------------------------------

def test_suggested_events_are_disabled_capped_and_attributed():
    raw = [
        {"at_sim_hour": 5, "poster_type": "MediaOutlet", "content": " Hypothetical headline "},
        {"at_sim_hour": 9999, "poster_type": "Official", "content": "Late"},
        {"at_sim_hour": -4, "content": "Early, no poster"},
        {"at_sim_hour": 7, "poster_type": "Student", "content": "Fourth is dropped"},
    ]
    out = sanitize_suggested_events(raw, total_hours=48)
    assert len(out) == 3
    assert all(e["enabled"] is False and e["source"] == "llm_suggested" for e in out)
    assert [e["id"] for e in out] == ["sug_1", "sug_2", "sug_3"]
    assert out[0]["content"] == "Hypothetical headline" and out[0]["at_sim_hour"] == 5
    assert out[1]["at_sim_hour"] == 47  # clamped to the last simulated hour
    assert out[2]["at_sim_hour"] == 0 and out[2]["poster_type"] == "Unknown"


@pytest.mark.parametrize("bad", [None, "text", 5, {}, [None, 3, "x", {"content": ""}, {"content": 7}, {"content": "  "}]])
def test_unusable_suggestions_are_dropped(bad):
    assert sanitize_suggested_events(bad, 72) == []


# --- poster assignment -------------------------------------------------------

def _agents_as_dicts():
    return [
        {"agent_id": 0, "entity_type": "Organization", "influence_weight": 1.0},
        {"agent_id": 1, "entity_type": "MediaOutlet", "influence_weight": 2.0},
        {"agent_id": 2, "entity_type": "MediaOutlet", "influence_weight": 1.5},
        {"agent_id": 3, "entity_type": "Student", "influence_weight": 0.8},
    ]


def test_poster_assignment_matches_type_and_rotates_agents():
    posts = [{"content": "a", "poster_type": "MediaOutlet"}, {"content": "b", "poster_type": "mediaoutlet"},
             {"content": "c", "poster_type": "MediaOutlet"}]
    out = assign_poster_agents(posts, _agents_as_dicts())
    assert [p["poster_agent_id"] for p in out] == [1, 2, 1]


def test_poster_assignment_uses_aliases_then_influence_fallback():
    out = assign_poster_agents(
        [{"content": "x", "poster_type": "Media"}, {"content": "y", "poster_type": "Wizard"}],
        _agents_as_dicts(),
    )
    assert out[0]["poster_agent_id"] == 1
    assert out[1]["poster_agent_id"] == 1  # most influential agent


def test_poster_assignment_accepts_dataclass_agents_and_keeps_the_legacy_shape():
    agents = [
        AgentActivityConfig(agent_id=7, entity_uuid="u", entity_name="n", entity_type="Student", influence_weight=0.9),
    ]
    out = assign_poster_agents([{"content": "hi", "poster_type": "Student", "extra": 1}], agents)
    assert out == [{"content": "hi", "poster_type": "Student", "poster_agent_id": 7}]
    kept = assign_poster_agents([{"content": "hi", "poster_type": "Student", "extra": 1}], agents, preserve_fields=True)
    assert kept == [{"content": "hi", "poster_type": "Student", "extra": 1, "poster_agent_id": 7}]
    assert assign_poster_agents([], agents) == []


# --- the generated config ----------------------------------------------------

def _entities():
    return [
        EntityNode(uuid="u1", name="HEG Graphite", labels=["Entity", "Organization"], summary="a company", attributes={}),
        EntityNode(uuid="u2", name="Market Media", labels=["Entity", "MediaOutlet"], summary="news", attributes={}),
        EntityNode(uuid="u3", name="Retail Trader", labels=["Entity", "Person"], summary="trader", attributes={}),
    ]


class FakeLLM:
    """Stands in for ``_call_llm_with_retry``, answering by prompt content."""

    def __init__(self):
        self.prompts = []

    def __call__(self, prompt, system_prompt):
        self.prompts.append((prompt, system_prompt))
        if "时间模拟配置" in prompt:
            return {"total_simulation_hours": 48, "minutes_per_round": 60,
                    "agents_per_hour_min": 1, "agents_per_hour_max": 2, "reasoning": "r"}
        if "生成事件配置" in prompt:
            return {
                "hot_topics": ["demerger"],
                "topic": "HEGAM share price reaction after the demerger " + "word " * 30,
                "narrative_direction": "SECRET hypothesis: the price will fall",
                "initial_posts": [{"content": "Official note", "poster_type": "Organization"}],
                "scheduled_events": [{"at_sim_hour": 3, "content": "LLM invented this", "poster_agent_id": 0}],
                "suggested_events": [
                    {"at_sim_hour": 10, "poster_type": "MediaOutlet", "content": "What if a broker downgrades?"},
                    {"at_sim_hour": 12, "poster_type": "Person", "content": "What if volumes spike?"},
                    {"at_sim_hour": 14, "poster_type": "Organization", "content": "What if a filing is delayed?"},
                    {"at_sim_hour": 16, "poster_type": "Person", "content": "Fourth, dropped"},
                ],
                "reasoning": "ok",
            }
        if "社交媒体活动配置" in prompt:
            return {"agent_configs": [
                {"agent_id": 0, "activity_level": 7, "stance": "BULLISH", "sentiment_bias": 3,
                 "response_delay_min": 300, "response_delay_max": 20, "posts_per_hour": -1,
                 "comments_per_hour": "lots", "influence_weight": 99, "active_hours": [30, 9, 9]},
                {"agent_id": 1, "stance": "observer", "sentiment_bias": 0.2},
                # agent 2 is missing: rule-based defaults apply
            ]}
        raise AssertionError("unexpected prompt")


@pytest.fixture
def generated():
    set_locale("en")
    generator = SimulationConfigGenerator(api_key="k", base_url="http://127.0.0.1:1/v1", model_name="m")
    fake = FakeLLM()
    generator._call_llm_with_retry = fake
    params = generator.generate_config(
        simulation_id="sim_x", project_id="proj_x", graph_id="graph_x",
        simulation_requirement="Will HEGAM trade higher after the demerger?",
        document_text="doc", entities=_entities(),
    )
    return params, params.to_dict(), fake


def test_generated_config_is_behavior_v2_with_run_block_and_locale(generated):
    params, data, _ = generated
    assert data["behavior_version"] == 2
    assert data["run"] == {"seed": None, "replicate_index": None, "ensemble_id": None}
    assert data["locale"] == "en"


def test_generated_locale_follows_the_active_locale():
    set_locale("zh")
    try:
        generator = SimulationConfigGenerator(api_key="k", base_url="http://127.0.0.1:1/v1", model_name="m")
        generator._call_llm_with_retry = FakeLLM()
        params = generator.generate_config(
            simulation_id="s", project_id="p", graph_id="g", simulation_requirement="req",
            document_text="", entities=_entities(),
        )
        assert params.to_dict()["locale"] == "zh"
    finally:
        set_locale("en")


def test_scheduled_events_stay_empty_and_suggestions_are_disabled(generated):
    _, data, _ = generated
    event_config = data["event_config"]
    assert event_config["scheduled_events"] == []
    suggested = event_config["suggested_events"]
    assert len(suggested) == 3
    assert all(e["enabled"] is False and e["source"] == "llm_suggested" for e in suggested)
    assert all(isinstance(e["poster_agent_id"], int) for e in suggested)
    assert suggested[0]["poster_agent_id"] == 1  # the MediaOutlet agent


def test_topic_is_stored_short(generated):
    _, data, _ = generated
    topic = data["event_config"]["topic"]
    assert topic.startswith("HEGAM share price reaction")
    assert len(topic.split()) <= 15


def test_narrative_direction_is_kept_as_a_hypothesis_only(generated):
    _, data, _ = generated
    assert data["event_config"]["narrative_direction"].startswith("SECRET hypothesis")


def test_v2_platform_configs_drop_the_unsupported_keys(generated):
    _, data, _ = generated
    assert data["twitter_config"] == {"platform": "twitter", "echo_chamber_strength": 0.5}
    assert data["reddit_config"] == {"platform": "reddit", "echo_chamber_strength": 0.6}


def test_agent_fields_are_sanitised_in_the_generated_config(generated):
    _, data, _ = generated
    first = data["agent_configs"][0]
    assert first["stance"] == "neutral"  # "BULLISH" is not a stance
    assert first["activity_level"] == 1.0
    assert first["sentiment_bias"] == 1.0
    assert first["influence_weight"] == 5.0
    assert (first["response_delay_min"], first["response_delay_max"]) == (300, 300)
    assert first["posts_per_hour"] == 0.0 and first["comments_per_hour"] == 1.0
    assert first["active_hours"] == [9]
    assert data["agent_configs"][1]["stance"] == "observer"
    # the agent the LLM skipped still gets a complete, valid rule-based config
    third = data["agent_configs"][2]
    assert third["stance"] in gen.VALID_STANCES and third["active_hours"]


def test_generated_config_is_json_serialisable_and_round_trips(generated):
    params, data, _ = generated
    assert json.loads(params.to_json()) == data


def test_event_prompt_asks_for_a_topic_and_warns_against_invented_facts(generated):
    _, _, fake = generated
    event_prompt = next(p for p, _ in fake.prompts if "生成事件配置" in p)
    assert '"topic"' in event_prompt and "suggested_events" in event_prompt
    assert "不要把虚构的内容写成既成事实" in event_prompt


# --- legacy configs ----------------------------------------------------------

def test_legacy_platform_keys_are_still_emitted_for_behavior_v1():
    params = SimulationParameters(
        simulation_id="s", project_id="p", graph_id="g", simulation_requirement="r",
        twitter_config=PlatformConfig(platform="twitter"), behavior_version=1,
    )
    twitter = params.to_dict()["twitter_config"]
    assert {"recency_weight", "popularity_weight", "relevance_weight", "viral_threshold"} <= set(twitter)
    assert params.to_dict()["behavior_version"] == 1


def test_event_config_dataclass_defaults():
    event_config = EventConfig()
    assert event_config.scheduled_events == [] and event_config.suggested_events == []
    assert event_config.topic == ""
