"""The real writer and monitor must agree on the configured simulation clock."""
import importlib.util
import json
from pathlib import Path

from flask import Flask
import pytest

from app.api import simulation as simulation_api
from app.services import simulation_runner as runner_module
from app.services.simulation_runner import RunnerStatus, SimulationRunState, SimulationRunner


@pytest.mark.parametrize("minutes_per_round", [30, 60, 120])
@pytest.mark.parametrize("completed_twitter_round", [1, 25])
def test_logged_round_duration_reaches_persisted_status_api(
    monkeypatch, tmp_path, minutes_per_round, completed_twitter_round
):
    scripts = Path(runner_module.__file__).resolve().parents[2] / "scripts"
    spec = importlib.util.spec_from_file_location("elapsed_action_logger", scripts / "action_logger.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    simulation_id = "elapsed-hours"
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(SimulationRunner, "_run_states", {})
    monkeypatch.setattr(SimulationRunner, "_graph_memory_enabled", {})
    state = SimulationRunState(simulation_id=simulation_id, runner_status=RunnerStatus.RUNNING)
    for platform, completed_round in [("twitter", completed_twitter_round), ("reddit", completed_twitter_round - 1)]:
        writer = module.PlatformActionLogger(platform, str(tmp_path / simulation_id))
        writer.log_simulation_start({"time_config": {
            "total_simulation_hours": 72, "minutes_per_round": minutes_per_round,
        }})
        # No agent actions are necessary for simulated time to advance.
        writer.log_round_end(0, 0)
        writer.log_round_end(completed_round, 0)
        records = [json.loads(line) for line in Path(writer.log_path).read_text().splitlines()]
        assert records[0]["total_rounds"] == 72 * 60 // minutes_per_round
        SimulationRunner._read_action_log(writer.log_path, 0, state, platform)
    SimulationRunner._save_run_state(state)
    SimulationRunner._run_states.clear()  # Exercise persisted-state reload too.
    app = Flask(__name__)
    app.register_blueprint(simulation_api.simulation_bp, url_prefix="/simulation")
    response = app.test_client().get(f"/simulation/{simulation_id}/run-status")
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["twitter_simulated_hours"] == completed_twitter_round * minutes_per_round / 60
    assert data["reddit_simulated_hours"] == (completed_twitter_round - 1) * minutes_per_round / 60
    assert data["simulated_hours"] == completed_twitter_round * minutes_per_round / 60
    assert data["current_round"] == completed_twitter_round
