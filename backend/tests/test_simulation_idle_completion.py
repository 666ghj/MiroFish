"""A finished run must publish its result while its environment stays alive.

After the last round the simulation script parks itself in command-wait mode
(so agents can still be interviewed) and never exits on its own. The run
therefore has to be published as COMPLETED when the rounds finish, not when the
process exits - otherwise the UI and the report API wait forever.
"""

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
    RunnerStatus,
    SimulationRunState,
    SimulationRunner,
)

_REAL_SLEEP = time.sleep


class FakeProcess:
    pid = 4242

    def __init__(self):
        self.returncode = None

    def poll(self):
        return self.returncode

    def exit(self, code):
        self.returncode = code


def _wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        _REAL_SLEEP(0.01)
    return False


def _action(platform):
    return {
        "round": 1,
        "timestamp": "2026-01-01T00:00:00",
        "platform": platform,
        "agent_id": 1,
        "agent_name": "agent",
        "action_type": "CREATE_POST",
        "action_args": {},
        "success": True,
    }


@pytest.fixture
def run(monkeypatch, tmp_path):
    """A RUNNING parallel simulation whose rounds are already finished."""

    simulation_id = "sim-idle"
    sim_dir = tmp_path / simulation_id
    for platform in ("twitter", "reddit"):
        platform_dir = sim_dir / platform
        platform_dir.mkdir(parents=True)
        records = [
            _action(platform),
            {"event_type": "simulation_end", "total_rounds": 1, "total_actions": 1},
        ]
        (platform_dir / "actions.jsonl").write_text(
            "".join(json.dumps(record) + "\n" for record in records),
            encoding="utf-8",
        )

    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(
        SimulationRunner,
        "_sync_simulation_status",
        classmethod(lambda _cls, *_args, **_kwargs: None),
    )
    # The monitor polls every 2s; keep the tests fast.
    monkeypatch.setattr(time, "sleep", lambda _seconds: _REAL_SLEEP(0.01))
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

    threads = []

    def start_monitor():
        thread = threading.Thread(
            target=SimulationRunner._monitor_simulation,
            args=(simulation_id, "en"),
            daemon=True,
        )
        SimulationRunner._monitor_threads[simulation_id] = thread
        thread.start()
        threads.append(thread)
        return thread

    def mark_env_alive():
        (sim_dir / "env_status.json").write_text(
            json.dumps({"status": "alive"}), encoding="utf-8"
        )

    try:
        yield SimpleNamespace(
            simulation_id=simulation_id,
            state=state,
            process=process,
            start_monitor=start_monitor,
            mark_env_alive=mark_env_alive,
        )
    finally:
        process.exit(0)
        for thread in threads:
            thread.join(timeout=5)
        SimulationRunner._run_states.pop(simulation_id, None)
        SimulationRunner._processes.pop(simulation_id, None)
        SimulationRunner._monitor_threads.pop(simulation_id, None)
        SimulationRunner._action_queues.pop(simulation_id, None)
        SimulationRunner._graph_memory_enabled.pop(simulation_id, None)
        SimulationRunner._manual_stop_requests.discard(simulation_id)


def test_run_completes_while_the_environment_stays_alive(run):
    run.mark_env_alive()
    monitor = run.start_monitor()

    assert _wait_until(lambda: run.state.runner_status == RunnerStatus.COMPLETED)
    assert run.process.poll() is None, "the environment must stay alive"
    assert run.state.completed_at is not None
    assert run.state.twitter_completed and run.state.reddit_completed
    assert not run.state.twitter_running and not run.state.reddit_running
    assert run.state.twitter_actions_count == 1
    assert run.state.reddit_actions_count == 1
    assert monitor.is_alive(), "the monitor keeps tracking the live process"

    # Closing the environment later (non-zero exit when it is terminated) must
    # not turn the finished run into a failure.
    run.process.exit(1)
    monitor.join(timeout=5)
    assert not monitor.is_alive()
    assert run.state.runner_status == RunnerStatus.COMPLETED
    assert run.state.error is None
    assert run.simulation_id not in SimulationRunner._processes
    assert run.simulation_id not in SimulationRunner._monitor_threads


