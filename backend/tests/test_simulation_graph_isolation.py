import json
import os

from app.config import Config
from app.services.simulation_manager import SimulationManager


def test_ensure_isolated_simulation_graph_clones_project_graph(tmp_path, monkeypatch):
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(Config, "ZEP_API_KEY", "zep-test-key", raising=False)

    clone_calls = []

    class FakeTaskClient:
        def get(self, task_id, **_kwargs):
            class Task:
                status = "completed"
                completed_at = "2026-01-01T00:00:00"
                error = None

            return Task()

    class FakeGraphClient:
        def clone(self, *, source_graph_id=None, target_graph_id=None, **_kwargs):
            clone_calls.append((source_graph_id, target_graph_id))

            class Resp:
                graph_id = target_graph_id
                task_id = "task_1"

            return Resp()

    class FakeZep:
        def __init__(self, api_key=None):
            self.api_key = api_key
            self.graph = FakeGraphClient()
            self.task = FakeTaskClient()

    import app.services.simulation_manager as sm

    monkeypatch.setattr(sm, "Zep", FakeZep)

    manager = SimulationManager()
    state = manager.create_simulation(project_id="proj_test", graph_id="graph_base")

    assert state.graph_id == "graph_base"
    assert state.project_graph_id == "graph_base"

    isolated_graph_id = manager.ensure_isolated_simulation_graph(state, timeout_seconds=1)
    assert isolated_graph_id != "graph_base"
    assert isolated_graph_id.startswith(f"mirofish_sim_{state.simulation_id}_")
    assert state.project_graph_id == "graph_base"
    assert state.graph_id == isolated_graph_id

    assert clone_calls == [("graph_base", isolated_graph_id)]

    # Second call should not re-clone
    clone_calls_before = list(clone_calls)
    isolated_again = manager.ensure_isolated_simulation_graph(state, timeout_seconds=1)
    assert isolated_again == isolated_graph_id
    assert clone_calls == clone_calls_before

    reloaded = manager.get_simulation(state.simulation_id)
    assert reloaded is not None
    assert reloaded.project_graph_id == "graph_base"
    assert reloaded.graph_id == isolated_graph_id


def test_branch_simulation_uses_project_graph_id_not_simulation_graph(tmp_path, monkeypatch):
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(tmp_path))

    manager = SimulationManager()
    source = manager.create_simulation(project_id="proj_test", graph_id="graph_base")

    # Prepare minimal required files
    src_dir = os.path.join(str(tmp_path), source.simulation_id)
    with open(os.path.join(src_dir, "simulation_config.json"), "w", encoding="utf-8") as f:
        json.dump(
            {
                "simulation_id": source.simulation_id,
                "project_id": source.project_id,
                "graph_id": source.graph_id,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    with open(os.path.join(src_dir, "twitter_profiles.csv"), "w", encoding="utf-8") as f:
        f.write("user_id,username,name,bio,persona,karma,created_at\n0,u0,A,b,p,100,2026-01-01\n")
    with open(os.path.join(src_dir, "reddit_profiles.json"), "w", encoding="utf-8") as f:
        json.dump([], f)

    # Simulate that the source simulation has an isolated graph already.
    source.project_graph_id = "graph_base"
    source.graph_id = "graph_sim_clone"
    manager._save_simulation_state(source)

    branched = manager.branch_simulation(source.simulation_id)
    assert branched.project_graph_id == "graph_base"
    assert branched.graph_id == "graph_base"

    dst_dir = os.path.join(str(tmp_path), branched.simulation_id)
    with open(os.path.join(dst_dir, "simulation_config.json"), "r", encoding="utf-8") as f:
        cfg = json.load(f)
    assert cfg["graph_id"] == "graph_base"

