from datetime import datetime
import threading

from flask import Flask
from types import SimpleNamespace

from app.api import graph as graph_api
from app.api import simulation as simulation_api
from app.models.project import Project, ProjectManager, ProjectStatus
from app.services.graph_builder import GraphBuilderService
from app.services.graph_preflight import GraphPreflightResult
from app.services.simulation_manager import SimulationStatus
from app.models.task import TaskStatus


def _project(status, graph_id="graph-1"):
    now = datetime.now().isoformat()
    return Project(
        project_id="proj-1",
        name="Project",
        status=status,
        created_at=now,
        updated_at=now,
        ontology={"entity_types": [], "edge_types": []},
        graph_id=graph_id,
        graph_build_task_id="task-1",
        zep_batch_id="batch-1",
        zep_batch_operation_id="operation-1",
    )


def _json_result(result):
    if isinstance(result, tuple):
        response, status = result
    else:
        response, status = result, result.status_code
    return response.get_json(), status


def test_project_reset_deletes_the_cloud_graph_before_clearing_reference(monkeypatch):
    project = _project(ProjectStatus.GRAPH_COMPLETED)
    events = []

    class Builder:
        def __init__(self, **_kwargs):
            pass

        def delete_graph(self, graph_id):
            events.append(("cloud-delete", graph_id))

    monkeypatch.setattr(graph_api, "GraphBuilderService", Builder)
    monkeypatch.setattr(graph_api.Config, "ZEP_API_KEY", "test-key")
    monkeypatch.setattr(
        graph_api.ProjectManager,
        "get_project",
        classmethod(lambda _cls, _project_id: project),
    )
    monkeypatch.setattr(
        graph_api.ProjectManager,
        "save_project",
        classmethod(lambda _cls, saved: events.append(("save", saved.graph_id))),
    )

    app = Flask(__name__)
    with app.test_request_context("/api/graph/project/proj-1/reset", method="POST"):
        body, status = _json_result(graph_api.reset_project("proj-1"))

    assert status == 200
    assert body["success"] is True
    assert events == [("cloud-delete", "graph-1"), ("save", None)]
    assert project.zep_batch_id is None
    assert project.status == ProjectStatus.ONTOLOGY_GENERATED


def test_project_reset_refuses_a_graph_with_an_active_simulation(monkeypatch):
    project = _project(ProjectStatus.GRAPH_COMPLETED)
    monkeypatch.setattr(graph_api.Config, "ZEP_API_KEY", "test-key")
    monkeypatch.setattr(
        graph_api.ProjectManager,
        "get_project",
        classmethod(lambda _cls, _project_id: project),
    )
    monkeypatch.setattr(
        graph_api.ZepGraphMemoryManager,
        "get_simulation_ids_for_graph",
        classmethod(lambda _cls, _graph_id: ["sim-active"]),
    )

    app = Flask(__name__)
    with app.test_request_context("/api/graph/project/proj-1/reset", method="POST"):
        body, status = _json_result(graph_api.reset_project("proj-1"))

    assert status == 409
    assert "sim-active" in body["error"]


def test_graph_delete_cannot_discard_an_updater_during_finalization(monkeypatch):
    monkeypatch.setattr(
        graph_api.ZepGraphMemoryManager,
        "get_simulation_ids_for_graph",
        classmethod(lambda _cls, _graph_id: ["sim-finalizing"]),
    )
    discarded = []
    monkeypatch.setattr(
        graph_api.ZepGraphMemoryManager,
        "discard_inactive_updater",
        classmethod(
            lambda _cls, simulation_id: discarded.append(simulation_id)
        ),
    )
    lock = graph_api.SimulationRunner._finalization_lock("sim-finalizing")
    lock.acquire()
    try:
        assert graph_api._active_graph_consumers("graph-1") == ["sim-finalizing"]
    finally:
        lock.release()

    assert discarded == []


