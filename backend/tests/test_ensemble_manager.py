import hashlib
import json
import os
import threading
import time
from types import SimpleNamespace

import pytest

from app.services import ensemble_runner as er
from app.services.ensemble_runner import (
    EnsembleConflict,
    EnsembleError,
    EnsembleManager,
    EnsembleNotFound,
    derive_replicate_seed,
    estimate_cost,
    replicate_simulation_id,
)
from app.services.simulation_manager import SimulationManager, SimulationState, SimulationStatus
from app.services.simulation_runner import RunnerStatus, SimulationRunner

BASE_ID = "sim_base"
QUESTIONS = [{"id": "q1", "text": "Will it rise?", "type": "probability"}]


def base_config(**extra):
    config = {
        "simulation_id": BASE_ID,
        "simulation_requirement": "Will HEGAM rise after the demerger?",
        "behavior_version": 2,
        "time_config": {"total_simulation_hours": 120, "minutes_per_round": 60,
                        "agents_per_hour_min": 1, "agents_per_hour_max": 3, "peak_activity_multiplier": 1.5},
        "agent_configs": [{"agent_id": i, "entity_name": f"A{i}", "entity_type": "Person", "stance": "neutral"}
                          for i in range(6)],
        "event_config": {"initial_posts": [], "scheduled_events": [], "topic": "HEGAM"},
        "run": {"seed": 7, "replicate_index": None, "ensemble_id": None},
    }
    config.update(extra)
    return config


class FakeRunner:
    """Stands in for SimulationRunner: replicates stay RUNNING until ``finish`` is called."""

    def __init__(self):
        self.started = []
        self.stopped = []
        self.states = {}
        self.fail_start = set()
        self.lock = threading.Lock()
        self.max_active = 0

    def start(self, simulation_id, **kwargs):
        if simulation_id in self.fail_start:
            raise ValueError("cannot start")
        with self.lock:
            self.started.append({"simulation_id": simulation_id, **kwargs})
            self.states[simulation_id] = SimpleNamespace(
                runner_status=RunnerStatus.RUNNING, current_round=0,
                total_rounds=kwargs.get("max_rounds"), error=None,
            )
            active = sum(1 for s in self.states.values() if s.runner_status == RunnerStatus.RUNNING)
            self.max_active = max(self.max_active, active)

    def get_state(self, simulation_id):
        return self.states.get(simulation_id)

    def finish(self, simulation_id, status=RunnerStatus.COMPLETED, error=None):
        with self.lock:
            state = self.states[simulation_id]
            state.runner_status = status
            state.error = error
            if status == RunnerStatus.COMPLETED:
                state.current_round = state.total_rounds

    def stop(self, simulation_id):
        with self.lock:
            self.stopped.append(simulation_id)
            self.states[simulation_id].runner_status = RunnerStatus.STOPPED
            return self.states[simulation_id]

    def running(self):
        with self.lock:
            return [s for s, st in self.states.items() if st.runner_status == RunnerStatus.RUNNING]


@pytest.fixture
def env(monkeypatch, tmp_path):
    sims = tmp_path / "simulations"
    ensembles = tmp_path / "ensembles"
    sims.mkdir()
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(sims))
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(sims))
    monkeypatch.setattr(EnsembleManager, "ENSEMBLE_DATA_DIR", str(ensembles))
    monkeypatch.setattr(er, "POLL_INTERVAL_SECONDS", 0.01)

    runner = FakeRunner()
    monkeypatch.setattr(SimulationRunner, "start_simulation", classmethod(lambda _c, simulation_id, **kw: runner.start(simulation_id, **kw)))
    monkeypatch.setattr(SimulationRunner, "get_run_state", classmethod(lambda _c, simulation_id: runner.get_state(simulation_id)))
    monkeypatch.setattr(SimulationRunner, "stop_simulation", classmethod(lambda _c, simulation_id: runner.stop(simulation_id)))
    monkeypatch.setattr(SimulationRunner, "has_live_process", classmethod(lambda _c, simulation_id: False))

    manager = SimulationManager()

    def make_base(simulation_id=BASE_ID, *, prepared=True, config=True, **state_kwargs):
        sim_dir = sims / simulation_id
        manager._save_simulation_state(SimulationState(
            simulation_id=simulation_id, project_id="proj_1", graph_id="graph_1",
            status=SimulationStatus.COMPLETED, entities_count=6, profiles_count=6, entity_types=["Person"],
            profiles_generated=prepared, config_generated=prepared, config_reasoning="why", **state_kwargs,
        ))
        if config:
            (sim_dir / "simulation_config.json").write_text(json.dumps(base_config(simulation_id=simulation_id)), encoding="utf-8")
        (sim_dir / "twitter_profiles.csv").write_text("user_id,name,username,user_char,description\n0,A,a,p,d\n", encoding="utf-8")
        (sim_dir / "reddit_profiles.json").write_text("[]", encoding="utf-8")
        # artefacts of an earlier run that must never be cloned
        for name in ("twitter_simulation.db", "reddit_simulation.db", "run_state.json", "env_status.json",
                     "simulation.log", "final_poll.json", "twitter_profiles.effective.csv"):
            (sim_dir / name).write_text("stale", encoding="utf-8")
        for name in ("twitter", "reddit", "ipc_commands", "ipc_responses", "log"):
            (sim_dir / name).mkdir()
            (sim_dir / name / "x").write_text("stale", encoding="utf-8")
        return sim_dir

    make_base()
    yield SimpleNamespace(sims=sims, ensembles=ensembles, runner=runner, manager=manager, make_base=make_base)

    # No ensemble runner thread may outlive its test: it would keep polling
    # (and saving) against directories that no longer exist.
    for ensemble_id in list(EnsembleManager._threads):
        EnsembleManager._stop_requested.add(ensemble_id)
    for thread in list(EnsembleManager._threads.values()):
        thread.join(timeout=10)
    assert not any(t.is_alive() for t in EnsembleManager._threads.values()), "an ensemble thread leaked"
    EnsembleManager._threads.clear()
    EnsembleManager._stop_requested.clear()


