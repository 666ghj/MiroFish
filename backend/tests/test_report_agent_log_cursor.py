import json

from app.services.report_agent import ReportManager


def log_file(tmp_path, monkeypatch, contents):
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path))
    folder = tmp_path / "report-test"
    folder.mkdir()
    path = folder / "agent_log.jsonl"
    path.write_text(contents, encoding="utf-8")
    return path


def test_cursor_counts_malformed_physical_lines_without_replaying_valid_records(tmp_path, monkeypatch):
    entries = [{"action": "planning_complete"}, {"action": "section_complete"}]
    log_file(tmp_path, monkeypatch, json.dumps(entries[0]) + "\nnot JSON\n" + json.dumps(entries[1]) + "\n")
    result = ReportManager.get_agent_log("report-test")
    assert result["logs"] == entries
    assert result["from_line"] == 0
    assert result["next_line"] == 3
    assert ReportManager.get_agent_log("report-test", result["next_line"])["logs"] == []


def test_cursor_advances_past_only_malformed_records(tmp_path, monkeypatch):
    log_file(tmp_path, monkeypatch, "not JSON\n\n")
    result = ReportManager.get_agent_log("report-test")
    assert result["logs"] == []
    assert result["next_line"] == 2


def test_unfinished_final_record_is_delivered_after_writer_finishes_it(tmp_path, monkeypatch):
    first, second = {"action": "planning_start"}, {"action": "report_complete"}
    encoded = json.dumps(second)
    path = log_file(tmp_path, monkeypatch, json.dumps(first) + "\n" + encoded[:10])
    result = ReportManager.get_agent_log("report-test")
    assert result["logs"] == [first]
    assert result["next_line"] == 1
    with path.open("a", encoding="utf-8") as stream:
        stream.write(encoded[10:] + "\n")
    resumed = ReportManager.get_agent_log("report-test", result["next_line"])
    assert resumed["logs"] == [second]
    assert resumed["next_line"] == 2


def test_missing_log_starts_at_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path))
    result = ReportManager.get_agent_log("missing")
    assert result["logs"] == []
    assert result["next_line"] == 0