def test_repeated_build_request_reuses_the_existing_task(monkeypatch):
    project = _project(ProjectStatus.GRAPH_BUILDING)
    monkeypatch.setattr(graph_api.Config, "ZEP_API_KEY", "test-key")
    monkeypatch.setattr(
        graph_api.ProjectManager,
        "get_project",
        classmethod(lambda _cls, _project_id: project),
    )
    monkeypatch.setattr(
        graph_api,
        "TaskManager",
        lambda: SimpleNamespace(
            get_task=lambda _task_id: SimpleNamespace(status=TaskStatus.PROCESSING)
        ),
    )

    app = Flask(__name__)
    with app.test_request_context(
        "/api/graph/build",
        method="POST",
        json={"project_id": "proj-1", "force": True},
    ):
        body, status = _json_result(graph_api.build_graph())

    assert status == 200
    assert body["success"] is True
    assert body["data"]["reused"] is True
    assert body["data"]["task_id"] == "task-1"
    assert body["data"]["graph_id"] == "graph-1"


def test_stale_build_after_restart_is_recoverable_instead_of_reused(monkeypatch):
    project = _project(ProjectStatus.GRAPH_BUILDING)
    project.zep_batch_id = None
    project.zep_batch_operation_id = None
    saved = []
    monkeypatch.setattr(graph_api.Config, "ZEP_API_KEY", "test-key")
    monkeypatch.setattr(
        graph_api.ProjectManager,
        "get_project",
        classmethod(lambda _cls, _project_id: project),
    )
    monkeypatch.setattr(
        graph_api.ProjectManager,
        "save_project",
        classmethod(lambda _cls, value: saved.append(value.status)),
    )
    monkeypatch.setattr(
        graph_api,
        "TaskManager",
        lambda: SimpleNamespace(get_task=lambda _task_id: None),
    )

    app = Flask(__name__)
    with app.test_request_context(
        "/api/graph/build",
        method="POST",
        json={"project_id": "proj-1"},
    ):
        body, status = _json_result(graph_api.build_graph())

    assert status == 409
    assert body["recoverable"] is True
    assert project.status == ProjectStatus.FAILED
    assert saved == [ProjectStatus.FAILED]


def test_stale_build_resumes_a_persisted_processing_batch(monkeypatch):
    project = _project(ProjectStatus.GRAPH_BUILDING)
    created_threads = []

    class Tasks:
        def get_task(self, _task_id):
            return None

        def create_task(self, _description):
            return "task-resumed"

    class Builder:
        def __init__(self, **_kwargs):
            pass

        def get_batch_summary(self, batch_id):
            assert batch_id == "batch-1"
            return SimpleNamespace(status="processing")

    class Thread:
        def __init__(self, *, target, daemon):
            created_threads.append((target, daemon))

        def start(self):
            pass

    monkeypatch.setattr(graph_api.Config, "ZEP_API_KEY", "test-key")
    monkeypatch.setattr(graph_api, "TaskManager", Tasks)
    monkeypatch.setattr(graph_api, "GraphBuilderService", Builder)
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

    app = Flask(__name__)
    with app.test_request_context(
        "/api/graph/build",
        method="POST",
        json={"project_id": "proj-1"},
    ):
        body, status = _json_result(graph_api.build_graph())

    assert status == 200
    assert body["data"]["resumed"] is True
    assert body["data"]["task_id"] == "task-resumed"
    assert project.graph_build_task_id == "task-resumed"
    assert len(created_threads) == 1


def test_project_delete_removes_cloud_graph_before_local_files(monkeypatch):
    project = _project(ProjectStatus.GRAPH_COMPLETED)
    events = []

    class Builder:
        def __init__(self, **_kwargs):
            pass

        def delete_graph(self, graph_id):
            events.append(("cloud-delete", graph_id))

    monkeypatch.setattr(graph_api, "GraphBuilderService", Builder)
    monkeypatch.setattr(graph_api.Config, "ZEP_API_KEY", "test-key")
    monkeypatch.setattr(
        graph_api.ProjectManager,
        "get_project",
        classmethod(lambda _cls, _project_id: project),
    )
    monkeypatch.setattr(
        graph_api.ProjectManager,
        "delete_project",
        classmethod(
            lambda _cls, project_id: events.append(("local-delete", project_id)) or True
        ),
    )

    app = Flask(__name__)
    with app.test_request_context(
        "/api/graph/project/proj-1",
        method="DELETE",
    ):
        body, status = _json_result(graph_api.delete_project("proj-1"))

    assert status == 200
    assert body["success"] is True
    assert events == [
        ("cloud-delete", "graph-1"),
        ("local-delete", "proj-1"),
    ]


