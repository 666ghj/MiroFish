"""A stop that died with the backend leaves STOPPING on disk; it must not stay that way forever."""
import json
from types import SimpleNamespace

import pytest

from app.services import simulation_runner as runner_module
from app.services.simulation_runner import RunnerStatus, SimulationRunner

SIM = "sim-orphan"
SYNC_ERROR = f"{SimulationRunner.GRAPH_SYNC_ERROR_PREFIX}: timed out with 19 episode(s) pending"


@pytest.fixture
def disk(monkeypatch, tmp_path):
    (tmp_path / SIM).mkdir()
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path))
    synced = []
    monkeypatch.setattr(SimulationRunner, "_sync_simulation_status",
                        classmethod(lambda _c, simulation_id, status, error=None: synced.append((status, error))))
    monkeypatch.setattr(runner_module.ZepGraphMemoryManager, "get_updater", classmethod(lambda _c, _s: None))
    SimulationRunner._run_states.pop(SIM, None)
    SimulationRunner._processes.pop(SIM, None)

    def write(**fields):
        data = dict(runner_status="stopping", twitter_completed=True, reddit_completed=True, twitter_running=True,
                    reddit_running=True, error=SYNC_ERROR)
        data.update(fields)
        (tmp_path / SIM / "run_state.json").write_text(json.dumps(data), encoding="utf-8")

    yield SimpleNamespace(write=write, synced=synced, path=tmp_path / SIM / "run_state.json")
    SimulationRunner._run_states.pop(SIM, None)
    SimulationRunner._processes.pop(SIM, None)


def test_a_stop_that_was_waiting_on_zep_ends_as_the_graph_sync_failure_it_was(disk):
    disk.write()
    state = SimulationRunner.get_run_state(SIM)
    assert state.runner_status == RunnerStatus.FAILED and not state.twitter_running and state.completed_at
    assert SimulationRunner.graph_sync_incomplete_only(SIM) is True      # so a partial report can be requested
    assert json.loads(disk.path.read_text(encoding="utf-8"))["runner_status"] == "failed"   # settled once, on disk
    assert disk.synced == [(RunnerStatus.FAILED, SYNC_ERROR)]


def test_any_other_orphaned_stop_ends_as_stopped_so_it_can_be_resumed(disk):
    disk.write(error=None, twitter_completed=False, reddit_completed=False)
    assert SimulationRunner.get_run_state(SIM).runner_status == RunnerStatus.STOPPED


def test_a_real_stop_in_progress_is_left_alone(disk, monkeypatch):
    disk.write()
    monkeypatch.setattr(runner_module.ZepGraphMemoryManager, "get_updater", classmethod(lambda _c, _s: object()))
    assert SimulationRunner.get_run_state(SIM).runner_status == RunnerStatus.STOPPING     # the Zep drain is registered

    SimulationRunner._run_states.pop(SIM, None)
    monkeypatch.setattr(runner_module.ZepGraphMemoryManager, "get_updater", classmethod(lambda _c, _s: None))
    SimulationRunner._processes[SIM] = SimpleNamespace(poll=lambda: None)
    assert SimulationRunner.get_run_state(SIM).runner_status == RunnerStatus.STOPPING     # the process is still alive


@pytest.mark.parametrize("status", ["running", "paused", "starting", "completed", "failed", "stopped"])
def test_no_other_status_is_touched(disk, status):
    disk.write(runner_status=status)
    assert SimulationRunner.get_run_state(SIM).runner_status.value == status
