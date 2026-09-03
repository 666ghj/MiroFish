"""
Regression cover for the two log-cleanup defects on /start and /restart.

Both were silent data corruption rather than a crash: the previous run's
twitter/actions.jsonl and reddit/actions.jsonl survived into the new run, and
the new monitor reads those files from byte 0 while the child appends. The
whole previous run is replayed - re-counted, its simulation_end events trip the
completion flags, and every old action is pushed to Zep a second time. Nothing
raises, so only an assertion on the cleanup call keeps these fixed.

1. POST /start accepted force=true and silently ignored it whenever the manager
   status was already READY, because the cleanup was nested inside
   `if state.status != READY`. READY is where a finished run rests, so that was
   the common case.
2. POST /restart never reached cleanup_simulation_logs at all.

Plus the guards added alongside the fixes: /restart refuses a LIVE run
server-side, and /start's force path deletes nothing when the start cannot
proceed anyway.
"""

from types import SimpleNamespace

import pytest
from flask import Flask

from app.api import simulation as simulation_api
from app.services.simulation_manager import SimulationStatus
from app.services.simulation_runner import (
    RunnerStatus,
    SimulationRunState,
    SimulationRunner,
)


def _ready_simulation(simulation_id="sim-1", status=SimulationStatus.READY):
    return SimpleNamespace(
        simulation_id=simulation_id,
        project_id="proj-1",
        graph_id="graph-1",
        status=status,
        error=None,
    )


def _install_manager(monkeypatch, simulation):
    """Serve one simulation state and swallow the state saves."""
    monkeypatch.setattr(
        simulation_api,
        "SimulationManager",
        lambda: SimpleNamespace(
            get_simulation=lambda _simulation_id: simulation,
            _save_simulation_state=lambda _state: None,
        ),
    )


def _install_idle_runner(monkeypatch, calls, run_state):
    """
    Make the runner look idle, and record the calls the routes make on it.

    get_run_state and ZepGraphMemoryManager.get_updater are left as the real
    describe_start_blocker sees them - both empty - so that predicate runs for
    real rather than being stubbed out.
    """
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
        "cleanup_simulation_logs",
        classmethod(
            lambda _cls, simulation_id: (
                calls.append(("cleanup", simulation_id)),
                {"success": True},
            )[1]
        ),
    )
    monkeypatch.setattr(
        simulation_api.SimulationRunner,
        "start_simulation",
        classmethod(
            lambda _cls, simulation_id, **_kwargs: (
                calls.append(("start", simulation_id)),
                run_state,
            )[1]
        ),
    )


def test_force_start_on_a_ready_simulation_clears_the_previous_logs(monkeypatch):
    """force=true must reach cleanup even though READY skips the prepared check."""
    simulation = _ready_simulation()
    calls = []
    run_state = SimulationRunState(
        simulation_id="sim-1", runner_status=RunnerStatus.STARTING
    )
    _install_manager(monkeypatch, simulation)
    _install_idle_runner(monkeypatch, calls, run_state)

    app = Flask(__name__)
    with app.test_request_context(
        "/api/simulation/start",
        method="POST",
        json={"simulation_id": "sim-1", "force": True},
    ):
        response = simulation_api.start_simulation()

    payload = response.get_json()
    assert payload["success"] is True
    assert payload["data"]["force_restarted"] is True
    # The logs were really deleted, and before the new run was launched.
    assert calls == [("cleanup", "sim-1"), ("start", "sim-1")]


def test_start_without_force_on_a_ready_simulation_keeps_the_logs(monkeypatch):
    """The control for the test above: no force, no deletion."""
    simulation = _ready_simulation()
    calls = []
    run_state = SimulationRunState(
        simulation_id="sim-1", runner_status=RunnerStatus.STARTING
    )
    _install_manager(monkeypatch, simulation)
    _install_idle_runner(monkeypatch, calls, run_state)

    app = Flask(__name__)
    with app.test_request_context(
        "/api/simulation/start",
        method="POST",
        json={"simulation_id": "sim-1"},
    ):
        response = simulation_api.start_simulation()

    payload = response.get_json()
    assert payload["success"] is True
    assert payload["data"]["force_restarted"] is False
    assert calls == [("start", "sim-1")]


