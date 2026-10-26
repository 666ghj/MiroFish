"""Config generation: model timeouts, malformed agent entries, poster assignment, progress reporting.

These cover what went wrong while preparing a real simulation: one agent-config request took 6.5 minutes with no
sign of life, a model entry without ``agent_id`` threw away a whole batch, and seven opening posts all landed on the
same agent because the model invented poster types.
"""
import json
from types import SimpleNamespace

import httpx
import pytest
from openai import APITimeoutError

from app.config import Config
from app.services import simulation_config_generator as gen
from app.services import simulation_manager as simulation_manager_module
from app.services.simulation_config_generator import (
    SimulationConfigGenerator,
    assign_poster_agents,
    index_agent_configs,
)
from app.services.simulation_manager import SimulationManager, SimulationState, SimulationStatus
from app.services.zep_entity_reader import EntityNode, FilteredEntities
from app.utils.locale import set_locale


@pytest.fixture(autouse=True)
def english():
    set_locale("en")
    yield
    set_locale("en")


def make_generator(**kwargs):
    return SimulationConfigGenerator(api_key="k", base_url="http://127.0.0.1:1/v1", model_name="m", **kwargs)


def entity(name, entity_type="Organization"):
    return EntityNode(uuid=f"u-{name}", name=name, labels=["Entity", entity_type], summary="", attributes={})


# --- request timeout ---------------------------------------------------------

def test_client_waits_a_bounded_time_and_does_not_retry_silently():
    generator = make_generator()
    assert generator.request_timeout == Config.LLM_REQUEST_TIMEOUT
    assert generator.client.max_retries == 0
    assert generator.client.timeout.read == Config.LLM_REQUEST_TIMEOUT
    assert generator.client.timeout.connect <= 15


def test_request_timeout_can_be_chosen_and_bad_values_fall_back():
    assert make_generator(request_timeout=45).client.timeout.read == 45
    assert make_generator(request_timeout=5).client.timeout.connect == 5
    assert make_generator(request_timeout=-3).request_timeout == gen.DEFAULT_LLM_REQUEST_TIMEOUT


def ok_response(payload):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)), finish_reason="stop")]
    )


def timeout_error():
    return APITimeoutError(request=httpx.Request("POST", "http://127.0.0.1:1/v1/chat/completions"))


class Throttled(Exception):
    status_code = 402


def script_llm(monkeypatch, steps):
    """Make the generator's model call play ``steps``: an exception is raised, anything else is returned."""
    calls = []

    def fake(client, **kwargs):
        calls.append(kwargs)
        step = steps[len(calls) - 1]
        if isinstance(step, BaseException):
            raise step
        return step

    monkeypatch.setattr(gen, "create_chat_completion", fake)
    sleeps = []
    monkeypatch.setattr(gen.time, "sleep", sleeps.append)
    return calls, sleeps


def test_a_timed_out_request_is_retried_and_the_user_is_told(monkeypatch):
    calls, sleeps = script_llm(monkeypatch, [timeout_error(), ok_response({"ok": 1})])
    generator = make_generator(request_timeout=120)
    notes = []
    generator._status_note = notes.append

    assert generator._call_llm_with_retry("p", "s") == {"ok": 1}
    assert len(calls) == 2
    assert sleeps == [2]
    assert notes == ["model call 2/3 after: no complete reply within 120 s"]
    assert calls[1]["temperature"] < calls[0]["temperature"]


def test_it_gives_up_after_three_attempts_without_a_pointless_final_sleep(monkeypatch):
    calls, sleeps = script_llm(monkeypatch, [timeout_error(), timeout_error(), timeout_error()])
    with pytest.raises(APITimeoutError):
        make_generator()._call_llm_with_retry("p", "s")
    assert len(calls) == 3
    assert sleeps == [2, 4]


def test_a_throttling_provider_gets_longer_pauses(monkeypatch):
    calls, sleeps = script_llm(monkeypatch, [Throttled("402 in-flight budget"), Throttled("again"), ok_response({"ok": 2})])
    generator = make_generator()
    notes = []
    generator._status_note = notes.append
    assert generator._call_llm_with_retry("p", "s") == {"ok": 2}
    assert sleeps == [5, 15]
    assert "in-flight budget" in notes[0]


