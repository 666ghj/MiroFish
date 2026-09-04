"""The graph build refuses to start against an extraction endpoint that cannot serve it.

Both production failures were a bad extraction configuration that only became
visible tens of minutes into the ingest: an APITimeoutError after ~50 minutes,
and a JSONDecodeError on a completion the token budget had cut in half. Every
knob involved lives in the Zep-compatible service, not in this process, so the
check is an HTTP call into that service.
"""

from datetime import datetime
from types import SimpleNamespace

import httpx
from flask import Flask

from app.api import graph as graph_api
from app.models.project import Project, ProjectStatus
from app.services import graph_preflight
from app.services.graph_preflight import (
    DEFAULT_PREFLIGHT_SAMPLE_TEXT,
    MAX_PREFLIGHT_SAMPLE_CHARS,
    run_graph_preflight,
)

SHIM_BASE_URL = "http://127.0.0.1:8088/api/v2"
ONTOLOGY = {
    "entity_types": [{"name": "Person", "description": "A person."}],
    "edge_types": [{"name": "works_with", "description": "Collaboration."}],
}


def _use_shim(monkeypatch):
    monkeypatch.setenv("ZEP_BASE_URL", SHIM_BASE_URL)
    monkeypatch.delenv("GRAPH_BUILD_SKIP_PREFLIGHT", raising=False)


def _respond(monkeypatch, response, calls=None, probe=None):
    """Answer the preflight POST, and the GET that probes the shim is alive.

    ``probe`` defaults to a healthy batch listing: a 404 from the preflight
    route only counts as a missing route when the rest of the API answers.
    """

    probe_response = probe if probe is not None else httpx.Response(
        200, json={"batches": [], "next_cursor": None}
    )

    def fake_post(url, **kwargs):
        if calls is not None:
            calls.append((url, kwargs))
        if isinstance(response, Exception):
            raise response
        return response

    def fake_get(url, **kwargs):
        if calls is not None:
            calls.append((url, kwargs))
        if isinstance(probe_response, Exception):
            raise probe_response
        return probe_response

    monkeypatch.setattr(graph_preflight.httpx, "post", fake_post)
    monkeypatch.setattr(graph_preflight.httpx, "get", fake_get)


def _json_result(result):
    if isinstance(result, tuple):
        response, status = result
    else:
        response, status = result, result.status_code
    return response.get_json(), status


def test_preflight_sends_the_request_ontology_and_a_slice_of_the_real_text(
    monkeypatch,
):
    """A first build has no graph on the server, so the ontology travels with the request."""

    _use_shim(monkeypatch)
    calls = []
    _respond(
        monkeypatch,
        httpx.Response(
            200,
            json={
                "ok": True,
                "detail": "extracted 3 entities",
                "finish_reason": "stop",
                "completion_tokens": 412,
                "max_tokens": 16384,
                "structured_output_mode": "json_schema",
                "elapsed_seconds": 4.2,
            },
        ),
        calls,
    )

    result = run_graph_preflight(ONTOLOGY, "x" * (MAX_PREFLIGHT_SAMPLE_CHARS + 500))

    assert result.ok is True
    assert result.skipped is False
    assert result.report["finish_reason"] == "stop"
    url, kwargs = calls[0]
    assert url == f"{SHIM_BASE_URL}/graph/preflight"
    assert kwargs["json"]["entity_types"] == ONTOLOGY["entity_types"]
    assert kwargs["json"]["edge_types"] == ONTOLOGY["edge_types"]
    assert len(kwargs["json"]["sample_text"]) == MAX_PREFLIGHT_SAMPLE_CHARS


def test_preflight_falls_back_to_its_own_sample_when_there_is_no_text(monkeypatch):
    _use_shim(monkeypatch)
    calls = []
    _respond(monkeypatch, httpx.Response(200, json={"ok": True, "detail": ""}), calls)

    assert run_graph_preflight(None, "   ").ok is True
    assert calls[0][1]["json"]["sample_text"] == DEFAULT_PREFLIGHT_SAMPLE_TEXT
    assert calls[0][1]["json"]["entity_types"] is None