def rid(ensemble, index):
    """The simulation id of replicate ``index`` of a created ensemble."""
    return ensemble["replicates"][index - 1]["simulation_id"]


def create(env, **overrides):
    params = dict(n_replicates=3, max_rounds=12, outcome_questions=QUESTIONS, base_seed=1000)
    params.update(overrides)
    return EnsembleManager.create(BASE_ID, **params)


def wait_for(predicate, timeout=10.0, message="condition"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for {message}")


def status_of(ensemble_id):
    return EnsembleManager._load(ensemble_id)["status"]


def drive(env, ensemble_id, outcomes):
    """Complete replicates as they start. ``outcomes`` maps index -> RunnerStatus (default COMPLETED)."""
    deadline = time.monotonic() + 15
    done = set()
    while time.monotonic() < deadline:
        for simulation_id in env.runner.running():
            index = int(simulation_id.rsplit("__r", 1)[1])
            if simulation_id not in done:
                done.add(simulation_id)
                status = outcomes.get(index, RunnerStatus.COMPLETED)
                env.runner.finish(simulation_id, status, error="boom" if status == RunnerStatus.FAILED else None)
        if status_of(ensemble_id) in er.TERMINAL_STATUSES:
            return
        time.sleep(0.01)
    raise AssertionError(f"ensemble stuck in {status_of(ensemble_id)}")


# --- seeds and ids -------------------------------------------------------------------------

def test_replicate_seeds_are_derived_from_the_base_seed_like_the_plan_says():
    expected = int(hashlib.sha256(b"12345:3").hexdigest()[:8], 16)
    assert derive_replicate_seed(12345, 3) == expected
    assert derive_replicate_seed(12345, 3) == derive_replicate_seed(12345, 3)
    assert 0 <= derive_replicate_seed(1, 1) < 2 ** 32
    assert len({derive_replicate_seed(1, i) for i in range(1, 51)}) == 50
    assert derive_replicate_seed(1, 1) != derive_replicate_seed(2, 1)


def test_replicate_ids_include_the_ensemble_so_ensembles_never_collide():
    assert replicate_simulation_id("sim_1b05d92d9701", "ens_ab12cd34ef56", 1) == "sim_1b05d92d9701__ab12cd34ef56__r01"
    assert replicate_simulation_id("sim_x", "ens_ab12cd34ef56", 12) == "sim_x__ab12cd34ef56__r12"
    assert replicate_simulation_id("sim_x", "ens_a", 1) != replicate_simulation_id("sim_x", "ens_b", 1)


def test_a_second_ensemble_from_the_same_base_leaves_the_first_alone(env):
    first = create(env, n_replicates=2)
    first_files = {p: p.read_bytes() for r in first["replicates"]
                   for p in (env.sims / r["simulation_id"]).iterdir() if p.is_file()}
    second = create(env, n_replicates=2)
    assert {r["simulation_id"] for r in first["replicates"]}.isdisjoint({r["simulation_id"] for r in second["replicates"]})
    assert {p: p.read_bytes() for p in first_files} == first_files
    assert len([p for p in env.sims.iterdir() if "__" in p.name]) == 4


def test_a_failed_create_removes_only_what_it_created(env, monkeypatch):
    first = create(env, n_replicates=2)
    real_clone = EnsembleManager._clone_replicate
    calls = []

    def flaky(cls, *args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("disk full")
        return real_clone.__func__(cls, *args, **kwargs)

    monkeypatch.setattr(EnsembleManager, "_clone_replicate", classmethod(flaky))
    with pytest.raises(RuntimeError, match="disk full"):
        create(env, n_replicates=3)

    survivors = sorted(p.name for p in env.sims.iterdir() if "__" in p.name)
    assert survivors == sorted(r["simulation_id"] for r in first["replicates"])
    assert [p.name for p in env.ensembles.iterdir()] == [first["ensemble_id"]]


def test_an_existing_replicate_directory_is_never_overwritten_or_deleted(env, monkeypatch):
    monkeypatch.setattr(er.uuid, "uuid4", lambda: SimpleNamespace(hex="a" * 32))
    first = create(env, n_replicates=2)  # ens_aaaaaaaaaaaa
    victim = env.sims / first["replicates"][0]["simulation_id"]
    marker = victim / "precious.txt"
    marker.write_text("keep me", encoding="utf-8")
    monkeypatch.setattr(er.uuid, "uuid4", lambda: SimpleNamespace(hex="b" * 32))
    # simulate a freak id clash: another ensemble whose first replicate id already exists
    monkeypatch.setattr(er, "replicate_simulation_id", lambda base, ens, idx: first["replicates"][0]["simulation_id"])
    with pytest.raises(EnsembleConflict, match="already exists"):
        create(env, n_replicates=2)
    assert marker.read_text(encoding="utf-8") == "keep me"


# --- create: validation ------------------------------------------------------------------------

def test_max_rounds_is_required(env):
    with pytest.raises(EnsembleError, match="max_rounds is required"):
        EnsembleManager.create(BASE_ID, n_replicates=3, outcome_questions=QUESTIONS)


@pytest.mark.parametrize("name,value", [
    ("n_replicates", 0), ("n_replicates", 51), ("n_replicates", True), ("n_replicates", 2.5), ("n_replicates", "3"),
    ("concurrency", 0), ("concurrency", 5), ("concurrency", True),
    ("max_rounds", 0), ("max_rounds", -3), ("max_rounds", 1.5), ("max_rounds", False),
    ("base_seed", -1), ("base_seed", True), ("base_seed", "7"),
    ("llm_temperature", -0.1), ("llm_temperature", 2.1), ("llm_temperature", "hot"), ("llm_temperature", True),
])
def test_out_of_range_parameters_are_rejected(env, name, value):
    with pytest.raises(EnsembleError):
        create(env, **{name: value})
    assert not os.path.exists(str(env.ensembles)) or os.listdir(str(env.ensembles)) == []


def test_bounds_are_inclusive(env):
    ensemble = create(env, n_replicates=50, concurrency=4, max_rounds=1, llm_temperature=2)
    assert len(ensemble["replicates"]) == 50 and ensemble["concurrency"] == 4
    assert ensemble["llm_temperature"] == 2.0


def test_only_the_parallel_platform_is_supported(env):
    with pytest.raises(EnsembleError, match="parallel"):
        create(env, platform="twitter")


def test_unknown_unprepared_and_replicate_bases_are_rejected(env):
    with pytest.raises(EnsembleNotFound):
        EnsembleManager.create("sim_missing", max_rounds=5, outcome_questions=QUESTIONS)
    env.make_base("sim_raw", prepared=False)
    with pytest.raises(EnsembleConflict, match="not prepared"):
        EnsembleManager.create("sim_raw", max_rounds=5, outcome_questions=QUESTIONS)
    env.make_base("sim_noconfig", config=False)
    with pytest.raises(EnsembleConflict, match="no config"):
        EnsembleManager.create("sim_noconfig", max_rounds=5, outcome_questions=QUESTIONS)
    env.make_base("sim_rep__r01", ensemble_id="ens_other", replicate_index=1)
    with pytest.raises(EnsembleError, match="replicate"):
        EnsembleManager.create("sim_rep__r01", max_rounds=5, outcome_questions=QUESTIONS)


def test_a_missing_base_does_not_leave_directories_behind(env):
    with pytest.raises(EnsembleNotFound):
        EnsembleManager.create("sim_missing", max_rounds=5, outcome_questions=QUESTIONS)
    assert not (env.sims / "sim_missing").exists()


# --- create: what gets cloned --------------------------------------------------------------------

def test_create_clones_only_the_definition_files(env, monkeypatch):
    monkeypatch.delenv("LLM_MAX_CONCURRENCY", raising=False)  # the developer's .env may set it
    ensemble = create(env, llm_temperature=0.4, concurrency=2)
    token = ensemble["ensemble_id"][4:]
    assert [r["simulation_id"] for r in ensemble["replicates"]] == [
        f"sim_base__{token}__r01", f"sim_base__{token}__r02", f"sim_base__{token}__r03"]

    for replicate in ensemble["replicates"]:
        rep_dir = env.sims / replicate["simulation_id"]
        assert sorted(p.name for p in rep_dir.iterdir()) == [
            "reddit_profiles.json", "simulation_config.json", "state.json", "twitter_profiles.csv",
        ]
        config = json.loads((rep_dir / "simulation_config.json").read_text(encoding="utf-8"))
        assert config["simulation_id"] == replicate["simulation_id"]
        assert config["behavior_version"] == 2
        assert config["run"] == {
            "seed": replicate["seed"], "replicate_index": replicate["index"], "ensemble_id": ensemble["ensemble_id"],
            "max_rounds": 12, "outcome_questions": QUESTIONS, "llm_semaphore": 15, "llm_concurrency_share": 2, "llm_temperature": 0.4,
        }
        state = json.loads((rep_dir / "state.json").read_text(encoding="utf-8"))
        assert state["status"] == "ready" and state["simulation_id"] == replicate["simulation_id"]
        assert state["ensemble_id"] == ensemble["ensemble_id"] and state["replicate_index"] == replicate["index"]
        assert state["config_generated"] and state["profiles_generated"]
        assert state["project_id"] == "proj_1" and state["graph_id"] == "graph_1"


def test_the_base_simulation_is_left_untouched(env):
    base_dir = env.sims / BASE_ID
    before = {p.name: p.read_bytes() for p in base_dir.iterdir() if p.is_file()}
    create(env)
    assert {p.name: p.read_bytes() for p in base_dir.iterdir() if p.is_file()} == before


def test_replicate_seeds_come_from_the_base_seed(env):
    first = create(env, base_seed=2024)
    second = create(env, base_seed=2024)
    other = create(env, base_seed=2025)
    seeds = [r["seed"] for r in first["replicates"]]
    assert seeds == [derive_replicate_seed(2024, i) for i in (1, 2, 3)]
    assert seeds == [r["seed"] for r in second["replicates"]]
    assert seeds != [r["seed"] for r in other["replicates"]]
    assert first["base_seed"] == 2024


def test_a_base_seed_is_generated_when_absent(env):
    ensemble = create(env, base_seed=None)
    assert isinstance(ensemble["base_seed"], int) and 0 <= ensemble["base_seed"] < 2 ** 31
    assert ensemble["replicates"][0]["seed"] == derive_replicate_seed(ensemble["base_seed"], 1)


def test_the_definition_is_written_to_disk(env):
    ensemble = create(env)
    ens_dir = env.ensembles / ensemble["ensemble_id"]
    on_disk = json.loads((ens_dir / "ensemble.json").read_text(encoding="utf-8"))
    assert on_disk["status"] == "created" and on_disk["base_simulation_id"] == BASE_ID
    assert on_disk["max_rounds"] == 12 and on_disk["platform"] == "parallel" and on_disk["concurrency"] == 1
    assert [r["status"] for r in on_disk["replicates"]] == ["pending"] * 3
    assert json.loads((ens_dir / "outcome_questions.json").read_text(encoding="utf-8")) == QUESTIONS
    assert ensemble["progress"] == {"pending": 3, "running": 0, "completed": 0, "failed": 0, "stopped": 0}


# --- create: outcome questions --------------------------------------------------------------------------

def test_questions_are_derived_when_not_supplied(env):
    calls = []

    def fake_llm(messages):
        calls.append(messages)
        return {"questions": [{"text": "Will it rise?", "type": "probability"}]}

    ensemble = EnsembleManager.create(BASE_ID, max_rounds=5, llm_json=fake_llm)
    assert len(calls) == 1
    assert ensemble["questions_source"] == "llm"
    assert ensemble["outcome_questions"] == [{"id": "q1", "text": "Will it rise?", "type": "probability"}]


def test_a_failing_llm_falls_back_to_a_stance_question(env):
    def broken(_messages):
        raise RuntimeError("no network")

    ensemble = EnsembleManager.create(BASE_ID, max_rounds=5, llm_json=broken)
    assert ensemble["questions_source"] == "fallback"
    (question,) = ensemble["outcome_questions"]
    assert question["type"] == "choice" and "HEGAM" in question["text"] and question["stance_map"]


def test_an_invalid_llm_reply_also_falls_back(env):
    ensemble = EnsembleManager.create(BASE_ID, max_rounds=5, llm_json=lambda _m: {"questions": [{"text": "x", "type": "bogus"}]})
    assert ensemble["questions_source"] == "fallback"


def test_supplied_questions_are_validated_and_normalised(env):
    ensemble = create(env, outcome_questions=[{"text": "  Rise?  ", "type": "probability"}])
    assert ensemble["questions_source"] == "user"
    assert ensemble["outcome_questions"] == [{"id": "q1", "text": "Rise?", "type": "probability"}]
    with pytest.raises(EnsembleError, match="Invalid outcome questions"):
        create(env, outcome_questions=[{"text": "", "type": "probability"}])
    with pytest.raises(EnsembleError, match="at most 3"):
        create(env, outcome_questions=[QUESTIONS[0]] * 4)


def test_an_empty_question_list_means_no_poll(env):
    ensemble = create(env, outcome_questions=[])
    assert ensemble["outcome_questions"] == []
    config = json.loads((env.sims / rid(ensemble, 1) / "simulation_config.json").read_text(encoding="utf-8"))
    assert config["run"]["outcome_questions"] == []
    assert ensemble["cost_estimate"]["poll_calls"] == 0


# --- cost estimate ----------------------------------------------------------------------------------------

def test_cost_estimate_follows_the_documented_formula(env):
    ensemble = create(env, n_replicates=4, max_rounds=10)
    # 6 agents; agents_per_hour_max 3 * peak 1.5 -> ceil(4.5) = 5 woken per round at most
    estimate = ensemble["cost_estimate"]
    assert estimate["simulation_calls"] == 4 * 2 * 10 * 5
    assert estimate["poll_calls"] == 4 * 2 * 6 * 1
    assert estimate["llm_calls_upper_bound"] == estimate["simulation_calls"] + estimate["poll_calls"] == 448
    assert estimate["assumptions"]["agents_woken_per_round_max"] == 5


def test_cost_estimate_never_counts_more_rounds_than_the_simulation_has():
    config = base_config()
    config["time_config"]["total_simulation_hours"] = 5
    assert estimate_cost(config, 1, 1000, 0)["assumptions"]["rounds_per_run"] == 5
    assert estimate_cost(config, 1, 3, 0)["assumptions"]["rounds_per_run"] == 3


def test_cost_estimate_caps_woken_agents_at_the_number_of_agents():
    config = base_config()
    config["time_config"]["agents_per_hour_max"] = 500
    assert estimate_cost(config, 1, 1, 0)["assumptions"]["agents_woken_per_round_max"] == 6


# --- running -------------------------------------------------------------------------------------------------

def test_replicates_run_with_bounded_concurrency_and_never_write_to_zep(env):
    ensemble = create(env, n_replicates=5, concurrency=2, platform="parallel", max_rounds=7)
    EnsembleManager.start(ensemble["ensemble_id"])
    drive(env, ensemble["ensemble_id"], {})

    assert env.runner.max_active <= 2
    assert len(env.runner.started) == 5
    for index, call in enumerate(env.runner.started, start=1):
        assert call["simulation_id"] == rid(ensemble, index)
        assert call["enable_graph_memory_update"] is False
        assert call["wait_for_commands"] is False
        assert call["max_rounds"] == 7 and call["platform"] == "parallel"
        assert call["seed"] == derive_replicate_seed(1000, index)
    assert status_of(ensemble["ensemble_id"]) == "completed"


def test_concurrency_one_runs_replicates_strictly_one_at_a_time(env):
    ensemble = create(env, n_replicates=4, concurrency=1)
    EnsembleManager.start(ensemble["ensemble_id"])
    drive(env, ensemble["ensemble_id"], {})
    assert env.runner.max_active == 1


def test_concurrency_four_uses_all_the_slots(env):
    ensemble = create(env, n_replicates=8, concurrency=4)
    EnsembleManager.start(ensemble["ensemble_id"])
    wait_for(lambda: len(env.runner.running()) == 4, message="4 replicates running")
    assert env.runner.max_active == 4
    drive(env, ensemble["ensemble_id"], {})
    assert env.runner.max_active == 4


def test_an_ensemble_can_only_be_started_once(env):
    ensemble = create(env, n_replicates=2)
    EnsembleManager.start(ensemble["ensemble_id"])
    with pytest.raises(EnsembleConflict, match="newly created"):
        EnsembleManager.start(ensemble["ensemble_id"])
    drive(env, ensemble["ensemble_id"], {})
    with pytest.raises(EnsembleConflict):
        EnsembleManager.start(ensemble["ensemble_id"])
    with pytest.raises(EnsembleNotFound):
        EnsembleManager.start("ens_missing")


def test_progress_reports_rounds_per_replicate(env):
    ensemble = create(env, n_replicates=2, concurrency=2, max_rounds=9)
    EnsembleManager.start(ensemble["ensemble_id"])
    wait_for(lambda: len(env.runner.running()) == 2)
    env.runner.states[rid(ensemble, 1)].current_round = 4
    info = EnsembleManager.get(ensemble["ensemble_id"])
    first = info["replicates"][0]
    assert (first["current_round"], first["total_rounds"], first["runner_status"]) == (4, 9, "running")
    assert info["progress"]["running"] == 2 and info["status"] == "running"
    drive(env, ensemble["ensemble_id"], {})
    done = EnsembleManager.get(ensemble["ensemble_id"])
    assert done["progress"]["completed"] == 2 and done["replicates"][0]["current_round"] == 9


# --- failure policy ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "failures,expected_status,has_summary",
    [
        ({}, "completed", True),
        ({2: RunnerStatus.FAILED}, "partial", True),
        ({2: RunnerStatus.FAILED, 3: RunnerStatus.FAILED}, "partial", True),   # 3 of 5 still ok
        ({1: RunnerStatus.FAILED, 2: RunnerStatus.FAILED, 3: RunnerStatus.FAILED}, "partial", True),  # 2 ok
        ({1: RunnerStatus.FAILED, 2: RunnerStatus.FAILED, 3: RunnerStatus.FAILED, 4: RunnerStatus.FAILED}, "failed", False),
        ({i: RunnerStatus.FAILED for i in range(1, 6)}, "failed", False),
    ],
)
def test_failed_replicates_do_not_fail_the_ensemble_unless_fewer_than_two_succeed(
    env, monkeypatch, failures, expected_status, has_summary
):
    aggregated = []
    monkeypatch.setattr(er, "build_summary", lambda ens, q, sims: (aggregated.append(ens["replicates"]) or {"n": 1}))
    monkeypatch.setattr(er, "write_summary", lambda path, summary: open(os.path.join(path, "summary.json"), "w").write("{}"))

    ensemble = create(env, n_replicates=5, concurrency=1)
    EnsembleManager.start(ensemble["ensemble_id"])
    drive(env, ensemble["ensemble_id"], failures)

    final = EnsembleManager._load(ensemble["ensemble_id"])
    assert final["status"] == expected_status
    assert bool(aggregated) is has_summary
    assert (env.ensembles / ensemble["ensemble_id"] / "summary.json").exists() is has_summary
    for index, status in failures.items():
        replicate = final["replicates"][index - 1]
        assert replicate["status"] == "failed" and replicate["error"] == "boom"
    if expected_status == "failed":
        assert "fewer than 2" in final["error"]


@pytest.mark.parametrize("failures,expected_status", [({}, "completed"), ({1: RunnerStatus.FAILED}, "failed")])
def test_an_ensemble_of_one_run_needs_that_run(env, monkeypatch, failures, expected_status):
    monkeypatch.setattr(er, "build_summary", lambda ens, q, sims: {"n": 1})
    monkeypatch.setattr(er, "write_summary", lambda path, summary: open(os.path.join(path, "summary.json"), "w").write("{}"))

    ensemble = create(env, n_replicates=1, concurrency=1)
    EnsembleManager.start(ensemble["ensemble_id"])
    drive(env, ensemble["ensemble_id"], failures)

    assert EnsembleManager._load(ensemble["ensemble_id"])["status"] == expected_status


def test_a_replicate_that_cannot_start_is_failed_and_the_rest_continue(env):
    ensemble = create(env, n_replicates=3, concurrency=1)
    env.runner.fail_start.add(rid(ensemble, 2))
    EnsembleManager.start(ensemble["ensemble_id"])
    drive(env, ensemble["ensemble_id"], {})
    final = EnsembleManager._load(ensemble["ensemble_id"])
    assert [r["status"] for r in final["replicates"]] == ["completed", "failed", "completed"]
    assert final["replicates"][1]["error"] == "cannot start"
    assert final["status"] == "partial"


def test_the_summary_is_written_by_the_aggregator(env):
    ensemble = create(env, n_replicates=2)
    EnsembleManager.start(ensemble["ensemble_id"])
    drive(env, ensemble["ensemble_id"], {})
    summary = EnsembleManager.summary(ensemble["ensemble_id"])
    assert summary["n_replicates_ok"] == 2 and summary["ensemble_id"] == ensemble["ensemble_id"]
    assert "not calibrated probabilities" in (env.ensembles / ensemble["ensemble_id"] / "summary.md").read_text(encoding="utf-8")
    assert EnsembleManager.get(ensemble["ensemble_id"])["has_summary"] is True


def test_the_summary_is_none_until_it_exists(env):
    ensemble = create(env)
    assert EnsembleManager.summary(ensemble["ensemble_id"]) is None
    with pytest.raises(EnsembleNotFound):
        EnsembleManager.summary("ens_missing")


def test_an_aggregation_error_fails_the_ensemble_with_a_message(env, monkeypatch):
    def boom(*_args):
        raise RuntimeError("disk full")

    monkeypatch.setattr(er, "build_summary", boom)
    ensemble = create(env, n_replicates=2)
    EnsembleManager.start(ensemble["ensemble_id"])
    drive(env, ensemble["ensemble_id"], {})
    final = EnsembleManager._load(ensemble["ensemble_id"])
    assert final["status"] == "failed" and "disk full" in final["error"]


# --- stop ---------------------------------------------------------------------------------------------------------

def test_stop_halts_running_replicates_and_marks_the_rest_stopped(env):
    ensemble = create(env, n_replicates=5, concurrency=2)
    EnsembleManager.start(ensemble["ensemble_id"])
    wait_for(lambda: len(env.runner.running()) == 2)

    result = EnsembleManager.stop(ensemble["ensemble_id"])

    assert result["status"] == "stopped"
    assert sorted(env.runner.stopped) == sorted([rid(ensemble, 1), rid(ensemble, 2)])
    assert [r["status"] for r in result["replicates"]] == ["stopped"] * 5
    time.sleep(0.2)  # the runner thread must not start anything afterwards
    assert len(env.runner.started) == 2
    assert status_of(ensemble["ensemble_id"]) == "stopped"
    assert EnsembleManager.summary(ensemble["ensemble_id"]) is None


def test_stop_before_start_marks_everything_stopped(env):
    ensemble = create(env, n_replicates=2)
    result = EnsembleManager.stop(ensemble["ensemble_id"])
    assert result["status"] == "stopped" and [r["status"] for r in result["replicates"]] == ["stopped"] * 2
    assert env.runner.started == []


def test_stopping_a_finished_ensemble_is_a_no_op(env):
    ensemble = create(env, n_replicates=2)
    EnsembleManager.start(ensemble["ensemble_id"])
    drive(env, ensemble["ensemble_id"], {})
    assert EnsembleManager.stop(ensemble["ensemble_id"])["status"] == "completed"
    assert env.runner.stopped == []


def test_stop_keeps_a_replicate_that_finished_while_stopping(env, monkeypatch):
    ensemble = create(env, n_replicates=1)
    EnsembleManager.start(ensemble["ensemble_id"])
    wait_for(lambda: len(env.runner.running()) == 1)

    def finish_first(simulation_id):
        env.runner.finish(simulation_id, RunnerStatus.COMPLETED)
        return env.runner.states[simulation_id]

    monkeypatch.setattr(SimulationRunner, "stop_simulation", classmethod(lambda _c, simulation_id: finish_first(simulation_id)))
    result = EnsembleManager.stop(ensemble["ensemble_id"])
    assert result["replicates"][0]["status"] == "completed"


def test_stop_records_a_replicate_that_would_not_stop(env, monkeypatch):
    ensemble = create(env, n_replicates=1)
    EnsembleManager.start(ensemble["ensemble_id"])
    wait_for(lambda: len(env.runner.running()) == 1)

    def refuse(_c, _simulation_id):
        raise RuntimeError("stuck")

    monkeypatch.setattr(SimulationRunner, "stop_simulation", classmethod(refuse))
    result = EnsembleManager.stop(ensemble["ensemble_id"])
    assert result["status"] == "stopped" and result["replicates"][0]["error"] == "stuck"


# --- restart recovery ----------------------------------------------------------------------------------------------

def orphan(env, statuses, runner_states=None, ensemble_status="running"):
    """``runner_states`` maps replicate index -> RunnerStatus."""
    """An ensemble.json left behind by a process that no longer exists."""
    ensemble = create(env, n_replicates=len(statuses))
    path = env.ensembles / ensemble["ensemble_id"] / "ensemble.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["status"] = ensemble_status
    for replicate, status in zip(data["replicates"], statuses):
        replicate["status"] = status
    path.write_text(json.dumps(data), encoding="utf-8")
    for index, runner_status in (runner_states or {}).items():
        env.runner.states[rid(ensemble, index)] = SimpleNamespace(
            runner_status=runner_status, current_round=3, total_rounds=12, error="crashed" if runner_status == RunnerStatus.FAILED else None)
    return ensemble["ensemble_id"]


def test_reconcile_marks_orphaned_replicates_interrupted_and_aggregates_the_rest(env):
    ensemble_id = orphan(
        env, ["completed", "completed", "running", "pending"],
        runner_states={3: RunnerStatus.RUNNING},  # its process is gone (has_live_process is False)
    )
    result = EnsembleManager.reconcile(ensemble_id)

    assert [r["status"] for r in result["replicates"]] == ["completed", "completed", "failed", "stopped"]
    assert result["replicates"][2]["error"] == "interrupted"
    assert result["replicates"][3]["error"] == "interrupted"
    assert result["status"] == "partial"  # two replicates did finish
    assert EnsembleManager.summary(ensemble_id) is not None


def test_reconcile_below_two_completed_replicates_fails_the_ensemble(env):
    ensemble_id = orphan(env, ["completed", "running", "pending"])
    result = EnsembleManager.reconcile(ensemble_id)
    assert result["status"] == "failed" and "fewer than 2" in result["error"]


def test_reconcile_uses_the_runner_outcome_when_it_is_known(env):
    ensemble_id = orphan(
        env, ["running", "running", "running"],
        runner_states={1: RunnerStatus.COMPLETED, 2: RunnerStatus.FAILED, 3: RunnerStatus.COMPLETED},
    )
    result = EnsembleManager.reconcile(ensemble_id)
    assert [r["status"] for r in result["replicates"]] == ["completed", "failed", "completed"]
    assert result["replicates"][1]["error"] == "crashed"
    assert result["status"] == "partial"


def test_reconcile_leaves_a_replicate_with_a_live_process_alone(env, monkeypatch):
    ensemble_id = orphan(env, ["running", "completed"], runner_states={1: RunnerStatus.RUNNING})
    monkeypatch.setattr(SimulationRunner, "has_live_process", classmethod(lambda _c, simulation_id: True))
    result = EnsembleManager.reconcile(ensemble_id)
    assert result["replicates"][0]["status"] == "running" and result["status"] == "running"


def test_reconcile_ignores_ensembles_that_are_not_running(env):
    ensemble = create(env)
    assert EnsembleManager.reconcile(ensemble["ensemble_id"])["status"] == "created"
    ensemble_id = orphan(env, ["completed", "completed"], ensemble_status="completed")
    assert EnsembleManager.reconcile(ensemble_id)["status"] == "completed"


def test_reconcile_re_aggregates_an_interrupted_aggregation(env):
    ensemble_id = orphan(env, ["completed", "completed"], ensemble_status="aggregating")
    assert EnsembleManager.reconcile(ensemble_id)["status"] == "completed"
    assert EnsembleManager.summary(ensemble_id) is not None


def test_get_and_list_reconcile_lazily(env):
    ensemble_id = orphan(env, ["completed", "completed", "running"])
    assert EnsembleManager.get(ensemble_id)["status"] == "partial"
    other = orphan(env, ["running", "pending"])
    listed = {e["ensemble_id"]: e["status"] for e in EnsembleManager.list_ensembles()}
    assert listed[other] == "failed"


# --- queries ---------------------------------------------------------------------------------------------------------

def test_list_filters_by_base_simulation_and_sorts_newest_first(env):
    env.make_base("sim_other")
    first = create(env)
    time.sleep(0.01)
    second = create(env)
    other = EnsembleManager.create("sim_other", max_rounds=3, outcome_questions=QUESTIONS)

    everything = [e["ensemble_id"] for e in EnsembleManager.list_ensembles()]
    assert set(everything) == {first["ensemble_id"], second["ensemble_id"], other["ensemble_id"]}
    only_base = [e["ensemble_id"] for e in EnsembleManager.list_ensembles(BASE_ID)]
    assert only_base == [second["ensemble_id"], first["ensemble_id"]]
    assert EnsembleManager.list_ensembles("sim_nothing") == []


def test_list_with_no_ensembles_directory_is_empty(env):
    assert EnsembleManager.list_ensembles() == []


def test_get_unknown_ensemble_is_a_404(env):
    with pytest.raises(EnsembleNotFound):
        EnsembleManager.get("ens_missing")


# --- editing the questions -----------------------------------------------------------------------------------------------

def test_outcome_questions_can_be_edited_before_the_start_and_reach_every_replicate(env):
    ensemble = create(env, n_replicates=2, concurrency=1)
    new = [{"text": "Which way?", "type": "choice", "options": ["up", "down"]},
           {"id": "pct", "text": "How far?", "type": "number", "unit": "%"}]
    updated = EnsembleManager.update_outcome_questions(ensemble["ensemble_id"], new)

    assert [q["id"] for q in updated["outcome_questions"]] == ["q1", "pct"]
    assert updated["questions_source"] == "user"
    assert updated["cost_estimate"]["poll_calls"] == 2 * 2 * 6 * 2
    for replicate in updated["replicates"]:
        config = json.loads((env.sims / replicate["simulation_id"] / "simulation_config.json").read_text(encoding="utf-8"))
        assert [q["id"] for q in config["run"]["outcome_questions"]] == ["q1", "pct"]
        assert config["run"]["seed"] == replicate["seed"]  # nothing else changed
    saved = json.loads((env.ensembles / ensemble["ensemble_id"] / "outcome_questions.json").read_text(encoding="utf-8"))
    assert [q["id"] for q in saved] == ["q1", "pct"]


def test_invalid_replacement_questions_change_nothing(env):
    ensemble = create(env, n_replicates=1)
    with pytest.raises(EnsembleError, match="Invalid outcome questions"):
        EnsembleManager.update_outcome_questions(ensemble["ensemble_id"], [{"text": "x", "type": "nope"}])
    assert EnsembleManager.get(ensemble["ensemble_id"])["outcome_questions"] == QUESTIONS


def test_questions_cannot_be_edited_once_the_ensemble_has_started(env):
    ensemble = create(env, n_replicates=2)
    EnsembleManager.start(ensemble["ensemble_id"])
    with pytest.raises(EnsembleConflict, match="before the ensemble starts"):
        EnsembleManager.update_outcome_questions(ensemble["ensemble_id"], QUESTIONS)
    drive(env, ensemble["ensemble_id"], {})
    with pytest.raises(EnsembleConflict):
        EnsembleManager.update_outcome_questions(ensemble["ensemble_id"], QUESTIONS)


# --- replicates are hidden from the simulation list --------------------------------------------------------------------------

def test_replicates_are_hidden_from_simulation_listings_by_default(env):
    ensemble = create(env, n_replicates=3)
    visible = [s.simulation_id for s in env.manager.list_simulations()]
    assert visible == [BASE_ID]
    everything = {s.simulation_id for s in env.manager.list_simulations(include_replicates=True)}
    assert everything == {BASE_ID, *[r["simulation_id"] for r in ensemble["replicates"]]}
    replicate = env.manager.get_simulation(rid(ensemble, 2))
    assert replicate.is_replicate and replicate.ensemble_id == ensemble["ensemble_id"] and replicate.replicate_index == 2
    assert env.manager.get_simulation(BASE_ID).is_replicate is False


def test_the_replicate_marker_survives_a_reload_from_disk(env):
    ensemble = create(env, n_replicates=1)
    fresh = SimulationManager()
    state = fresh._load_simulation_state(rid(ensemble, 1))
    assert state.ensemble_id == ensemble["ensemble_id"] and state.replicate_index == 1
    assert fresh.get_simulation(rid(ensemble, 1)).to_dict()["replicate_index"] == 1


# --- robustness: corrupt files, durable writes, concurrent readers ------------------------

def zero_fill(path):
    """What an NTFS crash leaves behind: the right length, all NUL bytes."""
    size = os.path.getsize(path)
    with open(path, "wb") as handle:
        handle.write(b"\x00" * size)


def test_a_corrupt_ensemble_json_is_a_clear_error_not_a_crash(env):
    ensemble = create(env)
    zero_fill(env.ensembles / ensemble["ensemble_id"] / "ensemble.json")
    for call in (EnsembleManager.get, EnsembleManager.summary, EnsembleManager.stop, EnsembleManager.start):
        with pytest.raises(er.EnsembleCorrupt, match="cannot be read"):
            call(ensemble["ensemble_id"])
    assert er.EnsembleCorrupt.status_code == 500
    assert issubclass(er.EnsembleCorrupt, EnsembleError)


def test_one_corrupt_ensemble_does_not_hide_the_others_in_the_listing(env):
    good = create(env)
    broken = create(env)
    zero_fill(env.ensembles / broken["ensemble_id"] / "ensemble.json")
    (env.ensembles / "ens_empty_dir").mkdir()  # a directory without an ensemble.json
    listed = [e["ensemble_id"] for e in EnsembleManager.list_ensembles()]
    assert listed == [good["ensemble_id"]]


def test_a_missing_or_corrupt_outcome_questions_file_reads_as_empty(env):
    ensemble = create(env)
    zero_fill(env.ensembles / ensemble["ensemble_id"] / "outcome_questions.json")
    assert EnsembleManager.load_outcome_questions(ensemble["ensemble_id"]) == []
    assert EnsembleManager.get(ensemble["ensemble_id"])["outcome_questions"] == []


def test_a_corrupt_summary_reads_as_not_aggregated(env):
    ensemble = create(env, n_replicates=2)
    EnsembleManager.start(ensemble["ensemble_id"])
    drive(env, ensemble["ensemble_id"], {})
    assert EnsembleManager.summary(ensemble["ensemble_id"]) is not None
    zero_fill(env.ensembles / ensemble["ensemble_id"] / "summary.json")
    assert EnsembleManager.summary(ensemble["ensemble_id"]) is None


def test_saving_never_resurrects_a_removed_ensemble_directory(env):
    ensemble = create(env)
    data = EnsembleManager._load(ensemble["ensemble_id"])
    import shutil

    shutil.rmtree(env.ensembles / ensemble["ensemble_id"])
    with pytest.raises(EnsembleNotFound):
        EnsembleManager._save(data)
    assert not (env.ensembles / ensemble["ensemble_id"]).exists()


def test_a_replicate_state_that_cannot_be_read_does_not_break_the_simulation_list(env):
    ensemble = create(env, n_replicates=2)
    zero_fill(env.sims / rid(ensemble, 1) / "state.json")
    assert [s.simulation_id for s in env.manager.list_simulations()] == [BASE_ID]
    visible = {s.simulation_id for s in env.manager.list_simulations(include_replicates=True)}
    assert visible == {BASE_ID, rid(ensemble, 2)}  # the unreadable one is skipped, the rest survive


def test_reads_during_a_busy_run_never_fail(env, monkeypatch):
    monkeypatch.setattr(er, "POLL_INTERVAL_SECONDS", 0.0)  # save as fast as possible
    ensemble = create(env, n_replicates=12, concurrency=4)
    errors = []
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            try:
                EnsembleManager.get(ensemble["ensemble_id"])
                EnsembleManager.list_ensembles()
                EnsembleManager.summary(ensemble["ensemble_id"])
            except Exception as error:  # a Windows sharing violation would land here
                errors.append(repr(error))
                return

    readers = [threading.Thread(target=reader, daemon=True) for _ in range(4)]
    for thread in readers:
        thread.start()
    try:
        EnsembleManager.start(ensemble["ensemble_id"])
        drive(env, ensemble["ensemble_id"], {})
    finally:
        stop.set()
        for thread in readers:
            thread.join(timeout=10)
    assert errors == []
    assert status_of(ensemble["ensemble_id"]) == "completed"


@pytest.mark.parametrize("value,expected", [(None, 30), ("3", 3), ("0", 1), ("abc", 30)])
def test_llm_concurrency_can_be_lowered_from_the_environment(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("LLM_MAX_CONCURRENCY", raising=False)
    else:
        monkeypatch.setenv("LLM_MAX_CONCURRENCY", value)
    assert er._base_llm_semaphore() == expected


def test_a_failed_single_run_ensemble_says_so_instead_of_asking_for_two(env, monkeypatch):
    monkeypatch.setattr(er, "build_summary", lambda *a, **k: {"n": 1})
    ensemble = create(env, n_replicates=1, concurrency=1)
    EnsembleManager.start(ensemble["ensemble_id"])
    drive(env, ensemble["ensemble_id"], {1: RunnerStatus.FAILED})

    final = EnsembleManager._load(ensemble["ensemble_id"])
    assert final["status"] == "failed"
    assert "fewer than" not in final["error"] and "the run did not complete" in final["error"]
