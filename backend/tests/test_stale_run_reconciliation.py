import json

from app.services.simulation_runner import RunnerStatus, SimulationRunner


def _write_run_state(root, simulation_id, **overrides):
    simulation_dir = root / simulation_id
    simulation_dir.mkdir(parents=True)
    state = {
        "simulation_id": simulation_id,
        "runner_status": "stopping",
        "current_round": 40,
        "total_rounds": 40,
        "twitter_completed": True,
        "reddit_completed": True,
        "process_pid": 999999999,
        **overrides,
    }
    (simulation_dir / "run_state.json").write_text(
        json.dumps(state), encoding="utf-8"
    )
    return simulation_id, simulation_dir / "run_state.json"


def test_dead_process_with_completed_platforms_is_reconciled(tmp_path, monkeypatch):
    simulation_id, state_path = _write_run_state(tmp_path, "sim-complete")
    (tmp_path / simulation_id / "twitter").mkdir()
    (tmp_path / simulation_id / "reddit").mkdir()
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path))
    SimulationRunner._run_states.pop(simulation_id, None)
    SimulationRunner._processes.pop(simulation_id, None)
    SimulationRunner._monitor_threads.pop(simulation_id, None)

    try:
        state = SimulationRunner._load_run_state(simulation_id)
        assert state is not None
        assert state.runner_status == RunnerStatus.COMPLETED
        assert state.process_pid is None
        assert state.error is None
        persisted = json.loads(state_path.read_text(encoding="utf-8"))
        assert persisted["runner_status"] == "completed"
        assert persisted["process_pid"] is None
    finally:
        SimulationRunner._run_states.pop(simulation_id, None)


def test_dead_process_without_complete_horizon_fails_closed(tmp_path, monkeypatch):
    simulation_id, state_path = _write_run_state(
        tmp_path,
        "sim-incomplete",
        current_round=12,
        twitter_completed=False,
        reddit_completed=True,
    )
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path))
    SimulationRunner._run_states.pop(simulation_id, None)
    SimulationRunner._processes.pop(simulation_id, None)
    SimulationRunner._monitor_threads.pop(simulation_id, None)

    try:
        state = SimulationRunner._load_run_state(simulation_id)
        assert state is not None
        assert state.runner_status == RunnerStatus.FAILED
        assert state.process_pid is None
        assert state.error == "Simulation process exited before reaching a terminal state"
        persisted = json.loads(state_path.read_text(encoding="utf-8"))
        assert persisted["runner_status"] == "failed"
    finally:
        SimulationRunner._run_states.pop(simulation_id, None)
