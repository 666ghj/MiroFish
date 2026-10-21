"""A fresh restart must never consume commands intended for the previous run."""
import json
from pathlib import Path

from flask import Flask

from app.api import simulation as simulation_api
from app.config import Config
from app.services.simulation_ipc import CommandType, IPCCommand, SimulationIPCServer
from app.services.simulation_manager import SimulationManager, SimulationStatus
from app.services.simulation_runner import RunnerStatus, SimulationRunState, SimulationRunner


def prepare_old_run(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(SimulationRunner, "_run_states", {})
    monkeypatch.setattr(SimulationRunner, "_processes", {})
    monkeypatch.setattr(SimulationRunner, "_graph_memory_enabled", {})
    manager = SimulationManager()
    state = manager.create_simulation("project", "graph")
    state.status = SimulationStatus.COMPLETED
    state.profiles_generated = state.config_generated = True
    manager._save_simulation_state(state)
    folder = tmp_path / state.simulation_id
    preserved = {"simulation_config.json": '{"agent_configs": []}',
                 "reddit_profiles.json": "[]", "twitter_profiles.csv": "user_id,name\n"}
    for filename, content in preserved.items():
        (folder / filename).write_text(content, encoding="utf-8")
    old_server = SimulationIPCServer(str(folder))
    (Path(old_server.commands_dir) / "old-close.json").write_text(json.dumps(
        IPCCommand("old-close", CommandType.CLOSE_ENV, {}).to_dict()
    ), encoding="utf-8")
    (Path(old_server.responses_dir) / "old-response.json").write_text('{"result":"old"}', encoding="utf-8")
    SimulationRunner._save_run_state(SimulationRunState(
        simulation_id=state.simulation_id, runner_status=RunnerStatus.STOPPED
    ))
    return state, folder, preserved


def assert_fresh_queue(folder, preserved):
    server = SimulationIPCServer(str(folder))
    assert server.poll_commands() is None
    assert not list(Path(server.responses_dir).glob("*.json"))
    for filename, content in preserved.items():
        assert (folder / filename).read_text(encoding="utf-8") == content
    command = IPCCommand("new-interview", CommandType.INTERVIEW, {"agent_id": 0, "prompt": "new question"})
    (Path(server.commands_dir) / "new-interview.json").write_text(json.dumps(command.to_dict()), encoding="utf-8")
    assert server.poll_commands().command_id == "new-interview"


def test_cleanup_removes_previous_process_ipc_queues(monkeypatch, tmp_path):
    state, folder, preserved = prepare_old_run(monkeypatch, tmp_path)
    result = SimulationRunner.cleanup_simulation_logs(state.simulation_id)
    assert result["success"] is True
    assert_fresh_queue(folder, preserved)


def test_force_restart_cleans_ipc_before_launch_boundary(monkeypatch, tmp_path):
    state, folder, preserved = prepare_old_run(monkeypatch, tmp_path)
    launched = []

    def launch(_cls, simulation_id, **kwargs):
        # Subprocess/model execution is deliberately outside this API test.
        assert_fresh_queue(folder, preserved)
        launched.append(simulation_id)
        return SimulationRunState(simulation_id=simulation_id, runner_status=RunnerStatus.RUNNING)

    monkeypatch.setattr(SimulationRunner, "start_simulation", classmethod(launch))
    app = Flask(__name__)
    app.register_blueprint(simulation_api.simulation_bp, url_prefix="/simulation")
    response = app.test_client().post("/simulation/start", json={
        "simulation_id": state.simulation_id, "force": True,
    })
    assert response.status_code == 200
    assert response.get_json()["data"]["force_restarted"] is True
    assert launched == [state.simulation_id]
