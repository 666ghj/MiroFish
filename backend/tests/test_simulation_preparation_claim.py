"""
Regression cover for the preparation claim deadlock.

Step 2 mounts two components that each POST /prepare about thirty milliseconds
apart. The first took the claim, the second was refused with "Preparation is
already running", and the frontend rendered that as "Preparation error" - a
healthy run reported as a crash. Pressing Restart then answered "still being
prepared. Wait for preparation to finish", because /restart refused on the very
same claim. With both doors shut the simulation had no way out of 'preparing'
short of a backend restart, and a claim left behind by a thread that died
without releasing it was permanent.

Three things are pinned here:
1. A claim is only honoured while its thread is alive. A dead one is dropped
   and blocks nothing - not /prepare, not /restart.
2. A live claim still blocks both, because the preparation thread has no
   cancellation point and owns the profile and config files.
3. The refusal /prepare returns is marked coalesced and carries the in-flight
   task_id, so the caller can follow the run instead of reporting a failure.
"""

import threading
import time
from types import SimpleNamespace

import pytest
from flask import Flask

from app.api import simulation as simulation_api
from app.services.simulation_manager import SimulationStatus
from app.services.simulation_runner import RunnerStatus, SimulationRunState


@pytest.fixture(autouse=True)
def _clean_claim_registry():
    """The claim registry is process-global; no test may leak into the next."""
    simulation_api._active_preparations.clear()
    yield
    simulation_api._active_preparations.clear()


def _install_live_claim(simulation_id, task_id="task-live"):
    """Claim a simulation with a thread that really is running."""
    release = threading.Event()
    thread = threading.Thread(target=release.wait, daemon=True)
    thread.start()
    simulation_api._active_preparations[simulation_id] = (
        simulation_api._PreparationClaim(task_id=task_id, thread=thread)
    )
    return release, thread


def _install_dead_claim(simulation_id, task_id="task-dead"):
    """
    Claim a simulation with a thread that has already ended.

    This is the leaked claim: the entry the registry keeps when a preparation
    thread goes away without running its finally.
    """
    thread = threading.Thread(target=lambda: None, daemon=True)
    thread.start()
    thread.join()
    simulation_api._active_preparations[simulation_id] = (
        simulation_api._PreparationClaim(task_id=task_id, thread=thread)
    )
    return thread


def _install_manager(monkeypatch, simulation, is_prepared=True, saves=None):
    """Serve one simulation state and record the state saves."""
    monkeypatch.setattr(
        simulation_api,
        "SimulationManager",
        lambda: SimpleNamespace(
            get_simulation=lambda _simulation_id: simulation,
            is_prepared=lambda _simulation_id: is_prepared,
            _save_simulation_state=lambda state: (
                saves.append(state.status) if saves is not None else None
            ),
        ),
    )


def _simulation(status=SimulationStatus.READY, simulation_id="sim-1"):
    return SimpleNamespace(
        simulation_id=simulation_id,
        project_id="proj-1",
        graph_id="graph-1",
        status=status,
        error=None,
        entities_count=0,
        entity_types=[],
    )


# ============== The liveness check itself ==============


def test_a_claim_with_no_worker_yet_counts_as_live():
    """
    /prepare takes the claim a few statements before it has a thread to put in
    it. Reading that as dead would hand the simulation to a second preparation
    while the first request is still inside the route.
    """
    claim = simulation_api._PreparationClaim(task_id=None, thread=None)

    assert simulation_api._claim_is_live(claim) is True


def test_a_registered_but_unstarted_worker_counts_as_live():
    """
    The worker is attached to the claim before start(), and an unstarted
    Thread reports is_alive() False. Only ident tells that window apart from a
    thread that has finished.
    """
    thread = threading.Thread(target=lambda: None, daemon=True)
    claim = simulation_api._PreparationClaim(task_id="task-1", thread=thread)

    assert thread.is_alive() is False
    assert simulation_api._claim_is_live(claim) is True


def test_a_finished_worker_makes_the_claim_dead_and_droppable():
    _install_dead_claim("sim-1")

    assert simulation_api._discard_dead_preparation("sim-1") is True
    assert simulation_api._preparation_in_flight("sim-1") == (False, None)
    # Dropping is idempotent: there is nothing left to drop.
    assert simulation_api._discard_dead_preparation("sim-1") is False


def test_a_dead_claim_can_be_reclaimed():
    """A leaked claim must not stop the next preparation from being started."""
    _install_dead_claim("sim-1")

    assert simulation_api._claim_preparation("sim-1") is True


def test_a_live_claim_cannot_be_reclaimed():
    release, _thread = _install_live_claim("sim-1")
    try:
        assert simulation_api._claim_preparation("sim-1") is False
        assert simulation_api._preparation_in_flight("sim-1") == (
            True,
            "task-live",
        )
    finally:
        release.set()


# ============== POST /prepare ==============


