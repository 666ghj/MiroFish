import importlib.util
import sys
from datetime import date
from pathlib import Path

module_path = Path(__file__).resolve().parents[1] / "app" / "services" / "corpus_slimmer.py"
if module_path.exists():
    spec = importlib.util.spec_from_file_location("corpus_slimmer", module_path)
    corpus_slimmer = importlib.util.module_from_spec(spec)
    sys.modules["corpus_slimmer"] = corpus_slimmer
    spec.loader.exec_module(corpus_slimmer)
    build_recent_corpus = corpus_slimmer.build_recent_corpus
    detect_document_date = corpus_slimmer.detect_document_date
    parse_document_sections = corpus_slimmer.parse_document_sections
    subtract_years = corpus_slimmer.subtract_years
else:
    def _missing(*args, **kwargs):
        raise NotImplementedError("corpus_slimmer.py is missing")

    build_recent_corpus = _missing
    detect_document_date = _missing
    parse_document_sections = _missing
    subtract_years = _missing


def test_parse_document_sections_preserves_order_and_content():
    text = "=== a.txt ===\nA\n\n=== b.md ===\nB\n"
    sections = parse_document_sections(text)
    assert [(section.name, section.content) for section in sections] == [
        ("a.txt", "A\n\n"),
        ("b.md", "B\n"),
    ]


def test_parse_document_sections_rejects_text_without_headers():
    try:
        parse_document_sections("plain text")
    except ValueError as error:
        assert "header" in str(error).lower()
    else:
        raise AssertionError("text without document headers must fail")


def test_detect_document_date_handles_cutoff_and_month():
    cutoff = date(2023, 8, 27)
    assert detect_document_date("2023-08-27-公告.txt", cutoff).included_by_date is True
    assert detect_document_date("2023-08-26-公告.txt", cutoff).included_by_date is False

    month = detect_document_date("2024-02-研报.txt", cutoff)
    assert month.detected_date == date(2024, 2, 29)
    assert month.source == "filename_year_month"


def test_detect_document_date_handles_year_ambiguity_and_undated():
    cutoff = date(2023, 8, 27)
    assert detect_document_date("2024-访谈.txt", cutoff).included_by_date is True

    ambiguous = detect_document_date("2023-访谈.txt", cutoff)
    assert ambiguous.detected_date is None
    assert ambiguous.reason == "ambiguous_date"

    undated = detect_document_date("研究总索引.md", cutoff)
    assert undated.detected_date is None
    assert undated.reason == "undated"


def test_detect_document_date_uses_latest_of_multiple_full_dates():
    decision = detect_document_date(
        "2022-01-01至2025-06-30-评级历史.txt",
        date(2023, 8, 27),
    )
    assert decision.detected_date == date(2025, 6, 30)
    assert decision.source == "latest_date_fallback"
    assert decision.included_by_date is True


def test_build_recent_corpus_excludes_duplicate_reports_and_indexes():
    source = """=== 01_法定披露__2025-04-23-泡泡玛特2024年年度报告.txt ===
full annual report
=== 01_法定披露__2025-03-26-泡泡玛特2024年度业绩公告.txt ===
results announcement
=== 02_会议__2025-03-26-年度业绩会纪要.txt ===
meeting notes
=== 00_索引__会议覆盖矩阵-2024-2026.md ===
index
=== 03_券商__2024-10-08-华泰证券研报.txt ===
broker research
=== 07_历史基线__2025-01-01-旧资料.md ===
historical baseline
=== 02_会议__2022-06-01-旧会议.txt ===
old meeting
"""

    result = build_recent_corpus(
        source,
        cutoff=date(2023, 8, 27),
        exclude_full_reports=True,
    )

    included_names = [item.name for item in result.documents if item.included]
    assert included_names == [
        "01_法定披露__2025-03-26-泡泡玛特2024年度业绩公告.txt",
        "02_会议__2025-03-26-年度业绩会纪要.txt",
        "03_券商__2024-10-08-华泰证券研报.txt",
    ]
    assert "full annual report" not in result.text
    assert "results announcement" in result.text
    reasons = {item.name: item.reason for item in result.documents}
    assert reasons["01_法定披露__2025-04-23-泡泡玛特2024年年度报告.txt"] == "duplicate_full_report"
    assert reasons["00_索引__会议覆盖矩阵-2024-2026.md"] == "index_or_matrix"
    assert reasons["07_历史基线__2025-01-01-旧资料.md"] == "historical_baseline"
    assert reasons["02_会议__2022-06-01-旧会议.txt"] == "outside_window"


def test_build_recent_corpus_does_not_mutate_source():
    source = "=== 2025-01-01-a.txt ===\nA\n"
    original = source[:]
    build_recent_corpus(source, cutoff=date(2023, 8, 27), exclude_full_reports=True)
    assert source == original


def test_subtract_years_handles_leap_day():
    assert subtract_years(date(2026, 8, 27), 3) == date(2023, 8, 27)
    assert subtract_years(date(2024, 2, 29), 1) == date(2023, 2, 28)
    try:
        subtract_years(date(2026, 8, 27), 0)
    except ValueError:
        pass
    else:
        raise AssertionError("years must be positive")
