import json
import os

import pytest

from app.services.simulation_manager import SimulationManager, SimulationStatus


def test_branch_simulation_copies_prepared_files_without_modifying_source(tmp_path, monkeypatch):
    simulations_root = tmp_path / "uploads" / "simulations"
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(simulations_root))

    manager = SimulationManager()

    src_state = manager.create_simulation(project_id="proj_x", graph_id="graph_x", enable_twitter=True, enable_reddit=True)
    src_id = src_state.simulation_id

    # Create minimal "prepared" files
    src_dir = os.path.join(str(simulations_root), src_id)
    src_config_path = os.path.join(src_dir, "simulation_config.json")
    with open(src_config_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "simulation_id": src_id,
                "project_id": "proj_x",
                "graph_id": "graph_x",
                "simulation_requirement": "req",
                "time_config": {"total_simulation_hours": 1, "minutes_per_round": 60},
                "agent_configs": [],
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    twitter_profiles = os.path.join(src_dir, "twitter_profiles.csv")
    with open(twitter_profiles, "w", encoding="utf-8") as f:
        f.write("agent_id,entity_name\n0,A\n")

    reddit_profiles = os.path.join(src_dir, "reddit_profiles.json")
    with open(reddit_profiles, "w", encoding="utf-8") as f:
        json.dump([], f)

    # Make the source state ready so the branch inherits metadata
    src_state.status = SimulationStatus.READY
    src_state.config_generated = True
    src_state.entities_count = 1
    src_state.profiles_count = 1
    src_state.entity_types = ["X"]
    manager._save_simulation_state(src_state)

    new_state = manager.branch_simulation(src_id)
    assert new_state.simulation_id != src_id
    assert new_state.status == SimulationStatus.READY

    # Source remains unchanged
    with open(src_config_path, "r", encoding="utf-8") as f:
        assert json.load(f)["simulation_id"] == src_id

    # New branch has patched config + copied prepared files
    dst_dir = os.path.join(str(simulations_root), new_state.simulation_id)
    with open(os.path.join(dst_dir, "simulation_config.json"), "r", encoding="utf-8") as f:
        assert json.load(f)["simulation_id"] == new_state.simulation_id

    assert os.path.exists(os.path.join(dst_dir, "twitter_profiles.csv"))
    assert os.path.exists(os.path.join(dst_dir, "reddit_profiles.json"))

    # Branch should not contain run-state or DB/log outputs by default
    assert not os.path.exists(os.path.join(dst_dir, "run_state.json"))
    assert not os.path.exists(os.path.join(dst_dir, "twitter_simulation.db"))
    assert not os.path.exists(os.path.join(dst_dir, "reddit_simulation.db"))

