import json

import pytest

from app import create_app
from app.config import Config
from app.services import simulation_manager as simulation_manager_module
from app.services.oasis_profile_generator import OasisProfileGenerator
from app.services.simulation_manager import (
    SimulationManager,
    SimulationState,
    SimulationStatus,
)
from app.services.zep_entity_reader import EntityNode, FilteredEntities


def _write_failed_state(root, simulation_id="sim_failed"):
    sim_dir = root / simulation_id
    sim_dir.mkdir(parents=True)
    (sim_dir / "state.json").write_text(
        json.dumps(
            {
                "status": "failed",
                "error": "no usable entities",
                "entities_count": 0,
                "profiles_generated": False,
                "config_generated": False,
            }
        ),
        encoding="utf-8",
    )
    return simulation_id


def test_realtime_endpoints_expose_terminal_failure(tmp_path, monkeypatch):
    simulation_id = _write_failed_state(tmp_path)
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path))

    app = create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    config_response = client.get(f"/api/simulation/{simulation_id}/config/realtime")
    profile_response = client.get(f"/api/simulation/{simulation_id}/profiles/realtime")

    assert config_response.status_code == 200
    expected_config_state = {
        "status": "failed",
        "error": "no usable entities",
        "generation_stage": "failed",
        "profiles_generated": False,
        "config_generated": False,
        "is_generating": False,
    }
    for key, expected in expected_config_state.items():
        assert config_response.json["data"][key] == expected
    assert profile_response.status_code == 200
    assert profile_response.json["data"]["status"] == "failed"
    assert profile_response.json["data"]["error"] == "no usable entities"
    assert profile_response.json["data"]["is_generating"] is False


def test_zero_entities_persists_failed_state_and_raises(tmp_path, monkeypatch):
    class EmptyReader:
        def filter_defined_entities(self, **kwargs):
            return FilteredEntities(
                entities=[],
                entity_types=set(),
                total_count=3,
                filtered_count=0,
            )

    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(simulation_manager_module, "ZepEntityReader", EmptyReader)

    manager = SimulationManager()
    state = SimulationState(
        simulation_id="sim_empty",
        project_id="project",
        graph_id="graph",
        status=SimulationStatus.READY,
        profiles_generated=True,
        config_generated=True,
        config_reasoning="stale",
        error="stale",
    )
    manager._save_simulation_state(state)

    with pytest.raises(ValueError, match="没有找到符合条件的实体"):
        manager.prepare_simulation(
            simulation_id=state.simulation_id,
            simulation_requirement="requirement",
            document_text="document",
        )

    persisted = json.loads(
        (tmp_path / state.simulation_id / "state.json").read_text(encoding="utf-8")
    )
    assert persisted["status"] == "failed"
    assert persisted["profiles_generated"] is False
    assert persisted["config_generated"] is False
    assert persisted["config_reasoning"] == ""
    assert "没有找到符合条件的实体" in persisted["error"]


def test_prepare_uses_persona_filtered_entities_for_profiles_and_config(
    tmp_path,
    monkeypatch,
):
    entities = [
        EntityNode(
            uuid="person-1",
            name="Alice",
            labels=["Entity", "Person"],
            summary="A person",
            attributes={},
        ),
        EntityNode(
            uuid="company-1",
            name="MiroFish",
            labels=["Entity", "Company"],
            summary="The project",
            attributes={},
        ),
        EntityNode(
            uuid="topic-1",
            name="market event",
            labels=["Entity", "Topic"],
            summary="A discussion topic",
            attributes={},
        ),
    ]
    captured = {}

    class Reader:
        def filter_defined_entities(self, **kwargs):
            return FilteredEntities(
                entities=entities,
                entity_types={"Person", "Company", "Topic"},
                total_count=3,
                filtered_count=3,
            )

    class ConfigGenerator:
        def generate_config(self, **kwargs):
            captured["config_entities"] = kwargs["entities"]

            class Params:
                generation_reasoning = "ok"

                def to_json(self):
                    return "{}"

            return Params()

    def generate_profiles(self, **kwargs):
        captured["profile_entities"] = kwargs["entities"]
        return []

    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(simulation_manager_module, "ZepEntityReader", Reader)
    monkeypatch.setattr(
        simulation_manager_module,
        "SimulationConfigGenerator",
        lambda: ConfigGenerator(),
    )
    monkeypatch.setattr(OasisProfileGenerator, "__init__", lambda self, **kwargs: None)
    monkeypatch.setattr(
        OasisProfileGenerator,
        "generate_profiles_from_entities",
        generate_profiles,
    )
    monkeypatch.setattr(OasisProfileGenerator, "save_profiles", lambda *args, **kwargs: None)

    manager = SimulationManager()
    state = SimulationState(
        simulation_id="sim_filtered",
        project_id="project",
        graph_id="graph",
        status=SimulationStatus.CREATED,
        enable_reddit=False,
        enable_twitter=False,
    )
    manager._save_simulation_state(state)

    result = manager.prepare_simulation(
        simulation_id=state.simulation_id,
        simulation_requirement="Agent personas MUST be individual people.",
        document_text="document",
        use_llm_for_profiles=False,
    )

    assert result.entities_count == 1
    assert result.entity_types == ["Person"]
    assert [entity.name for entity in captured["profile_entities"]] == ["Alice"]
    assert [entity.name for entity in captured["config_entities"]] == ["Alice"]
