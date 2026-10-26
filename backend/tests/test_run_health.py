"""Telling the user why a run does nothing: failed model calls, the live round status and the health verdict.

OASIS swallows an exception from the model (it logs it and returns it), so before this a run whose provider
refused every request looked like a run that was merely slow.
"""
import asyncio
import time
import json

import pytest

import action_logger
import sim_runtime
from app.services.simulation_runner import SimulationRunner, SimulationRunState


# --- classifying failures ----------------------------------------------------

class WithStatus(Exception):
    def __init__(self, status, text="boom"):
        super().__init__(text)
        self.status_code = status


class APITimeoutError(Exception):
    pass


class ConnectError(Exception):
    pass


@pytest.mark.parametrize(
    "error,kind",
    [
        (WithStatus(402), "http_402"),
        (WithStatus(429), "http_429"),
        (WithStatus(401), "auth"),
        (WithStatus(403), "auth"),
        (WithStatus(408), "timeout"),
        (WithStatus(503), "http_5xx"),
        (WithStatus(400), "other"),
        (RuntimeError("Error code: 402 - {'error': {'message': 'This request requires more credits'}}"), "http_402"),
        ("Error code: 429 - slow down", "http_429"),
        (RuntimeError("HTTP 502 bad gateway"), "http_5xx"),
        (APITimeoutError("Request timed out."), "timeout"),
        (ConnectError("Connection error."), "connection"),
        (RuntimeError("something else entirely"), "other"),
    ],
)
def test_errors_are_classified(error, kind):
    assert sim_runtime.classify_error(error)[0] == kind


def test_the_message_is_short_and_on_one_line():
    _, message = sim_runtime.classify_error(RuntimeError("line one\n  line two " + "x" * 1000))
    assert "\n" not in message and len(message) <= sim_runtime.ERROR_MESSAGE_LIMIT


# --- the tracker around OASIS's swallowed errors -----------------------------

def make_agent_class(outcomes):
    """An OASIS-like agent whose model call returns a response or, like OASIS, *returns* the exception."""

    class Agent:
        def __init__(self, name):
            self.name = name

        async def perform_action_by_llm(self):
            return outcomes[self.name]

    return Agent


def run(coro):
    return asyncio.run(coro)


def test_a_returned_exception_is_recorded_for_the_agents_of_the_round():
    outcomes = {"a": "ok", "b": WithStatus(402, "no credit"), "c": WithStatus(429)}
    Agent = make_agent_class(outcomes)
    assert sim_runtime.install_failure_tracking(Agent) is True
    agents = {name: Agent(name) for name in outcomes}
    tracker = sim_runtime.FailureTracker()
    seen = []

    tracker.begin_round([(1, agents["a"]), (2, agents["b"]), (3, agents["c"])], on_failure=seen.append)

    async def step():
        return [await agent.perform_action_by_llm() for agent in agents.values()]

    results = run(step())
    assert results[0] == "ok" and isinstance(results[1], WithStatus)       # results pass through unchanged
    assert [(f["agent_id"], f["kind"]) for f in seen] == [(2, "http_402"), (3, "http_429")]   # reported at once
    done = tracker.end_round()
    assert [f["agent_id"] for f in done] == [2, 3] and done[0]["message"] == "no credit"
    assert tracker.end_round() == []


def test_agents_outside_the_round_and_later_rounds_are_not_counted():
    Agent = make_agent_class({"a": WithStatus(402), "b": WithStatus(402)})
    sim_runtime.install_failure_tracking(Agent)
    a, b = Agent("a"), Agent("b")
    tracker = sim_runtime.FailureTracker()

    tracker.begin_round([(1, a)])
    run(b.perform_action_by_llm())          # not woken this round
    assert tracker.end_round() == []

    run(a.perform_action_by_llm())          # the round is over: nobody is watching any more
    assert tracker.end_round() == []

    tracker.begin_round([(1, a)])
    run(a.perform_action_by_llm())
    assert len(tracker.end_round()) == 1    # a new round starts counting from zero


