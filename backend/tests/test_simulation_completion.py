import json
from types import SimpleNamespace

import pytest

from app.services import simulation_runner as module
from app.services.simulation_runner import SimulationRunner as Runner, SimulationRunState, RunnerStatus


@pytest.fixture
def completed_rounds(monkeypatch, tmp_path):
    sid = 'finished-rounds'
    folder = tmp_path / sid
    for platform in ('twitter', 'reddit'):
        (folder / platform).mkdir(parents=True)
        (folder / platform / 'actions.jsonl').write_text(
            json.dumps({'event_type': 'simulation_end', 'total_rounds': 40}) + '\n'
        )
    state = SimulationRunState(
        simulation_id=sid, runner_status=RunnerStatus.RUNNING,
        twitter_completed=True, reddit_completed=True, process_pid=12345,
    )
    saved = []
    monkeypatch.setattr(Runner, 'RUN_STATE_DIR', str(tmp_path))
    for name in ('_processes', '_run_states', '_graph_memory_enabled', '_monitor_threads', '_stdout_files', '_stderr_files', '_action_queues'):
        monkeypatch.setattr(Runner, name, {})
    monkeypatch.setattr(Runner, '_manual_stop_requests', set())
    monkeypatch.setattr(Runner, '_cleanup_done', False)
    monkeypatch.setattr(Runner, 'get_run_state', classmethod(lambda cls, sim_id: state))
    monkeypatch.setattr(Runner, '_save_run_state', classmethod(lambda cls, value: saved.append(value.runner_status)))
    monkeypatch.setattr(Runner, '_sync_simulation_status', classmethod(lambda cls, *args: None))
    monkeypatch.setattr(module.ZepGraphMemoryManager, 'get_updater', classmethod(lambda cls, sid: None))
    return state, saved, folder


def test_completes_after_drain_while_interview_process_remains_alive(monkeypatch, completed_rounds):
    state, saved, _ = completed_rounds
    process = SimpleNamespace(poll=lambda: None)
    Runner._processes[state.simulation_id] = process
    Runner._graph_memory_enabled[state.simulation_id] = True
    drains = []

    def drain(cls, sid):
        assert state.runner_status == RunnerStatus.STOPPING
        assert state.completed_at is None
        assert Runner._processes[sid].poll() is None
        drains.append(sid)

    monkeypatch.setattr(module.ZepGraphMemoryManager, 'stop_updater', classmethod(drain))
    assert Runner._finalize_completed_simulation(state)
    assert saved == [RunnerStatus.STOPPING, RunnerStatus.COMPLETED]
    assert state.completed_at and state.error is None
    assert Runner._processes[state.simulation_id] is process
    assert state.simulation_id not in Runner._graph_memory_enabled
    assert not Runner._finalize_completed_simulation(state)
    assert drains == [state.simulation_id]


@pytest.mark.parametrize('incomplete', ['twitter', 'reddit'])
def test_waits_for_every_enabled_platform(completed_rounds, incomplete):
    state, saved, _ = completed_rounds
    setattr(state, incomplete + '_completed', False)
    assert not Runner._finalize_completed_simulation(state)
    assert saved == []
    assert state.runner_status == RunnerStatus.RUNNING


def test_drain_failure_retains_ingestion_barrier(monkeypatch, completed_rounds):
    state, saved, _ = completed_rounds
    Runner._graph_memory_enabled[state.simulation_id] = True
    updater = object()
    monkeypatch.setattr(module.ZepGraphMemoryManager, 'get_updater', classmethod(lambda cls, sid: updater))

    def fail(cls, sid):
        raise TimeoutError('one episode is pending')

    monkeypatch.setattr(module.ZepGraphMemoryManager, 'stop_updater', classmethod(fail))
    assert not Runner._finalize_completed_simulation(state)
    assert state.runner_status == RunnerStatus.FAILED
    assert 'one episode is pending' in state.error
    assert Runner._graph_memory_enabled[state.simulation_id]
    assert saved == [RunnerStatus.STOPPING, RunnerStatus.FAILED]
    assert not Runner._finalize_completed_simulation(state)


def test_manual_stop_owns_finalization(completed_rounds):
    state, saved, _ = completed_rounds
    Runner._manual_stop_requests.add(state.simulation_id)
    assert not Runner._finalize_completed_simulation(state)
    assert not saved


def test_monitor_finishes_before_process_exit_and_preserves_result_after_exit(monkeypatch, completed_rounds):
    state, saved, _ = completed_rounds
    state.twitter_completed = state.reddit_completed = False
    polls = iter([None, 7])  # A later interview-process failure does not undo results.
    Runner._processes[state.simulation_id] = SimpleNamespace(poll=lambda: next(polls), returncode=7)
    monkeypatch.setattr(module.time, 'sleep', lambda _: None)
    Runner._monitor_simulation(state.simulation_id)
    assert state.runner_status == RunnerStatus.COMPLETED
    assert RunnerStatus.COMPLETED in saved
    assert state.error is None


def test_shutdown_closes_idle_environment_without_downgrading_completion(monkeypatch, completed_rounds):
    state, saved, _ = completed_rounds
    state.runner_status = RunnerStatus.COMPLETED
    process = SimpleNamespace(poll=lambda: None)
    Runner._processes[state.simulation_id] = process
    stopped = []
    monkeypatch.setattr(module.ZepGraphMemoryManager, 'get_simulation_ids', classmethod(lambda cls: []))
    monkeypatch.setattr(Runner, '_terminate_process', classmethod(lambda cls, proc, sid, **kwargs: stopped.append(proc)))
    Runner.cleanup_all_simulations()
    assert stopped == [process]
    assert state.runner_status == RunnerStatus.COMPLETED
    assert not saved


def test_cleanup_cannot_delete_database_while_completed_environment_is_alive(completed_rounds):
    state, _, folder = completed_rounds
    state.runner_status = RunnerStatus.COMPLETED
    database = folder / 'twitter_simulation.db'
    database.write_bytes(b'paid simulation results')
    Runner._processes[state.simulation_id] = SimpleNamespace(poll=lambda: None)
    result = Runner.cleanup_simulation_logs(state.simulation_id)
    assert result['success'] is False
    assert database.read_bytes() == b'paid simulation results'


def test_start_cannot_overwrite_a_completed_live_environment(completed_rounds):
    state, saved, folder = completed_rounds
    state.runner_status = RunnerStatus.COMPLETED
    (folder / 'simulation_config.json').write_text('{}')
    Runner._processes[state.simulation_id] = SimpleNamespace(poll=lambda: None)

    with pytest.raises(ValueError):
        Runner.start_simulation(state.simulation_id)

    assert not saved
    assert state.runner_status == RunnerStatus.COMPLETED
