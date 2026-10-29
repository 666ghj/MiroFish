"""Recovery must reuse verified Cloud data, never delete or replay ingestion."""
from datetime import datetime
from types import SimpleNamespace

from flask import Flask
import pytest

from app.api import graph as api
from app.models.project import Project, ProjectStatus
from app.models.task import TaskManager, TaskStatus
from app.services.graph_builder import GraphBuilderService, BatchSubmission
from app.services import graph_builder as builder_module


@pytest.fixture
def recovery(monkeypatch):
    graph_id = "existing-graph"
    text = "Original uploaded source."
    now = datetime.now().isoformat()
    project = Project(
        project_id="recovery-project", name="Recovery", status=ProjectStatus.FAILED,
        created_at=now, updated_at=now,
        ontology={"entity_types": [], "edge_types": []},
        graph_id=graph_id, zep_batch_id="existing-batch",
        zep_batch_operation_id=GraphBuilderService.build_operation_id(graph_id, [text]),
        error="Zep batch did not finish within 600s",
    )
    state = SimpleNamespace(project=project, batch_status="succeeded", threads=[],
                            saves=[], reads=[], item_status="succeeded", lookup_error=None)

    class Builder(GraphBuilderService):
        def __init__(self, **_kwargs):
            self.client = SimpleNamespace(batch=SimpleNamespace(
                get=self.get_batch_summary,
                list_items=self.list_items,
            ))

        def get_batch_summary(self, batch_id):
            assert batch_id == "existing-batch"
            state.reads.append("batch")
            if state.lookup_error:
                raise state.lookup_error
            return SimpleNamespace(status=state.batch_status, progress=None)

        def list_items(self, **kwargs):
            assert kwargs["batch_id"] == "existing-batch"
            state.reads.append("items")
            return SimpleNamespace(items=[SimpleNamespace(
                sequence_index=0, status=state.item_status,
                episode_uuid="episode-1", source_uuid="episode-1",
            )], next_cursor=None)

        def get_graph_data(self, graph_id):
            assert graph_id == "existing-graph"
            state.reads.append("graph")
            return {"node_count": 119, "edge_count": 187}

        def delete_graph(self, *_args, **_kwargs):
            pytest.fail("Recovery must not delete a Cloud graph")

        def create_graph(self, *_args, **_kwargs):
            pytest.fail("Recovery must not create a Cloud graph")

        def add_text_batches(self, *_args, **_kwargs):
            pytest.fail("Recovery must not resubmit source documents")

    class DeferredThread:
        def __init__(self, *, target, daemon):
            state.threads.append(target)

        def start(self):
            pass

    monkeypatch.setattr(api.Config, "ZEP_API_KEY", "test-key")
    monkeypatch.setattr(api, "GraphBuilderService", Builder)
    monkeypatch.setattr(api.threading, "Thread", DeferredThread)
    monkeypatch.setattr(api.ProjectManager, "get_project", classmethod(lambda *_: project))
    monkeypatch.setattr(api.ProjectManager, "get_extracted_text", classmethod(lambda *_: text))
    monkeypatch.setattr(api.ProjectManager, "save_project", classmethod(
        lambda _cls, p: state.saves.append(p.status)
    ))

    app = Flask(__name__)

    def request(resume_only=False, **kwargs):
        with app.test_request_context("/api/graph/build", method="POST",
                                      json={"project_id": project.project_id, **kwargs}):
            result = api.resume_graph() if resume_only else api.build_graph()
        response, status = result if isinstance(result, tuple) else (result, result.status_code)
        return response.get_json(), status

    state.request = request
    return state


