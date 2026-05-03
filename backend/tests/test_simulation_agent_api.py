import json
import os
import pytest
from flask import Flask


@pytest.fixture
def app():
    os.environ.setdefault("SECRET_KEY", "test")
    from backend.app import create_app
    application = create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False})
    return application


@pytest.fixture
def client(app):
    with app.test_client() as c:
        yield c


@pytest.fixture
def sim_with_profiles(tmp_path, monkeypatch):
    """Creates a simulation directory with a minimal state.json and reddit_profiles.json"""
    from backend.app.services import simulation_manager as sm_module
    monkeypatch.setattr(sm_module.SimulationManager, 'SIMULATION_DATA_DIR', str(tmp_path))

    sim_id = "sim_test001"
    sim_dir = tmp_path / sim_id
    sim_dir.mkdir()

    state = {
        "simulation_id": sim_id,
        "project_id": "proj_test",
        "graph_id": "g1",
        "status": "profiles_ready",
        "entities_count": 2,
        "profiles_count": 2,
        "entity_types": [],
        "config_generated": False,
        "config_reasoning": "",
        "current_round": 0,
        "twitter_status": "not_started",
        "reddit_status": "not_started",
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
        "error": None,
        "parent_simulation_id": None,
        "graph_id_simulation": None,
        "enable_twitter": True,
        "enable_reddit": True,
    }
    (sim_dir / "state.json").write_text(json.dumps(state))

    profiles = [
        {"user_id": 0, "user_name": "alice", "name": "Alice", "bio": "Original bio",
         "persona": "Curious", "manually_edited": False},
        {"user_id": 1, "user_name": "bob", "name": "Bob", "bio": "Bob bio",
         "persona": "Bold", "manually_edited": False},
    ]
    (sim_dir / "reddit_profiles.json").write_text(json.dumps(profiles))
    return sim_id


def test_patch_agent_updates_bio(client, sim_with_profiles):
    sim_id = sim_with_profiles
    resp = client.patch(f"/api/simulation/{sim_id}/agent/0", json={"bio": "Updated bio"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["data"]["bio"] == "Updated bio"
    assert data["data"]["manually_edited"] is True


def test_patch_agent_sets_manually_edited(client, sim_with_profiles, tmp_path):
    sim_id = sim_with_profiles
    client.patch(f"/api/simulation/{sim_id}/agent/0", json={"bio": "New bio"})
    sim_dir = tmp_path / sim_id
    profiles = json.loads((sim_dir / "reddit_profiles.json").read_text())
    assert profiles[0]["manually_edited"] is True
    assert profiles[1]["manually_edited"] is False  # untouched


def test_patch_agent_not_found(client, sim_with_profiles):
    sim_id = sim_with_profiles
    resp = client.patch(f"/api/simulation/{sim_id}/agent/99", json={"bio": "x"})
    assert resp.status_code == 404
