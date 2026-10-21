import pytest
from app.services.report_agent import ReportManager, ReportOutline, ReportSection


@pytest.mark.parametrize('block', [
    '```python\n# literal comment\n\n\n\nvalue = 1\n```',
    '~~~yaml\n## literal key\n---\n~~~',
    '````text\n```\n# literal comment\n````',
    '~~~text\n```\n# literal comment\n~~~',
    '   ```text\n# literal comment\n   ```',
    '```text\n# literal comment\n\n\n\nend of unclosed block',
])
def test_saved_and_assembled_report_preserves_literal_code(tmp_path, monkeypatch, block):
    monkeypatch.setattr(ReportManager, 'REPORTS_DIR', str(tmp_path))
    section = ReportSection(title='Evidence', content='## Evidence\n\n' + block)
    outline = ReportOutline(title='Report', summary='Summary', sections=[section])
    saved = ReportManager.save_section('report-fixture', 1, section)
    with open(saved, encoding='utf-8') as stream:
        assert block in stream.read()
    assembled = ReportManager.assemble_full_report('report-fixture', outline)
    assert block in assembled
    assert assembled.count('## Evidence') == 1


def test_literal_heading_is_not_a_previous_real_heading():
    outline = ReportOutline(title='Report', summary='', sections=[])
    content = '```text\n# Outside\n```\n## Outside'
    result = ReportManager._post_process_report(content, outline)
    assert '```text\n# Outside\n```' in result
    assert result.endswith('**Outside**\n')


def test_regular_heading_cleanup_still_applies():
    content = '## Evidence\n\n### Detail\n\ntext'
    assert ReportManager._clean_section_content(content, 'Evidence') == '**Detail**\n\n\ntext'


def test_crlf_fence_does_not_capture_later_prose():
    content = '```text\r\n# literal\r\n```\r\n### Actual heading'
    result = ReportManager._clean_section_content(content, 'Evidence')
    assert '```text\r\n# literal\r\n```\r' in result
    assert '**Actual heading**' in result


def test_initial_fence_indentation_is_preserved():
    content = '   ```text\n   # literal\n   ```'
    assert ReportManager._clean_section_content(content, 'Evidence') == content


def test_unclosed_code_keeps_trailing_literal_blank_lines():
    content = '```text\n# literal\n\n\n\n'
    assert ReportManager._clean_section_content(content, 'Evidence') == content
