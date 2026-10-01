"""
可复现性清单（Reproducibility Manifest）测试

覆盖 app/services/reproducibility_manifest.py 的哈希/版本辅助函数、
manifest 构建与保存/加载往返，以及 prepare_simulation 端到端流程中
manifest 与随机种子的实际生成。
"""

import json

import pytest

from app.services import reproducibility_manifest as manifest_module
from app.services.reproducibility_manifest import (
    ArtifactHashes,
    ModelInfo,
    RandomnessInfo,
    ReproducibilityManifest,
    RuntimeInfo,
    SimulationInfo,
    build_manifest,
    load_manifest,
    manifest_path,
    save_manifest,
    sha256_file,
    sha256_json,
    sha256_text,
)


class TestHashHelpers:
    def test_sha256_text_is_deterministic(self):
        assert sha256_text("hello") == sha256_text("hello")

    def test_sha256_text_differs_for_different_input(self):
        assert sha256_text("hello") != sha256_text("world")

    def test_sha256_text_none_for_empty_input(self):
        assert sha256_text(None) is None
        assert sha256_text("") is None

    def test_sha256_json_is_key_order_independent(self):
        a = sha256_json({"b": 1, "a": 2})
        b = sha256_json({"a": 2, "b": 1})
        assert a == b

    def test_sha256_json_none_for_empty_input(self):
        assert sha256_json(None) is None
        assert sha256_json({}) is None

    def test_sha256_file_matches_content(self, tmp_path):
        path = tmp_path / "data.txt"
        path.write_text("some content", encoding="utf-8")
        assert sha256_file(str(path)) == sha256_text("some content")

    def test_sha256_file_none_for_missing_file(self, tmp_path):
        assert sha256_file(str(tmp_path / "missing.txt")) is None
        assert sha256_file(None) is None


class TestVersionHelpers:
    def test_get_mirofish_revision_never_raises(self):
        # Whatever it returns (a git SHA, a package version, or "unknown"),
        # it must not raise even outside a git repo / without the package installed.
        result = manifest_module.get_mirofish_revision()
        assert isinstance(result, str) and result

    def test_get_package_version_unknown_package(self):
        assert manifest_module.get_package_version("definitely-not-a-real-package-xyz") == "unknown"


class TestManifestRoundTrip:
    def _sample(self) -> ReproducibilityManifest:
        return ReproducibilityManifest(
            schema_version=1,
            simulation=SimulationInfo(
                simulation_id="sim_test1234",
                project_id="proj_test1234",
                graph_id="graph_test1234",
                entity_types=["Person"],
                entities_count=5,
                agent_count=5,
            ),
            model=ModelInfo(provider="openai-compatible", name="gpt-4o-mini", base_url="https://api.openai.com/v1"),
            artifacts=ArtifactHashes(ontology_hash="abc123"),
            runtime=RuntimeInfo(mirofish_revision="deadbeef", oasis_version="0.2.5"),
            randomness=RandomnessInfo(seed=42),
        )

    def test_to_dict_shape(self):
        manifest = self._sample()
        data = manifest.to_dict()
        assert data["schema_version"] == 1
        assert data["simulation"]["simulation_id"] == "sim_test1234"
        assert data["model"]["name"] == "gpt-4o-mini"
        assert data["randomness"]["seed"] == 42

    def test_from_dict_round_trip(self):
        manifest = self._sample()
        rebuilt = ReproducibilityManifest.from_dict(manifest.to_dict())
        assert rebuilt.simulation.simulation_id == manifest.simulation.simulation_id
        assert rebuilt.randomness.seed == manifest.randomness.seed
        assert rebuilt.runtime.oasis_version == manifest.runtime.oasis_version

    def test_save_and_load_manifest(self, tmp_path):
        manifest = self._sample()
        save_manifest(str(tmp_path), manifest)

        assert (tmp_path / "reproducibility_manifest.json").exists()
        loaded = load_manifest(str(tmp_path))
        assert loaded["simulation"]["simulation_id"] == "sim_test1234"
        assert loaded["randomness"]["seed"] == 42

    def test_load_manifest_missing_returns_none(self, tmp_path):
        assert load_manifest(str(tmp_path)) is None

    def test_manifest_path(self, tmp_path):
        assert manifest_path(str(tmp_path)) == str(tmp_path / "reproducibility_manifest.json")


