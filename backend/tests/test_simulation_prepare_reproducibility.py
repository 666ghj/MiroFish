"""
prepare_simulation 端到端集成测试：验证随机种子在创建时生成、在准备阶段
被用来播种 MiroFish 自身的非 LLM 随机性，以及可复现性清单被正确生成、
持久化，并可通过 API 读取。

Zep / LLM / OASIS 相关的外部依赖均以最小可用假实现（fake）替换，风格
与 test_simulation_prepare_failure.py 中的 EmptyReader 一致。
"""

import json
import random

import pytest

from app import create_app
from app.config import Config
from app.models.project import ProjectManager
from app.services import simulation_manager as simulation_manager_module
from app.services.reproducibility_manifest import load_manifest
from app.services.simulation_manager import (
    SimulationManager,
    SimulationState,
    SimulationStatus,
)
from app.services.zep_entity_reader import FilteredEntities


class _FakeEntity:
    def __init__(self, i):
        self.uuid = f"entity-{i}"


class _FakeReader:
    def filter_defined_entities(self, **kwargs):
        return FilteredEntities(
            entities=[_FakeEntity(0), _FakeEntity(1)],
            entity_types={"Person"},
            total_count=2,
            filtered_count=2,
        )


class _FakeProfile:
    def __init__(self, i):
        self.id = i


class _FakeProfileGenerator:
    def __init__(self, graph_id=None, random_seed=None):
        self.graph_id = graph_id
        self.random_seed = random_seed

    def generate_profiles_from_entities(
        self,
        entities,
        use_llm=True,
        progress_callback=None,
        graph_id=None,
        parallel_count=3,
        realtime_output_path=None,
        output_platform="reddit",
    ):
        # Exercises the seeded, non-LLM randomness path the same way the real
        # generator's demographic fallbacks do.
        _ = random.randint(0, 1_000_000)
        return [_FakeProfile(i) for i in range(len(entities))]

    def save_profiles(self, profiles, file_path, platform):
        if platform == "reddit":
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump([{"id": p.id} for p in profiles], f)
        else:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("id\n" + "\n".join(str(p.id) for p in profiles))


class _FakeSimulationParameters:
    def __init__(self):
        self.generation_reasoning = "fake reasoning"
        self.agent_configs = [object(), object()]

    def to_json(self, indent: int = 2) -> str:
        return json.dumps({"llm_model": "fake-model", "llm_base_url": "http://fake"}, indent=indent)


class _FakeConfigGenerator:
    def generate_config(self, **kwargs):
        return _FakeSimulationParameters()


@pytest.fixture
def prepared_simulation(tmp_path, monkeypatch):
    sim_root = tmp_path / "simulations"
    proj_root = tmp_path / "projects"

    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(sim_root))
    monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(proj_root))
    monkeypatch.setattr(simulation_manager_module, "ZepEntityReader", _FakeReader)
    monkeypatch.setattr(simulation_manager_module, "OasisProfileGenerator", _FakeProfileGenerator)
    monkeypatch.setattr(simulation_manager_module, "SimulationConfigGenerator", _FakeConfigGenerator)

    project = ProjectManager.create_project(name="Test Project")
    project.ontology = {"entity_types": ["Person"], "edge_types": []}
    ProjectManager.save_project(project)
    ProjectManager.save_extracted_text(project.project_id, "some source document text")

    manager = SimulationManager()
    state = manager.create_simulation(
        project_id=project.project_id,
        graph_id="graph_test1234",
    )

    result = manager.prepare_simulation(
        simulation_id=state.simulation_id,
        simulation_requirement="test requirement",
        document_text="some source document text",
    )
    sim_dir = str(sim_root / state.simulation_id)
    return manager, result, sim_dir, project


class TestRandomSeedGeneration:
    def test_create_simulation_assigns_a_random_seed(self, tmp_path, monkeypatch):
        monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(tmp_path))
        manager = SimulationManager()
        state = manager.create_simulation(project_id="proj_x", graph_id="graph_x")
        assert isinstance(state.random_seed, int)
        assert 0 <= state.random_seed < 2**32

    def test_different_simulations_get_different_seeds(self, tmp_path, monkeypatch):
        monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(tmp_path))
        manager = SimulationManager()
        seeds = {
            manager.create_simulation(project_id="proj_x", graph_id="graph_x").random_seed
            for _ in range(5)
        }
        assert len(seeds) == 5  # astronomically unlikely to collide by chance

    def test_random_seed_persists_across_reload(self, tmp_path, monkeypatch):
        monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(tmp_path))
        manager = SimulationManager()
        state = manager.create_simulation(project_id="proj_x", graph_id="graph_x")

        manager._simulations.pop(state.simulation_id, None)
        reloaded = manager.get_simulation(state.simulation_id)
        assert reloaded.random_seed == state.random_seed