@pytest.mark.parametrize(
    "status",
    [SimulationStatus.COMPLETED, SimulationStatus.STOPPED, SimulationStatus.FAILED],
)
def test_force_start_clears_the_logs_for_the_other_resting_statuses(
    monkeypatch, status
):
    """Cleanup is not conditional on the manager status in either direction."""
    simulation = _ready_simulation(status=status)
    calls = []
    run_state = SimulationRunState(
        simulation_id="sim-1", runner_status=RunnerStatus.STARTING
    )
    _install_manager(monkeypatch, simulation)
    _install_idle_runner(monkeypatch, calls, run_state)
    monkeypatch.setattr(
        simulation_api,
        "_check_simulation_prepared",
        lambda _simulation_id: (True, {}),
    )

    app = Flask(__name__)
    with app.test_request_context(
        "/api/simulation/start",
        method="POST",
        json={"simulation_id": "sim-1", "force": True},
    ):
        response = simulation_api.start_simulation()

    assert response.get_json()["data"]["force_restarted"] is True
    assert calls == [("cleanup", "sim-1"), ("start", "sim-1")]


def test_force_start_deletes_nothing_when_the_start_cannot_proceed(monkeypatch):
    """
    A run resting at STARTING walks past the finalization guard and is refused
    by the runner. The force path must settle that BEFORE it deletes anything,
    or the caller loses the previous run and gets no new one.
    """
    simulation = _ready_simulation()
    calls = []
    run_state = SimulationRunState(
        simulation_id="sim-1", runner_status=RunnerStatus.STARTING
    )
    _install_manager(monkeypatch, simulation)
    _install_idle_runner(monkeypatch, calls, run_state)
    # Re-point get_run_state at a run the runner would refuse. describe_start_blocker
    # stays real, so this exercises the predicate the fix added.
    monkeypatch.setattr(
        simulation_api.SimulationRunner,
        "get_run_state",
        classmethod(
            lambda _cls, _simulation_id: SimpleNamespace(
                runner_status=RunnerStatus.STARTING
            )
        ),
    )

    app = Flask(__name__)
    with app.test_request_context(
        "/api/simulation/start",
        method="POST",
        json={"simulation_id": "sim-1", "force": True},
    ):
        response, status = simulation_api.start_simulation()

    assert status == 409
    assert "Nothing was deleted" in response.get_json()["error"]
    assert calls == []


def test_restart_api_reaches_cleanup_before_launching_the_new_run(monkeypatch):
    """
    End to end through the route: POST /restart must clear the previous run's
    logs. The route delegates to SimulationRunner.restart_simulation, which is
    left real here - only the process-level calls underneath it are stubbed -
    so the assertion covers the delegation and the cleanup together.
    """
    simulation = _ready_simulation()
    calls = []
    run_state = SimulationRunState(
        simulation_id="sim-1", runner_status=RunnerStatus.STARTING
    )
    _install_manager(monkeypatch, simulation)
    _install_idle_runner(monkeypatch, calls, run_state)
    monkeypatch.setattr(
        simulation_api.SimulationRunner,
        "describe_activity",
        classmethod(
            lambda _cls, simulation_id: {
                "simulation_id": simulation_id,
                "active": False,
                "runner_status": RunnerStatus.COMPLETED.value,
                "pid": None,
                "adopted": False,
                "stale": False,
            }
        ),
    )
    monkeypatch.setattr(
        SimulationRunner,
        "reap_simulation",
        classmethod(lambda _cls, _simulation_id: None),
    )
    monkeypatch.setattr(
        SimulationRunner,
        "release_simulation",
        classmethod(lambda _cls, _simulation_id: None),
    )
    SimulationRunner._monitor_threads.pop("sim-1", None)

    app = Flask(__name__)
    with app.test_request_context(
        "/api/simulation/restart",
        method="POST",
        json={"simulation_id": "sim-1"},
    ):
        response = simulation_api.restart_simulation()

    payload = response.get_json()
    assert payload["success"] is True
    assert payload["data"]["restarted"] is True
    assert calls == [("cleanup", "sim-1"), ("start", "sim-1")]


def test_restart_refuses_a_live_run_without_force(monkeypatch):
    """
    The refusal has to live in the route, not only in the Vue menu's disabled
    item - a curl reaches the route directly, and everything past that point is
    destructive.
    """
    simulation = _ready_simulation()
    calls = []
    run_state = SimulationRunState(
        simulation_id="sim-1", runner_status=RunnerStatus.STARTING
    )
    _install_manager(monkeypatch, simulation)
    _install_idle_runner(monkeypatch, calls, run_state)
    monkeypatch.setattr(
        simulation_api.SimulationRunner,
        "describe_activity",
        classmethod(
            lambda _cls, simulation_id: {
                "simulation_id": simulation_id,
                "active": True,
                "runner_status": RunnerStatus.RUNNING.value,
                "pid": 4321,
                "adopted": False,
                "stale": False,
            }
        ),
    )
    restarted = []
    monkeypatch.setattr(
        simulation_api.SimulationRunner,
        "restart_simulation",
        classmethod(
            lambda _cls, **kwargs: restarted.append(kwargs) or run_state
        ),
    )

    app = Flask(__name__)
    with app.test_request_context(
        "/api/simulation/restart",
        method="POST",
        json={"simulation_id": "sim-1"},
    ):
        response, status = simulation_api.restart_simulation()

    assert status == 409
    assert response.get_json()["live"] is True
    assert restarted == []
    assert calls == []


