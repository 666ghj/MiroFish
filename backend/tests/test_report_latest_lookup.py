import itertools
import json

import pytest

from app.services.report_agent import Report, ReportManager, ReportStatus


def make_report(report_id, simulation_id, created_at, status=ReportStatus.COMPLETED):
    return Report(report_id, simulation_id, "graph-test", "forecast", status,
                  created_at=created_at)


@pytest.mark.parametrize("order", list(itertools.permutations(["report_old", "report_new", "report_other"])))
@pytest.mark.parametrize("old_status", [ReportStatus.COMPLETED, ReportStatus.FAILED])
def test_lookup_returns_latest_matching_report_independent_of_directory_order(tmp_path, monkeypatch, order, old_status):
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path))
    old = make_report("report_old", "sim-test", "2026-10-20T12:00:00", old_status)
    new = make_report("report_new", "sim-test", "2026-10-21T12:00:00")
    other = make_report("report_other", "sim-other", "2026-10-22T12:00:00")
    for report in [old, new, other]:
        ReportManager.save_report(report)
    monkeypatch.setattr("app.services.report_agent.os.listdir", lambda path: list(order))
    assert ReportManager.get_report_by_simulation("sim-test").report_id == new.report_id


def test_lookup_includes_newer_legacy_report_and_returns_none_for_missing_simulation(tmp_path, monkeypatch):
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path))
    old = make_report("report_old", "sim-test", "2026-10-20T12:00:00")
    new = make_report("report_legacy", "sim-test", "2026-10-21T12:00:00")
    ReportManager.save_report(old)
    (tmp_path / "report_legacy.json").write_text(json.dumps(new.to_dict()), encoding="utf-8")
    monkeypatch.setattr("app.services.report_agent.os.listdir", lambda path: ["report_old", "report_legacy.json"])
    assert ReportManager.get_report_by_simulation("sim-test").report_id == new.report_id
    assert ReportManager.get_report_by_simulation("missing") is None
