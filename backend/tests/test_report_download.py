import json
from types import SimpleNamespace

from flask import Flask

from app.api import report as report_api


def _download_response(monkeypatch, tmp_path, query_string=""):
    report = SimpleNamespace(
        markdown_content="# 预测报告\n\n完整内容",
        to_dict=lambda: {
            "report_id": "report-1",
            "title": "预测报告",
        },
    )
    monkeypatch.setattr(
        report_api.ReportManager,
        "get_report",
        classmethod(lambda _cls, _report_id: report),
    )
    monkeypatch.setattr(
        report_api.ReportManager,
        "_get_report_markdown_path",
        classmethod(lambda _cls, _report_id: str(tmp_path / "missing.md")),
    )

    app = Flask(__name__)
    with app.test_request_context(
        f"/api/report/report-1/download{query_string}",
    ):
        return report_api.download_report("report-1")


def _response_text(response):
    response.direct_passthrough = False
    return response.get_data(as_text=True)


def test_download_report_returns_utf8_json_attachment(monkeypatch, tmp_path):
    response = _download_response(monkeypatch, tmp_path, "?format=json")

    assert response.status_code == 200
    assert response.mimetype == "application/json"
    assert "report-1.json" in response.headers["Content-Disposition"]
    assert json.loads(_response_text(response)) == {
        "report_id": "report-1",
        "title": "预测报告",
    }


def test_download_report_generates_markdown_attachment_in_memory(
    monkeypatch,
    tmp_path,
):
    response = _download_response(monkeypatch, tmp_path)

    assert response.status_code == 200
    assert response.mimetype == "text/markdown"
    assert "report-1.md" in response.headers["Content-Disposition"]
    assert _response_text(response) == "# 预测报告\n\n完整内容"
    assert list(tmp_path.iterdir()) == []


def test_download_report_rejects_unknown_format(monkeypatch, tmp_path):
    response, status = _download_response(
        monkeypatch,
        tmp_path,
        "?format=pdf",
    )

    assert status == 400
    assert response.get_json() == {
        "success": False,
        "error": "Unsupported report format. Use 'markdown' or 'json'.",
    }