def test_completed_build_request_is_idempotent_without_force(monkeypatch):
    project = _project(ProjectStatus.GRAPH_COMPLETED)
    monkeypatch.setattr(graph_api.Config, "ZEP_API_KEY", "test-key")
    monkeypatch.setattr(
        graph_api.ProjectManager,
        "get_project",
        classmethod(lambda _cls, _project_id: project),
    )

    app = Flask(__name__)
    with app.test_request_context(
        "/api/graph/build",
        method="POST",
        json={"project_id": "proj-1"},
    ):
        body, status = _json_result(graph_api.build_graph())

    assert status == 200
    assert body["data"]["reused"] is True
    assert body["data"]["graph_id"] == "graph-1"


def test_force_must_be_a_json_boolean(monkeypatch):
    project = _project(ProjectStatus.GRAPH_COMPLETED)
    monkeypatch.setattr(graph_api.Config, "ZEP_API_KEY", "test-key")
    monkeypatch.setattr(
        graph_api.ProjectManager,
        "get_project",
        classmethod(lambda _cls, _project_id: project),
    )

    app = Flask(__name__)
    with app.test_request_context(
        "/api/graph/build",
        method="POST",
        json={"project_id": "proj-1", "force": "false"},
    ):
        body, status = _json_result(graph_api.build_graph())

    assert status == 400
    assert "boolean" in body["error"]


def test_graph_reset_and_memory_start_cannot_cross_between_delete_and_clear(
    monkeypatch,
):
    project = _project(ProjectStatus.GRAPH_COMPLETED)
    simulation = SimpleNamespace(
        simulation_id="sim-1",
        project_id=project.project_id,
        graph_id=project.graph_id,
        status=SimulationStatus.READY,
    )
    delete_entered = threading.Event()
    allow_delete = threading.Event()
    runner_called = []

    class Builder:
        def __init__(self, **_kwargs):
            pass

        def delete_graph(self, graph_id):
            assert graph_id == "graph-1"
            delete_entered.set()
            assert allow_delete.wait(timeout=2)

    class Simulations:
        def get_simulation(self, _simulation_id):
            return simulation

    monkeypatch.setattr(graph_api, "GraphBuilderService", Builder)
    monkeypatch.setattr(graph_api.Config, "ZEP_API_KEY", "test-key")
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
    monkeypatch.setattr(simulation_api, "SimulationManager", Simulations)
    monkeypatch.setattr(
        simulation_api.ProjectManager,
        "get_project",
        classmethod(lambda _cls, _project_id: project),
    )
    monkeypatch.setattr(
        simulation_api.SimulationRunner,
        "start_simulation",
        classmethod(lambda _cls, **_kwargs: runner_called.append(True)),
    )

    app = Flask(__name__)
    results = {}

    def reset():
        with app.test_request_context(
            "/api/graph/project/proj-1/reset", method="POST"
        ):
            results["reset"] = _json_result(graph_api.reset_project("proj-1"))

    def start():
        with app.test_request_context(
            "/api/simulation/start",
            method="POST",
            json={
                "simulation_id": "sim-1",
                "enable_graph_memory_update": True,
            },
        ):
            results["start"] = _json_result(simulation_api.start_simulation())

    reset_thread = threading.Thread(target=reset)
    reset_thread.start()
    assert delete_entered.wait(timeout=2)

    start_thread = threading.Thread(target=start)
    start_thread.start()
    start_thread.join(timeout=0.05)
    assert start_thread.is_alive()

    allow_delete.set()
    reset_thread.join(timeout=2)
    start_thread.join(timeout=2)

    assert results["reset"][1] == 200
    assert results["start"][1] == 409
    assert runner_called == []
    assert project.graph_id is None


# ============== Abandoned graphs and the retry-batch journal ==============


def _skip_preflight(monkeypatch):
    """Keep the shim preflight out of tests that are about the build wiring."""

    monkeypatch.setattr(
        graph_api,
        "run_graph_preflight",
        lambda *_args, **_kwargs: GraphPreflightResult(
            ok=True, detail="not under test", skipped=True
        ),
    )