def test_two_platforms_do_not_see_each_others_failures():
    Agent = make_agent_class({"t": WithStatus(402), "r": "fine"})
    sim_runtime.install_failure_tracking(Agent)
    twitter_agent, reddit_agent = Agent("t"), Agent("r")
    twitter, reddit = sim_runtime.FailureTracker(), sim_runtime.FailureTracker()
    twitter.begin_round([(7, twitter_agent)])
    reddit.begin_round([(7, reddit_agent)])

    async def both():
        await asyncio.gather(twitter_agent.perform_action_by_llm(), reddit_agent.perform_action_by_llm())

    run(both())
    assert [f["kind"] for f in twitter.end_round()] == ["http_402"]
    assert reddit.end_round() == []


def test_installing_twice_wraps_once_and_a_broken_callback_cannot_stop_the_run():
    Agent = make_agent_class({"a": WithStatus(402)})
    assert sim_runtime.install_failure_tracking(Agent) is True
    assert sim_runtime.install_failure_tracking(Agent) is False
    tracker = sim_runtime.FailureTracker()

    def explode(_failure):
        raise RuntimeError("ui is gone")

    agent = Agent("a")
    tracker.begin_round([(1, agent)], on_failure=explode)
    assert isinstance(run(agent.perform_action_by_llm()), WithStatus)
    assert len(tracker.end_round()) == 1


# --- the events in actions.jsonl ---------------------------------------------

def read_events(path):
    return [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]


def test_the_platform_logger_writes_failures_round_ends_and_poll_status(tmp_path):
    log = action_logger.PlatformActionLogger("twitter", str(tmp_path))
    log.log_round_start(3, 9, active_agent_ids=[1, 2, 3])
    log.log_agent_error(3, 2, "http_402", "no credit")
    log.log_round_end(3, 1, failed_count=2)
    log.log_round_end(4, 0)
    log.log_poll_status({"state": "waiting", "answered": 0, "total": 3, "attempt": 1})

    events = read_events(log.log_path)
    assert events[1]["event_type"] == "agent_error" and events[1]["error_kind"] == "http_402"
    assert events[2]["failed_count"] == 2
    assert "failed_count" not in events[3]                      # older callers keep the old shape
    assert events[4]["event_type"] == "poll_status" and events[4]["answered"] == 0


# --- the live status and the verdict -----------------------------------------

def fresh_state():
    return SimulationRunState(simulation_id="sim_health")


def feed(state, tmp_path, events, platform="twitter"):
    path = tmp_path / f"{platform}.jsonl"
    path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    SimulationRunner._read_action_log(str(path), 0, state, platform)


def round_events(number, woken, failed, acted=0, kind="http_402"):
    events = [{"event_type": "round_start", "round": number, "active_agent_ids": list(range(woken))}]
    events += [
        {"event_type": "agent_error", "round": number, "agent_id": i, "error_kind": kind,
         "message": "Error code: 402 - no credit", "timestamp": f"2026-10-10T02:00:{number:02d}"}
        for i in range(failed)
    ]
    events.append({"event_type": "round_end", "round": number, "actions_count": acted, "failed_count": failed})
    return events


def test_the_status_shows_the_round_in_progress(tmp_path):
    state = fresh_state()
    feed(state, tmp_path, [
        {"event_type": "round_start", "round": 12, "active_agent_ids": [1, 2, 3, 4, 5, 6]},
        {"event_type": "agent_error", "round": 12, "agent_id": 2, "error_kind": "http_402", "message": "m"},
        {"event_type": "agent_error", "round": 12, "agent_id": 4, "error_kind": "http_402", "message": "m"},
    ])
    assert state.activity["twitter"] == {"round": 12, "woken": 6, "failed": 2, "acted": None, "state": "running"}


def test_a_finished_round_reports_what_was_done(tmp_path):
    state = fresh_state()
    feed(state, tmp_path, round_events(5, woken=4, failed=1, acted=3))
    assert state.activity["twitter"] == {"round": 5, "woken": 4, "failed": 1, "acted": 3, "state": "done"}


def test_each_platform_has_its_own_status(tmp_path):
    state = fresh_state()
    feed(state, tmp_path, round_events(2, 3, 0, acted=3), platform="twitter")
    feed(state, tmp_path, round_events(9, 5, 5), platform="reddit")
    assert state.activity["twitter"]["round"] == 2 and state.activity["reddit"]["round"] == 9


