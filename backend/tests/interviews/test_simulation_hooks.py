"""
Tests for SimulationManager lifecycle hooks (on_ready / on_completed).

NOTE ON SHAPE DIVERGENCE vs. original plan spec:
- SimulationState uses `simulation_id` (not `sim_id`)
- `status` is a SimulationStatus enum, not a plain string
- The COMPLETED transition lives in simulation_runner.py (SimulationRunner._monitor_simulation),
  not in simulation_manager.py.  The _notify_on_completed hook is registered on SimulationManager
  and the production insertion point for COMPLETED is documented in DONE_WITH_CONCERNS.

Hooks are stored on the class (C3 fix), so each test snapshots/restores the
registries via the autouse fixture to keep test isolation.
"""

import pytest

from app.services.simulation_manager import SimulationManager, SimulationState, SimulationStatus


@pytest.fixture(autouse=True)
def _isolate_class_hooks():
    saved_ready = list(SimulationManager._on_ready_hooks)
    saved_completed = list(SimulationManager._on_completed_hooks)
    try:
        yield
    finally:
        SimulationManager._on_ready_hooks[:] = saved_ready
        SimulationManager._on_completed_hooks[:] = saved_completed


def test_register_post_ready_hook_invoked():
    called = []
    mgr = SimulationManager()
    mgr.register_on_ready(lambda state: called.append(("ready", state.simulation_id)))
    state = SimulationState(
        simulation_id="abc",
        project_id="proj1",
        graph_id="graph1",
        status=SimulationStatus.READY,
    )
    mgr._notify_on_ready(state)
    assert called == [("ready", "abc")]


def test_register_post_completed_hook_invoked():
    called = []
    mgr = SimulationManager()
    mgr.register_on_completed(lambda state: called.append(("done", state.simulation_id)))
    state = SimulationState(
        simulation_id="abc",
        project_id="proj1",
        graph_id="graph1",
        status=SimulationStatus.COMPLETED,
    )
    mgr._notify_on_completed(state)
    assert called == [("done", "abc")]


def test_hooks_survive_across_instances():
    """C3: hook registries are class-level, so callbacks registered through the
    classmethod must still fire on a freshly constructed instance.  This is
    what makes the Flask per-request ``SimulationManager()`` pattern work
    after ``install_hooks(SimulationManager)`` runs at app startup.
    """
    called: list[str] = []

    # Register via the class — the production install_hooks(cls) path.
    SimulationManager.register_on_ready(lambda s: called.append(f"ready:{s.simulation_id}"))
    SimulationManager.register_on_completed(lambda s: called.append(f"done:{s.simulation_id}"))

    # New, independently-constructed instance must still see the hooks.
    fresh = SimulationManager()
    state = SimulationState(
        simulation_id="cross_instance",
        project_id="p",
        graph_id="g",
        status=SimulationStatus.READY,
    )
    fresh._notify_on_ready(state)
    state.status = SimulationStatus.COMPLETED
    fresh._notify_on_completed(state)

    assert "ready:cross_instance" in called
    assert "done:cross_instance" in called


def test_register_via_instance_also_lands_on_class():
    """Registering through an instance must populate the class registry too —
    backward-compatibility with code that calls ``manager.register_on_*``.
    """
    mgr1 = SimulationManager()
    mgr1.register_on_ready(lambda s: None)
    # A second, unrelated instance must see the hook.
    mgr2 = SimulationManager()
    assert len(SimulationManager._on_ready_hooks) >= 1
    assert SimulationManager._on_ready_hooks is mgr2.__class__._on_ready_hooks
