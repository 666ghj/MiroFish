"""A run that played every round but whose Zep graph sync timed out may still get a report, if the user opts in."""
from types import SimpleNamespace

import pytest
from flask import Flask

from app.api import report as report_api
from app.services.simulation_runner import RunnerStatus, SimulationRunner

SYNC_ERROR = f"{SimulationRunner.GRAPH_SYNC_ERROR_PREFIX}: Zep simulation ingestion timed out with 94 episode(s) pending"


def call(monkeypatch, run_state, *, updater=object(), body=None, project=None):
    simulation = SimpleNamespace(project_id="proj-1", graph_id="graph-1")
    monkeypatch.setattr(report_api, "SimulationManager", lambda: SimpleNamespace(get_simulation=lambda _id: simulation))
    monkeypatch.setattr(report_api.ReportManager, "get_report_by_simulation", classmethod(lambda _c, _id: None))
    monkeypatch.setattr(report_api.SimulationRunner, "get_run_state", classmethod(lambda _c, _id: run_state))
    monkeypatch.setattr(report_api.ZepGraphMemoryManager, "get_updater", classmethod(lambda _c, _id: updater))
    monkeypatch.setattr(report_api.ProjectManager, "get_project", classmethod(lambda _c, _id: project))
    with Flask(__name__).test_request_context("/api/report/generate", method="POST",
                                              json={"simulation_id": "sim-1", **(body or {})}):
        result = report_api.generate_report()
    response, status = result if isinstance(result, tuple) else (result, result.status_code)
    return response.get_json(), status


def finished_run(**changes):
    state = dict(runner_status=RunnerStatus.FAILED, error=SYNC_ERROR, platforms=("twitter", "reddit"),
                 twitter_completed=True, reddit_completed=True)
    state.update(changes)
    return SimpleNamespace(**state)


def test_by_default_the_run_is_still_blocked_but_the_answer_says_a_partial_report_is_possible(monkeypatch):
    body, status = call(monkeypatch, finished_run())
    assert status == 409 and body["can_generate_partial"] is True and body["ingestion_pending"] is True


def test_the_same_run_after_a_restart_is_blocked_too_and_offers_the_same_choice(monkeypatch):
    body, status = call(monkeypatch, finished_run(), updater=None)
    assert status == 409 and body["can_generate_partial"] is True and "successfully completed" in body["error"]


def test_with_the_opt_in_the_run_gets_past_the_barrier(monkeypatch):
    # no project is set up in this test, so getting as far as the project lookup (404) proves the guards let it through
    for updater in (object(), None):
        body, status = call(monkeypatch, finished_run(), updater=updater, body={"allow_partial_graph": True})
        assert status == 404, (updater, body)


@pytest.mark.parametrize("changes", [
    dict(error="Process exit code 1: Traceback ..."),        # a real failure, not a graph sync problem
    dict(error=None),
    dict(reddit_completed=False),                              # a platform did not finish its rounds
    dict(runner_status=RunnerStatus.RUNNING),
    dict(runner_status=RunnerStatus.STOPPING),
])
def test_the_opt_in_never_lets_through_a_run_that_is_really_broken_or_still_going(monkeypatch, changes):
    body, status = call(monkeypatch, finished_run(**changes), body={"allow_partial_graph": True})
    assert status == 409 and body["can_generate_partial"] is False


def test_a_single_platform_run_only_needs_its_own_platform_finished(monkeypatch):
    run = finished_run(platforms=("twitter",), reddit_completed=False)
    _body, status = call(monkeypatch, run, body={"allow_partial_graph": True})
    assert status == 404


def test_the_opt_in_must_be_a_json_boolean(monkeypatch):
    _body, status = call(monkeypatch, finished_run(), body={"allow_partial_graph": "yes"})
    assert status == 400


def test_the_helper_is_false_without_a_run_state(monkeypatch):
    monkeypatch.setattr(SimulationRunner, "get_run_state", classmethod(lambda _c, _id: None))
    assert SimulationRunner.graph_sync_incomplete_only("sim-x") is False