def test_unparseable_replies_are_retried_with_a_reason(monkeypatch):
    garbage = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="sorry, no json here"), finish_reason="stop")]
    )
    _, sleeps = script_llm(monkeypatch, [garbage, ok_response({"ok": 3})])
    generator = make_generator()
    notes = []
    generator._status_note = notes.append
    assert generator._call_llm_with_retry("p", "s") == {"ok": 3}
    assert notes == ["model call 2/3 after: the reply was not valid JSON"]
    assert sleeps == []


def test_a_server_that_never_answers_is_cut_off_without_hidden_sdk_retries(monkeypatch):
    """The real OpenAI client against a socket that accepts the request and then says nothing."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    hits = []
    release = threading.Event()

    class Silent(BaseHTTPRequestHandler):
        def do_POST(self):
            hits.append(self.path)
            release.wait(10)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Silent)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    sleeps = []
    monkeypatch.setattr(gen.time, "sleep", sleeps.append)
    try:
        generator = SimulationConfigGenerator(
            api_key="k", base_url=f"http://127.0.0.1:{server.server_port}/v1", model_name="m", request_timeout=0.4
        )
        with pytest.raises(APITimeoutError):
            generator._call_llm_with_retry("p", "s")
    finally:
        release.set()
        server.shutdown()
        server.server_close()

    assert len(hits) == 3          # one request per attempt: the SDK did not add retries of its own
    assert sleeps == [2, 4]


def test_a_failing_progress_note_never_breaks_generation(monkeypatch):
    script_llm(monkeypatch, [timeout_error(), ok_response({"ok": 4})])
    generator = make_generator()

    def explode(_):
        raise RuntimeError("ui is gone")

    generator._status_note = explode
    assert generator._call_llm_with_retry("p", "s") == {"ok": 4}


# --- progress reaches the caller ---------------------------------------------

def test_generate_config_reports_every_step_and_waiting_notes():
    generator = make_generator()
    seen = []

    def fake_llm(prompt, system_prompt):
        if "时间模拟配置" in prompt:
            return {"total_simulation_hours": 24, "minutes_per_round": 60}
        if "生成事件配置" in prompt:
            return {"initial_posts": [], "hot_topics": []}
        generator._note("model call 2/3 after: no complete reply within 300 s")
        return {"agent_configs": []}

    generator._call_llm_with_retry = fake_llm
    generator.generate_config(
        simulation_id="s", project_id="p", graph_id="g", simulation_requirement="req", document_text="",
        entities=[entity("A"), entity("B")],
        progress_callback=lambda step, total, message: seen.append((step, total, message)),
    )

    steps = [(step, total) for step, total, message in seen if "no complete reply" not in message]
    assert steps == [(1, 4), (2, 4), (3, 4), (4, 4)]
    waiting = [message for _, _, message in seen if "no complete reply" in message]
    assert waiting == ["Generating agent config (1-2/2)... (model call 2/3 after: no complete reply within 300 s)"]
    assert generator._status_note is None  # released once the config is complete


def test_the_manager_forwards_config_steps_to_the_ui(tmp_path, monkeypatch):
    class Reader:
        def filter_defined_entities(self, **kwargs):
            return FilteredEntities(entities=[entity("A")], entity_types={"Organization"}, total_count=1, filtered_count=1)

    class Profiles:
        def __init__(self, **kwargs):
            pass

        def generate_profiles_from_entities(self, **kwargs):
            return [object()]

        def save_profiles(self, **kwargs):
            pass

    class ConfigGenerator:
        def generate_config(self, progress_callback=None, **kwargs):
            progress_callback(1, 5, "time config")
            progress_callback(3, 5, "agent config (waiting)")
            return SimpleNamespace(to_json=lambda: "{}", generation_reasoning="r")

    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(simulation_manager_module, "ZepEntityReader", Reader)
    monkeypatch.setattr(simulation_manager_module, "OasisProfileGenerator", Profiles)
    monkeypatch.setattr(simulation_manager_module, "SimulationConfigGenerator", ConfigGenerator)

    manager = SimulationManager()
    manager._save_simulation_state(
        SimulationState(simulation_id="sim_p", project_id="proj", graph_id="graph", status=SimulationStatus.CREATED)
    )
    calls = []
    manager.prepare_simulation(
        simulation_id="sim_p", simulation_requirement="req", document_text="doc",
        progress_callback=lambda stage, progress, message, **kw: calls.append((stage, progress, message, kw)),
    )

    forwarded = [c for c in calls if c[2] in ("time config", "agent config (waiting)")]
    assert [(c[0], c[1], c[3]) for c in forwarded] == [
        ("generating_config", 30, {"current": 1, "total": 5}),
        ("generating_config", 46, {"current": 3, "total": 5}),
    ]
    progress = [c[1] for c in calls if c[0] == "generating_config"]
    assert progress == sorted(progress)  # the bar never moves backwards


# --- malformed agent entries -------------------------------------------------

def test_index_keeps_valid_entries_and_drops_the_rest():
    result = {"agent_configs": [
        {"agent_id": 15, "stance": "opposing"},
        {"stance": "supportive"},                    # no agent_id: the entry that used to crash the batch
        {"agent_id": "16", "stance": "observer"},    # numeric string
        {"agent_id": 17.0},                          # integral float, but not part of this batch
        {"agent_id": True}, {"agent_id": None}, {"agent_id": "x"}, {"agent_id": 15.5},
        "not an object", None, 7,
    ]}
    indexed = index_agent_configs(result, [15, 16])
    assert sorted(indexed) == [15, 16]
    assert indexed[15]["stance"] == "opposing" and indexed[16]["stance"] == "observer"


@pytest.mark.parametrize("result", [None, [], "text", {}, {"agent_configs": None}, {"agent_configs": "x"}, {"agent_configs": {"agent_id": 1}}])
def test_index_survives_unusable_replies(result):
    assert index_agent_configs(result, [0, 1]) == {}


def test_one_malformed_entry_only_costs_that_agent_its_model_config():
    generator = make_generator()
    generator._call_llm_with_retry = lambda prompt, system_prompt: {"agent_configs": [
        {"stance": "opposing", "influence_weight": 2.0},                    # lost its agent_id
        {"agent_id": 16, "stance": "supportive", "influence_weight": 2.5},
    ]}
    configs = generator._generate_agent_configs_batch(
        context="", entities=[entity("Fifteen"), entity("Sixteen")], start_idx=15, simulation_requirement="req"
    )
    assert [c.agent_id for c in configs] == [15, 16]
    assert configs[1].stance == "supportive" and configs[1].influence_weight == 2.5   # kept from the model
    assert configs[0].stance != "opposing"                                           # rule-based defaults instead


def test_a_failed_batch_call_still_falls_back_to_rules_for_everyone():
    generator = make_generator()

    def boom(prompt, system_prompt):
        raise RuntimeError("provider is down")

    generator._call_llm_with_retry = boom
    configs = generator._generate_agent_configs_batch(
        context="", entities=[entity("A"), entity("B")], start_idx=0, simulation_requirement="req"
    )
    assert [c.agent_id for c in configs] == [0, 1]


# --- poster assignment -------------------------------------------------------

def agents():
    return [
        {"agent_id": 0, "entity_type": "Organization", "entity_name": "Ministry of Home Affairs", "influence_weight": 2.0},
        {"agent_id": 1, "entity_type": "GovernmentOfficial", "entity_name": "Jyotiraditya Scindia", "influence_weight": 2.5},
        {"agent_id": 2, "entity_type": "CorporateEntity", "entity_name": "Reliance Jio", "influence_weight": 1.8},
        {"agent_id": 3, "entity_type": "CorporateEntity", "entity_name": "Reliance Industries", "influence_weight": 2.2},
        {"agent_id": 4, "entity_type": "Organization", "entity_name": "satcom applicants", "influence_weight": 1.0},
        {"agent_id": 5, "entity_type": "Organization", "entity_name": "Department of Telecommunications (DoT)", "influence_weight": 3.0},
        {"agent_id": 6, "entity_type": "Organization", "entity_name": "TRAI", "influence_weight": 1.5},
        {"agent_id": 7, "entity_type": "Organization", "entity_name": "Vodafone Idea", "influence_weight": 0.9},
    ]


def assign(poster_types, agent_list=None):
    posts = [{"content": f"post {i}", "poster_type": t} for i, t in enumerate(poster_types)]
    return [p["poster_agent_id"] for p in assign_poster_agents(posts, agent_list if agent_list is not None else agents())]


def test_the_real_run_no_longer_puts_every_opening_post_on_one_agent():
    # the poster types the model actually returned for the HEGAM-style run, none of them an entity type
    ids = assign([
        "telecom sector analysts", "retail traders", "policy and regulatory commentators",
        "domestic mutual fund managers", "f&o traders", "ministry of home affairs", "department of telecommunications",
    ])
    assert ids[5] == 0            # written as the entity's name
    assert ids[6] == 5            # name contained in "Department of Telecommunications (DoT)"
    unmatched = ids[:5]
    assert len(set(unmatched)) == 5
    assert unmatched == [5, 1, 3, 0, 2]   # most influential first, one post each


@pytest.mark.parametrize("written", ["GovernmentOfficial", "government official", "Government_Official", "GOVERNMENT-OFFICIAL"])
def test_type_matching_ignores_case_spacing_and_punctuation(written):
    assert assign([written]) == [1]


def test_a_type_contained_in_a_real_type_matches_it():
    assert assign(["Official"]) == [1]
    assert assign(["corporate"]) == [2]
    assert assign(["Government officials"]) == [1]


def test_entity_names_match_exactly_before_partially():
    people = agents() + [
        {"agent_id": 8, "entity_type": "Organization", "entity_name": "Reliance Industries Limited", "influence_weight": 1.0},
    ]
    assert assign(["Reliance Industries"], people) == [3]            # exact beats the longer name
    assert assign(["Reliance Industries Limited"], people) == [8]
    assert assign(["jio"], people) != [2]                            # too short to match by containment


def test_short_fragments_do_not_match_by_containment():
    people = [
        {"agent_id": 0, "entity_type": "Organization", "entity_name": "Alpha", "influence_weight": 0.5},
        {"agent_id": 1, "entity_type": "Person", "entity_name": "Beta", "influence_weight": 3.0},
    ]
    assert assign(["Org"], people) == [1]      # falls back to the most influential agent, not the Organization


def test_alias_types_still_work():
    people = [
        {"agent_id": 0, "entity_type": "MediaOutlet", "entity_name": "Daily", "influence_weight": 1.0},
        {"agent_id": 1, "entity_type": "Student", "entity_name": "Sam", "influence_weight": 2.0},
    ]
    assert assign(["Media", "media outlet", "Person"], people) == [0, 0, 1]


def test_fallback_wraps_around_when_there_are_more_unmatched_posts_than_agents():
    people = [
        {"agent_id": 0, "entity_type": "Organization", "entity_name": "A", "influence_weight": 1.0},
        {"agent_id": 1, "entity_type": "Organization", "entity_name": "B", "influence_weight": 2.0},
    ]
    assert assign(["x", "y", "z", "w"], people) == [1, 0, 1, 0]


@pytest.mark.parametrize("poster_type", [None, "", "   ", "???", 5])
def test_unusable_poster_types_fall_back_instead_of_crashing(poster_type):
    assert assign([poster_type]) == [5]   # the most influential agent


def test_missing_or_bad_influence_weights_do_not_break_the_fallback():
    people = [
        {"agent_id": 0, "entity_type": "A", "entity_name": "a"},
        {"agent_id": 1, "entity_type": "B", "entity_name": "b", "influence_weight": None},
        {"agent_id": 2, "entity_type": "C", "entity_name": "c", "influence_weight": "high"},
        {"agent_id": 3, "entity_type": "D", "entity_name": "d", "influence_weight": 4.0},
    ]
    assert assign(["unknown"], people)[0] == 3
    assert assign(["unknown"], []) == [0]


def test_the_event_prompt_names_the_allowed_poster_types():
    generator = make_generator()
    seen = {}

    def capture(prompt, system_prompt):
        seen["prompt"] = prompt
        return {}

    generator._call_llm_with_retry = capture
    generator._generate_event_config(
        "context", "requirement",
        [entity("A", "Organization"), entity("B", "GovernmentOfficial"), entity("C", "Organization")],
    )
    prompt = seen["prompt"]
    assert "Organization / GovernmentOfficial" in prompt
    assert '"poster_type": "<Organization / GovernmentOfficial>"' in prompt
    assert "Official/University" not in prompt   # the old example named types that may not exist


def test_a_reasoning_block_before_the_json_costs_no_retry(monkeypatch):
    """Gemma writes <thought>…{braces}…</thought> and then a fenced answer."""
    reply = SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(content='<thought>plan: {"a": [1</thought>```json\n{"ok": 3}\n```'),
            finish_reason="stop",
        )]
    )
    calls, sleeps = script_llm(monkeypatch, [reply])
    assert make_generator()._call_llm_with_retry("p", "s") == {"ok": 3}
    assert len(calls) == 1 and sleeps == []


def raw_response(text):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason="stop")])


def test_a_reply_that_is_a_one_item_list_is_unwrapped(monkeypatch):
    calls, _ = script_llm(monkeypatch, [raw_response('[{"initial_posts": []}]')])
    assert make_generator()._call_llm_with_retry("p", "s") == {"initial_posts": []}
    assert len(calls) == 1


def test_a_reply_that_is_not_an_object_is_retried_not_returned(monkeypatch):
    calls, _ = script_llm(monkeypatch, [raw_response('[1, 2]'), raw_response('"text"'), raw_response('{"ok": 4}')])
    assert make_generator()._call_llm_with_retry("p", "s") == {"ok": 4}
    assert len(calls) == 3


def test_it_gives_up_with_a_clear_error_when_every_reply_is_a_list(monkeypatch):
    script_llm(monkeypatch, [raw_response('[1, 2]')] * 3)
    with pytest.raises(ValueError, match="expected a JSON object"):
        make_generator()._call_llm_with_retry("p", "s")


def test_a_separate_preparation_model_is_used_for_personas_and_config(monkeypatch):
    from app.config import Config
    from app.services.oasis_profile_generator import OasisProfileGenerator

    monkeypatch.setattr(Config, "LLM_PREP_API_KEY", "prep-key")
    monkeypatch.setattr(Config, "LLM_PREP_MODEL_NAME", "fast-model")
    monkeypatch.setattr(Config, "LLM_PREP_BASE_URL", None)
    monkeypatch.setattr(Config, "LLM_BASE_URL", "https://main.example/v1")

    config_generator = gen.SimulationConfigGenerator()
    profile_generator = OasisProfileGenerator()
    for generator in (config_generator, profile_generator):
        assert generator.model_name == "fast-model"
        assert generator.api_key == "prep-key"
        assert generator.base_url == "https://main.example/v1"   # falls back to the main endpoint


def test_without_a_preparation_model_the_main_one_is_used(monkeypatch):
    from app.config import Config

    monkeypatch.setattr(Config, "LLM_PREP_API_KEY", None)
    monkeypatch.setattr(Config, "LLM_PREP_MODEL_NAME", "fast-model")   # key missing: not usable
    assert Config.prep_llm()["model_name"] == Config.LLM_MODEL_NAME


def test_the_report_and_its_tools_use_the_preparation_model(monkeypatch):
    from app.config import Config
    from app.services.report_agent import ReportAgent
    from app.services.zep_tools import ZepToolsService
    from app.utils.llm_client import LLMClient

    monkeypatch.setattr(Config, "LLM_PREP_API_KEY", "prep-key")
    monkeypatch.setattr(Config, "LLM_PREP_MODEL_NAME", "strong-model")
    monkeypatch.setattr(Config, "LLM_PREP_BASE_URL", "https://prep.example/v1")

    assert LLMClient.for_preparation().model == "strong-model"
    assert LLMClient.for_preparation().base_url == "https://prep.example/v1"
    agent = ReportAgent("graph_1", "sim_x", "requirement", zep_tools=object())
    assert agent.llm.model == "strong-model" and agent.llm.api_key == "prep-key"
    assert ZepToolsService.llm.fget(SimpleNamespace(_llm_client=None)).model == "strong-model"


def test_without_a_preparation_model_the_report_uses_the_main_one(monkeypatch):
    from app.config import Config
    from app.services.report_agent import ReportAgent

    monkeypatch.setattr(Config, "LLM_PREP_API_KEY", None)
    monkeypatch.setattr(Config, "LLM_PREP_MODEL_NAME", None)
    assert ReportAgent("graph_1", "sim_x", "requirement", zep_tools=object()).llm.model == Config.LLM_MODEL_NAME
