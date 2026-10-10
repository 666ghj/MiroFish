"""Provider-failure classification for the graph API.

The fixtures here are built from the real SDK exception classes rather than
hand-rolled stand-ins, because the shapes differ in ways the classifier has to
cope with: ``zep_cloud``'s ``ApiError`` has no ``request_id`` attribute at all
and leaves the id in the response headers, while ``openai``'s
``APIStatusError`` exposes both ``status_code`` and ``request_id`` directly. A
fake that sets both as instance attributes would pass against code that only
ever reads attributes, which is the bug these fixtures exist to catch.
"""

import logging
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace

import httpx
import pytest
from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    RateLimitError,
)
from openai import NotFoundError as OpenAINotFoundError
from werkzeug.exceptions import BadRequest, Forbidden, RequestEntityTooLarge
from zep_cloud import NotFoundError as ZepNotFoundError
from zep_cloud.core.api_error import ApiError as ZepApiError

from app import create_app
from app.api import graph as graph_api
from app.models.project import Project, ProjectStatus

# Stands in for whatever a provider echoes back in an error body. Both SDKs
# render it into str(error), so asserting its absence from a response proves the
# body is not being serialized to the client.
SECRET_DETAIL = "SECRET-PROVIDER-BODY"

PROVIDER_URL = "https://provider.invalid/v1/chat/completions"


def _zep_error(status_code, *, request_id=None, detail=SECRET_DETAIL):
    """A ``zep_cloud`` failure in its real shape.

    The body deliberately uses the ``{'type': 'about:blank', 'title': ...}``
    envelope from issue #836 rather than ``{'error': {...}}``, so the test fails
    if anyone switches the classifier to parsing bodies.
    """

    return ZepApiError(
        status_code=status_code,
        # Real responses vary the casing, and zep hands back a plain dict, so
        # the lookup has to be case-insensitive.
        headers={"X-Request-Id": request_id} if request_id else None,
        body={
            "type": "about:blank",
            "title": "Gone",
            "status": status_code,
            "detail": detail,
        },
    )


def _openai_error(error_cls, status_code, *, request_id=None):
    """An ``openai`` failure in its real shape, built from a real response."""

    request = httpx.Request("POST", PROVIDER_URL)
    response = httpx.Response(
        status_code,
        request=request,
        headers={"x-request-id": request_id} if request_id else {},
    )
    return error_cls(SECRET_DETAIL, response=response, body={"detail": SECRET_DETAIL})


@contextmanager
def _captured_logs(*names):
    """Collect records from the app's loggers.

    pytest's ``caplog`` cannot see these: ``app/utils/logger.py`` sets
    ``propagate = False``, so records never reach the root logger it hooks.
    """

    records = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = _Capture()
    loggers = [logging.getLogger(name) for name in names]
    for logger in loggers:
        logger.addHandler(handler)
    try:
        yield records
    finally:
        for logger in loggers:
            logger.removeHandler(handler)


def _log_text(records):
    return "\n".join(record.getMessage() for record in records)


def _client():
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def _project(status=ProjectStatus.ONTOLOGY_GENERATED):
    now = datetime.now().isoformat()
    return Project(
        project_id="proj-1",
        name="Project",
        status=status,
        created_at=now,
        updated_at=now,
        ontology={"entity_types": [], "edge_types": []},
        graph_id="graph-1",
        graph_build_task_id="task-1",
        zep_batch_id="batch-1",
        zep_batch_operation_id="operation-1",
    )


def _install_failing_builder(monkeypatch, error):
    class Builder:
        def __init__(self, **_kwargs):
            pass

        def validate_batch_chunks(self, _chunks, batch_size=350):
            return None

        def get_graph_data(self, _graph_id):
            raise error

        def delete_graph(self, _graph_id):
            raise error

        def get_batch_summary(self, _batch_id):
            raise error

        def create_graph(self, **_kwargs):
            raise error

    monkeypatch.setattr(graph_api.Config, "ZEP_API_KEY", "test-key")
    monkeypatch.setattr(graph_api, "GraphBuilderService", Builder)


def _assert_nothing_internal_leaked(response):
    body = response.get_data(as_text=True)
    assert "traceback" not in response.json
    assert "Traceback" not in body
    assert SECRET_DETAIL not in body


# ---------------------------------------------------------------- status mapping


def test_graph_data_maps_a_retired_model_to_502(monkeypatch):
    _install_failing_builder(monkeypatch, _zep_error(410, request_id="req-gone"))

    response = _client().get("/api/graph/data/graph-1")

    assert response.status_code == 502
    assert response.json["success"] is False
    assert "HTTP 410" in response.json["error"]
    assert "req-gone" in response.json["error"]
    _assert_nothing_internal_leaked(response)


