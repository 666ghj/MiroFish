import json
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services import simulation_runner as module
from app.services.simulation_runner import SimulationRunner, SimulationRunState, RunnerStatus


@pytest.mark.parametrize('script', ['run_parallel_simulation.py', 'run_twitter_simulation.py', 'run_reddit_simulation.py'])
@pytest.mark.parametrize('hours,minutes,expected', [(0.1, 60, 1), (1.5, 30, 3), (73, 60, 73)])
def test_script_round_budget_is_positive_integer(script, hours, minutes, expected):
    # Execute the real budget expressions without importing OASIS or invoking AI.
    tree = ast.parse((Path(__file__).parents[1] / 'scripts' / script).read_text())
    budgets = [node.value for node in ast.walk(tree) if isinstance(node, ast.Assign)
               and any(isinstance(target, ast.Name) and target.id in {'total_rounds', 'config_total_rounds'}
                       for target in node.targets)
               and any(isinstance(part, ast.Name) and part.id == 'total_hours' for part in ast.walk(node.value))]
    assert budgets
    for expression in budgets:
        result = eval(compile(ast.Expression(expression), script, 'eval'),
                      {'total_hours': hours, 'minutes_per_round': minutes})
        assert result == expected
        assert isinstance(result, int)


@pytest.fixture
def runner(tmp_path, monkeypatch):
    monkeypatch.setattr(SimulationRunner, 'RUN_STATE_DIR', str(tmp_path))
    for name in ('_run_states', '_processes', '_monitor_threads', '_action_queues',
                 '_stdout_files', '_stderr_files', '_graph_memory_enabled'):
        monkeypatch.setattr(SimulationRunner, name, {})
    monkeypatch.setattr(SimulationRunner, '_manual_stop_requests', set())
    monkeypatch.setattr(SimulationRunner, '_sync_simulation_status', Mock())
    monkeypatch.setattr(module.ZepGraphMemoryManager, 'get_updater', lambda _: None)
    return tmp_path


@pytest.mark.parametrize('effort,expected', [('quick', 19), ('moderate', 37), ('full', 73)])
def test_effort_budget_controls_actual_subprocess_and_persists(runner, monkeypatch, effort, expected):
    folder = runner / 'sim_budget'
    folder.mkdir()
    (folder / 'simulation_config.json').write_text(json.dumps({'time_config': {
        'total_simulation_hours': 73, 'minutes_per_round': 60}}))
    commands = []
    class Process:
        pid = 900001
        def poll(self): return 0
    monkeypatch.setattr(module.subprocess, 'Popen', lambda cmd, **kw: commands.append(cmd) or Process())
    monkeypatch.setattr(module.threading, 'Thread', lambda **kw: SimpleNamespace(start=lambda: None))
    state = SimulationRunner.start_simulation('sim_budget', simulation_effort=effort)
    assert state.total_rounds == expected
    command = commands[0]
    assert command[command.index('--max-rounds')+1] == str(expected)
    saved = SimulationRunner._load_run_state('sim_budget')
    assert saved.simulation_effort == effort
    assert saved.planned_full_rounds == 73
    assert saved.total_rounds == expected
    for handle in SimulationRunner._stdout_files.values(): handle.close()


def test_invalid_effort_rejected_before_startup_mutation(runner):
    folder = runner / 'sim_invalid'
    folder.mkdir()
    (folder / 'simulation_config.json').write_text('{}')
    with pytest.raises(ValueError, match='simulation_effort'):
        SimulationRunner.start_simulation('sim_invalid', simulation_effort='extreme')
    assert not (folder / 'run_state.json').exists()