def test_zep_ingestion_is_drained_before_completion_is_published(
    monkeypatch, run
):
    events = []

    def stop_updater(_cls, simulation_id):
        events.append(SimulationRunner.get_run_state(simulation_id).runner_status)

    monkeypatch.setattr(
        runner_module.ZepGraphMemoryManager,
        "stop_updater",
        classmethod(stop_updater),
    )
    SimulationRunner._graph_memory_enabled[run.simulation_id] = True
    run.mark_env_alive()
    run.start_monitor()

    assert _wait_until(lambda: run.state.runner_status == RunnerStatus.COMPLETED)
    # The drain ran behind the non-terminal STOPPING barrier, exactly once.
    assert events == [RunnerStatus.STOPPING]
    assert run.simulation_id not in SimulationRunner._graph_memory_enabled
    assert run.process.poll() is None


def test_zep_drain_failure_fails_the_run_without_killing_the_environment(
    monkeypatch, run
):
    monkeypatch.setattr(
        runner_module.ZepGraphMemoryManager,
        "stop_updater",
        classmethod(
            lambda _cls, _simulation_id: (_ for _ in ()).throw(
                RuntimeError("zep down")
            )
        ),
    )
    SimulationRunner._graph_memory_enabled[run.simulation_id] = True
    run.mark_env_alive()
    monitor = run.start_monitor()

    assert _wait_until(lambda: run.state.runner_status == RunnerStatus.FAILED)
    assert "zep down" in run.state.error
    assert SimulationRunner._graph_memory_enabled[run.simulation_id] is True

    run.process.exit(1)
    monitor.join(timeout=5)
    assert run.state.runner_status == RunnerStatus.FAILED


def test_exit_without_a_live_environment_still_completes_the_run(run):
    # No env_status.json: the script is not parked in command-wait mode (for
    # example `--no-wait`), so process exit remains the completion signal.
    monitor = run.start_monitor()

    _REAL_SLEEP(0.2)
    assert run.state.runner_status == RunnerStatus.RUNNING

    run.process.exit(0)
    monitor.join(timeout=5)
    assert run.state.runner_status == RunnerStatus.COMPLETED
    assert run.state.error is None


def test_crash_without_a_live_environment_still_fails_the_run(run):
    monitor = run.start_monitor()

    run.process.exit(3)
    monitor.join(timeout=5)
    assert run.state.runner_status == RunnerStatus.FAILED
    assert "3" in run.state.error


def test_pending_manual_stop_owns_the_outcome(run):
    SimulationRunner._manual_stop_requests.add(run.simulation_id)
    run.mark_env_alive()

    assert SimulationRunner._publish_completion_while_idle(run.simulation_id) is False
    assert run.state.runner_status == RunnerStatus.RUNNING


def test_idle_detection_requires_every_condition(run):
    state = run.state
    state.twitter_completed = state.reddit_completed = True
    state.twitter_running = state.reddit_running = False

    assert not SimulationRunner._is_idle_in_command_wait(state), "env not alive"

    run.mark_env_alive()
    assert SimulationRunner._is_idle_in_command_wait(state)

    state.reddit_running = True
    assert not SimulationRunner._is_idle_in_command_wait(state), "still running"
    state.reddit_running = False

    state.reddit_completed = False
    assert not SimulationRunner._is_idle_in_command_wait(state), "not finished"
    state.reddit_completed = True

    state.runner_status = RunnerStatus.STOPPING
    assert not SimulationRunner._is_idle_in_command_wait(state), "not RUNNING"