def test_live_claim_coalesces_prepare_and_hands_back_the_task(monkeypatch):
    """
    The refusal the user saw. It keeps 409 and the task_id - the frontend needs
    that to follow the run - but says coalesced so it cannot be rendered as a
    failure.
    """
    _install_manager(monkeypatch, _simulation())
    release, _thread = _install_live_claim("sim-1", task_id="task-inflight")

    app = Flask(__name__)
    try:
        with app.test_request_context(
            "/api/simulation/prepare",
            method="POST",
            json={"simulation_id": "sim-1"},
        ):
            response, status = simulation_api.prepare_simulation()
    finally:
        release.set()

    payload = response.get_json()
    assert status == 409
    assert payload["coalesced"] is True
    assert payload["pending"] is True
    assert payload["task_id"] == "task-inflight"
    assert "task-inflight" in payload["error"]


def test_dead_claim_does_not_block_prepare(monkeypatch):
    """
    Same request, same simulation, only the claim's thread is gone: /prepare
    must get past the guard. It lands on the already-prepared shortcut here,
    which is proof enough that the refusal did not fire.
    """
    _install_manager(monkeypatch, _simulation())
    _install_dead_claim("sim-1")
    monkeypatch.setattr(
        simulation_api,
        "_check_simulation_prepared",
        lambda _simulation_id: (True, {"status": "ready"}),
    )

    app = Flask(__name__)
    with app.test_request_context(
        "/api/simulation/prepare",
        method="POST",
        json={"simulation_id": "sim-1"},
    ):
        response = simulation_api.prepare_simulation()

    payload = response.get_json()
    assert payload["success"] is True
    assert payload["data"]["already_prepared"] is True
    # And the dead claim is gone, so nothing else trips over it either.
    assert "sim-1" not in simulation_api._active_preparations


# ============== The claim is released on every exit ==============


class _FakeTaskManager:
    """Records what the route and its worker thread do to the task."""

    created = []
    failed = []
    create_error = None

    def __init__(self):
        pass

    def create_task(self, task_type, metadata=None):
        if type(self).create_error is not None:
            raise type(self).create_error
        type(self).created.append((task_type, metadata))
        return "task-created"

    def update_task(self, task_id, **kwargs):
        return None

    def complete_task(self, task_id, result):
        return None

    def fail_task(self, task_id, error):
        type(self).failed.append((task_id, error))


def _install_prepare_prerequisites(monkeypatch, simulation, saves=None):
    """Everything /prepare reads before it starts the preparation thread."""
    _install_manager(monkeypatch, simulation, saves=saves)
    monkeypatch.setattr(
        simulation_api,
        "_check_simulation_prepared",
        lambda _simulation_id: (False, {"reason": "not prepared"}),
    )
    monkeypatch.setattr(
        simulation_api.ProjectManager,
        "get_project",
        classmethod(
            lambda _cls, _project_id: SimpleNamespace(
                simulation_requirement="requirement",
                graph_id="graph-1",
            )
        ),
    )
    monkeypatch.setattr(
        simulation_api.ProjectManager,
        "get_extracted_text",
        classmethod(lambda _cls, _project_id: "document"),
    )
    # The entity pre-count is best effort in the route; failing it keeps the
    # test off the network without changing the path under test.
    monkeypatch.setattr(
        simulation_api,
        "ZepEntityReader",
        lambda: (_ for _ in ()).throw(RuntimeError("no graph in tests")),
    )
    _FakeTaskManager.created = []
    _FakeTaskManager.failed = []
    _FakeTaskManager.create_error = None
    monkeypatch.setattr("app.models.task.TaskManager", _FakeTaskManager)