class TestPrepareSimulationReproducibility:
    def test_prepare_simulation_persists_manifest(self, prepared_simulation):
        manager, result, sim_dir, project = prepared_simulation

        assert result.status == SimulationStatus.READY
        manifest = load_manifest(sim_dir)
        assert manifest is not None
        assert manifest["simulation"]["simulation_id"] == result.simulation_id
        assert manifest["simulation"]["project_id"] == project.project_id
        assert manifest["simulation"]["agent_count"] == 2
        assert manifest["randomness"]["seed"] == result.random_seed

    def test_manifest_hashes_match_generated_artifacts(self, prepared_simulation):
        from app.services.reproducibility_manifest import sha256_file

        manager, result, sim_dir, project = prepared_simulation
        manifest = load_manifest(sim_dir)

        import os
        assert manifest["artifacts"]["reddit_profiles_hash"] == sha256_file(
            os.path.join(sim_dir, "reddit_profiles.json")
        )
        assert manifest["artifacts"]["simulation_config_hash"] == sha256_file(
            os.path.join(sim_dir, "simulation_config.json")
        )

    def test_manifest_hashes_ontology_and_source_document(self, prepared_simulation):
        from app.services.reproducibility_manifest import sha256_json, sha256_text

        manager, result, sim_dir, project = prepared_simulation
        manifest = load_manifest(sim_dir)

        assert manifest["artifacts"]["ontology_hash"] == sha256_json(project.ontology)
        assert manifest["artifacts"]["source_document_hash"] == sha256_text(
            "some source document text"
        )

    def test_manifest_records_model_config(self, prepared_simulation):
        manager, result, sim_dir, project = prepared_simulation
        manifest = load_manifest(sim_dir)

        assert manifest["model"]["name"] == Config.LLM_MODEL_NAME
        assert manifest["model"]["base_url"] == Config.LLM_BASE_URL

    def test_prepare_failure_does_not_block_on_manifest_errors(
        self, tmp_path, monkeypatch
    ):
        """A manifest-building failure must not fail simulation preparation."""
        sim_root = tmp_path / "simulations"
        proj_root = tmp_path / "projects"
        monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(sim_root))
        monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(proj_root))
        monkeypatch.setattr(simulation_manager_module, "ZepEntityReader", _FakeReader)
        monkeypatch.setattr(
            simulation_manager_module, "OasisProfileGenerator", _FakeProfileGenerator
        )
        monkeypatch.setattr(
            simulation_manager_module, "SimulationConfigGenerator", _FakeConfigGenerator
        )
        monkeypatch.setattr(
            simulation_manager_module.reproducibility_manifest,
            "build_manifest",
            lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        manager = SimulationManager()
        state = manager.create_simulation(project_id="proj_x", graph_id="graph_x")

        result = manager.prepare_simulation(
            simulation_id=state.simulation_id,
            simulation_requirement="test requirement",
            document_text="doc",
        )
        assert result.status == SimulationStatus.READY

    def test_failed_reprepare_clears_stale_manifest(self, prepared_simulation, monkeypatch):
        """
        Regression test: re-preparing a simulation that already has a manifest
        from a prior successful run must not leave that manifest in place if
        the new attempt fails -- GET /manifest should not keep describing a
        stale, no-longer-accurate run.
        """
        manager, result, sim_dir, project = prepared_simulation
        assert load_manifest(sim_dir) is not None  # sanity: manifest exists from fixture

        class _EmptyReader:
            def filter_defined_entities(self, **kwargs):
                return FilteredEntities(
                    entities=[], entity_types=set(), total_count=0, filtered_count=0
                )

        monkeypatch.setattr(simulation_manager_module, "ZepEntityReader", _EmptyReader)

        with pytest.raises(ValueError):
            manager.prepare_simulation(
                simulation_id=result.simulation_id,
                simulation_requirement="test requirement",
                document_text="some source document text",
            )

        assert load_manifest(sim_dir) is None


class TestManifestApiEndpoint:
    def test_get_manifest_returns_persisted_manifest(self, prepared_simulation):
        manager, result, sim_dir, project = prepared_simulation

        app = create_app()
        app.config.update(TESTING=True)
        client = app.test_client()

        response = client.get(f"/api/simulation/{result.simulation_id}/manifest")
        assert response.status_code == 200
        assert response.json["data"]["simulation"]["simulation_id"] == result.simulation_id

    def test_get_manifest_404_when_not_prepared(self, tmp_path, monkeypatch):
        monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(tmp_path))
        manager = SimulationManager()
        state = manager.create_simulation(project_id="proj_x", graph_id="graph_x")

        app = create_app()
        app.config.update(TESTING=True)
        client = app.test_client()

        response = client.get(f"/api/simulation/{state.simulation_id}/manifest")
        assert response.status_code == 404
