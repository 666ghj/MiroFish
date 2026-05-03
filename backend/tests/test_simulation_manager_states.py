import pytest
from backend.app.services.simulation_manager import SimulationStatus, SimulationState

def test_profiles_ready_status_exists():
    assert SimulationStatus.PROFILES_READY == "profiles_ready"

def test_configuring_status_exists():
    assert SimulationStatus.CONFIGURING == "configuring"

def test_simulation_state_has_parent_id():
    state = SimulationState(simulation_id="sim_x", project_id="p", graph_id="g")
    assert hasattr(state, 'parent_simulation_id')
    assert state.parent_simulation_id is None

def test_simulation_state_has_graph_id_simulation():
    state = SimulationState(simulation_id="sim_x", project_id="p", graph_id="g")
    assert hasattr(state, 'graph_id_simulation')
    assert state.graph_id_simulation is None

def test_to_dict_includes_new_fields():
    state = SimulationState(simulation_id="sim_x", project_id="p", graph_id="g")
    d = state.to_dict()
    assert 'parent_simulation_id' in d
    assert 'graph_id_simulation' in d