def test_graph_data_maps_a_rate_limit_to_502(monkeypatch):
    _install_failing_builder(
        monkeypatch, _openai_error(RateLimitError, 429, request_id="req-slow")
    )

    response = _client().get("/api/graph/data/graph-1")

    assert response.status_code == 502
    assert "HTTP 429" in response.json["error"]
    _assert_nothing_internal_leaked(response)


def test_graph_data_maps_an_auth_failure_to_502(monkeypatch):
    # The rejected credential is the server's, not the caller's, so this must
    # not become a 401 that tells the caller to re-authenticate.
    _install_failing_builder(monkeypatch, _openai_error(AuthenticationError, 401))

    response = _client().get("/api/graph/data/graph-1")

    assert response.status_code == 502
    assert "HTTP 401" in response.json["error"]
    _assert_nothing_internal_leaked(response)


def test_graph_data_maps_a_missing_graph_to_404_not_502(monkeypatch):
    # Absent is not broken. A 502 would tell every proxy and retry layer in the
    # path that the upstream is down, for what is usually a mistyped id.
    _install_failing_builder(monkeypatch, ZepNotFoundError(body={"message": "nope"}))

    response = _client().get("/api/graph/data/graph-1")

    assert response.status_code == 404
    assert "HTTP 404" in response.json["error"]
    assert "Traceback" not in response.get_data(as_text=True)


def test_graph_data_maps_a_missing_model_to_404(monkeypatch):
    # Same rule for the other SDK, which reaches 404 by a different route:
    # a class-level status_code plus a 404 response object.
    _install_failing_builder(
        monkeypatch, _openai_error(OpenAINotFoundError, 404, request_id="req-absent")
    )

    response = _client().get("/api/graph/data/graph-1")

    assert response.status_code == 404
    assert "req-absent" in response.json["error"]
    _assert_nothing_internal_leaked(response)


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(httpx.ConnectError("connection refused"), id="connect-error"),
        pytest.param(httpx.ConnectTimeout("timed out"), id="connect-timeout"),
        pytest.param(httpx.ReadTimeout("read timed out"), id="read-timeout"),
        pytest.param(
            APITimeoutError(request=httpx.Request("POST", PROVIDER_URL)),
            id="openai-timeout",
        ),
        pytest.param(
            APIConnectionError(request=httpx.Request("POST", PROVIDER_URL)),
            id="openai-connection",
        ),
    ],
)
def test_an_unreachable_provider_is_a_502_not_a_500(monkeypatch, error):
    # These carry no status_code at all -- zep_cloud does not wrap httpx
    # transport errors, and openai's connection errors are not APIStatusError
    # subclasses -- but they are gateway failures, not server bugs.
    _install_failing_builder(monkeypatch, error)

    response = _client().get("/api/graph/data/graph-1")

    assert response.status_code == 502
    assert response.json["error"] == "Provider unreachable or timed out"
    assert "Traceback" not in response.get_data(as_text=True)


def test_graph_data_maps_an_unexpected_error_to_500(monkeypatch):
    _install_failing_builder(monkeypatch, RuntimeError("postgres://user:hunter2@db"))

    response = _client().get("/api/graph/data/graph-1")

    assert response.status_code == 500
    assert response.json["error"] == "Graph data request failed; check the server logs"
    body = response.get_data(as_text=True)
    assert "traceback" not in response.json
    assert "Traceback" not in body
    assert "hunter2" not in body


@pytest.mark.parametrize(
    "status_code",
    [
        pytest.param(True, id="bool-is-an-int-subclass"),
        pytest.param(0, id="zero"),
        pytest.param(-1, id="negative"),
        pytest.param(99999, id="out-of-range"),
        pytest.param("410", id="string"),
        pytest.param(None, id="none"),
    ],
)
def test_a_non_status_status_code_is_not_a_provider_failure(monkeypatch, status_code):
    class Odd(RuntimeError):
        pass

    error = Odd("boom")
    error.status_code = status_code
    _install_failing_builder(monkeypatch, error)

    response = _client().get("/api/graph/data/graph-1")

    assert response.status_code == 500
    assert response.json["error"] == "Graph data request failed; check the server logs"


# --------------------------------------------------------- server-side logging


