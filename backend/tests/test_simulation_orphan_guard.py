import pytest

from app.services import simulation_runner as module
from app.services.simulation_runner import SimulationRunner, SimulationRunState, RunnerStatus


@pytest.mark.parametrize('permission_denied', [False, True])
def test_stop_preserves_live_or_unverifiable_detached_run(monkeypatch, permission_denied):
    state = SimulationRunState(
        simulation_id='detached-test', runner_status=RunnerStatus.RUNNING,
        process_pid=12345,
    )
    saved = []
    monkeypatch.setattr(module, 'IS_WINDOWS', False)
    monkeypatch.setattr(SimulationRunner, '_processes', {})
    monkeypatch.setattr(SimulationRunner, 'get_run_state', classmethod(lambda cls, sid: state))
    monkeypatch.setattr(SimulationRunner, '_save_run_state', classmethod(lambda cls, state: saved.append(state)))

    def probe(pid, sig):
        assert (pid, sig) == (12345, 0)
        if permission_denied:
            raise PermissionError()

    monkeypatch.setattr(module.os, 'kill', probe)
    with pytest.raises(RuntimeError, match='preserv'):
        SimulationRunner.stop_simulation(state.simulation_id)

    assert state.runner_status == RunnerStatus.RUNNING
    assert not saved


@pytest.mark.parametrize('windows', [False, True])
def test_unowned_process_guard_does_not_signal_windows_processes(monkeypatch, windows):
    state = SimulationRunState(simulation_id='detached-test', process_pid=12345)
    monkeypatch.setattr(module, 'IS_WINDOWS', windows)
    monkeypatch.setattr(SimulationRunner, '_processes', {})

    def probe(pid, sig):
        assert not windows, 'Windows must never receive a signal-zero probe'
        assert (pid, sig) == (12345, 0)
        raise ProcessLookupError()

    monkeypatch.setattr(module.os, 'kill', probe)
    assert SimulationRunner._has_live_process(state.simulation_id, state) is windows
