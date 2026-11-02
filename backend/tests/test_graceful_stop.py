"""Pause, continue and graceful stop of a run: the runner asks the script (control.json) instead of killing it."""
import json
import subprocess
import threading
import time
from types import SimpleNamespace

import pytest

from app.services import simulation_runner as runner_module
from app.services.simulation_runner import RunnerStatus, SimulationRunState, SimulationRunner

_REAL_SLEEP = time.sleep
SIM = "sim-graceful"


class FakeProcess:
    pid = 4343

    def __init__(self):
        self.returncode = None
        self.exited = threading.Event()

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if not self.exited.wait(timeout):
            raise subprocess.TimeoutExpired("fake", timeout)
        return self.returncode

    def exit(self, code=0):
        self.returncode = code
        self.exited.set()


def control(tmp_path):
    path = tmp_path / SIM / "control.json"
    return json.loads(path.read_text(encoding="utf-8"))["action"] if path.exists() else None


@pytest.fixture
def run(monkeypatch, tmp_path):
    (tmp_path / SIM).mkdir()
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path))
    synced = []
    monkeypatch.setattr(SimulationRunner, "_sync_simulation_status",
                        classmethod(lambda _c, simulation_id, status, *_a, **_k: synced.append(status)))
    monkeypatch.setattr(runner_module.ZepGraphMemoryManager, "get_updater", classmethod(lambda _c, _s: None))
    monkeypatch.setattr(time, "sleep", lambda _s: _REAL_SLEEP(0.01))
    killed = []
    monkeypatch.setattr(SimulationRunner, "_terminate_process",
                        classmethod(lambda _c, process, simulation_id, timeout=10: (killed.append(simulation_id), process.exit(1))))

    process = FakeProcess()
    state = SimulationRunState(simulation_id=SIM, runner_status=RunnerStatus.RUNNING, twitter_running=True, reddit_running=True)
    SimulationRunner._save_run_state(state)
    SimulationRunner._processes[SIM] = process
    SimulationRunner._graph_memory_enabled[SIM] = False
    threads = []
    try:
        yield SimpleNamespace(state=state, process=process, killed=killed, synced=synced, threads=threads, tmp=tmp_path)
    finally:
        process.exit(0)
        for thread in threads:
            thread.join(timeout=5)
        for registry in (SimulationRunner._run_states, SimulationRunner._processes, SimulationRunner._monitor_threads,
                         SimulationRunner._action_queues, SimulationRunner._graph_memory_enabled):
            registry.pop(SIM, None)
        SimulationRunner._manual_stop_requests.discard(SIM)


def test_pause_asks_the_script_and_shows_paused(run):
    state = SimulationRunner.pause_simulation(SIM)
    assert state.runner_status == RunnerStatus.PAUSED
    assert control(run.tmp) == "pause"
    assert RunnerStatus.PAUSED in run.synced
    assert run.killed == []                      # the process is untouched: it waits at the next round boundary


def test_continue_lets_a_paused_run_carry_on(run):
    SimulationRunner.pause_simulation(SIM)
    state = SimulationRunner.continue_simulation(SIM)
    assert state.runner_status == RunnerStatus.RUNNING and control(run.tmp) == "run"


def test_pause_and_continue_refuse_the_wrong_state(run):
    with pytest.raises(ValueError):
        SimulationRunner.continue_simulation(SIM)               # not paused
    run.state.runner_status = RunnerStatus.COMPLETED
    with pytest.raises(ValueError):
        SimulationRunner.pause_simulation(SIM)                   # not running
    run.state.runner_status = RunnerStatus.RUNNING
    run.process.exit(0)
    with pytest.raises(ValueError):
        SimulationRunner.pause_simulation(SIM)                   # the process is gone: nothing to pause
    run.state.runner_status = RunnerStatus.PAUSED
    with pytest.raises(ValueError):
        SimulationRunner.continue_simulation(SIM)                # a paused state with no process must be resumed instead


def test_graceful_stop_returns_stopping_and_does_not_kill(run):
    state = SimulationRunner.stop_simulation(SIM, graceful=True)
    assert state.runner_status == RunnerStatus.STOPPING
    assert control(run.tmp) == "stop"
    assert SIM in SimulationRunner._manual_stop_requests        # so the monitor publishes STOPPED, not COMPLETED
    assert run.killed == []


def test_graceful_stop_of_a_paused_run_stops_it(run):
    SimulationRunner.pause_simulation(SIM)
    assert SimulationRunner.stop_simulation(SIM, graceful=True).runner_status == RunnerStatus.STOPPING
    assert control(run.tmp) == "stop"


def test_a_second_graceful_request_changes_nothing_and_a_plain_stop_kills_now(run):
    SimulationRunner.stop_simulation(SIM, graceful=True)
    SimulationRunner.stop_simulation(SIM, graceful=True)         # a double click must not turn into a kill
    assert run.killed == []
    SimulationRunner.stop_simulation(SIM)                        # "stop now"
    assert run.killed == [SIM]


def test_a_run_that_does_not_end_its_round_is_killed_after_the_grace_period(run, monkeypatch):
    monkeypatch.setenv("SIM_STOP_GRACE_SECONDS", "0.3")
    SimulationRunner.stop_simulation(SIM, graceful=True)
    deadline = time.monotonic() + 5
    while not run.killed and time.monotonic() < deadline:
        _REAL_SLEEP(0.02)
    assert run.killed == [SIM]


def test_a_run_that_ends_in_time_is_not_killed(run, monkeypatch):
    monkeypatch.setenv("SIM_STOP_GRACE_SECONDS", "0.5")
    SimulationRunner.stop_simulation(SIM, graceful=True)
    run.process.exit(0)                                          # it finished its round and exited by itself
    _REAL_SLEEP(0.9)
    assert run.killed == []


def test_the_monitor_publishes_stopped_when_the_script_exits_after_a_graceful_stop(run):
    thread = threading.Thread(target=SimulationRunner._monitor_simulation, args=(SIM, "en"), daemon=True)
    SimulationRunner._monitor_threads[SIM] = thread
    thread.start()
    run.threads.append(thread)
    SimulationRunner.stop_simulation(SIM, graceful=True)
    assert SimulationRunner.get_run_state(SIM).runner_status == RunnerStatus.STOPPING
    run.process.exit(0)
    thread.join(timeout=10)
    final = SimulationRunner.get_run_state(SIM)
    assert final.runner_status == RunnerStatus.STOPPED and not final.error


def test_a_new_run_starts_without_an_old_pause_or_stop_request(run):
    SimulationRunner.pause_simulation(SIM)
    SimulationRunner._sim_control().clear(str(run.tmp / SIM))    # what start_simulation does before launching
    assert control(run.tmp) is None


def test_the_helper_modules_load_in_a_fresh_process_state(monkeypatch):
    # conftest preloads them, which once hid a loader that only worked when the module was already imported
    import sys
    for name in ("sim_resume", "sim_control"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    assert hasattr(SimulationRunner._sim_resume(), "ResumePlan")      # defines a dataclass: needs sys.modules while loading
    assert hasattr(SimulationRunner._sim_control(), "write_action")
    assert "sim_resume" in sys.modules and "sim_control" in sys.modules


def test_a_helper_that_fails_to_load_leaves_no_stub_behind(monkeypatch, tmp_path):
    import sys
    monkeypatch.delitem(sys.modules, "sim_control", raising=False)
    monkeypatch.setattr(SimulationRunner, "SCRIPTS_DIR", str(tmp_path))     # no sim_control.py there
    with pytest.raises(Exception):
        SimulationRunner._sim_control()
    assert "sim_control" not in sys.modules