def _batch_item(sequence_index, status, episode_uuid=None, error=None, graph_id="graph-1"):
    return SimpleNamespace(
        sequence_index=sequence_index,
        status=status,
        episode_uuid=episode_uuid,
        source_uuid=episode_uuid,
        graph_id=graph_id,
        error=error,
    )


def test_non_forced_rebuild_records_the_graph_it_walks_away_from(monkeypatch):
    """The new build overwrites graph_id, so the old graph needs a record."""

    project = _project(ProjectStatus.FAILED)
    saved = []

    class Tasks:
        def get_task(self, _task_id):
            return None

        def create_task(self, _description):
            return "task-2"

        def update_task(self, *_args, **_kwargs):
            pass

    class Builder:
        def __init__(self, **_kwargs):
            pass

        def get_batch_summary(self, _batch_id):
            # Terminal and unresumable, so this request builds a fresh graph.
            return SimpleNamespace(status="failed")

    class Thread:
        def __init__(self, *, target, daemon):
            pass

        def start(self):
            pass

    _skip_preflight(monkeypatch)
    monkeypatch.setattr(graph_api.Config, "ZEP_API_KEY", "test-key")
    monkeypatch.setattr(graph_api, "TaskManager", Tasks)
    monkeypatch.setattr(graph_api, "GraphBuilderService", Builder)
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
        classmethod(
            lambda _cls, value: saved.append(
                (value.graph_id, list(value.orphaned_graph_ids))
            )
        ),
    )

    app = Flask(__name__)
    with app.test_request_context(
        "/api/graph/build",
        method="POST",
        json={"project_id": "proj-1"},
    ):
        body, status = _json_result(graph_api.build_graph())

    assert status == 200
    assert body["data"]["resumed"] is False
    # The graph is deliberately not deleted, but it is no longer this
    # project's graph, so it is recorded instead of being lost.
    assert project.orphaned_graph_ids == ["graph-1"]
    assert project.zep_batch_id is None
    assert project.zep_batch_operation_id is None
    assert (None, ["graph-1"]) in saved


def test_forced_rebuild_deletes_the_graph_instead_of_orphaning_it(monkeypatch):
    project = _project(ProjectStatus.FAILED)
    deleted = []

    class Tasks:
        def get_task(self, _task_id):
            return None

        def create_task(self, _description):
            return "task-2"

        def update_task(self, *_args, **_kwargs):
            pass

    class Builder:
        def __init__(self, **_kwargs):
            pass

        def delete_graph(self, graph_id):
            deleted.append(graph_id)

    class Thread:
        def __init__(self, *, target, daemon):
            pass

        def start(self):
            pass

    _skip_preflight(monkeypatch)
    monkeypatch.setattr(graph_api.Config, "ZEP_API_KEY", "test-key")
    monkeypatch.setattr(graph_api, "TaskManager", Tasks)
    monkeypatch.setattr(graph_api, "GraphBuilderService", Builder)
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

    app = Flask(__name__)
    with app.test_request_context(
        "/api/graph/build",
        method="POST",
        json={"project_id": "proj-1", "force": True},
    ):
        _body, status = _json_result(graph_api.build_graph())

    assert status == 200
    assert deleted == ["graph-1"]
    # Deleted, so there is nothing left to orphan.
    assert project.orphaned_graph_ids == []


def test_an_abandoned_graph_is_still_findable_for_cleanup(monkeypatch):
    project = _project(ProjectStatus.GRAPH_BUILDING, graph_id="graph-2")
    project.orphaned_graph_ids = ["graph-1"]
    monkeypatch.setattr(
        ProjectManager,
        "list_projects",
        classmethod(lambda _cls, limit=None: [project]),
    )

    assert ProjectManager.find_projects_by_graph_id("graph-1") == [project]
    assert ProjectManager.find_projects_by_graph_id("graph-2") == [project]
    assert ProjectManager.find_projects_by_graph_id("graph-3") == []


