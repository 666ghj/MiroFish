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


def test_delete_agent_removes_from_profiles(client, sim_with_profiles, tmp_path):
    sim_id = sim_with_profiles
    resp = client.delete(f"/api/simulation/{sim_id}/agent/1")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    # Verify file on disk
    from pathlib import Path
    import json as _json
    import os as _os
    sim_dir = Path(_os.environ.get("OASIS_SIMULATION_DATA_DIR", str(tmp_path))) / sim_id
    # Use the monkeypatched path from SimulationManager
    from backend.app.services.simulation_manager import SimulationManager
    sim_manager_dir = Path(SimulationManager.SIMULATION_DATA_DIR) / sim_id
    profiles = _json.loads((sim_manager_dir / "reddit_profiles.json").read_text())
    assert all(p["user_id"] != 1 for p in profiles)
    assert len(profiles) == 1


def test_delete_agent_not_found(client, sim_with_profiles):
    sim_id = sim_with_profiles
    resp = client.delete(f"/api/simulation/{sim_id}/agent/99")
    assert resp.status_code == 404


def test_generate_config_returns_task_id(client, sim_with_profiles, monkeypatch):
    sim_id = sim_with_profiles
    # Mock SimulationConfigGenerator to avoid real LLM calls
    # We just need the endpoint to accept the request and return task_id
    # The background thread will fail quickly but that's OK for this test
    import backend.app.services.simulation_config_generator as scg_module
    from backend.app.models.project import ProjectManager

    class FakeParams:
        def to_dict(self):
            return {"time_config": {"total_simulation_hours": 24}}

    monkeypatch.setattr(scg_module, "SimulationConfigGenerator",
                        lambda **kwargs: type('G', (), {
                            'generate_simulation_parameters': lambda self, **kw: FakeParams()
                        })())

    monkeypatch.setattr(ProjectManager, "get_project",
                        staticmethod(lambda pid: {"project_id": pid, "simulation_requirement": "test"}))

    resp = client.post(f"/api/simulation/{sim_id}/generate-config", json={})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "task_id" in data["data"]


@pytest.fixture
def sim_prepared(tmp_path, monkeypatch):
    """Creates a simulation with status=ready and a simulation_config.json"""
    from backend.app.services.simulation_manager import SimulationManager
    monkeypatch.setattr(SimulationManager, 'SIMULATION_DATA_DIR', str(tmp_path))
    sim_id = "sim_prepared001"
    sim_dir = tmp_path / sim_id
    sim_dir.mkdir()
    state = {
        "simulation_id": sim_id, "project_id": "p", "graph_id": "g",
        "status": "ready", "entities_count": 1, "profiles_count": 1,
        "entity_types": [], "config_generated": True, "config_reasoning": "",
        "current_round": 0, "twitter_status": "not_started", "reddit_status": "not_started",
        "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00",
        "error": None, "parent_simulation_id": None, "graph_id_simulation": None,
        "enable_twitter": True, "enable_reddit": True,
    }
    (sim_dir / "state.json").write_text(json.dumps(state))
    config = {"time_config": {"total_simulation_hours": 24, "minutes_per_round": 60}, "agent_configs": []}
    (sim_dir / "simulation_config.json").write_text(json.dumps(config))
    return sim_id


def test_patch_config_updates_total_hours(client, sim_prepared):
    sim_id = sim_prepared
    resp = client.patch(f"/api/simulation/{sim_id}/config", json={"total_simulation_hours": 48})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["data"]["time_config"]["total_simulation_hours"] == 48


def test_create_agent_adds_to_profiles(client, sim_with_profiles, monkeypatch):
    sim_id = sim_with_profiles

    import backend.app.services.simulation_manager as sm_module
    from backend.app.services.zep_entity_reader import EntityNode

    fake_entity = EntityNode(
        uuid="uuid_carol", name="Carol", labels=["Person", "Entity"],
        summary="Carol is a scientist", attributes={}
    )

    def fake_get_entity(self, graph_id, uuid_):
        return fake_entity

    monkeypatch.setattr(
        "backend.app.services.zep_entity_reader.ZepEntityReader.get_entity_with_context",
        fake_get_entity
    )

    from backend.app.services.oasis_profile_generator import OasisAgentProfile
    fake_profile = OasisAgentProfile(user_id=99, user_name="carol", name="Carol",
                                      bio="Carol bio", persona="Scientist",
                                      source_entity_uuid="uuid_carol")

    monkeypatch.setattr(
        "backend.app.services.oasis_profile_generator.OasisProfileGenerator.generate_profile_from_entity",
        lambda self, entity, extra_instructions=None: fake_profile
    )

    resp = client.post(f"/api/simulation/{sim_id}/agent",
                       json={"source_entity_uuid": "uuid_carol", "extra_instructions": "Make her skeptical"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "task_id" in data["data"]


def test_regenerate_agent_returns_task_id(client, sim_with_profiles, monkeypatch):
    sim_id = sim_with_profiles
    from backend.app.services.zep_entity_reader import EntityNode
    fake_entity = EntityNode(uuid="uuid_alice", name="Alice", labels=["Entity"], summary="", attributes={})
    monkeypatch.setattr(
        "backend.app.services.zep_entity_reader.ZepEntityReader.get_entity_with_context",
        lambda self, g, u: fake_entity
    )
    from backend.app.services.oasis_profile_generator import OasisAgentProfile
    fake_profile = OasisAgentProfile(user_id=0, user_name="alice2", name="Alice2",
                                      bio="New bio", persona="Skeptic",
                                      source_entity_uuid="uuid_alice")
    monkeypatch.setattr(
        "backend.app.services.oasis_profile_generator.OasisProfileGenerator.generate_profile_from_entity",
        lambda self, entity, extra_instructions=None: fake_profile
    )

    # Add source_entity_uuid to the first profile in the fixture's sim directory
    import json as _j
    from pathlib import Path
    from backend.app.services.simulation_manager import SimulationManager
    sim_dir = Path(SimulationManager.SIMULATION_DATA_DIR) / sim_id
    profiles = _j.loads((sim_dir / "reddit_profiles.json").read_text())
    profiles[0]["source_entity_uuid"] = "uuid_alice"
    (sim_dir / "reddit_profiles.json").write_text(_j.dumps(profiles))

    resp = client.post(f"/api/simulation/{sim_id}/agent/0/regenerate",
                       json={"extra_instructions": "Make her skeptical"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "task_id" in data["data"]
