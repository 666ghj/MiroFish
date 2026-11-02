"""Zep falls behind on a big run: a configurable wait, a switch for the live graph write, and a status the UI can show."""
import pytest
from flask import Flask

from app.api import simulation as simulation_api
from app.services.simulation_runner import RunnerStatus, SimulationRunState, SimulationRunner
from app.utils import zep


def test_the_wait_for_zep_defaults_to_ten_minutes_and_can_be_raised(monkeypatch):
    monkeypatch.delenv("ZEP_INGESTION_WAIT_TIMEOUT_SECONDS", raising=False)
    assert zep._wait_timeout_seconds() == 600
    monkeypatch.setenv("ZEP_INGESTION_WAIT_TIMEOUT_SECONDS", "3600")
    assert zep._wait_timeout_seconds() == 3600


@pytest.mark.parametrize("bad", ["", "abc", "0", "-5"])
def test_a_missing_or_unusable_wait_falls_back_to_the_default(monkeypatch, bad):
    monkeypatch.setenv("ZEP_INGESTION_WAIT_TIMEOUT_SECONDS", bad)
    assert zep._wait_timeout_seconds() == 600


@pytest.mark.parametrize("value", ["false", "False", "0", "no", "off", " OFF "])
def test_the_live_graph_write_can_be_turned_off_for_every_run(monkeypatch, value):
    monkeypatch.setenv("ZEP_GRAPH_MEMORY_UPDATE", value)
    assert simulation_api._graph_updates_allowed(True) is False
    assert simulation_api._graph_updates_allowed(False) is False


@pytest.mark.parametrize("value", [None, "", "true", "1", "anything"])
def test_otherwise_the_request_decides(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("ZEP_GRAPH_MEMORY_UPDATE", raising=False)
    else:
        monkeypatch.setenv("ZEP_GRAPH_MEMORY_UPDATE", value)
    assert simulation_api._graph_updates_allowed(True) is True
    assert simulation_api._graph_updates_allowed(False) is False


def run_status(monkeypatch, **changes):
    state = SimulationRunState(simulation_id="sim-x", runner_status=RunnerStatus.FAILED,
                               twitter_completed=True, reddit_completed=True,
                               error=f"{SimulationRunner.GRAPH_SYNC_ERROR_PREFIX}: timed out with 94 episode(s) pending")
    for key, value in changes.items():
        setattr(state, key, value)
    monkeypatch.setattr(SimulationRunner, "get_run_state", classmethod(lambda _c, _id: state))
    with Flask(__name__).test_request_context():
        return simulation_api.get_run_status("sim-x").get_json()["data"]


def test_run_status_says_when_only_the_graph_sync_is_pending(monkeypatch):
    data = run_status(monkeypatch)
    assert data["runner_status"] == "failed" and data["graph_sync_pending"] is True


def test_a_genuinely_failed_or_unfinished_run_is_not_called_sync_pending(monkeypatch):
    assert run_status(monkeypatch, error="Process exit code 1")["graph_sync_pending"] is False
    assert run_status(monkeypatch, reddit_completed=False)["graph_sync_pending"] is False
    assert run_status(monkeypatch, runner_status=RunnerStatus.COMPLETED, error=None)["graph_sync_pending"] is False


def test_run_status_says_whether_a_process_is_left(monkeypatch):
    # "stopping" with no process left means the backend waits for Zep: the UI must not offer a pointless Stop now
    monkeypatch.setattr(SimulationRunner, "has_live_process", classmethod(lambda _c, _id: False))
    assert run_status(monkeypatch, runner_status=RunnerStatus.STOPPING)["process_alive"] is False
    monkeypatch.setattr(SimulationRunner, "has_live_process", classmethod(lambda _c, _id: True))
    assert run_status(monkeypatch, runner_status=RunnerStatus.RUNNING)["process_alive"] is True
