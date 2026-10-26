"""Seeds, ``--no-wait`` and non-behaviour log records in the simulation runner."""

import json
import threading
import time
from types import SimpleNamespace

import pytest
from flask import Flask

from app.api import simulation as simulation_api
from app.services import simulation_runner as runner_module
from app.services.simulation_manager import SimulationStatus
from app.services.simulation_runner import (
    NON_BEHAVIOR_PHASES,
    RunnerStatus,
    SimulationRunState,
    SimulationRunner,
)

_REAL_SLEEP = time.sleep


class FakeProcess:
    pid = 4321

    def __init__(self):
        self.returncode = None

    def poll(self):
        return self.returncode

    def exit(self, code):
        self.returncode = code


class InertThread:
    def __init__(self, **_kwargs):
        pass

    def start(self):
        pass


def _write_config(sim_dir, **extra):
    config = {"time_config": {"total_simulation_hours": 24, "minutes_per_round": 60}}
    config.update(extra)
    (sim_dir / "simulation_config.json").write_text(json.dumps(config), encoding="utf-8")


@pytest.fixture
def launch(monkeypatch, tmp_path):
    """Start simulations without spawning anything; records the command line."""
    simulation_id = "sim-seed"
    runs = tmp_path / "runs"
    sim_dir = runs / simulation_id
    scripts = tmp_path / "scripts"
    sim_dir.mkdir(parents=True)
    scripts.mkdir()
    (scripts / "run_parallel_simulation.py").write_text("pass\n", encoding="utf-8")

    commands = []
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(runs))
    monkeypatch.setattr(SimulationRunner, "SCRIPTS_DIR", str(scripts))
    monkeypatch.setattr(
        runner_module.subprocess,
        "Popen",
        lambda cmd, **_kwargs: (commands.append(list(cmd)), FakeProcess())[1],
    )
    monkeypatch.setattr(runner_module.threading, "Thread", InertThread)
    monkeypatch.setattr(
        SimulationRunner,
        "_sync_simulation_status",
        classmethod(lambda _cls, *_args, **_kwargs: None),
    )
    monkeypatch.setattr(
        runner_module.ZepGraphMemoryManager,
        "get_updater",
        classmethod(lambda _cls, _simulation_id: None),
    )

    def start(**kwargs):
        return SimulationRunner.start_simulation(simulation_id, **kwargs)

    try:
        yield SimpleNamespace(
            simulation_id=simulation_id, sim_dir=sim_dir, commands=commands, start=start
        )
    finally:
        for registry in (
            SimulationRunner._run_states,
            SimulationRunner._processes,
            SimulationRunner._monitor_threads,
            SimulationRunner._action_queues,
            SimulationRunner._stdout_files,
            SimulationRunner._stderr_files,
            SimulationRunner._graph_memory_enabled,
        ):
            registry.pop(simulation_id, None)


def _option(command, flag):
    return command[command.index(flag) + 1]


# --- --no-wait ---------------------------------------------------------------

def test_wait_for_commands_false_appends_no_wait(launch):
    _write_config(launch.sim_dir)
    launch.start(platform="parallel", wait_for_commands=False)
    assert "--no-wait" in launch.commands[0]


def test_default_start_keeps_the_environment_alive(launch):
    _write_config(launch.sim_dir)
    launch.start(platform="parallel")
    assert "--no-wait" not in launch.commands[0]


def test_exit_code_zero_publishes_completed_without_an_idle_environment(
    monkeypatch, tmp_path
):
    simulation_id = "sim-no-wait-exit"
    sim_dir = tmp_path / simulation_id
    sim_dir.mkdir()
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(time, "sleep", lambda _s: _REAL_SLEEP(0.01))
    monkeypatch.setattr(
        SimulationRunner,
        "_sync_simulation_status",
        classmethod(lambda _cls, *_args, **_kwargs: None),
    )
    monkeypatch.setattr(
        runner_module.ZepGraphMemoryManager,
        "get_updater",
        classmethod(lambda _cls, _simulation_id: None),
    )
    process = FakeProcess()
    state = SimulationRunState(
        simulation_id=simulation_id,
        runner_status=RunnerStatus.RUNNING,
        twitter_running=True,
        reddit_running=True,
    )
    SimulationRunner._save_run_state(state)
    SimulationRunner._processes[simulation_id] = process
    SimulationRunner._graph_memory_enabled[simulation_id] = False

    thread = threading.Thread(
        target=SimulationRunner._monitor_simulation, args=(simulation_id, "en"), daemon=True
    )
    SimulationRunner._monitor_threads[simulation_id] = thread
    thread.start()
    try:
        _REAL_SLEEP(0.2)
        assert state.runner_status == RunnerStatus.RUNNING  # no env marker: nothing to publish yet
        process.exit(0)
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert state.runner_status == RunnerStatus.COMPLETED
        assert state.error is None
        assert simulation_id not in SimulationRunner._processes
    finally:
        process.exit(0)
        thread.join(timeout=5)
        for registry in (SimulationRunner._run_states, SimulationRunner._processes,
                         SimulationRunner._monitor_threads, SimulationRunner._graph_memory_enabled):
            registry.pop(simulation_id, None)