def test_restart_of_a_stale_run_is_still_allowed(monkeypatch):
    """
    A stale row - saved state claims a run whose process is gone - must stay
    restartable. /restart is the documented way out of that state, which is why
    it asks _run_is_live rather than /start's _run_needs_finalization.
    """
    simulation = _ready_simulation()
    calls = []
    run_state = SimulationRunState(
        simulation_id="sim-1", runner_status=RunnerStatus.STARTING
    )
    _install_manager(monkeypatch, simulation)
    _install_idle_runner(monkeypatch, calls, run_state)
    monkeypatch.setattr(
        simulation_api.SimulationRunner,
        "describe_activity",
        classmethod(
            lambda _cls, simulation_id: {
                "simulation_id": simulation_id,
                "active": False,
                "runner_status": RunnerStatus.RUNNING.value,
                "pid": None,
                "adopted": False,
                "stale": True,
            }
        ),
    )
    restarted = []
    monkeypatch.setattr(
        simulation_api.SimulationRunner,
        "restart_simulation",
        classmethod(
            lambda _cls, **kwargs: restarted.append(kwargs["simulation_id"])
            or run_state
        ),
    )

    app = Flask(__name__)
    with app.test_request_context(
        "/api/simulation/restart",
        method="POST",
        json={"simulation_id": "sim-1"},
    ):
        response = simulation_api.restart_simulation()

    assert response.get_json()["success"] is True
    assert restarted == ["sim-1"]


def test_runner_restart_cleans_the_logs_before_starting(monkeypatch):
    """
    The unit underneath the route: restart_simulation clears the logs
    unconditionally, and only after the previous child is reaped and its
    resources released - clearing earlier would delete actions.jsonl out from
    under a child still appending to it.
    """
    simulation_id = "sim-runner-restart"
    order = []
    run_state = SimulationRunState(
        simulation_id=simulation_id, runner_status=RunnerStatus.STARTING
    )

    monkeypatch.setattr(
        SimulationRunner,
        "reap_simulation",
        classmethod(lambda _cls, _sid: order.append("reap") or None),
    )
    monkeypatch.setattr(
        SimulationRunner,
        "release_simulation",
        classmethod(lambda _cls, _sid: order.append("release")),
    )
    monkeypatch.setattr(
        SimulationRunner,
        "cleanup_simulation_logs",
        classmethod(
            lambda _cls, _sid: (order.append("cleanup"), {"success": True})[1]
        ),
    )
    monkeypatch.setattr(
        SimulationRunner,
        "start_simulation",
        classmethod(
            lambda _cls, **_kwargs: (order.append("start"), run_state)[1]
        ),
    )
    SimulationRunner._monitor_threads.pop(simulation_id, None)

    result = SimulationRunner.restart_simulation(simulation_id)

    assert result is run_state
    assert order == ["reap", "release", "cleanup", "start"]


def test_runner_restart_does_not_start_when_the_cleanup_fails(monkeypatch):
    """A restart that could not clear the logs must not launch a new run on top."""
    simulation_id = "sim-runner-restart-fail"
    started = []

    monkeypatch.setattr(
        SimulationRunner,
        "reap_simulation",
        classmethod(lambda _cls, _sid: None),
    )
    monkeypatch.setattr(
        SimulationRunner,
        "release_simulation",
        classmethod(lambda _cls, _sid: None),
    )
    monkeypatch.setattr(
        SimulationRunner,
        "cleanup_simulation_logs",
        classmethod(
            lambda _cls, _sid: {"success": False, "errors": ["actions.jsonl busy"]}
        ),
    )
    monkeypatch.setattr(
        SimulationRunner,
        "start_simulation",
        classmethod(lambda _cls, **kwargs: started.append(kwargs)),
    )
    SimulationRunner._monitor_threads.pop(simulation_id, None)

    with pytest.raises(RuntimeError, match="actions.jsonl busy"):
        SimulationRunner.restart_simulation(simulation_id)

    assert started == []