def test_stop_request_returns_immediately_and_deduplicates_worker(runner, monkeypatch):
    state = SimulationRunState('sim_stop', runner_status=RunnerStatus.RUNNING, current_round=2, total_rounds=8, error='Previous save timed out')
    SimulationRunner._save_run_state(state)
    workers = []
    class Thread:
        def __init__(self, target, **kw): self.target = target
        def start(self): workers.append(self.target)
        def is_alive(self): return True
    monkeypatch.setattr(module.threading, 'Thread', Thread)
    SimulationRunner._stop_threads = {}
    try:
        first = SimulationRunner.request_stop('sim_stop')
        second = SimulationRunner.request_stop('sim_stop')
        assert first.runner_status == second.runner_status == RunnerStatus.STOPPING
        assert first.stop_requested is True
        assert first.error is None
        assert len(workers) == 1
        assert SimulationRunner._load_run_state('sim_stop').stop_requested is True
        workers[0]()
        assert SimulationRunner.get_run_state('sim_stop').runner_status == RunnerStatus.STOPPED
        assert SimulationRunner.get_run_state('sim_stop').current_round == 2
    finally:
        SimulationRunner._stop_threads = {}


def test_natural_completion_race_with_stop_is_successful(runner):
    state = SimulationRunState('sim_done', runner_status=RunnerStatus.COMPLETED)
    SimulationRunner._save_run_state(state)
    result = SimulationRunner.stop_simulation('sim_done')
    assert result.runner_status == RunnerStatus.COMPLETED


def test_stop_during_start_never_publishes_a_running_child(runner, monkeypatch):
    folder = runner / 'sim_race'
    folder.mkdir()
    (folder / 'simulation_config.json').write_text('{}')
    class Process:
        pid = 900002
        stopped = False
        def poll(self): return 0 if self.stopped else None
    process = Process()
    def launch(*args, **kwargs):
        SimulationRunner.stop_simulation('sim_race')
        return process
    monkeypatch.setattr(module.subprocess, 'Popen', launch)
    monkeypatch.setattr(SimulationRunner, '_terminate_process', lambda p, *a: setattr(p, 'stopped', True))
    state = SimulationRunner.start_simulation('sim_race')
    assert state.runner_status == RunnerStatus.STOPPED
    assert process.stopped
    assert 'sim_race' not in SimulationRunner._processes


def test_nonblocking_stop_api_returns_pending_state(runner, monkeypatch):
    from flask import Flask
    from app.api import simulation as api
    state = SimulationRunState('sim_stop', runner_status=RunnerStatus.STOPPING, stop_requested=True)
    monkeypatch.setattr(SimulationRunner, 'request_stop', lambda _: state)
    with Flask(__name__).test_request_context(json={'simulation_id': 'sim_stop', 'wait': False}):
        response, status = api.stop_simulation()
    assert status == 202
    assert response.json['success'] is True
    assert response.json['data']['stop_requested'] is True
    assert response.json['data']['runner_status'] == 'stopping'


def test_async_stop_still_waits_for_monitor_tail_before_ingestion_drain(runner, monkeypatch):
    state = SimulationRunState('sim_tail', runner_status=RunnerStatus.STOPPING, stop_requested=True)
    SimulationRunner._save_run_state(state)
    SimulationRunner._graph_memory_enabled['sim_tail'] = True
    events = []
    monkeypatch.setattr(module.ZepGraphMemoryManager, 'get_updater', lambda _: object())
    def drain(_):
        events.append('drain')
        assert events[0] == 'tail'
    monkeypatch.setattr(module.ZepGraphMemoryManager, 'stop_updater', drain)
    class Monitor:
        alive = True
        def is_alive(self): return self.alive
        def join(self, **kw):
            events.append('tail')
            drain('sim_tail')
            state.runner_status = RunnerStatus.STOPPED
            self.alive = False
    SimulationRunner._monitor_threads['sim_tail'] = Monitor()
    result = SimulationRunner.stop_simulation('sim_tail')
    assert result.runner_status == RunnerStatus.STOPPED
    assert events == ['tail', 'drain']


@pytest.mark.parametrize('effort', ['unknown', None, 12, []])
def test_start_api_rejects_invalid_effort_before_side_effects(effort):
    from flask import Flask
    from app.api import simulation as api
    with Flask(__name__).test_request_context(json={'simulation_id': 'sim_missing', 'simulation_effort': effort}):
        response, status = api.start_simulation()
    assert status == 400
    assert 'simulation_effort' in response.json['error']
