from datetime import datetime
from types import SimpleNamespace

import pytest
from flask import Flask

from app.api import report as report_api
from app.models.task import Task, TaskStatus
from app.services.report_agent import Report, ReportStatus


def completed_report():
    return Report("report-old", "sim-test", "graph-test", "forecast", ReportStatus.COMPLETED)


@pytest.mark.parametrize("status", [TaskStatus.PROCESSING, TaskStatus.FAILED, TaskStatus.COMPLETED])
def test_explicit_task_status_takes_precedence_over_older_completed_report(monkeypatch, status):
    task = Task("task-new", "report_generation", status, datetime.now(), datetime.now(),
                progress=35, error="provider failed" if status == TaskStatus.FAILED else None)
    monkeypatch.setattr(report_api, "TaskManager", lambda: SimpleNamespace(get_task=lambda task_id: task))
    monkeypatch.setattr(report_api.ReportManager, "get_report_by_simulation", lambda simulation_id: completed_report())
    with Flask(__name__).test_request_context(json={"task_id": "task-new", "simulation_id": "sim-test"}):
        response = report_api.get_generate_status()
    payload = response.get_json()
    assert payload["data"] == task.to_dict()


def test_unknown_explicit_task_is_not_hidden_by_completed_report(monkeypatch):
    monkeypatch.setattr(report_api, "TaskManager", lambda: SimpleNamespace(get_task=lambda task_id: None))
    monkeypatch.setattr(report_api.ReportManager, "get_report_by_simulation", lambda simulation_id: completed_report())
    with Flask(__name__).test_request_context(json={"task_id": "missing", "simulation_id": "sim-test"}):
        response, status = report_api.get_generate_status()
    assert status == 404
    assert response.get_json()["success"] is False


def test_simulation_only_lookup_still_returns_completed_report(monkeypatch):
    monkeypatch.setattr(report_api.ReportManager, "get_report_by_simulation", lambda simulation_id: completed_report())
    with Flask(__name__).test_request_context(json={"simulation_id": "sim-test"}):
        response = report_api.get_generate_status()
    data = response.get_json()["data"]
    assert data["report_id"] == "report-old"
    assert data["already_completed"] is True
