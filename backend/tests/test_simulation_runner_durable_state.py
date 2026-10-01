"""
SimulationRunner 的持久化运行状态机测试：合法/非法转换、乐观并发控制
（CAS）、以及"进程重启"后从磁盘恢复的行为。这些测试直接调用真实的
_save_run_state / _load_run_state（不像 test_zep_simulation_barrier.py
那样 mock 掉它们），专门覆盖 TASK 4 新增的持久化层本身。
"""

import json

import pytest

from app.services.simulation_runner import RunnerStatus, SimulationRunState, SimulationRunner
from app.utils.state_machine import ConcurrentModificationError, InvalidStateTransitionError


@pytest.fixture(autouse=True)
def _isolated_run_state_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(SimulationRunner, "_run_states", {})
    yield


def _state(simulation_id="sim_durable1234", status=RunnerStatus.STARTING):
    return SimulationRunState(simulation_id=simulation_id, runner_status=status)


class TestTransitionValidation:
    def test_first_save_of_any_status_is_allowed(self):
        state = _state(status=RunnerStatus.STARTING)
        SimulationRunner._save_run_state(state)
        assert state.revision == 1

    def test_valid_transition_chain_succeeds(self):
        sim_id = "sim_chain12345"
        state = _state(sim_id, RunnerStatus.STARTING)
        SimulationRunner._save_run_state(state)

        state.runner_status = RunnerStatus.RUNNING
        SimulationRunner._save_run_state(state)

        state.runner_status = RunnerStatus.STOPPING
        SimulationRunner._save_run_state(state)

        state.runner_status = RunnerStatus.STOPPED
        SimulationRunner._save_run_state(state)

        assert state.revision == 4
        assert SimulationRunner.get_run_state(sim_id).runner_status == RunnerStatus.STOPPED

    def test_invalid_transition_is_rejected(self):
        sim_id = "sim_invalid1234"
        state = _state(sim_id, RunnerStatus.STARTING)
        SimulationRunner._save_run_state(state)

        # STARTING -> STOPPED is not a legal direct transition.
        state.runner_status = RunnerStatus.STOPPED
        with pytest.raises(InvalidStateTransitionError):
            SimulationRunner._save_run_state(state)

    def test_invalid_transition_from_terminal_state_is_rejected(self):
        sim_id = "sim_terminal1234"
        state = _state(sim_id, RunnerStatus.STARTING)
        SimulationRunner._save_run_state(state)
        state.runner_status = RunnerStatus.RUNNING
        SimulationRunner._save_run_state(state)
        state.runner_status = RunnerStatus.COMPLETED
        SimulationRunner._save_run_state(state)

        # A completed run cannot jump straight back into RUNNING.
        state.runner_status = RunnerStatus.RUNNING
        with pytest.raises(InvalidStateTransitionError):
            SimulationRunner._save_run_state(state)

    def test_restart_from_failed_is_allowed(self):
        sim_id = "sim_restart1234"
        state = _state(sim_id, RunnerStatus.STARTING)
        SimulationRunner._save_run_state(state)
        state.runner_status = RunnerStatus.FAILED
        SimulationRunner._save_run_state(state)

        # A fresh SimulationRunState (as produced by start_simulation on
        # retry) is allowed to begin again at STARTING.
        fresh = _state(sim_id, RunnerStatus.STARTING)
        SimulationRunner._save_run_state(fresh)
        assert fresh.revision == 3

    def test_invalid_transition_does_not_persist(self):
        sim_id = "sim_norewrite123"
        state = _state(sim_id, RunnerStatus.STARTING)
        SimulationRunner._save_run_state(state)

        bad_state = _state(sim_id, RunnerStatus.STOPPED)
        with pytest.raises(InvalidStateTransitionError):
            SimulationRunner._save_run_state(bad_state)

        # The on-disk state must still be the last legally-saved one.
        reloaded = SimulationRunner._load_run_state(sim_id)
        assert reloaded.runner_status == RunnerStatus.STARTING
        assert reloaded.revision == 1


