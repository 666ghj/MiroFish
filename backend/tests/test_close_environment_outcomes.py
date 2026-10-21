"""Unconfirmed IPC delivery must not report successful simulation completion."""
import json
from pathlib import Path
import threading
import time

from flask import Flask
import pytest

from app.api import simulation as simulation_api
from app.services.simulation_ipc import SimulationIPCServer
from app.services.simulation_manager import SimulationManager, SimulationStatus
from app.services.simulation_runner import SimulationRunner


@pytest.fixture
def close_environment(monkeypatch, tmp_path):
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path))
    manager = SimulationManager()
    state = manager.create_simulation("project", "graph")
    state.status = SimulationStatus.FAILED
    manager._save_simulation_state(state)
    folder = tmp_path / state.simulation_id
    (folder / "env_status.json").write_text(json.dumps({"status": "alive"}), encoding="utf-8")
    app = Flask(__name__)
    app.register_blueprint(simulation_api.simulation_bp, url_prefix="/simulation")
    return app.test_client(), manager, state, folder


def test_unconsumed_close_command_times_out_without_completing_simulation(close_environment):
    client, manager, state, folder = close_environment
    response = client.post("/simulation/close-env", json={"simulation_id": state.simulation_id, "timeout": 0})
    assert response.status_code == 504
    assert response.get_json()["success"] is False
    assert json.loads((folder / "env_status.json").read_text())["status"] == "alive"
    assert not list((folder / "ipc_commands").glob("*.json"))
    assert SimulationManager().get_simulation(state.simulation_id).status == SimulationStatus.FAILED


@pytest.mark.parametrize("success", [False, True])
def test_real_close_ack_controls_success_and_persisted_status(close_environment, success):
    client, manager, state, folder = close_environment
    server = SimulationIPCServer(str(folder))
    stop = threading.Event()
    errors = []

    def respond():
        try:
            deadline = time.monotonic() + 3
            while not stop.is_set() and time.monotonic() < deadline:
                command = server.poll_commands()
                if command:
                    if success:
                        server.stop()
                        server.send_success(command.command_id, {"message": "closed"})
                    else:
                        server.send_error(command.command_id, "close rejected")
                    return
                stop.wait(0.005)
        except Exception as error:
            errors.append(error)

    thread = threading.Thread(target=respond)
    thread.start()
    try:
        response = client.post("/simulation/close-env", json={"simulation_id": state.simulation_id, "timeout": 2})
    finally:
        stop.set()
        thread.join(timeout=3)
    assert not errors
    assert not thread.is_alive()
    assert response.status_code == 200
    assert response.get_json()["success"] is success
    expected = SimulationStatus.COMPLETED if success else SimulationStatus.FAILED
    assert SimulationManager().get_simulation(state.simulation_id).status == expected


def test_already_stopped_environment_remains_idempotent(close_environment):
    client, manager, state, folder = close_environment
    (folder / "env_status.json").write_text(json.dumps({"status": "stopped"}), encoding="utf-8")
    result = SimulationRunner.close_simulation_env(state.simulation_id, timeout=0)
    assert result["success"] is True