# --- seeds -------------------------------------------------------------------

def test_explicit_seed_reaches_the_script_state_and_config(launch):
    _write_config(launch.sim_dir)
    state = launch.start(platform="parallel", seed=424242, max_rounds=12)

    command = launch.commands[0]
    assert _option(command, "--seed") == "424242"
    assert _option(command, "--max-rounds") == "12"
    assert state.seed == 424242
    assert state.to_dict()["seed"] == 424242

    saved = json.loads((launch.sim_dir / "run_state.json").read_text(encoding="utf-8"))
    assert saved["seed"] == 424242
    config = json.loads((launch.sim_dir / "simulation_config.json").read_text(encoding="utf-8"))
    assert config["run"] == {
        "seed": 424242, "replicate_index": None, "ensemble_id": None, "max_rounds": 12,
    }
    # a reload from disk keeps the seed
    SimulationRunner._run_states.pop(launch.simulation_id)
    assert SimulationRunner.get_run_state(launch.simulation_id).seed == 424242


def test_a_seed_is_generated_when_none_is_given_and_it_is_recorded_everywhere(launch):
    _write_config(launch.sim_dir)
    state = launch.start(platform="parallel")
    assert isinstance(state.seed, int) and 0 <= state.seed < 2 ** 31
    assert _option(launch.commands[0], "--seed") == str(state.seed)
    config = json.loads((launch.sim_dir / "simulation_config.json").read_text(encoding="utf-8"))
    assert config["run"]["seed"] == state.seed


def test_generated_seeds_differ_between_starts(launch):
    _write_config(launch.sim_dir)
    seeds = set()
    for _ in range(5):
        seeds.add(launch.start(platform="parallel").seed)
        # forget the finished "run" so the next start is not refused
        SimulationRunner._run_states.pop(launch.simulation_id, None)
        SimulationRunner._processes.pop(launch.simulation_id, None)
        (launch.sim_dir / "run_state.json").unlink()
    assert len(seeds) == 5


def test_seed_zero_is_a_real_seed(launch):
    _write_config(launch.sim_dir)
    state = launch.start(platform="parallel", seed=0)
    assert state.seed == 0 and _option(launch.commands[0], "--seed") == "0"


def test_other_run_settings_survive_and_a_stale_round_cap_is_removed(launch):
    run = {
        "seed": 1, "replicate_index": 2, "ensemble_id": "ens_x", "llm_temperature": 0.3,
        "outcome_questions": [{"id": "q1", "text": "?", "type": "probability"}], "max_rounds": 99,
    }
    _write_config(launch.sim_dir, run=run, behavior_version=2)
    launch.start(platform="parallel", seed=7)  # no max_rounds this time

    config = json.loads((launch.sim_dir / "simulation_config.json").read_text(encoding="utf-8"))
    assert config["run"] == {
        "seed": 7, "replicate_index": 2, "ensemble_id": "ens_x", "llm_temperature": 0.3,
        "outcome_questions": run["outcome_questions"],
    }
    assert config["behavior_version"] == 2
    assert "--max-rounds" not in launch.commands[0]


def test_the_config_file_is_replaced_atomically(launch):
    _write_config(launch.sim_dir)
    launch.start(platform="parallel", seed=1)
    assert [p.name for p in launch.sim_dir.iterdir() if p.suffix == ".tmp"] == []


# --- /start API --------------------------------------------------------------

@pytest.mark.parametrize("seed", [True, False, -1, 1.5, "7", [1], 2 ** 63])
def test_start_api_rejects_invalid_seeds(seed):
    app = Flask(__name__)
    with app.test_request_context(
        "/api/simulation/start", method="POST", json={"simulation_id": "sim-1", "seed": seed}
    ):
        response, status = simulation_api.start_simulation()
    assert status == 400
    assert "seed" in response.get_json()["error"].lower()