def test_delete_removes_an_abandoned_graph_while_its_project_builds(monkeypatch):
    """The build that abandoned the graph must not block cleaning it up."""

    project = _project(ProjectStatus.GRAPH_BUILDING, graph_id="graph-2")
    project.orphaned_graph_ids = ["graph-1"]
    deleted = []
    saved = []

    class Builder:
        def __init__(self, **_kwargs):
            pass

        def delete_graph(self, graph_id):
            deleted.append(graph_id)

    monkeypatch.setattr(graph_api, "GraphBuilderService", Builder)
    monkeypatch.setattr(graph_api.Config, "ZEP_API_KEY", "test-key")
    monkeypatch.setattr(
        graph_api,
        "TaskManager",
        lambda: SimpleNamespace(
            get_task=lambda _task_id: SimpleNamespace(status=TaskStatus.PROCESSING)
        ),
    )
    monkeypatch.setattr(
        graph_api.ProjectManager,
        "find_projects_by_graph_id",
        classmethod(lambda _cls, _graph_id: [project]),
    )
    monkeypatch.setattr(
        graph_api.ProjectManager,
        "save_project",
        classmethod(lambda _cls, value: saved.append(value.project_id)),
    )

    app = Flask(__name__)
    with app.test_request_context("/api/graph/delete/graph-1", method="DELETE"):
        body, status = _json_result(graph_api.delete_graph("graph-1"))

    assert status == 200
    assert body["success"] is True
    assert deleted == ["graph-1"]
    assert project.orphaned_graph_ids == []
    # The graph this project is actually building is untouched.
    assert project.graph_id == "graph-2"
    assert project.status == ProjectStatus.GRAPH_BUILDING
    assert saved == ["proj-1"]


def test_project_reset_also_deletes_the_graphs_earlier_attempts_abandoned(
    monkeypatch,
):
    project = _project(ProjectStatus.FAILED)
    project.orphaned_graph_ids = ["graph-0"]
    deleted = []

    class Builder:
        def __init__(self, **_kwargs):
            pass

        def delete_graph(self, graph_id):
            deleted.append(graph_id)

    monkeypatch.setattr(graph_api, "GraphBuilderService", Builder)
    monkeypatch.setattr(graph_api.Config, "ZEP_API_KEY", "test-key")
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

    app = Flask(__name__)
    with app.test_request_context(
        "/api/graph/project/proj-1/reset", method="POST"
    ):
        _body, status = _json_result(graph_api.reset_project("proj-1"))

    assert status == 200
    assert deleted == ["graph-1", "graph-0"]
    assert project.orphaned_graph_ids == []