def test_a_truncated_extraction_fails_the_preflight_and_names_the_numbers(
    monkeypatch,
):
    """finish_reason=length is the 4096-token JSONDecodeError, seen early."""

    _use_shim(monkeypatch)
    _respond(
        monkeypatch,
        httpx.Response(
            200,
            json={
                "ok": False,
                "detail": (
                    "the extraction was truncated; raise GRAPHITI_LLM_MAX_TOKENS "
                    "or bound the extraction schema"
                ),
                "finish_reason": "length",
                "completion_tokens": 4096,
                "max_tokens": 4096,
                "structured_output_mode": "json_schema",
                "elapsed_seconds": 31.5,
            },
        ),
    )

    result = run_graph_preflight(ONTOLOGY, "source text")

    assert result.ok is False
    assert result.skipped is False
    assert "GRAPHITI_LLM_MAX_TOKENS" in result.detail
    # The measured numbers ride along with the reason, so the operator does not
    # have to go and read the other process's log to learn what happened.
    assert "finish_reason=length" in result.detail
    assert "max_tokens=4096" in result.detail
    assert result.report["completion_tokens"] == 4096


def test_an_older_shim_without_the_endpoint_is_a_warning_not_a_failure(monkeypatch):
    _use_shim(monkeypatch)
    _respond(monkeypatch, httpx.Response(404, json={"detail": "Not Found"}))

    result = run_graph_preflight(ONTOLOGY, "source text")

    assert result.ok is True
    assert result.skipped is True
    assert "404" in result.detail


def test_a_shim_whose_get_route_claims_the_path_is_also_a_skip(monkeypatch):
    """GET /graph/{graph_id} matches /graph/preflight, so an old shim answers 405."""

    _use_shim(monkeypatch)
    _respond(monkeypatch, httpx.Response(405, json={"detail": "Method Not Allowed"}))

    result = run_graph_preflight(ONTOLOGY, "source text")

    assert result.ok is True
    assert result.skipped is True


def test_a_base_url_that_404s_everywhere_is_not_waved_through_as_an_old_shim(
    monkeypatch,
):
    """A ZEP_BASE_URL pointing at the wrong host 404s exactly like an old shim."""

    _use_shim(monkeypatch)
    calls = []
    _respond(
        monkeypatch,
        httpx.Response(404, json={"detail": "Not Found"}),
        calls,
        probe=httpx.Response(404, json={"detail": "Not Found"}),
    )

    result = run_graph_preflight(ONTOLOGY, "source text")

    assert result.ok is False
    assert result.skipped is False
    assert "ZEP_BASE_URL" in result.detail
    # The batch API the ingest itself runs on is what settled it.
    assert calls[1][0] == f"{SHIM_BASE_URL}/batches"


def test_an_unreachable_extraction_endpoint_fails_the_preflight(monkeypatch):
    _use_shim(monkeypatch)
    _respond(monkeypatch, httpx.ConnectError("connection refused"))

    result = run_graph_preflight(ONTOLOGY, "source text")

    assert result.ok is False
    assert result.skipped is False
    assert "ConnectError" in result.detail
    assert "GRAPH_BUILD_PREFLIGHT_TIMEOUT" in result.detail


def test_a_server_error_from_the_shim_fails_the_preflight(monkeypatch):
    _use_shim(monkeypatch)
    _respond(monkeypatch, httpx.Response(500, json={"detail": "embedder is down"}))

    result = run_graph_preflight(ONTOLOGY, "source text")

    assert result.ok is False
    assert "embedder is down" in result.detail


def test_an_unrecognised_body_is_a_skip_rather_than_a_blocked_build(monkeypatch):
    _use_shim(monkeypatch)
    _respond(monkeypatch, httpx.Response(200, text="pong"))

    result = run_graph_preflight(ONTOLOGY, "source text")

    assert result.ok is True
    assert result.skipped is True


def test_zep_cloud_deployments_have_nothing_to_preflight(monkeypatch):
    monkeypatch.delenv("ZEP_BASE_URL", raising=False)
    monkeypatch.delenv("GRAPH_BUILD_SKIP_PREFLIGHT", raising=False)
    calls = []
    _respond(monkeypatch, httpx.Response(200, json={"ok": True}), calls)

    result = run_graph_preflight(ONTOLOGY, "source text")

    assert result.skipped is True
    assert result.ok is True
    assert calls == []


