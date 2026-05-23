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


def test_build_orchestrator_reads_graph_id_from_state(tmp_path, monkeypatch):
    """C1+C2: ``_build_orchestrator`` must resolve the Zep graph_id from
    ``state.json`` (written by ``SimulationManager``), not from the
    nonexistent ``graph_id.txt``.  The graph_id then must reach the
    ``InterviewZepWriter`` instead of being silently swallowed.
    """
    monkeypatch.setenv("LLM_STUB_MODE", "true")
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path))
    monkeypatch.setenv("ZEP_API_KEY", "test-fake-key")
    from app.config import Config
    Config.LLM_STUB_MODE = True
    Config.UPLOADS_DIR = str(tmp_path)
    Config.ZEP_API_KEY = "test-fake-key"

    # SimulationManager's data dir is class-level — point it at tmp_path.
    from app.services.simulation_manager import SimulationManager
    sim_root = tmp_path / "simulations"
    sim_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(sim_root))

    sim_id = "sim_graphid"
    sim_dir = sim_root / sim_id
    sim_dir.mkdir(parents=True)
    # Seed a profile file so FileSystemPersonaProvider can work.
    (sim_dir / "reddit_profiles.json").write_text(
        json.dumps([
            {"user_id": 0, "user_name": "u0", "name": "A0",
             "persona": "p", "profession": "fisher",
             "source_entity_uuid": "uuid-zero"},
            {"user_id": 1, "user_name": "u1", "name": "A1",
             "persona": "p", "profession": "fisher",
             "source_entity_uuid": "uuid-one"},
        ]),
        encoding="utf-8",
    )
    # Seed state.json with the graph_id.
    state_doc = {
        "simulation_id": sim_id,
        "project_id": "p",
        "graph_id": "graph-from-state",
        "status": "ready",
        "enable_twitter": False,
        "enable_reddit": True,
    }
    (sim_dir / "state.json").write_text(json.dumps(state_doc), encoding="utf-8")

    # Patch ZepGraphMemoryUpdater + ZepEntityReader so we don't hit the network.
    import app.services.zep_graph_memory_updater as zgmu
    import app.services.zep_entity_reader as zer

    class _FakeUpdater:
        def __init__(self, graph_id, api_key=None):
            self.graph_id = graph_id

        def add_text_episode(self, graph_id, text):
            return None

    class _FakeReader:
        def __init__(self, api_key=None):
            pass

        def get_entity_with_context(self, graph_id, entity_uuid):
            return None

    monkeypatch.setattr(zgmu, "ZepGraphMemoryUpdater", _FakeUpdater)
    monkeypatch.setattr(zer, "ZepEntityReader", _FakeReader)

    from app.api.interview import _build_orchestrator

    orch = _build_orchestrator(sim_id)
    assert orch.zep_writer.graph_id == "graph-from-state"
    # Updater on the writer must be the real (or fake) ZepGraphMemoryUpdater path,
    # NOT the null updater — i.e. its graph_id must match.
    assert getattr(orch.zep_writer.updater, "graph_id", None) == "graph-from-state"

    # ZepMemoryProvider must have received the agent_to_entity map (C5).
    assert hasattr(orch.memory, "map")
    assert orch.memory.map == {0: "uuid-zero", 1: "uuid-one"}


def test_build_orchestrator_falls_back_when_state_missing(tmp_path, monkeypatch):
    """C1+C2: when ``state.json`` is missing, the orchestrator must still be
    constructed with the null updater/memory path (not crash, not silently
    pass a bare ``ZepGraphMemoryUpdater()`` that would error out).
    """
    monkeypatch.setenv("LLM_STUB_MODE", "true")
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path))
    from app.config import Config
    Config.LLM_STUB_MODE = True
    Config.UPLOADS_DIR = str(tmp_path)

    from app.services.simulation_manager import SimulationManager
    sim_root = tmp_path / "simulations"
    sim_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(sim_root))

    sim_id = "sim_no_state"
    sim_dir = sim_root / sim_id
    sim_dir.mkdir(parents=True)
    (sim_dir / "reddit_profiles.json").write_text(
        json.dumps([{"user_id": 0, "user_name": "u0", "name": "A0",
                     "persona": "p", "profession": "fisher"}]),
        encoding="utf-8",
    )

    from app.api.interview import _build_orchestrator

    orch = _build_orchestrator(sim_id)
    assert orch.zep_writer.graph_id == ""
    # Null updater path: writer must still respond to _emit without raising.
    orch.zep_writer._emit("hello")
