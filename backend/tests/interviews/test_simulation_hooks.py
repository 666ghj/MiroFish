"""
Tests for SimulationManager lifecycle hooks (on_ready / on_completed).

NOTE ON SHAPE DIVERGENCE vs. original plan spec:
- SimulationState uses `simulation_id` (not `sim_id`)
- `status` is a SimulationStatus enum, not a plain string
- The COMPLETED transition lives in simulation_runner.py (SimulationRunner._monitor_simulation),
  not in simulation_manager.py.  The _notify_on_completed hook is registered on SimulationManager
  and the production insertion point for COMPLETED is documented in DONE_WITH_CONCERNS.
"""

from app.services.simulation_manager import SimulationManager, SimulationState, SimulationStatus


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