def test_most_agents_failing_is_an_error_with_the_providers_reason(tmp_path):
    state = fresh_state()
    for number in (1, 2, 3):
        feed(state, tmp_path, round_events(number, woken=6, failed=6))
    health = state.health()
    assert health["level"] == "error" and health["kind"] == "http_402"
    assert "402" in health["message"]
    assert health["recent_failed"] == 18 and health["total_failed"] == 18
    assert state.failures["kinds"] == {"http_402": 18}


def test_a_few_failures_are_only_a_warning_and_one_is_ignored(tmp_path):
    state = fresh_state()
    feed(state, tmp_path, round_events(1, woken=10, failed=1))
    assert state.health()["level"] == "ok"
    assert state.health()["recent_failed"] == 1                 # one failure in ten is noise
    feed(state, tmp_path, round_events(2, woken=6, failed=3))    # 4 of 16 woken agents failed: 25%
    assert state.health()["level"] == "warning"


def test_the_warning_goes_away_when_the_provider_recovers(tmp_path):
    state = fresh_state()
    feed(state, tmp_path, round_events(1, woken=6, failed=6))
    assert state.health()["level"] == "error"
    for number in range(2, 8):
        feed(state, tmp_path, round_events(number, woken=6, failed=0, acted=6))
    health = state.health()
    assert health["level"] == "ok" and health["kind"] is None
    assert health["total_failed"] == 6          # history is kept, the verdict only looks at the latest rounds


def test_rounds_in_which_nobody_woke_are_not_failures(tmp_path):
    state = fresh_state()
    for number in range(1, 6):
        feed(state, tmp_path, round_events(number, woken=0, failed=0))
    assert state.health()["level"] == "ok"


def test_old_logs_without_the_new_fields_still_parse(tmp_path):
    state = fresh_state()
    feed(state, tmp_path, [
        {"event_type": "round_start", "round": 1, "simulated_hour": 9},                  # no active_agent_ids
        {"event_type": "round_end", "round": 1, "actions_count": 4},                    # no failed_count
    ])
    assert state.activity["twitter"]["woken"] is None and state.activity["twitter"]["acted"] == 4
    assert state.health()["level"] == "ok"


def test_the_poll_failing_is_reported_and_clears_when_answers_arrive(tmp_path):
    state = fresh_state()
    feed(state, tmp_path, [{"event_type": "poll_status", "state": "waiting", "answered": 0, "total": 17,
                            "attempt": 1, "max_attempts": 3, "retry_in": 15, "error_kind": "http_402",
                            "message": "Error code: 402 - no credit"}])
    health = state.health()
    assert health["level"] == "error" and health["source"] == "poll" and health["kind"] == "http_402"
    assert state.poll["answered"] == 0 and state.poll["attempt"] == 1

    feed(state, tmp_path, [{"event_type": "poll_status", "state": "done", "answered": 17, "total": 17,
                            "attempt": 2, "max_attempts": 3, "retry_in": None, "error_kind": None, "message": None}])
    assert state.health()["level"] == "ok"


def test_some_agents_answering_makes_the_poll_a_warning(tmp_path):
    state = fresh_state()
    feed(state, tmp_path, [{"event_type": "poll_status", "state": "waiting", "answered": 12, "total": 17,
                            "attempt": 1, "max_attempts": 3, "error_kind": "http_429", "message": "slow"}])
    assert state.health()["level"] == "warning"


def test_activity_and_failures_survive_a_backend_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path))
    state = fresh_state()
    feed(state, tmp_path, round_events(4, woken=5, failed=5))
    feed(state, tmp_path, [{"event_type": "poll_status", "state": "running", "answered": 1, "total": 5}])
    SimulationRunner._save_run_state(state)

    loaded = SimulationRunner._load_run_state("sim_health")
    assert loaded.activity == state.activity and loaded.failures == state.failures and loaded.poll == state.poll
    assert loaded.health()["level"] == "error"
    payload = loaded.to_dict()
    assert payload["health"]["level"] == "error" and payload["activity"]["twitter"]["round"] == 4