class TestOptimisticConcurrencyControl:
    def test_revision_increments_on_each_save(self):
        sim_id = "sim_revcount1234"
        state = _state(sim_id, RunnerStatus.STARTING)
        SimulationRunner._save_run_state(state)
        assert state.revision == 1

        state.runner_status = RunnerStatus.RUNNING
        SimulationRunner._save_run_state(state)
        assert state.revision == 2

    def test_matching_expected_revision_succeeds(self):
        sim_id = "sim_castrue1234"
        state = _state(sim_id, RunnerStatus.STARTING)
        SimulationRunner._save_run_state(state)

        state.runner_status = RunnerStatus.RUNNING
        SimulationRunner._save_run_state(state, expected_revision=1)
        assert state.revision == 2

    def test_stale_expected_revision_is_rejected(self):
        sim_id = "sim_casstale1234"
        state = _state(sim_id, RunnerStatus.STARTING)
        SimulationRunner._save_run_state(state)  # revision -> 1

        # Simulate a concurrent writer advancing the persisted state first.
        concurrent_state = SimulationRunner._load_run_state(sim_id)
        concurrent_state.runner_status = RunnerStatus.RUNNING
        SimulationRunner._save_run_state(concurrent_state)  # revision -> 2

        # The original caller still thinks it's at revision 1.
        state.runner_status = RunnerStatus.RUNNING
        with pytest.raises(ConcurrentModificationError):
            SimulationRunner._save_run_state(state, expected_revision=1)

    def test_conflicting_cas_save_does_not_persist(self, tmp_path):
        sim_id = "sim_casnowrite12"
        state = _state(sim_id, RunnerStatus.STARTING)
        SimulationRunner._save_run_state(state)

        concurrent_state = SimulationRunner._load_run_state(sim_id)
        concurrent_state.runner_status = RunnerStatus.RUNNING
        SimulationRunner._save_run_state(concurrent_state)

        state.runner_status = RunnerStatus.RUNNING
        with pytest.raises(ConcurrentModificationError):
            SimulationRunner._save_run_state(state, expected_revision=1)

        on_disk = SimulationRunner._load_run_state(sim_id)
        assert on_disk.revision == 2
        assert on_disk.runner_status == RunnerStatus.RUNNING


class TestProcessRestartRecovery:
    def test_state_survives_cache_clear(self, monkeypatch):
        sim_id = "sim_recover12345"
        state = _state(sim_id, RunnerStatus.STARTING)
        SimulationRunner._save_run_state(state)
        state.runner_status = RunnerStatus.RUNNING
        state.current_round = 7
        SimulationRunner._save_run_state(state)

        # Simulate a process restart: the in-memory cache is gone, only the
        # file on disk survives.
        monkeypatch.setattr(SimulationRunner, "_run_states", {})

        recovered = SimulationRunner.get_run_state(sim_id)
        assert recovered is not None
        assert recovered.runner_status == RunnerStatus.RUNNING
        assert recovered.current_round == 7
        assert recovered.revision == 2

    def test_transition_validation_continues_correctly_after_restart(self, monkeypatch):
        sim_id = "sim_recover_tv12"
        state = _state(sim_id, RunnerStatus.STARTING)
        SimulationRunner._save_run_state(state)
        state.runner_status = RunnerStatus.RUNNING
        SimulationRunner._save_run_state(state)

        monkeypatch.setattr(SimulationRunner, "_run_states", {})

        recovered = SimulationRunner.get_run_state(sim_id)
        recovered.runner_status = RunnerStatus.STOPPING
        SimulationRunner._save_run_state(recovered)  # legal: RUNNING -> STOPPING
        assert recovered.revision == 3

        recovered.runner_status = RunnerStatus.RUNNING
        with pytest.raises(InvalidStateTransitionError):
            SimulationRunner._save_run_state(recovered)  # STOPPING -> RUNNING illegal


def test_raw_file_contains_expected_shape(tmp_path):
    sim_id = "sim_rawshape1234"
    state = _state(sim_id, RunnerStatus.STARTING)
    SimulationRunner._save_run_state(state)

    state_file = tmp_path / sim_id / "run_state.json"
    with open(state_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["runner_status"] == "starting"
    assert data["revision"] == 1
