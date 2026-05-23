import json
import os
from pathlib import Path
import pytest

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_STUB_MODE", "true")
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path))
    from app.config import Config
    Config.LLM_STUB_MODE = True
    Config.UPLOADS_DIR = str(tmp_path)
    # Seed a minimal reddit_profiles.json
    sim_dir = tmp_path / "simulations" / "sim_test"
    sim_dir.mkdir(parents=True)
    profiles = [{"user_id": i, "user_name": f"u{i}", "name": f"A{i}",
                 "persona": "p", "profession": "fisher"} for i in range(3)]
    (sim_dir / "reddit_profiles.json").write_text(json.dumps(profiles), encoding="utf-8")
    from flask import Flask
    from app.api import register_blueprints
    app = Flask(__name__)
    register_blueprints(app)
    return app.test_client()

def test_post_pre_returns_task_id(client):
    res = client.post("/api/interview/sim_test/pre")
    assert res.status_code == 200
    body = res.get_json()
    assert body["success"] is True
    assert "task_id" in body["data"]

def test_status_endpoint_returns_progress(client):
    res = client.post("/api/interview/sim_test/pre")
    task_id = res.get_json()["data"]["task_id"]
    res2 = client.get(f"/api/interview/sim_test/status?task_id={task_id}")
    assert res2.status_code == 200
    assert "status" in res2.get_json()["data"]

def test_unknown_subagent_returns_400(client):
    res = client.post("/api/interview/sim_test/rerun",
                      json={"subagent": "nonsense"})
    assert res.status_code == 400