def test_a_state_file_from_before_this_change_loads(tmp_path, monkeypatch):
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path))
    (tmp_path / "sim_old").mkdir()
    (tmp_path / "sim_old" / "run_state.json").write_text(
        json.dumps({"simulation_id": "sim_old", "runner_status": "running", "current_round": 3}), encoding="utf-8"
    )
    state = SimulationRunner._load_run_state("sim_old")
    assert state.activity == {} and state.poll is None and state.health()["level"] == "ok"


# --- the poll reports its progress -------------------------------------------

POLL_QUESTIONS = [{"id": "q1", "text": "Will it trade higher?", "type": "probability"}]


def poll_config(n):
    return {"agent_configs": [{"agent_id": i, "entity_name": f"Agent {i}", "stance": "neutral"} for i in range(n)]}


def test_the_final_poll_reports_who_answered_and_why_the_rest_did_not(monkeypatch):
    answers = json.dumps({"q1": 50, "reason": "r"})
    calls = []

    async def fake_batch(env, graph, db, prompts, **kwargs):
        calls.append(sorted(prompts))
        if len(calls) == 1:   # first pass: only agent 0 gets through, the others are refused
            return {
                i: ({"agent_id": i, "response": answers} if i == 0
                    else {"agent_id": i, "response": None, "error": "Error code: 402 - no credit"})
                for i in prompts
            }
        return {i: {"agent_id": i, "response": answers} for i in prompts}   # the provider recovers

    monkeypatch.setattr(sim_runtime, "batch_interview", fake_batch)
    seen = []
    rows = asyncio.run(sim_runtime.run_final_poll(
        None, None, "db", poll_config(3), POLL_QUESTIONS,
        retry_delays=(0, 0), log=lambda _m: None, status=seen.append,
    ))

    assert all(row["parse_ok"] for row in rows)
    assert [(s["state"], s["answered"], s["attempt"]) for s in seen] == [
        ("running", 0, 0), ("running", 1, 0), ("waiting", 1, 1), ("running", 3, 1), ("done", 3, 1),
    ]
    refused = seen[1]
    assert refused["total"] == 3 and refused["error_kind"] == "http_402" and refused["max_attempts"] == 2
    assert seen[2]["retry_in"] == 0 and seen[-1]["error_kind"] is None


def test_a_broken_status_callback_does_not_break_the_poll(monkeypatch):
    async def fake_batch(env, graph, db, prompts, **kwargs):
        return {i: {"agent_id": i, "response": json.dumps({"q1": 1})} for i in prompts}

    monkeypatch.setattr(sim_runtime, "batch_interview", fake_batch)

    def explode(_status):
        raise RuntimeError("ui is gone")

    rows = asyncio.run(sim_runtime.run_final_poll(
        None, None, "db", poll_config(2), POLL_QUESTIONS, retry_delays=(0,), log=lambda _m: None, status=explode,
    ))
    assert len(rows) == 2


# --- the ensemble progress view carries it to the UI --------------------------

def test_ensemble_progress_includes_each_runs_live_status(tmp_path, monkeypatch):
    from app.services.ensemble_runner import EnsembleManager

    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path))
    state = SimulationRunState(simulation_id="sim_r01", total_rounds=10)
    feed(state, tmp_path, round_events(4, woken=5, failed=5))
    SimulationRunner._save_run_state(state)
    ensemble = {
        "ensemble_id": "ens_health", "max_rounds": 10,
        "replicates": [
            {"index": 1, "simulation_id": "sim_r01", "status": "running"},
            {"index": 2, "simulation_id": "sim_r02", "status": "pending"},   # no run state yet
        ],
    }
    progress = EnsembleManager._with_progress(ensemble)

    first, second = progress["replicates"]
    assert first["health"]["level"] == "error" and first["health"]["kind"] == "http_402"
    assert first["activity"]["twitter"]["failed"] == 5
    assert second["health"] is None and second["activity"] == {} and second["poll"] is None


