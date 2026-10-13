import json
from pathlib import Path
from unittest.mock import Mock

from app.services.simulation_runner import SimulationRunner, RunnerStatus


def test_restart_archives_runtime_and_preserves_preparation(tmp_path, monkeypatch):
    monkeypatch.setattr(SimulationRunner, 'RUN_STATE_DIR', str(tmp_path))
    monkeypatch.setattr(SimulationRunner, '_run_states', {})
    sim = tmp_path / 'sim_archive'
    (sim / 'reddit').mkdir(parents=True)
    for filename in ['simulation_config.json', 'reddit_profiles.json', 'run_state.json',
                     'reddit_simulation.db', 'reddit_simulation.db-wal', 'simulation.log',
                     'reddit/actions.jsonl']:
        (sim / filename).write_text(filename)
    result = SimulationRunner.cleanup_simulation_logs('sim_archive')
    assert result['success']
    archive = Path(result['archive_path'])
    assert (archive / 'reddit/actions.jsonl').read_text() == 'reddit/actions.jsonl'
    assert (archive / 'reddit_simulation.db-wal').exists()
    assert not (sim / 'reddit/actions.jsonl').exists()
    assert not (sim / 'reddit_simulation.db').exists()
    assert (sim / 'simulation_config.json').exists()
    assert (sim / 'reddit_profiles.json').exists()


def test_failed_archive_does_not_remove_runtime_files(tmp_path, monkeypatch):
    import shutil
    monkeypatch.setattr(SimulationRunner, 'RUN_STATE_DIR', str(tmp_path))
    sim = tmp_path / 'sim_archive'
    sim.mkdir()
    (sim / 'run_state.json').write_text('original')
    monkeypatch.setattr(shutil, 'copy2', Mock(side_effect=OSError('disk full')))
    result = SimulationRunner.cleanup_simulation_logs('sim_archive')
    assert not result['success']
    assert (sim / 'run_state.json').read_text() == 'original'


def test_orphaned_running_state_exposes_interruption(tmp_path, monkeypatch):
    monkeypatch.setattr(SimulationRunner, 'RUN_STATE_DIR', str(tmp_path))
    monkeypatch.setattr(SimulationRunner, '_run_states', {})
    monkeypatch.setattr(SimulationRunner, '_processes', {})
    monkeypatch.setattr(SimulationRunner, '_sync_simulation_status', Mock())
    sim = tmp_path / 'sim_orphan'
    sim.mkdir()
    (sim / 'run_state.json').write_text(json.dumps({'runner_status': 'running', 'current_round': 4}))
    state = SimulationRunner.get_run_state('sim_orphan')
    assert state.runner_status == RunnerStatus.FAILED
    assert state.current_round == 4
    assert 'interrupted' in state.error.lower()


def test_surviving_orphan_cannot_be_archived_or_restarted(tmp_path, monkeypatch):
    import os
    import pytest
    monkeypatch.setattr(SimulationRunner, 'RUN_STATE_DIR', str(tmp_path))
    monkeypatch.setattr(SimulationRunner, '_run_states', {})
    monkeypatch.setattr(SimulationRunner, '_processes', {})
    monkeypatch.setattr(SimulationRunner, '_sync_simulation_status', Mock())
    sim = tmp_path / 'sim_orphan'
    sim.mkdir()
    (sim / 'run_state.json').write_text(json.dumps({'runner_status': 'running', 'process_pid': os.getpid()}))
    (sim / 'simulation_config.json').write_text('{}')
    result = SimulationRunner.cleanup_simulation_logs('sim_orphan')
    assert not result['success']
    assert (sim / 'run_state.json').exists()
    assert not (sim / 'attempts').exists()
    with pytest.raises(ValueError, match='still alive'):
        SimulationRunner.start_simulation('sim_orphan')