def test_the_deployment_can_switch_the_preflight_off(monkeypatch):
    _use_shim(monkeypatch)
    monkeypatch.setenv("GRAPH_BUILD_SKIP_PREFLIGHT", "true")
    calls = []
    _respond(monkeypatch, httpx.Response(200, json={"ok": True}), calls)

    result = run_graph_preflight(ONTOLOGY, "source text")

    assert result.skipped is True
    assert calls == []


# ============== The build route ==============


def _project():
    now = datetime.now().isoformat()
    return Project(
        project_id="proj-1",
        name="Project",
        status=ProjectStatus.ONTOLOGY_GENERATED,
        created_at=now,
        updated_at=now,
        ontology=ONTOLOGY,
    )


def _wire_build_route(monkeypatch, project, created_tasks, started_threads):
    class Tasks:
        def get_task(self, _task_id):
            return None

        def create_task(self, description):
            created_tasks.append(description)
            return "task-1"

        def update_task(self, *_args, **_kwargs):
            pass

    class Thread:
        def __init__(self, *, target, daemon):
            started_threads.append(target)

        def start(self):
            pass

    monkeypatch.setattr(graph_api.Config, "ZEP_API_KEY", "test-key")
    monkeypatch.setattr(graph_api, "TaskManager", Tasks)
    monkeypatch.setattr(graph_api.threading, "Thread", Thread)
    monkeypatch.setattr(
        graph_api,
        "GraphBuilderService",
        lambda **_kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        graph_api.ProjectManager,
        "get_project",
        classmethod(lambda _cls, _project_id: project),
    )
    monkeypatch.setattr(
        graph_api.ProjectManager,
        "get_extracted_text",
        classmethod(lambda _cls, _project_id: "source text"),
    )
    monkeypatch.setattr(
        graph_api.ProjectManager,
        "save_project",
        classmethod(lambda _cls, _project: None),
    )


def test_build_refuses_to_start_when_the_extraction_endpoint_cannot_serve_it(
    monkeypatch,
):
    """Seconds instead of ~50 minutes, and nothing was created in between."""

    project = _project()
    created_tasks = []
    started_threads = []
    _wire_build_route(monkeypatch, project, created_tasks, started_threads)
    _use_shim(monkeypatch)
    _respond(
        monkeypatch,
        httpx.Response(
            200,
            json={
                "ok": False,
                "detail": "truncated; raise GRAPHITI_LLM_MAX_TOKENS",
                "finish_reason": "length",
                "max_tokens": 4096,
            },
        ),
    )

    app = Flask(__name__)
    with app.test_request_context(
        "/api/graph/build",
        method="POST",
        json={"project_id": "proj-1"},
    ):
        body, status = _json_result(graph_api.build_graph())

    assert status == 502
    assert body["success"] is False
    assert "GRAPHITI_LLM_MAX_TOKENS" in body["error"]
    assert "skip_preflight=true" in body["error"]
    assert body["preflight"]["finish_reason"] == "length"
    # No task, no thread, no Cloud mutation: the request failed before the
    # build existed.
    assert created_tasks == []
    assert started_threads == []
    assert project.status == ProjectStatus.ONTOLOGY_GENERATED


def test_build_starts_once_the_extraction_endpoint_answers_cleanly(monkeypatch):
    project = _project()
    created_tasks = []
    started_threads = []
    _wire_build_route(monkeypatch, project, created_tasks, started_threads)
    _use_shim(monkeypatch)
    _respond(
        monkeypatch,
        httpx.Response(200, json={"ok": True, "detail": "extracted 3 entities"}),
    )

    app = Flask(__name__)
    with app.test_request_context(
        "/api/graph/build",
        method="POST",
        json={"project_id": "proj-1"},
    ):
        body, status = _json_result(graph_api.build_graph())

    assert status == 200
    assert body["data"]["task_id"] == "task-1"
    assert len(started_threads) == 1


def test_build_can_be_asked_to_skip_the_preflight(monkeypatch):
    project = _project()
    created_tasks = []
    started_threads = []
    _wire_build_route(monkeypatch, project, created_tasks, started_threads)
    _use_shim(monkeypatch)
    calls = []
    _respond(monkeypatch, httpx.Response(200, json={"ok": False}), calls)

    app = Flask(__name__)
    with app.test_request_context(
        "/api/graph/build",
        method="POST",
        json={"project_id": "proj-1", "skip_preflight": True},
    ):
        _body, status = _json_result(graph_api.build_graph())

    assert status == 200
    assert calls == []
    assert len(started_threads) == 1


