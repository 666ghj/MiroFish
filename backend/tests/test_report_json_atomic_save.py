import json
from pathlib import Path

import pytest

from app.services.report_agent import Report, ReportManager, ReportOutline, ReportSection, ReportStatus


@pytest.fixture
def report_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path))
    return tmp_path


def writer(kind, text):
    if kind == "meta":
        report = Report("report-test", "sim-test", "graph-test", text, ReportStatus.COMPLETED)
        return lambda: ReportManager.save_report(report), "meta.json"
    if kind == "outline":
        outline = ReportOutline(text, "Summary", [ReportSection("Section", "Content")])
        return lambda: ReportManager.save_outline("report-test", outline), "outline.json"
    return lambda: ReportManager.update_progress("report-test", "generating", 50, text), "progress.json"


@pytest.mark.parametrize("kind", ["meta", "outline", "progress"])
def test_failed_write_preserves_previous_report_json(report_storage, monkeypatch, kind):
    save_old, filename = writer(kind, "Original")
    save_old()
    folder = report_storage / "report-test"
    target = folder / filename
    original = target.read_bytes()

    def interrupted_dump(data, stream, **kwargs):
        stream.write('{"interrupted":')
        raise OSError("simulated storage write failure")

    with monkeypatch.context() as patch:
        patch.setattr("app.services.report_agent.json.dump", interrupted_dump)
        save_new, _ = writer(kind, "Replacement")
        with pytest.raises(OSError, match="storage write failure"):
            save_new()
    assert target.read_bytes() == original
    assert json.loads(target.read_text(encoding="utf-8"))
    assert set(path.name for path in folder.iterdir()) == {filename}


@pytest.mark.parametrize("kind", ["meta", "outline", "progress"])
def test_failed_replacement_preserves_previous_report_json(report_storage, monkeypatch, kind):
    save_old, filename = writer(kind, "Original")
    save_old()
    folder = report_storage / "report-test"
    target = folder / filename
    original = target.read_bytes()

    def reject_replace(source, destination):
        assert Path(source).parent == Path(destination).parent
        raise OSError("simulated replace failure")

    with monkeypatch.context() as patch:
        patch.setattr("app.services.report_agent.os.replace", reject_replace)
        save_new, _ = writer(kind, "Replacement")
        with pytest.raises(OSError, match="replace failure"):
            save_new()
    assert target.read_bytes() == original
    assert set(path.name for path in folder.iterdir()) == {filename}


@pytest.mark.parametrize("kind", ["meta", "outline", "progress"])
def test_successful_write_replaces_report_json(report_storage, kind):
    save_old, filename = writer(kind, "Original")
    save_old()
    save_new, _ = writer(kind, "Replacement — 预测")
    save_new()
    folder = report_storage / "report-test"
    content = json.loads((folder / filename).read_text(encoding="utf-8"))
    field = {"meta": "simulation_requirement", "outline": "title", "progress": "message"}[kind]
    assert content[field] == "Replacement — 预测"
    assert set(path.name for path in folder.iterdir()) == {filename}
    if kind == "meta":
        assert ReportManager.get_report("report-test").simulation_requirement == content[field]
    if kind == "progress":
        assert ReportManager.get_progress("report-test")[field] == content[field]
