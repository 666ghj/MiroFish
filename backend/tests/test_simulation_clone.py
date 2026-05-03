import json
import pytest
from pathlib import Path


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    from backend.app.services.simulation_manager import SimulationManager
    monkeypatch.setattr(SimulationManager, 'SIMULATION_DATA_DIR', str(tmp_path))
    from backend.app import create_app
    app = create_app({'TESTING': True})
    with app.test_client() as c:
        yield c, tmp_path


@pytest.fixture
def completed_sim(app_client):
    client, tmp_path = app_client
    sim_id = "sim_src001"
    sim_dir = tmp_path / sim_id
    sim_dir.mkdir()
    state = {
        "simulation_id": sim_id, "project_id": "proj_src", "graph_id": "g1",
        "status": "completed", "entities_count": 2, "profiles_count": 2,
        "entity_types": [], "config_generated": True,
        "parent_simulation_id": None, "graph_id_simulation": None,
    }
    (sim_dir / "state.json").write_text(json.dumps(state))
    profiles = [
        {"user_id": 0, "name": "Alice", "bio": "Bio A", "manually_edited": False},
        {"user_id": 1, "name": "Bob", "bio": "Bio B", "manually_edited": True},
    ]
    (sim_dir / "reddit_profiles.json").write_text(json.dumps(profiles))
    (sim_dir / "twitter_profiles.csv").write_text("user_id,name\n0,Alice\n1,Bob\n")
    (sim_dir / "agent_profiles.json").write_text(json.dumps(profiles))
    (sim_dir / "simulation_config.json").write_text(json.dumps({"time_config": {}}))
    return client, tmp_path, sim_id


def test_clone_creates_new_simulation(completed_sim):
    """POST /api/simulation/<src_id>/clone returns 200, success=True, with new_simulation_id and parent_simulation_id."""
    client, tmp_path, src_id = completed_sim
    resp = client.post(
        f'/api/simulation/{src_id}/clone',
        json={"project_id": "proj_clone"},
        content_type='application/json',
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "new_simulation_id" in data["data"]
    assert data["data"]["parent_simulation_id"] == src_id
    assert data["data"]["new_simulation_id"] != src_id


def test_clone_copies_profiles_not_config(completed_sim):
    """Cloned sim dir has reddit_profiles.json + twitter_profiles.csv, but NOT simulation_config.json."""
    client, tmp_path, src_id = completed_sim
    resp = client.post(
        f'/api/simulation/{src_id}/clone',
        json={"project_id": "proj_clone"},
        content_type='application/json',
    )
    assert resp.status_code == 200
    data = resp.get_json()
    new_id = data["data"]["new_simulation_id"]

    new_dir = tmp_path / new_id
    assert (new_dir / "reddit_profiles.json").exists(), "reddit_profiles.json should be copied"
    assert (new_dir / "twitter_profiles.csv").exists(), "twitter_profiles.csv should be copied"
    assert not (new_dir / "simulation_config.json").exists(), "simulation_config.json must NOT be copied"


def test_clone_status_is_profiles_ready(completed_sim):
    """Cloned sim state.json has status='profiles_ready' and correct parent_simulation_id."""
    client, tmp_path, src_id = completed_sim
    resp = client.post(
        f'/api/simulation/{src_id}/clone',
        json={"project_id": "proj_clone"},
        content_type='application/json',
    )
    assert resp.status_code == 200
    data = resp.get_json()
    new_id = data["data"]["new_simulation_id"]

    state_file = tmp_path / new_id / "state.json"
    assert state_file.exists(), "state.json must be created for cloned simulation"
    state = json.loads(state_file.read_text())
    assert state["status"] == "profiles_ready"
    assert state["parent_simulation_id"] == src_id