def test_skip_preflight_must_be_a_json_boolean(monkeypatch):
    project = _project()
    _wire_build_route(monkeypatch, project, [], [])
    _use_shim(monkeypatch)

    app = Flask(__name__)
    with app.test_request_context(
        "/api/graph/build",
        method="POST",
        json={"project_id": "proj-1", "skip_preflight": "yes"},
    ):
        body, status = _json_result(graph_api.build_graph())

    assert status == 400
    assert "boolean" in body["error"]


def test_a_skipped_preflight_is_reported_to_whoever_started_the_build(monkeypatch):
    """A skip is not a pass, and a server-side log line is invisible to the caller."""

    project = _project()
    _wire_build_route(monkeypatch, project, [], [])
    _use_shim(monkeypatch)
    _respond(monkeypatch, httpx.Response(404, json={"detail": "Not Found"}))

    app = Flask(__name__)
    with app.test_request_context(
        "/api/graph/build",
        method="POST",
        json={"project_id": "proj-1"},
    ):
        body, status = _json_result(graph_api.build_graph())

    assert status == 200
    assert "404" in body["data"]["preflight_skipped"]


def test_an_older_shim_does_not_block_the_build(monkeypatch):
    project = _project()
    created_tasks = []
    started_threads = []
    _wire_build_route(monkeypatch, project, created_tasks, started_threads)
    _use_shim(monkeypatch)
    _respond(monkeypatch, httpx.Response(404, json={"detail": "Not Found"}))

    app = Flask(__name__)
    with app.test_request_context(
        "/api/graph/build",
        method="POST",
        json={"project_id": "proj-1"},
    ):
        _body, status = _json_result(graph_api.build_graph())

    assert status == 200
    assert len(started_threads) == 1


def test_a_transport_blip_on_the_probe_does_not_blame_zep_base_url(monkeypatch):
    """An unreachable probe is undetermined, not proof of a wrong base URL.

    The probe only runs after the preflight route itself answered 404, so the
    service demonstrably took a request moments ago. Treating a transport
    failure here as "not a Zep service" would fail the build of a healthy
    install on the strength of one dropped packet.
    """

    _use_shim(monkeypatch)
    _respond(
        monkeypatch,
        httpx.Response(404),
        probe=httpx.ConnectError("connection reset"),
    )

    result = graph_preflight.run_graph_preflight(None, "some extracted text")

    assert result.ok is True
    assert "ZEP_BASE_URL does not point" not in result.detail


def test_a_base_url_that_404s_everywhere_still_fails_the_preflight(monkeypatch):
    """A definitive 404 on the batch API is different from a transport blip."""

    _use_shim(monkeypatch)
    _respond(monkeypatch, httpx.Response(404), probe=httpx.Response(404))

    result = graph_preflight.run_graph_preflight(None, "some extracted text")

    assert result.ok is False
    assert "ZEP_BASE_URL" in result.detail


def test_the_preflight_is_not_run_for_a_request_that_cannot_start_a_build(
    monkeypatch,
):
    """The probe costs up to GRAPH_BUILD_PREFLIGHT_TIMEOUT seconds.

    Hoisting it above the per-project lock also hoisted it above every
    short-circuit in _build_graph_impl, so a request that only gets a "reused"
    reply, or is about to be rejected outright, must not pay for it.
    """

    project = Project(
        project_id="proj_guard",
        name="Guard",
        status=ProjectStatus.GRAPH_COMPLETED,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    project.graph_id = "graph_guard"
    monkeypatch.setattr(
        graph_api.ProjectManager, "get_project", lambda _pid: project
    )

    # Already built and not forced: the reply is "reused", so no probe.
    assert graph_api._preflight_is_worth_running({}, "proj_guard") is False
    # Forcing a rebuild does start a build, so the probe is worth paying for.
    assert graph_api._preflight_is_worth_running(
        {"force": True}, "proj_guard"
    ) is True
    # A malformed request is about to be rejected with a 400.
    assert graph_api._preflight_is_worth_running(
        {"force": True, "chunk_size": "500"}, "proj_guard"
    ) is False
    # An explicit opt-out is still honoured.
    assert graph_api._preflight_is_worth_running(
        {"force": True, "skip_preflight": True}, "proj_guard"
    ) is False