def _await_claim_release(simulation_id, timeout=10.0):
    """Wait for the preparation thread to hand its claim back."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if simulation_id not in simulation_api._active_preparations:
            return True
        time.sleep(0.01)
    return simulation_id not in simulation_api._active_preparations


def test_a_failure_before_the_thread_starts_releases_the_claim(monkeypatch):
    """
    The leak that made this unrecoverable. Anything raising between the claim
    and the thread start - here the task file - reaches the route's 500 handler,
    which knows nothing about the claim. Without the release the claim outlives
    the request with no thread behind it, and /prepare and /restart then both
    refuse until the backend is restarted.
    """
    _install_prepare_prerequisites(monkeypatch, _simulation())
    _FakeTaskManager.create_error = OSError("read-only task directory")

    app = Flask(__name__)
    with app.test_request_context(
        "/api/simulation/prepare",
        method="POST",
        json={"simulation_id": "sim-1"},
    ):
        response, status = simulation_api.prepare_simulation()

    assert status == 500
    assert "read-only task directory" in response.get_json()["error"]
    assert "sim-1" not in simulation_api._active_preparations


def test_the_worker_releases_the_claim_when_the_preparation_fails(monkeypatch):
    """
    The other half: a preparation that blows up mid-way still hands the claim
    back, so the next /prepare is accepted rather than coalesced into a run
    that no longer exists.
    """
    simulation = _simulation()
    _install_prepare_prerequisites(monkeypatch, simulation)
    monkeypatch.setattr(
        simulation_api,
        "SimulationManager",
        lambda: SimpleNamespace(
            get_simulation=lambda _simulation_id: simulation,
            is_prepared=lambda _simulation_id: False,
            _save_simulation_state=lambda _state: None,
            prepare_simulation=lambda **_kwargs: (_ for _ in ()).throw(
                RuntimeError("the LLM endpoint refused the run")
            ),
        ),
    )

    app = Flask(__name__)
    with app.test_request_context(
        "/api/simulation/prepare",
        method="POST",
        json={"simulation_id": "sim-1"},
    ):
        response = simulation_api.prepare_simulation()

    assert response.get_json()["data"]["task_id"] == "task-created"
    assert _await_claim_release("sim-1") is True
    assert _FakeTaskManager.failed == [
        ("task-created", "the LLM endpoint refused the run")
    ]


# ============== POST /restart ==============


def _install_idle_runner(monkeypatch, restarted):
    """An idle runner that records the restart instead of launching one."""
    run_state = SimulationRunState(
        simulation_id="sim-1", runner_status=RunnerStatus.STARTING
    )
    monkeypatch.setattr(
        simulation_api.SimulationRunner,
        "get_run_state",
        classmethod(lambda _cls, _simulation_id: None),
    )
    monkeypatch.setattr(
        simulation_api.ZepGraphMemoryManager,
        "get_updater",
        classmethod(lambda _cls, _simulation_id: None),
    )
    monkeypatch.setattr(
        simulation_api.SimulationRunner,
        "describe_activity",
        classmethod(
            lambda _cls, simulation_id: {
                "simulation_id": simulation_id,
                "active": False,
                "runner_status": RunnerStatus.IDLE.value,
                "pid": None,
                "adopted": False,
                "stale": False,
            }
        ),
    )
    monkeypatch.setattr(
        simulation_api.SimulationRunner,
        "restart_simulation",
        classmethod(
            lambda _cls, **kwargs: (
                restarted.append(kwargs["simulation_id"]),
                run_state,
            )[1]
        ),
    )


def test_live_claim_still_blocks_restart_and_says_what_to_do(monkeypatch):
    """
    A live preparation owns the files a restart deletes, so the refusal stays.
    What changes is that the reply names the task to follow and marks itself
    preparation_live, so it cannot be confused with the dead-claim case.
    """
    _install_manager(monkeypatch, _simulation(status=SimulationStatus.PREPARING))
    restarted = []
    _install_idle_runner(monkeypatch, restarted)
    release, _thread = _install_live_claim("sim-1", task_id="task-inflight")

    app = Flask(__name__)
    try:
        with app.test_request_context(
            "/api/simulation/restart",
            method="POST",
            json={"simulation_id": "sim-1"},
        ):
            response, status = simulation_api.restart_simulation()
    finally:
        release.set()

    payload = response.get_json()
    assert status == 409
    assert payload["preparation_live"] is True
    assert payload["pending"] is True
    assert payload["task_id"] == "task-inflight"
    assert "task-inflight" in payload["error"]
    assert restarted == []


def test_dead_claim_lets_restart_break_the_deadlock(monkeypatch):
    """
    The escape. A simulation sitting in 'preparing' behind a claim whose thread
    is gone used to refuse /prepare and /restart alike; now the restart drops
    the claim, rescues the row and relaunches, and says which it did.
    """
    simulation = _simulation(status=SimulationStatus.PREPARING)
    saves = []
    _install_manager(monkeypatch, simulation, is_prepared=True, saves=saves)
    restarted = []
    _install_idle_runner(monkeypatch, restarted)
    _install_dead_claim("sim-1")

    app = Flask(__name__)
    with app.test_request_context(
        "/api/simulation/restart",
        method="POST",
        json={"simulation_id": "sim-1"},
    ):
        response = simulation_api.restart_simulation()

    payload = response.get_json()
    assert payload["success"] is True
    assert payload["data"]["cleared_dead_preparation"] is True
    assert payload["data"]["rescued_from_preparing"] is True
    assert restarted == ["sim-1"]
    # The row was rested at ready on the way through, not left in 'preparing'.
    assert saves == [SimulationStatus.READY]
    assert "sim-1" not in simulation_api._active_preparations


def test_dead_claim_restart_reports_a_rescue_that_cannot_reach_ready(monkeypatch):
    """
    Same escape, incomplete files: the row is rested at failed and the caller
    is told so. The point is that it is never again told to wait for a
    preparation that is not running.
    """
    simulation = _simulation(status=SimulationStatus.PREPARING)
    _install_manager(monkeypatch, simulation, is_prepared=False)
    restarted = []
    _install_idle_runner(monkeypatch, restarted)
    _install_dead_claim("sim-1")

    app = Flask(__name__)
    with app.test_request_context(
        "/api/simulation/restart",
        method="POST",
        json={"simulation_id": "sim-1"},
    ):
        response, status = simulation_api.restart_simulation()

    payload = response.get_json()
    assert status == 409
    assert payload["data"]["cleared_dead_preparation"] is True
    assert payload["data"]["status"] == SimulationStatus.FAILED.value
    assert "pending" not in payload
    assert restarted == []