@pytest.mark.parametrize("resume_only", [False, True])
def test_completed_cloud_batch_recovers_failed_project_without_ingestion(recovery, resume_only):
    body, status = recovery.request(resume_only=resume_only)
    assert status == 200 and body["data"]["resumed"] is True
    assert recovery.project.error is None
    recovery.threads[0]()
    task = TaskManager().get_task(body["data"]["task_id"])
    assert task.status == TaskStatus.COMPLETED
    assert task.result["node_count"] == 119
    assert task.result["edge_count"] == 187
    assert recovery.project.status == ProjectStatus.GRAPH_COMPLETED
    assert recovery.project.graph_id == "existing-graph"
    assert recovery.project.zep_batch_id == "existing-batch"
    assert "items" in recovery.reads and "graph" in recovery.reads
    second, status = recovery.request()
    assert status == 200 and second["data"]["reused"] is True
    assert second["data"]["status"] == "graph_completed"
    assert len(recovery.threads) == 1


@pytest.mark.parametrize("missing", ["graph_id", "zep_batch_id", "zep_batch_operation_id"])
def test_recovery_endpoint_rejects_missing_identity_without_writes(recovery, missing):
    setattr(recovery.project, missing, None)
    _, status = recovery.request(resume_only=True)
    assert status == 409
    assert not recovery.saves and not recovery.threads and not recovery.reads


def test_recovery_endpoint_refuses_forced_rebuild(recovery):
    _, status = recovery.request(resume_only=True, force=True)
    assert status == 409
    assert recovery.project.graph_id == "existing-graph"
    assert not recovery.saves and not recovery.threads and not recovery.reads


@pytest.mark.parametrize("batch_status", ["partial", "failed", "invalid", "canceled", "draft", "unknown"])
def test_unrecoverable_cloud_batch_is_preserved_until_explicit_rebuild(recovery, batch_status):
    recovery.batch_status = batch_status
    body, status = recovery.request()
    assert status == 409 and "preserved" in body["error"]
    assert recovery.project.graph_id == "existing-graph"
    assert recovery.project.zep_batch_id == "existing-batch"
    assert not recovery.threads


def test_failed_graph_without_batch_identity_is_not_silently_deleted(recovery):
    recovery.project.zep_batch_id = None
    body, status = recovery.request()
    assert status == 409
    assert recovery.project.graph_id == "existing-graph"
    assert not recovery.threads


def test_changed_chunking_cannot_resume_a_different_input(recovery):
    body, status = recovery.request(chunk_size=10, chunk_overlap=2)
    assert status == 409 and "does not match" in body["error"]
    assert recovery.project.chunk_size == 500
    assert recovery.project.chunk_overlap == 50
    assert not recovery.saves and not recovery.threads


def test_cloud_read_failure_cannot_trigger_deletion(recovery):
    recovery.lookup_error = RuntimeError("Cloud unavailable")
    _, status = recovery.request()
    assert status == 500
    assert recovery.project.graph_id == "existing-graph"
    assert not recovery.saves and not recovery.threads


def test_batch_summary_success_does_not_bypass_item_validation(recovery):
    recovery.item_status = "failed"
    body, status = recovery.request()
    assert status == 200
    recovery.threads[0]()
    assert recovery.project.status == ProjectStatus.FAILED
    assert recovery.project.graph_id == "existing-graph"
    task = TaskManager().get_task(body["data"]["task_id"])
    assert task.status == TaskStatus.FAILED
    assert "graph" not in recovery.reads


def test_default_graph_wait_allows_success_after_ten_minutes(monkeypatch):
    ticks = iter([0.0, 601.0])
    monkeypatch.setattr(builder_module.time, "time", lambda: next(ticks))
    monkeypatch.setattr(builder_module.Config, "ZEP_GRAPH_BUILD_TIMEOUT_SECONDS", 1800)
    builder = object.__new__(GraphBuilderService)
    builder.client = SimpleNamespace(batch=SimpleNamespace(
        get=lambda **_: SimpleNamespace(status="succeeded", progress=None),
        list_items=lambda **_: SimpleNamespace(items=[SimpleNamespace(
            sequence_index=0, status="succeeded", episode_uuid="episode-1", source_uuid="episode-1",
        )], next_cursor=None),
    ))
    assert builder._wait_for_batch(BatchSubmission("batch", "op", [], 1)) == ["episode-1"]
