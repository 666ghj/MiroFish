"""Aggregate APIs must include every persisted action, not one history page."""
import json
from datetime import datetime, timedelta

from flask import Flask
import pytest

from app.api import simulation as simulation_api
from app.services.simulation_runner import SimulationRunner


@pytest.mark.parametrize("split_platforms", [False, True])
def test_aggregate_endpoints_include_history_beyond_ten_thousand_actions(
    monkeypatch, tmp_path, split_platforms
):
    simulation_id = "aggregate-history"
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path))
    sim_dir = tmp_path / simulation_id
    records = []
    for index in range(10001):
        records.append({
            "round": 1 if index == 0 else 2,
            "agent_id": 1 if index == 0 else 2,
            "timestamp": (datetime(2026, 1, 1) + timedelta(seconds=index)).isoformat(),
            "action_type": "CREATE_POST",
        })
    for platform, entries in (
        [("twitter", records[:5000]), ("reddit", records[5000:])]
        if split_platforms else [("twitter", records)]
    ):
        folder = sim_dir / platform
        folder.mkdir(parents=True)
        (folder / "actions.jsonl").write_text(
            "".join(json.dumps(record) + "\n" for record in entries), encoding="utf-8"
        )

    app = Flask(__name__)
    app.register_blueprint(simulation_api.simulation_bp, url_prefix="/simulation")
    client = app.test_client()
    response = client.get(f"/simulation/{simulation_id}/timeline")
    assert response.status_code == 200
    timeline = response.get_json()["data"]["timeline"]
    assert sum(item["total_actions"] for item in timeline) == 10001
    assert [item["round_num"] for item in timeline] == [1, 2]
    assert timeline[0]["total_actions"] == 1

    response = client.get(f"/simulation/{simulation_id}/agent-stats")
    assert response.status_code == 200
    stats = response.get_json()["data"]["stats"]
    assert sum(item["total_actions"] for item in stats) == 10001
    assert {item["agent_id"] for item in stats} == {1, 2}

    response = client.get(f"/simulation/{simulation_id}/timeline?end_round=1")
    assert response.get_json()["data"]["timeline"][0]["total_actions"] == 1