def test_start_api_passes_the_seed_through_and_returns_it(monkeypatch):
    simulation = SimpleNamespace(
        simulation_id="sim-1", project_id="proj-1", graph_id="g", status=SimulationStatus.READY
    )
    monkeypatch.setattr(
        simulation_api,
        "SimulationManager",
        lambda: SimpleNamespace(
            get_simulation=lambda _simulation_id: simulation,
            _save_simulation_state=lambda _state: None,
        ),
    )
    received = {}

    def fake_start(_cls, **kwargs):
        received.update(kwargs)
        return SimulationRunState(
            simulation_id="sim-1", runner_status=RunnerStatus.RUNNING, seed=kwargs["seed"]
        )

    monkeypatch.setattr(SimulationRunner, "start_simulation", classmethod(fake_start))

    app = Flask(__name__)
    with app.test_request_context(
        "/api/simulation/start", method="POST", json={"simulation_id": "sim-1", "seed": 99}
    ):
        response = simulation_api.start_simulation()

    assert received["seed"] == 99
    assert response.get_json()["data"]["seed"] == 99


def test_start_api_without_a_seed_lets_the_runner_pick_one(monkeypatch):
    simulation = SimpleNamespace(
        simulation_id="sim-1", project_id="proj-1", graph_id="g", status=SimulationStatus.READY
    )
    monkeypatch.setattr(
        simulation_api,
        "SimulationManager",
        lambda: SimpleNamespace(
            get_simulation=lambda _simulation_id: simulation,
            _save_simulation_state=lambda _state: None,
        ),
    )
    received = {}
    monkeypatch.setattr(
        SimulationRunner,
        "start_simulation",
        classmethod(
            lambda _cls, **kwargs: (
                received.update(kwargs),
                SimulationRunState(simulation_id="sim-1", seed=5),
            )[1]
        ),
    )
    app = Flask(__name__)
    with app.test_request_context(
        "/api/simulation/start", method="POST", json={"simulation_id": "sim-1"}
    ):
        response = simulation_api.start_simulation()
    assert received["seed"] is None
    assert response.get_json()["data"]["seed"] == 5


# --- setup / poll records are not agent behaviour ----------------------------

def _record(agent_id, round_num, **extra):
    return {
        "round": round_num, "timestamp": "2026-01-01T00:00:00", "agent_id": agent_id,
        "agent_name": f"A{agent_id}", "action_type": "CREATE_POST",
        "action_args": {"content": f"post {agent_id}-{round_num}"}, "result": None,
        "success": True, **extra,
    }


def _write_log(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


RECORDS = [
    _record(0, 0, phase="setup"),
    _record(1, 0, phase="setup"),
    _record(2, 1),
    _record(3, 2, phase="injected", event_id="evt_1"),
    _record(4, 3, phase="poll"),
    _record(5, 3),
]


def test_non_behavior_phases_constant():
    assert NON_BEHAVIOR_PHASES == {"setup", "poll"}


def test_monitor_counts_injected_actions_but_not_setup_or_poll(monkeypatch, tmp_path):
    simulation_id = "sim-phases"
    log = tmp_path / simulation_id / "twitter" / "actions.jsonl"
    _write_log(log, RECORDS)
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path))
    state = SimulationRunState(simulation_id=simulation_id, runner_status=RunnerStatus.RUNNING)

    SimulationRunner._read_action_log(str(log), 0, state, "twitter")

    assert state.twitter_actions_count == 3  # agents 2, 3 (injected) and 5
    assert sorted(a.agent_id for a in state.recent_actions) == [2, 3, 5]


def test_setup_and_poll_records_never_reach_the_zep_updater(monkeypatch, tmp_path):
    simulation_id = "sim-zep-phases"
    log = tmp_path / simulation_id / "reddit" / "actions.jsonl"
    _write_log(log, RECORDS)
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path))
    forwarded = []
    updater = SimpleNamespace(
        add_activity_from_dict=lambda data, platform: forwarded.append((data["agent_id"], platform))
    )
    monkeypatch.setattr(
        runner_module.ZepGraphMemoryManager,
        "get_updater",
        classmethod(lambda _cls, _simulation_id: updater),
    )
    SimulationRunner._graph_memory_enabled[simulation_id] = True
    state = SimulationRunState(simulation_id=simulation_id, runner_status=RunnerStatus.RUNNING)
    try:
        SimulationRunner._read_action_log(str(log), 0, state, "reddit")
    finally:
        SimulationRunner._graph_memory_enabled.pop(simulation_id, None)

    assert forwarded == [(2, "reddit"), (3, "reddit"), (5, "reddit")]


def test_action_queries_timeline_and_stats_exclude_setup_and_poll(monkeypatch, tmp_path):
    simulation_id = "sim-queries"
    _write_log(tmp_path / simulation_id / "twitter" / "actions.jsonl", RECORDS)
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path))

    actions = SimulationRunner.get_all_actions(simulation_id)
    assert sorted(a.agent_id for a in actions) == [2, 3, 5]
    stats = {row["agent_id"]: row["total_actions"] for row in SimulationRunner.get_agent_stats(simulation_id)}
    assert stats == {2: 1, 3: 1, 5: 1}
    assert sum(entry["total_actions"] for entry in SimulationRunner.get_timeline(simulation_id)) == 3
