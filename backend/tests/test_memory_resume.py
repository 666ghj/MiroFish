import json
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from app.config import Config
from app.services import zep_graph_memory_updater as module
from app.services.zep_graph_memory_updater import ZepGraphMemoryUpdater, ZepGraphMemoryManager


def local_updater(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, 'GRAPH_PROVIDER', 'graphiti')
    monkeypatch.setattr(Config, 'OASIS_SIMULATION_DATA_DIR', str(tmp_path))
    client = SimpleNamespace(provider='graphiti', graph=SimpleNamespace(
        resume_simulation=Mock(return_value=SimpleNamespace(episode_uuids=['failed', 'canceled'])),
        episode=SimpleNamespace(get=Mock(side_effect=RuntimeError('Codex request timed out')))))
    monkeypatch.setattr(module, 'get_zep_client', lambda *a: client)
    monkeypatch.setattr(ZepGraphMemoryManager, '_updaters', {})
    updater = ZepGraphMemoryUpdater('g1', simulation_id='sim1')
    updater._pending_episode_uuids = ['done', 'failed', 'canceled']
    return updater, client


def test_failed_ingestion_is_checkpointed_and_explicit_resume_requeues(tmp_path, monkeypatch):
    updater, client = local_updater(tmp_path, monkeypatch)
    with pytest.raises(RuntimeError, match='timed out'):
        updater.stop()
    checkpoint = tmp_path / 'sim1' / 'ingestion_checkpoint.json'
    assert set(json.loads(checkpoint.read_text())['episode_uuids']) == {'done', 'failed', 'canceled'}
    ZepGraphMemoryManager._updaters['sim1'] = updater
    ZepGraphMemoryManager.resume_updater('sim1')
    assert updater._pending_episode_uuids == ['failed', 'canceled']
    client.graph.episode.get.side_effect = None
    client.graph.episode.get.return_value = SimpleNamespace(processed=True)
    ZepGraphMemoryManager.stop_updater('sim1')
    assert ZepGraphMemoryManager.get_updater('sim1') is None
    assert json.loads(checkpoint.read_text())['episode_uuids'] == []


def test_resume_restores_checkpoint_without_resending_activity(tmp_path, monkeypatch):
    updater, client = local_updater(tmp_path, monkeypatch)
    with pytest.raises(RuntimeError): updater.stop()
    assert ZepGraphMemoryManager.resume_updater('sim1') is True
    restored = ZepGraphMemoryManager.get_updater('sim1')
    assert restored.graph_id == 'g1'
    assert restored._pending_episode_uuids == ['failed', 'canceled']
    assert restored._running is False


def test_ambiguous_unsent_batches_cannot_publish_complete_checkpoint(tmp_path, monkeypatch):
    updater, client = local_updater(tmp_path, monkeypatch)
    updater._failed_batches = [{'error': 'uncertain write'}]
    with pytest.raises(RuntimeError, match='batch'):
        updater.stop()
    assert not (tmp_path / 'sim1' / 'ingestion_checkpoint.json').exists()


def test_runner_can_finalize_saved_ingestion_after_restart_without_new_rounds(tmp_path, monkeypatch):
    from app.services.simulation_runner import SimulationRunner, SimulationRunState, RunnerStatus
    updater, client = local_updater(tmp_path, monkeypatch)
    with pytest.raises(RuntimeError): updater.stop()
    monkeypatch.setattr(SimulationRunner, 'RUN_STATE_DIR', str(tmp_path))
    for name in ('_run_states', '_processes', '_monitor_threads', '_graph_memory_enabled'):
        monkeypatch.setattr(SimulationRunner, name, {})
    monkeypatch.setattr(SimulationRunner, '_sync_simulation_status', Mock())
    state = SimulationRunState('sim1', runner_status=RunnerStatus.FAILED, current_round=37, total_rounds=336,
                               stop_requested=True, error='Graph ingestion failed')
    SimulationRunner._save_run_state(state)
    client.graph.episode.get.side_effect = None
    client.graph.episode.get.return_value = SimpleNamespace(processed=True)
    result = SimulationRunner.stop_simulation('sim1')
    assert result.runner_status == RunnerStatus.STOPPED
    assert result.current_round == 37
    assert result.total_rounds == 336
    assert result.error is None
    assert not SimulationRunner._processes
    assert ZepGraphMemoryManager.get_updater('sim1') is None


def test_failed_automatic_finalization_recovers_saving_even_if_stop_flag_was_false(tmp_path, monkeypatch):
    from app.services.simulation_runner import SimulationRunner, SimulationRunState, RunnerStatus
    updater, client = local_updater(tmp_path, monkeypatch)
    with pytest.raises(RuntimeError): updater.stop()
    monkeypatch.setattr(SimulationRunner, 'RUN_STATE_DIR', str(tmp_path))
    state = SimulationRunState('sim1', runner_status=RunnerStatus.FAILED, stop_requested=False)
    # Simulate an older saved state that explicitly includes false.
    path = tmp_path / 'sim1' / 'run_state.json'
    path.write_text(json.dumps(state.to_dict()))
    assert SimulationRunner._load_run_state('sim1').stop_requested is True
    SimulationRunner._save_run_state(state)
    assert state.stop_requested is True


def test_async_stop_after_restart_cannot_hide_unjournaled_failed_upload(tmp_path, monkeypatch):
    from app.services.simulation_runner import SimulationRunner, SimulationRunState, RunnerStatus
    updater, client = local_updater(tmp_path, monkeypatch)
    monkeypatch.setattr(SimulationRunner, 'RUN_STATE_DIR', str(tmp_path))
    for name in ('_run_states', '_processes', '_monitor_threads', '_graph_memory_enabled', '_stop_threads'):
        monkeypatch.setattr(SimulationRunner, name, {})
    state = SimulationRunState('sim1', runner_status=RunnerStatus.FAILED,
                               error='Activity upload failed before extraction')
    SimulationRunner._save_run_state(state)
    with pytest.raises(ValueError, match='checkpoint|saving'):
        SimulationRunner.request_stop('sim1')
    assert state.runner_status == RunnerStatus.FAILED
    assert not SimulationRunner._stop_threads