def test_the_provider_detail_reaches_the_log_but_not_the_response(monkeypatch):
    """The operator must be able to learn *which* model died from the log alone.

    Issue #836's complaint is that there was nothing to diagnose the failure
    with, "not even in the logs". Withholding the provider's body from the
    response is right; withholding it from the server log is the bug.
    """

    detail = (
        "The model 'openai/gpt-oss-120b' has reached its end of life on "
        "2026-09-03T08:00:00Z and is no longer available."
    )
    _install_failing_builder(
        monkeypatch, _zep_error(410, request_id="req-gone", detail=detail)
    )

    with _captured_logs("mirofish.api") as records:
        response = _client().get("/api/graph/data/graph-1")

    logged = _log_text(records)
    assert "openai/gpt-oss-120b" in logged
    assert "has reached its end of life" in logged
    assert "status=410" in logged
    assert "request_id=req-gone" in logged

    body = response.get_data(as_text=True)
    assert "end of life" not in body
    assert "gpt-oss-120b" not in body


def test_an_unexpected_failure_logs_a_stack(monkeypatch):
    # The stack is what makes a 500 diagnosable, so it has to be in the log
    # even though it is no longer in the response.
    _install_failing_builder(monkeypatch, RuntimeError("ZEP_API_KEY=hunter2"))

    with _captured_logs("mirofish.api") as records:
        _client().get("/api/graph/data/graph-1")

    unexpected = [r for r in records if "failed unexpectedly" in r.getMessage()]
    assert len(unexpected) == 1
    assert unexpected[0].levelno == logging.ERROR
    assert unexpected[0].exc_info is not None


def test_a_provider_failure_does_not_log_a_stack(monkeypatch):
    # A stack is reserved for failures the classifier cannot explain; a status
    # plus the provider's own detail is the better record for the rest.
    _install_failing_builder(monkeypatch, _zep_error(410, request_id="req-gone"))

    with _captured_logs("mirofish.api") as records:
        _client().get("/api/graph/data/graph-1")

    provider = [r for r in records if "failed at the provider" in r.getMessage()]
    assert len(provider) == 1
    assert provider[0].exc_info is None


# ------------------------------------------------------------------ request ids


def test_a_zep_request_id_is_read_from_the_response_headers(monkeypatch):
    """``zep_cloud``'s ``ApiError`` has no ``request_id`` attribute.

    Reading only ``error.request_id`` means the id is silently dropped on every
    Zep-backed path, which is all four call sites.
    """

    error = _zep_error(503, request_id="zep-req-1")
    assert not hasattr(error, "request_id")

    _install_failing_builder(monkeypatch, error)
    response = _client().get("/api/graph/data/graph-1")

    assert response.status_code == 502
    assert "request_id: zep-req-1" in response.json["error"]


def test_an_openai_request_id_is_read_from_the_attribute(monkeypatch):
    error = _openai_error(RateLimitError, 429, request_id="openai-req-1")
    assert error.request_id == "openai-req-1"

    _install_failing_builder(monkeypatch, error)
    response = _client().get("/api/graph/data/graph-1")

    assert "request_id: openai-req-1" in response.json["error"]


@pytest.mark.parametrize(
    "hostile",
    [
        pytest.param('req-1\n<script>alert("x")</script>', id="newline-and-markup"),
        pytest.param("req-1\r\nX-Evil: 1", id="crlf"),
        pytest.param("req-1\rrest", id="bare-carriage-return"),
        pytest.param('req-1","admin":true', id="json-breakout"),
        pytest.param("req-1\x00tail", id="null-byte"),
        pytest.param("req-1\x1b[31m", id="ansi-escape"),
        pytest.param("req-1 next", id="unicode-line-separator"),
    ],
)
def test_a_request_id_is_sanitized_before_it_is_echoed(monkeypatch, hostile):
    """The id lands in a JSON response body and in log lines.

    So the threats are body-context escaping and log-line forgery, not header
    injection -- nothing here is ever written to a response header. The
    allowlist drops everything outside ``[a-zA-Z0-9._:-]``, which covers all of
    these without enumerating them.
    """

    _install_failing_builder(monkeypatch, _zep_error(410, request_id=hostile))

    response = _client().get("/api/graph/data/graph-1")
    error = response.json["error"]

    assert error.startswith("Provider request failed (HTTP 410) (request_id: ")
    assert error.endswith(")")
    echoed = error.split("(request_id: ", 1)[1][:-1]
    assert echoed, "a usable prefix of the id should survive sanitization"
    for forbidden in ("\n", "\r", "\x00", "\x1b", " ", "<", ">", '"', " "):
        assert forbidden not in echoed


