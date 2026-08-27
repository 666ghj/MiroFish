import importlib.util
import json
import sys
import types
from datetime import date
from pathlib import Path


def _load_corpus_module():
    path = Path(__file__).resolve().parents[1] / "app" / "services" / "corpus_slimmer.py"
    spec = importlib.util.spec_from_file_location("corpus_slimmer_persistence", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_project_module(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    app_package = types.ModuleType("app")
    app_package.__path__ = [str(backend / "app")]
    models_package = types.ModuleType("app.models")
    models_package.__path__ = [str(backend / "app" / "models")]
    config_module = types.ModuleType("app.config")
    config_module.Config = type("Config", (), {"UPLOAD_FOLDER": str(tmp_path)})
    sys.modules["app"] = app_package
    sys.modules["app.models"] = models_package
    sys.modules["app.config"] = config_module
    name = "app.models.project"
    spec = importlib.util.spec_from_file_location(name, backend / "app" / "models" / "project.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_write_recent_corpus_creates_text_and_auditable_manifest(tmp_path):
    module = _load_corpus_module()
    source = "=== 2025-01-01-a.txt ===\nA\n"
    result = module.build_recent_corpus(
        source,
        cutoff=date(2023, 8, 27),
        exclude_full_reports=True,
    )

    artifacts = module.write_recent_corpus(
        tmp_path,
        result,
        cutoff=date(2023, 8, 27),
        generated_at="2026-08-27T12:00:00+00:00",
    )

    assert artifacts.output_path.name == "extracted_text_recent_3y.txt"
    assert artifacts.output_path.read_text() == result.text
    manifest = json.loads(artifacts.manifest_path.read_text())
    assert manifest["cutoff_date"] == "2023-08-27"
    assert manifest["summary"]["included_sections"] == 1
    assert manifest["summary"]["output_characters"] == len(result.text)
    assert manifest["documents"][0]["reason"] == "within_window"
    assert list(tmp_path.glob("*.tmp")) == []


def test_empty_result_does_not_replace_existing_artifacts(tmp_path):
    module = _load_corpus_module()
    output = tmp_path / "extracted_text_recent_3y.txt"
    output.write_text("existing")
    empty = module.build_recent_corpus(
        "=== 2020-01-01-old.txt ===\nold\n",
        cutoff=date(2023, 8, 27),
        exclude_full_reports=True,
    )

    try:
        module.write_recent_corpus(
            tmp_path,
            empty,
            cutoff=date(2023, 8, 27),
            generated_at="2026-08-27T12:00:00+00:00",
        )
    except ValueError as error:
        assert "empty" in str(error).lower()
    else:
        raise AssertionError("empty corpus should fail")

    assert output.read_text() == "existing"


def test_project_model_defaults_and_round_trips_corpus_fields(tmp_path):
    module = _load_project_module(tmp_path)
    legacy = {
        "project_id": "proj_test",
        "name": "test",
        "status": "ontology_generated",
        "created_at": "now",
        "updated_at": "now",
    }
    project = module.Project.from_dict(legacy)
    assert project.active_corpus == "full"
    assert project.corpus_manifest is None

    project.active_corpus = "recent_3y"
    project.corpus_manifest = {"included_sections": 57}
    restored = module.Project.from_dict(project.to_dict())
    assert restored.active_corpus == "recent_3y"
    assert restored.corpus_manifest == {"included_sections": 57}


def test_project_manager_reads_only_known_corpus_names(tmp_path):
    module = _load_project_module(tmp_path)
    project_dir = Path(module.ProjectManager.PROJECTS_DIR) / "proj_test"
    project_dir.mkdir(parents=True)
    (project_dir / "extracted_text.txt").write_text("full")
    (project_dir / "extracted_text_recent_3y.txt").write_text("recent")

    assert module.ProjectManager.get_corpus_text("proj_test", "full") == "full"
    assert module.ProjectManager.get_corpus_text("proj_test", "recent_3y") == "recent"
    try:
        module.ProjectManager.get_corpus_text("proj_test", "unknown")
    except ValueError as error:
        assert "unknown" in str(error)
    else:
        raise AssertionError("unknown corpus should fail")