def test_a_line_still_being_written_is_read_on_the_next_poll(tmp_path):
    path = tmp_path / "actions.jsonl"
    state = SimulationRunState(simulation_id="sim_partial")
    first = json.dumps({"event_type": "round_start", "round": 1, "active_agent_ids": [1, 2]}) + "\n"
    second = json.dumps({"event_type": "round_end", "round": 1, "actions_count": 2, "failed_count": 0})
    path.write_bytes((first + second[:20]).encode("utf-8"))

    position = SimulationRunner._read_action_log(str(path), 0, state, "twitter")
    assert position == len(first.encode("utf-8"))
    assert state.current_round == 0

    with open(path, "ab") as handle:
        handle.write((second[20:] + "\n").encode("utf-8"))
    position = SimulationRunner._read_action_log(str(path), position, state, "twitter")
    assert state.current_round == 1
    assert position == path.stat().st_size


# --- model fallback -------------------------------------------------------------

class FakeBackend:
    def __init__(self, name, error=None):
        self.name, self.error, self.calls = name, error, 0

    def run(self, *args, **kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return f"{self.name}-answer"

    async def arun(self, *args, **kwargs):
        return self.run(*args, **kwargs)


class Status(Exception):
    def __init__(self, status, text="provider said no"):
        super().__init__(f"Error code: {status} - {text}")
        self.status_code = status


@pytest.mark.parametrize("error", [Status(429), Status(402), Status(500), Status(401), Status(413), TimeoutError("timed out")])
def test_a_call_the_primary_cannot_serve_goes_to_the_fallback(error):
    seen = []
    primary, backup = FakeBackend("main", error), FakeBackend("boost")
    sim_runtime.install_model_fallback(primary, backup, seen.append)

    assert primary.run([]) == "boost-answer"
    assert asyncio.run(primary.arun([])) == "boost-answer"
    assert primary.calls == 2 and backup.calls == 2 and len(seen) == 2


def test_a_healthy_primary_never_touches_the_fallback():
    primary, backup = FakeBackend("main"), FakeBackend("boost")
    sim_runtime.install_model_fallback(primary, backup)
    assert primary.run([]) == "main-answer" and backup.calls == 0


def test_errors_another_model_cannot_fix_are_not_retried():
    primary, backup = FakeBackend("main", Status(400, "bad parameter")), FakeBackend("boost")
    sim_runtime.install_model_fallback(primary, backup)
    with pytest.raises(Status):
        primary.run([])
    assert backup.calls == 0


def test_when_the_fallback_fails_too_its_error_is_raised_and_a_broken_callback_is_harmless():
    primary, backup = FakeBackend("main", Status(429)), FakeBackend("boost", Status(413, "too large"))

    def broken(error):
        raise RuntimeError("reporting failed")

    sim_runtime.install_model_fallback(primary, backup, broken)
    with pytest.raises(Status) as raised:
        primary.run([])
    assert raised.value.status_code == 413


# --- pacing the fallback ----------------------------------------------------------

def test_a_pacer_hands_out_slots_one_interval_apart(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(sim_runtime.time, "monotonic", lambda: clock[0])
    pacer = sim_runtime.Pacer(1.0)
    assert [pacer.reserve() for _ in range(3)] == [0.0, 1.0, 2.0]   # three callers arriving together
    clock[0] += 10                                                   # a quiet spell: no backlog
    assert pacer.reserve() == 0.0


def test_a_pacer_with_no_interval_never_waits():
    assert sim_runtime.Pacer(0).reserve() == 0.0


def test_fallback_calls_are_spaced_even_when_made_together():
    primary, backup = FakeBackend("main", Status(429)), FakeBackend("boost")
    started = []
    original = backup.run

    def timed(*args, **kwargs):
        started.append(time.monotonic())
        return original(*args, **kwargs)

    backup.run = timed   # FakeBackend.arun delegates to run, so this sees every fallback call
    sim_runtime.install_model_fallback(primary, backup, pacer=sim_runtime.Pacer(0.1))

    async def together():
        await asyncio.gather(*(primary.arun([]) for _ in range(3)))

    asyncio.run(together())
    # slots are 0.1 s apart; allow for the OS timer's granularity on each wake-up
    assert len(started) == 3 and started[-1] - started[0] >= 0.15


# --- per-request timeout and retries ----------------------------------------------

@pytest.mark.parametrize("env,expected", [
    ({}, {}),
    ({"LLM_MODEL_TIMEOUT": "60"}, {"timeout": 60.0}),
    ({"LLM_MODEL_MAX_RETRIES": "0"}, {"max_retries": 0}),
    ({"LLM_MODEL_TIMEOUT": "45", "LLM_MODEL_MAX_RETRIES": "1"}, {"timeout": 45.0, "max_retries": 1}),
    ({"LLM_MODEL_TIMEOUT": "abc", "LLM_MODEL_MAX_RETRIES": "x"}, {}),
    ({"LLM_MODEL_TIMEOUT": "-5", "LLM_MODEL_MAX_RETRIES": "-1"}, {}),
    ({"LLM_MODEL_TIMEOUT": "", "LLM_MODEL_MAX_RETRIES": ""}, {}),
])
def test_model_client_options_come_from_the_environment(env, expected):
    assert sim_runtime.model_client_options(env) == expected


def test_the_options_reach_a_real_camel_client():
    from camel.models import ModelFactory
    from camel.types import ModelPlatformType

    options = sim_runtime.model_client_options({"LLM_MODEL_TIMEOUT": "42", "LLM_MODEL_MAX_RETRIES": "0"})
    model = sim_runtime.apply_model_client_options(ModelFactory.create(
        model_platform=ModelPlatformType.OPENAI, model_type="m", api_key="k", url="http://127.0.0.1:1/v1",
        **options,
    ), options)
    assert model._timeout == 42.0
    assert model._client.max_retries == 0 and model._async_client.max_retries == 0   # camel alone leaves 3
    assert model._client.timeout == 42.0


# --- per-platform concurrency -----------------------------------------------------------

@pytest.mark.parametrize("platform,run_settings,env,expected", [
    ("twitter", None, {}, 30),                                                        # the default
    ("twitter", None, {"LLM_MAX_CONCURRENCY": "3"}, 3),                              # one number for both
    ("reddit", None, {"LLM_MAX_CONCURRENCY": "3"}, 3),
    ("twitter", None, {"LLM_MAX_CONCURRENCY": "1", "LLM_REDDIT_MAX_CONCURRENCY": "8"}, 1),   # per platform
    ("reddit", None, {"LLM_MAX_CONCURRENCY": "1", "LLM_REDDIT_MAX_CONCURRENCY": "8"}, 8),
    ("twitter", None, {"LLM_TWITTER_MAX_CONCURRENCY": "2"}, 2),                      # no general value needed
    ("reddit", None, {"LLM_TWITTER_MAX_CONCURRENCY": "2"}, 30),
    ("reddit", {"llm_semaphore": 5}, {}, 5),                                         # a config's own number
    ("reddit", {"llm_semaphore": 5}, {"LLM_REDDIT_MAX_CONCURRENCY": "8"}, 8),        # the environment wins
    ("twitter", {"llm_concurrency_share": 2, "llm_semaphore": 15}, {}, 15),         # replicates divide the default
    ("twitter", {"llm_concurrency_share": 2}, {"LLM_MAX_CONCURRENCY": "4"}, 2),
    ("reddit", {"llm_concurrency_share": 2}, {"LLM_MAX_CONCURRENCY": "4", "LLM_REDDIT_MAX_CONCURRENCY": "8"}, 4),
    ("reddit", {"llm_concurrency_share": 4}, {"LLM_REDDIT_MAX_CONCURRENCY": "2"}, 1),   # never below one
    ("twitter", None, {"LLM_MAX_CONCURRENCY": "abc", "LLM_TWITTER_MAX_CONCURRENCY": "0"}, 30),   # junk is ignored
    ("twitter", {"llm_concurrency_share": "x"}, {"LLM_MAX_CONCURRENCY": "6"}, 6),
])
def test_each_platform_gets_its_own_concurrency(platform, run_settings, env, expected):
    assert sim_runtime.platform_llm_concurrency(platform, run_settings, env) == expected