def test_a_request_id_that_sanitizes_to_nothing_is_omitted(monkeypatch):
    # Guards the `if safe_request_id` branch: an id made entirely of rejected
    # characters must not leave a dangling "(request_id: )".
    _install_failing_builder(monkeypatch, _zep_error(410, request_id="<<<>>>"))

    response = _client().get("/api/graph/data/graph-1")

    assert response.json["error"] == "Provider request failed (HTTP 410)"
    assert "request_id" not in response.json["error"]


def test_an_uncooperative_exception_still_gets_classified(monkeypatch):
    # The classifier runs while handling a failure, so looking for a request id
    # must not be able to replace the error being reported.
    class Hostile(RuntimeError):
        status_code = 503

        @property
        def headers(self):
            raise RuntimeError("header access blew up")

    _install_failing_builder(monkeypatch, Hostile("boom"))

    response = _client().get("/api/graph/data/graph-1")

    assert response.status_code == 502
    assert response.json["error"] == "Provider request failed (HTTP 503)"
    assert "blew up" not in response.get_data(as_text=True)


def test_a_long_request_id_is_truncated(monkeypatch):
    _install_failing_builder(monkeypatch, _zep_error(410, request_id="a" * 200))

    response = _client().get("/api/graph/data/graph-1")

    assert "a" * 128 in response.json["error"]
    assert "a" * 129 not in response.json["error"]


# ---------------------------------------------------------- aborted HTTP errors


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        pytest.param(BadRequest(), 400, id="bad-request"),
        pytest.param(RequestEntityTooLarge(), 413, id="too-large"),
        pytest.param(Forbidden(), 403, id="forbidden"),
    ],
)
def test_an_http_exception_keeps_its_own_status(error, expected_status):
    # A bare `except Exception` catches werkzeug's HTTPException too, which used
    # to turn a client error into "check the server logs" with a 500.
    message, status = graph_api._classify_failure(error, "Graph build request")

    assert status == expected_status
    assert message == error.description
    assert "check the server logs" not in message


@pytest.mark.parametrize(
    ("payload", "content_type"),
    [
        pytest.param("this-is-not-json", "application/json", id="malformed-json"),
        pytest.param("", "application/json", id="empty-body"),
        pytest.param("hello", "text/plain", id="wrong-content-type"),
    ],
)
def test_a_malformed_build_request_is_a_400(monkeypatch, payload, content_type):
    monkeypatch.setattr(
        graph_api.Config, "ZEP_API_KEY", "test-key"
    )

    response = _client().post(
        "/api/graph/build", data=payload, content_type=content_type
    )

    assert response.status_code == 400
    body = response.get_data(as_text=True)
    assert "check the server logs" not in body
    assert "Traceback" not in body


# ------------------------------------------------------------- the other routes


def test_graph_delete_maps_a_provider_failure_to_502(monkeypatch):
    project = _project(ProjectStatus.GRAPH_COMPLETED)
    _install_failing_builder(monkeypatch, _zep_error(503, request_id="req-delete"))
    monkeypatch.setattr(
        graph_api.ProjectManager,
        "find_projects_by_graph_id",
        classmethod(lambda _cls, _graph_id: [project]),
    )
    monkeypatch.setattr(
        graph_api.ZepGraphMemoryManager,
        "get_simulation_ids_for_graph",
        classmethod(lambda _cls, _graph_id: []),
    )
    monkeypatch.setattr(
        graph_api,
        "SimulationManager",
        lambda: SimpleNamespace(list_simulations=lambda: []),
    )

    response = _client().delete("/api/graph/delete/graph-1")

    assert response.status_code == 502
    assert "HTTP 503" in response.json["error"]
    assert "req-delete" in response.json["error"]
    _assert_nothing_internal_leaked(response)


def _install_build_request_project(monkeypatch, project):
    monkeypatch.setattr(
        graph_api.ProjectManager,
        "get_project",
        classmethod(lambda _cls, _project_id: project),
    )
    monkeypatch.setattr(
        graph_api.ProjectManager,
        "save_project",
        classmethod(lambda _cls, _project: None),
    )
    monkeypatch.setattr(
        graph_api,
        "TaskManager",
        lambda: SimpleNamespace(get_task=lambda _task_id: None),
    )


def test_build_request_maps_a_provider_failure_to_502(monkeypatch):
    project = _project(ProjectStatus.GRAPH_BUILDING)
    _install_failing_builder(monkeypatch, _zep_error(410, request_id="req-batch"))
    _install_build_request_project(monkeypatch, project)

    response = _client().post("/api/graph/build", json={"project_id": "proj-1"})

    assert response.status_code == 502
    assert "HTTP 410" in response.json["error"]
    assert "req-batch" in response.json["error"]
    _assert_nothing_internal_leaked(response)