def test_retry_batch_journal_is_persisted_and_replayed_by_the_build_route(
    monkeypatch,
):
    """End-to-end wiring: journal on the project, hand the snapshot back.

    The mechanism is covered elsewhere by passing known_retry_batches by hand.
    This exercises the part that actually recovers a build: remember_retry_batch
    in the route, its persistence onto the project, and the snapshot the resume
    passes back - so a crash after the retries succeeded replays the batch they
    created instead of ingesting those chunks a second time.
    """

    project = _project(ProjectStatus.ONTOLOGY_GENERATED, graph_id=None)
    project.graph_build_task_id = None
    project.zep_batch_id = None
    project.zep_batch_operation_id = None
    project.chunk_size = 30
    project.chunk_overlap = 1

    source_text = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu"
    journal_snapshots = []
    created_batches = []
    ingested = []
    threads = []

    class BatchApi:
        def get(self, **kwargs):
            if kwargs["batch_id"] == "batch-main":
                return SimpleNamespace(status="partial", progress=None)
            return SimpleNamespace(status="succeeded", progress=None)

        def create(self, **_kwargs):
            batch_id = "batch-main" if not created_batches else "batch-retry"
            created_batches.append(batch_id)
            return SimpleNamespace(batch_id=batch_id)

        def add(self, **kwargs):
            ingested.append([item.data for item in kwargs["items"]])
            return [
                SimpleNamespace(episode_uuid=f"episode-{index}")
                for index, _item in enumerate(kwargs["items"])
            ]

        def process(self, **_kwargs):
            return SimpleNamespace(status="queued")

        def list_items(self, **kwargs):
            if kwargs["batch_id"] == "batch-main":
                return SimpleNamespace(
                    items=[
                        _batch_item(0, "succeeded", "episode-0", graph_id="graph-built"),
                        _batch_item(
                            1, "failed", error={"message": "llm timeout"},
                            graph_id="graph-built",
                        ),
                        _batch_item(2, "succeeded", "episode-2", graph_id="graph-built"),
                    ],
                    next_cursor=None,
                )
            return SimpleNamespace(
                items=[
                    _batch_item(0, "succeeded", "episode-1", graph_id="graph-built")
                ],
                next_cursor=None,
            )

    class Builder(GraphBuilderService):
        def __init__(self, **_kwargs):
            # Everything below the Batch API is the real implementation; only
            # the transport is faked, so the journal really round-trips.
            self.client = SimpleNamespace(batch=BatchApi())
            self.task_manager = None

        def create_graph(self, name, *, graph_id=None, graph_id_callback=None):
            if graph_id_callback:
                graph_id_callback("graph-built")
            return "graph-built"

        def set_ontology(self, graph_id, ontology):
            pass

        def get_graph_data(self, graph_id):
            return {"node_count": 4, "edge_count": 3}

    class Tasks:
        def get_task(self, _task_id):
            return None

        def create_task(self, _description):
            return "task-build"

        def update_task(self, *_args, **_kwargs):
            pass

    class Thread:
        def __init__(self, *, target, daemon):
            threads.append(target)

        def start(self):
            pass

    _skip_preflight(monkeypatch)
    monkeypatch.setattr(graph_api.Config, "ZEP_API_KEY", "test-key")
    monkeypatch.setattr(graph_api, "TaskManager", Tasks)
    monkeypatch.setattr(graph_api, "GraphBuilderService", Builder)
    monkeypatch.setattr(graph_api.threading, "Thread", Thread)
    monkeypatch.setattr(
        graph_api.ProjectManager,
        "get_project",
        classmethod(lambda _cls, _project_id: project),
    )
    monkeypatch.setattr(
        graph_api.ProjectManager,
        "get_extracted_text",
        classmethod(lambda _cls, _project_id: source_text),
    )
    monkeypatch.setattr(
        graph_api.ProjectManager,
        "save_project",
        classmethod(
            lambda _cls, value: journal_snapshots.append(
                [dict(entry) for entry in value.zep_retry_batches]
            )
        ),
    )

    app = Flask(__name__)
    with app.test_request_context(
        "/api/graph/build",
        method="POST",
        json={"project_id": "proj-1"},
    ):
        _body, status = _json_result(graph_api.build_graph())
    assert status == 200
    assert len(threads) == 1
    threads[0]()

    assert project.status == ProjectStatus.GRAPH_COMPLETED
    assert project.error is None
    assert created_batches == ["batch-main", "batch-retry"]
    # Only the failed chunk went back out.
    assert ingested[-1] == ["n zeta eta theta iota kappa la"]

    operation_id = project.zep_retry_batches[0]["operation_id"]
    assert project.zep_retry_batches == [
        {"operation_id": operation_id, "batch_id": "batch-retry"}
    ]
    # Journalled before the create POST, then completed with the batch ID: a
    # crash between the two still leaves the operation named.
    assert [{"operation_id": operation_id, "batch_id": None}] in journal_snapshots
    assert project.zep_retry_batches in journal_snapshots

    # Now resume the same project. The persisted journal must be handed back
    # so the retry batch is polled rather than submitted again.
    project.status = ProjectStatus.FAILED
    created_batches.clear()
    ingested.clear()
    threads.clear()

    with app.test_request_context(
        "/api/graph/build",
        method="POST",
        json={"project_id": "proj-1"},
    ):
        body, status = _json_result(graph_api.build_graph())
    assert status == 200
    assert body["data"]["resumed"] is True
    assert len(threads) == 1
    threads[0]()

    assert project.status == ProjectStatus.GRAPH_COMPLETED
    assert project.error is None
    # Nothing was created and nothing was ingested: both the main batch and the
    # retry batch came out of the journal.
    assert created_batches == []
    assert ingested == []
    assert project.zep_retry_batches == [
        {"operation_id": operation_id, "batch_id": "batch-retry"}
    ]