def test_stop_closes_the_idle_environment_of_a_completed_run(monkeypatch):
    simulation_id = "sim-idle-stop"
    state = SimulationRunState(
        simulation_id=simulation_id, runner_status=RunnerStatus.COMPLETED
    )
    process = FakeProcess()
    terminated = []
    monkeypatch.setattr(
        SimulationRunner,
        "get_run_state",
        classmethod(lambda _cls, _simulation_id: state),
    )
    monkeypatch.setattr(
        runner_module.ZepGraphMemoryManager,
        "get_updater",
        classmethod(lambda _cls, _simulation_id: None),
    )
    monkeypatch.setattr(
        SimulationRunner,
        "_terminate_process",
        classmethod(
            lambda _cls, proc, sim_id, **_kwargs: (
                terminated.append(sim_id),
                proc.exit(1),
            )
        ),
    )
    SimulationRunner._processes[simulation_id] = process

    try:
        result = SimulationRunner.stop_simulation(simulation_id)
    finally:
        SimulationRunner._processes.pop(simulation_id, None)

    assert terminated == [simulation_id]
    assert result is state
    assert state.runner_status == RunnerStatus.COMPLETED
    assert simulation_id not in SimulationRunner._manual_stop_requests


def test_stop_still_rejects_a_completed_run_without_a_live_process(monkeypatch):
    state = SimulationRunState(
        simulation_id="sim-done", runner_status=RunnerStatus.COMPLETED
    )
    monkeypatch.setattr(
        SimulationRunner,
        "get_run_state",
        classmethod(lambda _cls, _simulation_id: state),
    )
    monkeypatch.setattr(
        runner_module.ZepGraphMemoryManager,
        "get_updater",
        classmethod(lambda _cls, _simulation_id: None),
    )
    SimulationRunner._processes.pop("sim-done", None)

    with pytest.raises(ValueError, match="模拟未在运行"):
        SimulationRunner.stop_simulation("sim-done")