def test_build_request_maps_an_unexpected_error_to_500(monkeypatch):
    project = _project(ProjectStatus.GRAPH_BUILDING)
    _install_failing_builder(monkeypatch, RuntimeError("ZEP_API_KEY=hunter2"))
    _install_build_request_project(monkeypatch, project)

    response = _client().post("/api/graph/build", json={"project_id": "proj-1"})

    assert response.status_code == 500
    assert response.json["error"] == "Graph build request failed; check the server logs"
    body = response.get_data(as_text=True)
    assert "traceback" not in response.json
    assert "Traceback" not in body
    assert "hunter2" not in body


# ----------------------------------------------------------- the background task


def _install_background_build(monkeypatch, project, error):
    """Run the build task inline so its failure handling can be inspected."""

    build_targets = []

    class Thread:
        def __init__(self, *, target, daemon):
            build_targets.append(target)

        def start(self):
            pass

    _install_failing_builder(monkeypatch, error)
    monkeypatch.setattr(graph_api.threading, "Thread", Thread)
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
    return build_targets


def test_background_build_failure_reports_a_safe_task_error(monkeypatch):
    project = _project(ProjectStatus.ONTOLOGY_GENERATED)
    client = _client()
    build_targets = _install_background_build(
        monkeypatch, project, _zep_error(410, request_id="req-gone")
    )

    response = client.post("/api/graph/build", json={"project_id": "proj-1"})
    assert response.status_code == 200
    task_id = response.json["data"]["task_id"]

    assert len(build_targets) == 1
    build_targets[0]()

    task = client.get(f"/api/graph/task/{task_id}")

    assert task.status_code == 200
    assert task.json["data"]["status"] == "failed"
    assert task.json["data"]["error"] == (
        "Provider request failed (HTTP 410) (request_id: req-gone)"
    )
    assert project.status == ProjectStatus.FAILED
    assert project.error == task.json["data"]["error"]
    body = task.get_data(as_text=True)
    assert "Traceback" not in body
    assert SECRET_DETAIL not in body


def test_background_build_keeps_an_unexpected_error_out_of_the_task(monkeypatch):
    project = _project(ProjectStatus.ONTOLOGY_GENERATED)
    client = _client()
    build_targets = _install_background_build(
        monkeypatch, project, RuntimeError("ZEP_API_KEY=hunter2")
    )

    response = client.post("/api/graph/build", json={"project_id": "proj-1"})
    task_id = response.json["data"]["task_id"]

    assert len(build_targets) == 1
    build_targets[0]()

    task = client.get(f"/api/graph/task/{task_id}")

    assert task.json["data"]["error"] == "Graph build failed; check the server logs"
    body = task.get_data(as_text=True)
    assert "Traceback" not in body
    assert "hunter2" not in body


def test_background_build_logs_the_provider_detail_to_the_build_logger(monkeypatch):
    """The build path uses its own logger, so the detail has to land there.

    This also pins down a regression the old code had independently of the
    response: it logged the background stack at DEBUG, below the console
    handler's INFO threshold, so nothing reached `docker logs` at all.
    """

    project = _project(ProjectStatus.ONTOLOGY_GENERATED)
    client = _client()
    build_targets = _install_background_build(
        monkeypatch, project, _zep_error(410, request_id="req-gone")
    )

    response = client.post("/api/graph/build", json={"project_id": "proj-1"})
    task_id = response.json["data"]["task_id"]

    with _captured_logs("mirofish.build") as records:
        build_targets[0]()

    assert records, "the build task must log to mirofish.build"
    assert all(record.name == "mirofish.build" for record in records)
    logged = _log_text(records)
    assert SECRET_DETAIL in logged
    assert "status=410" in logged
    assert "request_id=req-gone" in logged
    assert min(record.levelno for record in records) >= logging.INFO

    task = client.get(f"/api/graph/task/{task_id}")
    assert SECRET_DETAIL not in task.get_data(as_text=True)


def test_background_build_logs_a_stack_for_an_unexpected_failure(monkeypatch):
    project = _project(ProjectStatus.ONTOLOGY_GENERATED)
    client = _client()
    build_targets = _install_background_build(
        monkeypatch, project, RuntimeError("ZEP_API_KEY=hunter2")
    )

    client.post("/api/graph/build", json={"project_id": "proj-1"})

    with _captured_logs("mirofish.build") as records:
        build_targets[0]()

    with_stack = [r for r in records if r.exc_info is not None]
    assert len(with_stack) == 1
    assert with_stack[0].levelno == logging.ERROR
