import pytest
import pymupdf
from flask import Flask
from app.services.report_agent import Report, ReportStatus, ReportOutline
from app.api import report as api


def saved_report():
    return Report('report_test', 'sim_test', 'graph_test', 'Launch decision', ReportStatus.COMPLETED,
        outline=ReportOutline(title='Business opportunity', summary='Summary', sections=[]),
        markdown_content='# Business opportunity\n\n> **Simulation coverage**\n> Partial simulation: stopped at round 37.\n\n## Findings\n\nChoose **S$14**. Café demand is uncertain.\n\n| Option | Price |\n| --- | --- |\n| Pilot | S$14 |\n\n- First condition\n- Second condition\n\n[Source](https://example.com/evidence)\n')


def download(monkeypatch, report=None, query='?format=pdf'):
    monkeypatch.setattr(api.ReportManager, 'get_report', lambda _: report)
    app = Flask(__name__)
    with app.test_request_context('/api/report/report_test/download'+query):
        result = api.download_report('report_test')
        response = app.make_response(result)
        response.direct_passthrough = False
        return response


def test_pdf_download_contains_saved_content_tables_coverage_and_clickable_sources(monkeypatch):
    response = download(monkeypatch, saved_report())
    assert response.status_code == 200
    assert response.mimetype == 'application/pdf'
    assert 'report_test.pdf' in response.headers['Content-Disposition']
    with pymupdf.open(stream=response.get_data(), filetype='pdf') as document:
        text = ''.join(p.get_text() for p in document)
        for value in ['Business opportunity', 'Partial simulation', 'round 37', 'S$14', 'Café', 'Pilot', 'First condition']:
            assert value in text
        assert any(link.get('uri') == 'https://example.com/evidence' for p in document for link in p.get_links())
        assert document.metadata['title'] == 'Business opportunity'


@pytest.mark.parametrize('status', [ReportStatus.GENERATING, ReportStatus.FAILED])
def test_incomplete_report_cannot_be_downloaded_as_a_finished_pdf(monkeypatch, status):
    report = saved_report(); report.status = status
    assert download(monkeypatch, report).status_code == 409


def test_missing_report_and_unknown_format_are_visible_errors(monkeypatch):
    assert download(monkeypatch).status_code == 404
    assert download(monkeypatch, saved_report(), '?format=exe').status_code == 400


def test_long_pdf_retains_last_section_and_page_numbers(monkeypatch):
    report = saved_report()
    report.markdown_content += '\n\n'.join('## Finding '+str(i)+'\n\n'+'Detailed evidence from the recorded simulation. '*30 for i in range(15))
    report.markdown_content += '\n\nFINAL EVIDENCE MARKER'
    response = download(monkeypatch, report)
    with pymupdf.open(stream=response.get_data(), filetype='pdf') as document:
        assert len(document) > 2
        assert 'FINAL EVIDENCE MARKER' in document[-1].get_text()
        for index,page in enumerate(document):
            assert f'{index+1} / {len(document)}' in page.get_text()


def test_separate_ordered_lists_preserve_their_start_numbers(monkeypatch):
    report = saved_report()
    report.markdown_content = '# Decisions\n\n1. First gate\n\nA supporting paragraph.\n\n2. Second gate\n\nAnother paragraph.\n\n3. Third gate\n'
    response = download(monkeypatch, report)
    with pymupdf.open(stream=response.get_data(), filetype='pdf') as document:
        text = ''.join(p.get_text() for p in document)
        assert '2. Second gate' in text
        assert '3. Third gate' in text
