"""Deterministic, auditable corpus slimming for dated project documents."""

from __future__ import annotations

import calendar
import json
import os
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path


_HEADER_PATTERN = re.compile(r"^=== (.*?) ===\n", re.MULTILINE)
_FULL_DATE_PATTERN = re.compile(
    r"(?<!\d)(20\d{2})[-_/年](\d{1,2})[-_/月](\d{1,2})(?:日)?(?!\d)"
)
_YEAR_MONTH_PATTERN = re.compile(r"(?<!\d)(20\d{2})[-_/年](\d{1,2})(?:月)?(?!\d)")
_YEAR_PATTERN = re.compile(r"(?<!\d)(20\d{2})(?!\d)")


@dataclass(frozen=True)
class DocumentSection:
    name: str
    content: str


@dataclass(frozen=True)
class DateDecision:
    detected_date: date | None
    source: str
    reason: str | None
    included_by_date: bool


@dataclass(frozen=True)
class CorpusDocumentDecision:
    name: str
    detected_date: str | None
    date_source: str
    included: bool
    reason: str
    characters: int


@dataclass(frozen=True)
class CorpusBuildResult:
    text: str
    documents: tuple[CorpusDocumentDecision, ...]
    total_sections: int
    included_sections: int
    excluded_sections: int
    source_characters: int
    output_characters: int


@dataclass(frozen=True)
class CorpusArtifacts:
    output_path: Path
    manifest_path: Path
    summary: dict


def subtract_years(value: date, years: int) -> date:
    if years <= 0:
        raise ValueError("years must be positive")
    try:
        return value.replace(year=value.year - years)
    except ValueError:
        return value.replace(year=value.year - years, month=2, day=28)


def parse_document_sections(text: str) -> list[DocumentSection]:
    matches = list(_HEADER_PATTERN.finditer(text))
    if not matches:
        raise ValueError("document header not found")
    if text[: matches[0].start()].strip():
        raise ValueError("content exists before first document header")

    sections = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections.append(DocumentSection(name=match.group(1), content=text[match.end() : end]))
    return sections


def detect_document_date(name: str, cutoff: date) -> DateDecision:
    full_dates = []
    for year, month, day in _FULL_DATE_PATTERN.findall(name):
        try:
            full_dates.append(date(int(year), int(month), int(day)))
        except ValueError:
            continue
    if full_dates:
        detected = max(full_dates)
        source = "filename_full_date" if len(full_dates) == 1 else "latest_date_fallback"
        return DateDecision(detected, source, None, detected >= cutoff)

    year_months = []
    for year, month in _YEAR_MONTH_PATTERN.findall(name):
        try:
            last_day = calendar.monthrange(int(year), int(month))[1]
            year_months.append(date(int(year), int(month), last_day))
        except (ValueError, calendar.IllegalMonthError):
            continue
    if year_months:
        detected = max(year_months)
        source = "filename_year_month" if len(year_months) == 1 else "latest_date_fallback"
        return DateDecision(detected, source, None, detected >= cutoff)

    years = sorted({int(year) for year in _YEAR_PATTERN.findall(name)})
    if len(years) == 1:
        year = years[0]
        if year == cutoff.year:
            return DateDecision(None, "filename_year", "ambiguous_date", False)
        detected = date(year, 12, 31)
        return DateDecision(detected, "filename_year", None, detected >= cutoff)
    if len(years) > 1:
        detected = date(max(years), 12, 31)
        return DateDecision(detected, "latest_year_fallback", None, detected >= cutoff)
    return DateDecision(None, "none", "undated", False)


def _category_exclusion_reason(name: str, exclude_full_reports: bool) -> str | None:
    if name.startswith("00_索引") or any(
        marker in name for marker in ("覆盖矩阵", "元数据库", "研究总索引")
    ):
        return "index_or_matrix"
    if name.startswith("07_历史基线"):
        return "historical_baseline"
    if exclude_full_reports and "业绩" not in name and any(
        marker in name for marker in ("年度报告", "中期报告")
    ):
        return "duplicate_full_report"
    return None


def build_recent_corpus(
    text: str,
    *,
    cutoff: date,
    exclude_full_reports: bool,
) -> CorpusBuildResult:
    sections = parse_document_sections(text)
    decisions = []
    included_sections = []

    for section in sections:
        date_decision = detect_document_date(section.name, cutoff)
        reason = _category_exclusion_reason(section.name, exclude_full_reports)
        if reason is None and not date_decision.included_by_date:
            reason = date_decision.reason or "outside_window"
        included = reason is None
        if included:
            reason = "within_window"
            included_sections.append(section)
        decisions.append(
            CorpusDocumentDecision(
                name=section.name,
                detected_date=(
                    date_decision.detected_date.isoformat()
                    if date_decision.detected_date
                    else None
                ),
                date_source=date_decision.source,
                included=included,
                reason=reason,
                characters=len(section.content),
            )
        )

    output = "".join(
        f"=== {section.name} ===\n{section.content}"
        for section in included_sections
    )
    return CorpusBuildResult(
        text=output,
        documents=tuple(decisions),
        total_sections=len(sections),
        included_sections=len(included_sections),
        excluded_sections=len(sections) - len(included_sections),
        source_characters=len(text),
        output_characters=len(output),
    )


def _write_synced_temp(path: Path, content: str) -> Path:
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temp.open("w", encoding="utf-8") as file:
        file.write(content)
        file.flush()
        os.fsync(file.fileno())
    return temp


def write_recent_corpus(
    project_dir: Path,
    result: CorpusBuildResult,
    *,
    cutoff: date,
    generated_at: str | None = None,
) -> CorpusArtifacts:
    if result.included_sections == 0 or not result.text:
        raise ValueError("derived corpus is empty")

    project_dir = Path(project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)
    output_path = project_dir / "extracted_text_recent_3y.txt"
    manifest_path = project_dir / "corpus_recent_3y_manifest.json"
    summary = {
        "total_sections": result.total_sections,
        "included_sections": result.included_sections,
        "excluded_sections": result.excluded_sections,
        "source_characters": result.source_characters,
        "output_characters": result.output_characters,
    }
    manifest = {
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "cutoff_date": cutoff.isoformat(),
        "source_file": "extracted_text.txt",
        "output_file": output_path.name,
        "summary": summary,
        "documents": [asdict(document) for document in result.documents],
    }

    output_temp = None
    manifest_temp = None
    try:
        output_temp = _write_synced_temp(output_path, result.text)
        manifest_temp = _write_synced_temp(
            manifest_path,
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        )
        os.replace(output_temp, output_path)
        output_temp = None
        os.replace(manifest_temp, manifest_path)
        manifest_temp = None
    finally:
        for temp in (output_temp, manifest_temp):
            if temp is not None and temp.exists():
                temp.unlink()

    return CorpusArtifacts(output_path, manifest_path, summary)
