"""Tests for report download endpoint (MD and PDF formats)."""
import io
import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock
from app import create_app


@pytest.fixture
def app():
    app = create_app({'TESTING': True})
    yield app


@pytest.fixture
def client(app):
    return app.test_client()


def _make_mock_report(report_id="report_test123", content="# Test Report\n\nHello **world**."):
    mock = MagicMock()
    mock.report_id = report_id
    mock.markdown_content = content
    return mock


def _make_md_file(tmp_path, report_id, content):
    md_path = os.path.join(tmp_path, f"{report_id}_full_report.md")
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(content)
    return md_path


class TestDownloadMD:
    def test_download_md_format_param(self, client, tmp_path):
        """?format=md returns a .md file."""
        mock_report = _make_mock_report()
        md_path = _make_md_file(tmp_path, mock_report.report_id, mock_report.markdown_content)

        with patch('app.api.report.ReportManager.get_report', return_value=mock_report), \
             patch('app.api.report.ReportManager._get_report_markdown_path', return_value=md_path):
            resp = client.get(f'/api/report/{mock_report.report_id}/download?format=md')

        assert resp.status_code == 200
        assert 'attachment' in resp.headers.get('Content-Disposition', '')
        assert '.md' in resp.headers.get('Content-Disposition', '')

    def test_download_default_is_md(self, client, tmp_path):
        """No format param defaults to md."""
        mock_report = _make_mock_report()
        md_path = _make_md_file(tmp_path, mock_report.report_id, mock_report.markdown_content)

        with patch('app.api.report.ReportManager.get_report', return_value=mock_report), \
             patch('app.api.report.ReportManager._get_report_markdown_path', return_value=md_path):
            resp = client.get(f'/api/report/{mock_report.report_id}/download')

        assert resp.status_code == 200
        assert '.md' in resp.headers.get('Content-Disposition', '')


class TestDownloadPDF:
    def test_download_pdf_returns_pdf_bytes(self, client, tmp_path):
        """?format=pdf returns a valid PDF file."""
        mock_report = _make_mock_report()
        md_path = _make_md_file(tmp_path, mock_report.report_id, mock_report.markdown_content)

        with patch('app.api.report.ReportManager.get_report', return_value=mock_report), \
             patch('app.api.report.ReportManager._get_report_markdown_path', return_value=md_path):
            resp = client.get(f'/api/report/{mock_report.report_id}/download?format=pdf')

        assert resp.status_code == 200
        assert resp.headers.get('Content-Type', '').startswith('application/pdf')
        assert resp.data[:4] == b'%PDF'

    def test_download_pdf_report_not_found(self, client):
        """Returns 404 when report does not exist."""
        with patch('app.api.report.ReportManager.get_report', return_value=None):
            resp = client.get('/api/report/nonexistent/download?format=pdf')

        assert resp.status_code == 404

    def test_download_pdf_invalid_format(self, client, tmp_path):
        """Returns 400 for unknown format parameter."""
        mock_report = _make_mock_report()
        md_path = _make_md_file(tmp_path, mock_report.report_id, mock_report.markdown_content)

        with patch('app.api.report.ReportManager.get_report', return_value=mock_report), \
             patch('app.api.report.ReportManager._get_report_markdown_path', return_value=md_path):
            resp = client.get(f'/api/report/{mock_report.report_id}/download?format=docx')

        assert resp.status_code == 400