class _FakeState:
    def __init__(self):
        self.simulation_id = "sim_buildtest12"
        self.project_id = "proj_buildtest12"
        self.graph_id = "graph_buildtest12"
        self.entity_types = ["Person", "Organization"]
        self.entities_count = 3
        self.profiles_count = 3
        self.enable_twitter = True
        self.enable_reddit = True
        self.random_seed = 12345


class _FakeSimParams:
    agent_configs = [object(), object(), object()]


class _FakeProject:
    def __init__(self, project_id, ontology):
        self.project_id = project_id
        self.ontology = ontology


class TestBuildManifest:
    def test_build_manifest_without_project(self, tmp_path):
        state = _FakeState()
        manifest = build_manifest(state=state, sim_dir=str(tmp_path))

        assert manifest.simulation.simulation_id == "sim_buildtest12"
        assert manifest.artifacts.ontology_hash is None
        assert manifest.randomness.seed == 12345
        assert manifest.randomness.deterministic is False

    def test_build_manifest_hashes_generated_artifacts(self, tmp_path):
        (tmp_path / "reddit_profiles.json").write_text('[{"id": 1}]', encoding="utf-8")
        (tmp_path / "twitter_profiles.csv").write_text("id\n1", encoding="utf-8")
        (tmp_path / "simulation_config.json").write_text('{"a": 1}', encoding="utf-8")

        state = _FakeState()
        manifest = build_manifest(state=state, sim_dir=str(tmp_path), sim_params=_FakeSimParams())

        assert manifest.artifacts.reddit_profiles_hash == sha256_file(str(tmp_path / "reddit_profiles.json"))
        assert manifest.artifacts.twitter_profiles_hash == sha256_file(str(tmp_path / "twitter_profiles.csv"))
        assert manifest.artifacts.simulation_config_hash == sha256_file(str(tmp_path / "simulation_config.json"))
        assert manifest.simulation.agent_count == 3

    def test_build_manifest_with_project_hashes_ontology(self, tmp_path):
        state = _FakeState()
        project = _FakeProject("proj_buildtest12", ontology={"entity_types": ["Person"]})
        manifest = build_manifest(state=state, sim_dir=str(tmp_path), project=project)

        assert manifest.artifacts.ontology_hash == sha256_json(project.ontology)

    def test_disabled_platform_has_no_profile_hash(self, tmp_path):
        (tmp_path / "twitter_profiles.csv").write_text("id\n1", encoding="utf-8")
        state = _FakeState()
        state.enable_reddit = False

        manifest = build_manifest(state=state, sim_dir=str(tmp_path))
        assert manifest.artifacts.reddit_profiles_hash is None
        assert manifest.artifacts.twitter_profiles_hash is not None

    def test_explicit_document_text_is_hashed_directly(self, tmp_path):
        # Regression test: build_manifest must hash the document_text that was
        # actually used for preparation, not silently re-read a (possibly
        # different) copy from the project's persisted extracted text.
        state = _FakeState()
        project = _FakeProject("proj_buildtest12", ontology=None)
        manifest = build_manifest(
            state=state,
            sim_dir=str(tmp_path),
            project=project,
            document_text="the exact text passed to prepare_simulation",
        )
        assert manifest.artifacts.source_document_hash == sha256_text(
            "the exact text passed to prepare_simulation"
        )

    def test_explicit_document_text_overrides_project_extracted_text(
        self, tmp_path, monkeypatch
    ):
        from app.models.project import ProjectManager

        monkeypatch.setattr(
            ProjectManager, "get_extracted_text", staticmethod(lambda project_id: "stale project text")
        )
        state = _FakeState()
        project = _FakeProject("proj_buildtest12", ontology=None)

        manifest = build_manifest(
            state=state,
            sim_dir=str(tmp_path),
            project=project,
            document_text="fresh text actually used this run",
        )
        assert manifest.artifacts.source_document_hash == sha256_text(
            "fresh text actually used this run"
        )
        assert manifest.artifacts.source_document_hash != sha256_text("stale project text")

    def test_no_document_text_falls_back_to_project_extracted_text(
        self, tmp_path, monkeypatch
    ):
        from app.models.project import ProjectManager

        monkeypatch.setattr(
            ProjectManager, "get_extracted_text", staticmethod(lambda project_id: "text from disk")
        )
        state = _FakeState()
        project = _FakeProject("proj_buildtest12", ontology=None)

        manifest = build_manifest(state=state, sim_dir=str(tmp_path), project=project)
        assert manifest.artifacts.source_document_hash == sha256_text("text from disk")