def test_start_refuses_to_share_a_directory_with_a_live_environment(
    monkeypatch, tmp_path
):
    simulation_id = "sim-still-alive"
    sim_dir = tmp_path / simulation_id
    sim_dir.mkdir()
    (sim_dir / "simulation_config.json").write_text(
        json.dumps({
            "time_config": {"total_simulation_hours": 1, "minutes_per_round": 60}
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(
        runner_module.ZepGraphMemoryManager,
        "get_updater",
        classmethod(lambda _cls, _simulation_id: None),
    )
    SimulationRunner._run_states[simulation_id] = SimulationRunState(
        simulation_id=simulation_id, runner_status=RunnerStatus.COMPLETED
    )
    SimulationRunner._processes[simulation_id] = FakeProcess()

    try:
        with pytest.raises(ValueError, match="模拟已在运行"):
            SimulationRunner.start_simulation(simulation_id, platform="twitter")
    finally:
        SimulationRunner._run_states.pop(simulation_id, None)
        SimulationRunner._processes.pop(simulation_id, None)


def test_start_clears_a_stale_alive_marker_from_a_previous_run(
    monkeypatch, tmp_path
):
    simulation_id = "sim-stale-marker"
    sim_dir = tmp_path / "runs" / simulation_id
    scripts_dir = tmp_path / "scripts"
    sim_dir.mkdir(parents=True)
    scripts_dir.mkdir()
    (sim_dir / "simulation_config.json").write_text(
        json.dumps({
            "time_config": {"total_simulation_hours": 1, "minutes_per_round": 60}
        }),
        encoding="utf-8",
    )
    # Left behind by an earlier process that was killed instead of closed.
    (sim_dir / "env_status.json").write_text(
        json.dumps({"status": "alive"}), encoding="utf-8"
    )
    (scripts_dir / "run_parallel_simulation.py").write_text(
        "pass\n", encoding="utf-8"
    )

    class InertThread:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            pass

    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path / "runs"))
    monkeypatch.setattr(SimulationRunner, "SCRIPTS_DIR", str(scripts_dir))
    monkeypatch.setattr(
        runner_module.subprocess, "Popen", lambda *_args, **_kwargs: FakeProcess()
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

    try:
        SimulationRunner.start_simulation(simulation_id, platform="twitter")
        assert not (sim_dir / "env_status.json").exists()
        assert not SimulationRunner.check_env_alive(simulation_id)
    finally:
        SimulationRunner._run_states.pop(simulation_id, None)
        SimulationRunner._processes.pop(simulation_id, None)
        SimulationRunner._monitor_threads.pop(simulation_id, None)
        SimulationRunner._action_queues.pop(simulation_id, None)
        SimulationRunner._stdout_files.pop(simulation_id, None)
        SimulationRunner._stderr_files.pop(simulation_id, None)
        SimulationRunner._graph_memory_enabled.pop(simulation_id, None)


def _patch_start_api(monkeypatch, *, stop_calls):
    simulation = SimpleNamespace(
        simulation_id="sim-1",
        project_id="proj-1",
        graph_id="graph-1",
        status=SimulationStatus.COMPLETED,
    )
    monkeypatch.setattr(
        simulation_api,
        "SimulationManager",
        lambda: SimpleNamespace(
            get_simulation=lambda _simulation_id: simulation,
            _save_simulation_state=lambda _state: None,
        ),
    )
    monkeypatch.setattr(
        simulation_api,
        "_check_simulation_prepared",
        lambda _simulation_id: (True, {}),
    )
    monkeypatch.setattr(
        simulation_api.SimulationRunner,
        "get_run_state",
        classmethod(
            lambda _cls, _simulation_id: SimpleNamespace(
                runner_status=RunnerStatus.COMPLETED
            )
        ),
    )
    monkeypatch.setattr(
        simulation_api.SimulationRunner,
        "has_live_process",
        classmethod(lambda _cls, _simulation_id: True),
    )
    monkeypatch.setattr(
        simulation_api.ZepGraphMemoryManager,
        "get_updater",
        classmethod(lambda _cls, _simulation_id: None),
    )
    monkeypatch.setattr(
        simulation_api.SimulationRunner,
        "stop_simulation",
        classmethod(
            lambda _cls, simulation_id: (
                stop_calls.append(simulation_id),
                SimpleNamespace(runner_status=RunnerStatus.COMPLETED),
            )[1]
        ),
    )


def test_restart_without_force_keeps_the_live_environment(monkeypatch):
    stop_calls = []
    _patch_start_api(monkeypatch, stop_calls=stop_calls)

    app = Flask(__name__)
    with app.test_request_context(
        "/api/simulation/start", method="POST", json={"simulation_id": "sim-1"}
    ):
        response, status = simulation_api.start_simulation()

    assert status == 400
    assert stop_calls == []


def test_forced_restart_closes_the_live_environment_before_cleanup(monkeypatch):
    stop_calls = []
    cleanup_calls = []
    _patch_start_api(monkeypatch, stop_calls=stop_calls)
    monkeypatch.setattr(
        simulation_api.SimulationRunner,
        "cleanup_simulation_logs",
        classmethod(
            lambda _cls, simulation_id: (
                cleanup_calls.append((simulation_id, list(stop_calls))),
                {"success": False, "errors": ["stop here"]},
            )[1]
        ),
    )

    app = Flask(__name__)
    with app.test_request_context(
        "/api/simulation/start",
        method="POST",
        json={"simulation_id": "sim-1", "force": True},
    ):
        response, status = simulation_api.start_simulation()

    # COMPLETED is the expected outcome of closing an idle environment, so the
    # restart proceeds as far as the (deliberately failing) log cleanup.
    assert stop_calls == ["sim-1"]
    assert cleanup_calls == [("sim-1", ["sim-1"])]
    assert status == 500


def test_stop_api_keeps_a_finished_run_marked_completed(monkeypatch):
    simulation = SimpleNamespace(status=SimulationStatus.COMPLETED, error=None)
    monkeypatch.setattr(
        simulation_api.SimulationRunner,
        "stop_simulation",
        classmethod(
            lambda _cls, _simulation_id: SimpleNamespace(
                runner_status=RunnerStatus.COMPLETED,
                to_dict=lambda: {"runner_status": "completed"},
            )
        ),
    )
    monkeypatch.setattr(
        simulation_api,
        "SimulationManager",
        lambda: SimpleNamespace(
            get_simulation=lambda _simulation_id: simulation,
            _save_simulation_state=lambda _state: None,
        ),
    )

    app = Flask(__name__)
    with app.test_request_context(
        "/api/simulation/stop", method="POST", json={"simulation_id": "sim-1"}
    ):
        response = simulation_api.stop_simulation()

    assert response.get_json()["success"] is True
    assert simulation.status == SimulationStatus.COMPLETED
