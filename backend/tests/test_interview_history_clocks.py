"""Pinned OASIS clocks are platform-local and cannot be globally compared."""
import json
import sqlite3

from flask import Flask
import pytest

from app.api import simulation as simulation_api
from app.services.simulation_runner import SimulationRunner

# camel-ai/oasis v0.2.5, oasis/social_platform/schema/trace.sql.
# DATETIME has numeric affinity: get_time_step()'s numeric strings become ints,
# while time_transfer()'s datetime strings remain strings.
TRACE_SCHEMA = """
CREATE TABLE trace (
    user_id INTEGER,
    created_at DATETIME,
    action TEXT,
    info TEXT,
    PRIMARY KEY(user_id, created_at, action, info),
    FOREIGN KEY(user_id) REFERENCES user(user_id)
);
"""


@pytest.mark.parametrize("platform,limit,missing,expected", [
    (None, 4, None, ["twitter10", "twitter2", "reddit-new", "reddit-old"]),
    (None, 3, None, ["twitter10", "twitter2", "reddit-new"]),
    ("twitter", 1, None, ["twitter10"]),
    ("reddit", 2, None, ["reddit-new", "reddit-old"]),
    (None, 4, "reddit", ["twitter10", "twitter2"]),
    (None, 4, "both", []),
])
def test_actual_clock_types_are_preserved_without_cross_platform_sort(
    monkeypatch, tmp_path, platform, limit, missing, expected
):
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path))
    simulation = tmp_path / "clocks"
    simulation.mkdir()
    rows = {
        "twitter": [("2", "twitter2"), ("10", "twitter10")],
        "reddit": [("2026-01-01 12:00:00", "reddit-old"), ("2026-01-02 12:00:00", "reddit-new")],
    }
    for name, entries in rows.items():
        if missing in (name, "both"):
            continue
        with sqlite3.connect(simulation / f"{name}_simulation.db") as connection:
            connection.executescript(TRACE_SCHEMA)
            for timestamp, response in entries:
                connection.execute("INSERT INTO trace VALUES (?, ?, ?, ?)", (
                    0, timestamp, "interview", json.dumps({"response": response, "prompt": "question"})
                ))
    app = Flask(__name__)
    app.register_blueprint(simulation_api.simulation_bp, url_prefix="/simulation")
    payload = {"simulation_id": "clocks", "limit": limit}
    if platform:
        payload["platform"] = platform
    response = app.test_client().post("/simulation/interview/history", json=payload)
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert [item["response"] for item in data["history"]] == expected
    expected_ordering = "platform_local" if platform else "platform_grouped"
    if platform is None and missing is None:
        assert data["ordering"] == expected_ordering
    elif "ordering" in data:
        assert data["ordering"] == expected_ordering
    assert data["count"] == len(expected)
    for item in data["history"]:
        assert type(item["timestamp"]) is (int if item["platform"] == "twitter" else str)
