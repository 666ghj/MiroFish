"""
SimulationManager 的持久化状态（state.json，run_state.json 的派生投影）测试：
原子写入、乐观并发控制（CAS）、以及"进程重启"（新建 SimulationManager 实例，
内存缓存为空）后从磁盘恢复的行为。
"""

import json

import pytest

from app.services.simulation_manager import SimulationManager, SimulationState, SimulationStatus
from app.utils.state_machine import ConcurrentModificationError


@pytest.fixture
def manager(tmp_path, monkeypatch):
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(tmp_path))
    return SimulationManager()


def _state(simulation_id="sim_durable1234", status=SimulationStatus.CREATED):
    return SimulationState(
        simulation_id=simulation_id,
        project_id="proj_test",
        graph_id="graph_test",
        status=status,
    )


class TestAtomicPersistence:
    def test_save_and_reload_round_trips(self, manager):
        state = _state()
        manager._save_simulation_state(state)

        reloaded = manager.get_simulation(state.simulation_id)
        assert reloaded.status == SimulationStatus.CREATED
        assert reloaded.revision == 1

    def test_revision_increments_on_each_save(self, manager):
        state = _state()
        manager._save_simulation_state(state)
        assert state.revision == 1

        state.status = SimulationStatus.PREPARING
        manager._save_simulation_state(state)
        assert state.revision == 2

    def test_raw_file_contains_revision(self, tmp_path, manager):
        state = _state()
        manager._save_simulation_state(state)

        state_file = tmp_path / state.simulation_id / "state.json"
        with open(state_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["revision"] == 1
        assert data["status"] == "created"


class TestOptimisticConcurrencyControl:
    def test_matching_expected_revision_succeeds(self, manager):
        state = _state()
        manager._save_simulation_state(state)

        state.status = SimulationStatus.PREPARING
        manager._save_simulation_state(state, expected_revision=1)
        assert state.revision == 2

    def test_stale_expected_revision_is_rejected(self, manager):
        state = _state()
        manager._save_simulation_state(state)  # revision -> 1

        # A concurrent writer advances the persisted state first.
        concurrent_state = manager._load_simulation_state(state.simulation_id)
        concurrent_state.status = SimulationStatus.READY
        # Bypass the in-memory cache read for the concurrent writer too, by
        # going through a second manager instance sharing the same directory.
        manager._simulations.pop(state.simulation_id, None)
        manager._save_simulation_state(concurrent_state)  # revision -> 2

        state.status = SimulationStatus.PREPARING
        with pytest.raises(ConcurrentModificationError):
            manager._save_simulation_state(state, expected_revision=1)

    def test_conflicting_cas_save_does_not_persist(self, manager):
        state = _state()
        manager._save_simulation_state(state)

        manager._simulations.pop(state.simulation_id, None)
        concurrent_state = manager._load_simulation_state(state.simulation_id)
        concurrent_state.status = SimulationStatus.READY
        manager._save_simulation_state(concurrent_state)

        state.status = SimulationStatus.PREPARING
        with pytest.raises(ConcurrentModificationError):
            manager._save_simulation_state(state, expected_revision=1)

        manager._simulations.pop(state.simulation_id, None)
        on_disk = manager._load_simulation_state(state.simulation_id)
        assert on_disk.revision == 2
        assert on_disk.status == SimulationStatus.READY


class TestProcessRestartRecovery:
    def test_state_survives_new_manager_instance(self, tmp_path, monkeypatch):
        monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(tmp_path))
        first = SimulationManager()
        state = _state()
        state.status = SimulationStatus.READY
        state.entities_count = 42
        first._save_simulation_state(state)

        # A fresh instance has no in-memory cache -- simulates a process restart.
        second = SimulationManager()
        recovered = second.get_simulation(state.simulation_id)
        assert recovered is not None
        assert recovered.status == SimulationStatus.READY
        assert recovered.entities_count == 42
        assert recovered.revision == 1
