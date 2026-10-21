import io

from app import create_app
from app.api import graph as graph_api
from app.models.project import ProjectManager, ProjectStatus
from app.utils.llm_client import LLMResponseError


def _post_ontology(client):
    return client.post(
        "/api/graph/ontology/generate",
        data={
            "simulation_requirement": "Simulate the discussion.",
            "files": (io.BytesIO(b"A short source document."), "source.md"),
        },
        content_type="multipart/form-data",
    )


def test_ontology_api_returns_safe_truncation_error_and_failed_project(
    tmp_path,
    monkeypatch,
):
    class FailingGenerator:
        def generate(self, **kwargs):
            raise LLMResponseError(
                "LLM JSON output was truncated at the token limit",
                finish_reason="length",
            )

    monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(tmp_path))
    monkeypatch.setattr(graph_api, "OntologyGenerator", FailingGenerator)

    app = create_app()
    app.config.update(TESTING=True)
    response = _post_ontology(app.test_client())

    assert response.status_code == 502
    assert response.json["success"] is False
    assert "token limit" in response.json["error"]
    assert "traceback" not in response.json

    project_id = response.json["data"]["project_id"]
    project = ProjectManager.get_project(project_id)
    assert project.status == ProjectStatus.FAILED
    assert project.error == response.json["error"]


def test_ontology_api_does_not_expose_provider_error_body(tmp_path, monkeypatch):
    class ProviderError(RuntimeError):
        status_code = 401
        request_id = "request-safe-id"
        body = {"error": {"message": "SECRET-PROVIDER-BODY"}}

    class FailingGenerator:
        def generate(self, **kwargs):
            raise ProviderError("SECRET-PROVIDER-BODY")

    monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(tmp_path))
    monkeypatch.setattr(graph_api, "OntologyGenerator", FailingGenerator)

    app = create_app()
    app.config.update(TESTING=True)
    response = _post_ontology(app.test_client())

    assert response.status_code == 502
    assert "HTTP 401" in response.json["error"]
    assert "request-safe-id" in response.json["error"]
    assert "SECRET-PROVIDER-BODY" not in response.get_data(as_text=True)
    assert "traceback" not in response.json


def test_ontology_api_rejects_blank_files_before_calling_the_llm(tmp_path, monkeypatch):
    calls = []

    class RecordingGenerator:
        def generate(self, **kwargs):
            calls.append(kwargs)
            return {"entity_types": [], "edge_types": [], "analysis_summary": "ok"}

    monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(tmp_path))
    monkeypatch.setattr(graph_api, "OntologyGenerator", RecordingGenerator)
    app = create_app()
    app.config.update(TESTING=True)
    response = app.test_client().post(
        "/api/graph/ontology/generate",
        data={"simulation_requirement": "Simulate the discussion.",
              "files": [(io.BytesIO(b""), "empty.txt"),
                        (io.BytesIO(b" \r\n\t "), "blank.md")]},
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert response.json["success"] is False
    assert calls == []
    assert list(tmp_path.iterdir()) == []


def test_ontology_api_ignores_blank_text_when_other_documents_have_content(
    tmp_path, monkeypatch,
):
    calls = []

    class RecordingGenerator:
        def generate(self, **kwargs):
            calls.append(kwargs)
            return {"entity_types": [], "edge_types": [], "analysis_summary": "ok"}

    monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(tmp_path))
    monkeypatch.setattr(graph_api, "OntologyGenerator", RecordingGenerator)
    app = create_app()
    app.config.update(TESTING=True)
    response = app.test_client().post(
        "/api/graph/ontology/generate",
        data={"simulation_requirement": "Simulate the discussion.",
              "files": [(io.BytesIO(b""), "empty.txt"),
                        (io.BytesIO(b"Actual source text."), "source.md")]},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert calls[0]["document_texts"] == ["Actual source text."]
    text = ProjectManager.get_extracted_text(response.json["data"]["project_id"])
    assert "source.md" in text
    assert "empty.txt" not in text
