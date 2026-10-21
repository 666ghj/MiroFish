"""Chronological aggregate bounds must not inherit reverse history order."""
import json

from flask import Flask

from app.api import simulation as simulation_api
from app.services.simulation_runner import SimulationRunner


def test_timeline_and_agent_stats_preserve_chronological_time_bounds(monkeypatch, tmp_path):
    simulation_id = "time-bounds"
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path))
    first = "2026-01-01T10:00:00"
    last = "2026-01-01T11:00:00"
    # Include out-of-order writes across both platform files. API history is
    # newest-first, but first/last describe chronological bounds of each group.
    for platform, times in [("twitter", [last, first]), ("reddit", ["2026-01-01T10:30:00"])]:
        folder = tmp_path / simulation_id / platform
        folder.mkdir(parents=True)
        (folder / "actions.jsonl").write_text("".join(
            json.dumps({"round": 1, "agent_id": 7, "timestamp": timestamp, "action_type": "CREATE_POST"}) + "\n"
            for timestamp in times
        ), encoding="utf-8")
    app = Flask(__name__)
    app.register_blueprint(simulation_api.simulation_bp, url_prefix="/simulation")
    client = app.test_client()
    for endpoint, key in [("timeline", "timeline"), ("agent-stats", "stats")]:
        response = client.get(f"/simulation/{simulation_id}/{endpoint}")
        assert response.status_code == 200
        item = response.get_json()["data"][key][0]
        assert item["first_action_time"] == first
        assert item["last_action_time"] == last
        assert item["first_action_time"] <= item["last_action_time"]
        assert item["total_actions"] == 3
