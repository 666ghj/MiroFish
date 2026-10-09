"""History limits must select recent simulations, not filesystem directory order."""
from app.services import simulation_manager as module
from app.services.simulation_manager import SimulationManager, SimulationState


def test_latest_simulation_is_in_default_history_window(tmp_path, monkeypatch):
    monkeypatch.setattr(SimulationManager, 'SIMULATION_DATA_DIR', str(tmp_path))
    manager = SimulationManager()
    ids = []
    for day in range(1, 22):
        simulation_id = f'sim_{day:02}'
        ids.append(simulation_id)
        manager._save_simulation_state(SimulationState(
            simulation_id=simulation_id, project_id='project', graph_id='graph',
            created_at=f'2026-01-{day:02}T12:00:00', updated_at=f'2026-01-{day:02}T12:00:00'))
    # Filesystem iteration order is explicitly not an API contract.
    monkeypatch.setattr(module.os, 'listdir', lambda _: ids)
    first = [s.simulation_id for s in manager.list_simulations()[:20]]
    monkeypatch.setattr(module.os, 'listdir', lambda _: list(reversed(ids)))
    second = [s.simulation_id for s in manager.list_simulations()[:20]]
    assert first == second
    assert first[0] == 'sim_21'
    assert 'sim_01' not in first


def test_order_is_stable_for_ties_and_project_filter(tmp_path, monkeypatch):
    monkeypatch.setattr(SimulationManager, 'SIMULATION_DATA_DIR', str(tmp_path))
    manager = SimulationManager()
    for simulation_id, project in [('sim_b', 'selected'), ('sim_z', 'other'), ('sim_a', 'selected')]:
        manager._save_simulation_state(SimulationState(
            simulation_id=simulation_id, project_id=project, graph_id='graph',
            created_at='2026-01-01T12:00:00', updated_at='2026-01-01T12:00:00'))
    monkeypatch.setattr(module.os, 'listdir', lambda _: ['sim_a', 'sim_z', 'sim_b'])
    first = [s.simulation_id for s in manager.list_simulations(project_id='selected')]
    monkeypatch.setattr(module.os, 'listdir', lambda _: ['sim_b', 'sim_z', 'sim_a'])
    assert first == [s.simulation_id for s in manager.list_simulations(project_id='selected')]
    assert set(first) == {'sim_a', 'sim_b'}
