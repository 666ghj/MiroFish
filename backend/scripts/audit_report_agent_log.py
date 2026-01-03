"""
Audit ReportAgent structured logs (agent_log.jsonl).

Checks:
- tool_call entries that do not have a matching tool_result (by tool_call_id)
- tool_result entries without a preceding tool_call (by tool_call_id)
- section/subsection content entries that were finalized with too few tool calls

Usage:
  python3 backend/scripts/audit_report_agent_log.py report_XXXXXXXXXXXX
"""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from typing import Any, Dict, List, Tuple


def _load_jsonl(path: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return items


def _report_id_to_log_path(repo_root: str, report_id: str) -> str:
    return os.path.join(repo_root, "backend", "uploads", "reports", report_id, "agent_log.jsonl")


def audit_agent_log(entries: List[Dict[str, Any]], *, min_tool_calls_per_section: int) -> Tuple[int, str]:
    tool_calls_by_id: Dict[str, Dict[str, Any]] = {}
    tool_results_by_id: Dict[str, Dict[str, Any]] = {}

    calls_without_id: List[Dict[str, Any]] = []
    results_without_id: List[Dict[str, Any]] = []

    per_section_call_counts: Dict[int, int] = defaultdict(int)
    per_section_result_counts: Dict[int, int] = defaultdict(int)
    finalized_sections: Dict[int, int] = {}

    for entry in entries:
        action = entry.get("action")
        section_index = entry.get("section_index")
        details = entry.get("details") or {}

        if action == "tool_call":
            tc_id = details.get("tool_call_id")
            if isinstance(section_index, int):
                per_section_call_counts[section_index] += 1
            if tc_id:
                tool_calls_by_id[str(tc_id)] = entry
            else:
                calls_without_id.append(entry)

        elif action == "tool_result":
            tc_id = details.get("tool_call_id")
            if isinstance(section_index, int):
                per_section_result_counts[section_index] += 1
            if tc_id:
                tool_results_by_id[str(tc_id)] = entry
            else:
                results_without_id.append(entry)

        elif action in ("section_content", "subsection_content"):
            tool_calls_count = details.get("tool_calls_count")
            if isinstance(section_index, int) and isinstance(tool_calls_count, int):
                finalized_sections[section_index] = tool_calls_count

    missing_results = [tc_id for tc_id in tool_calls_by_id.keys() if tc_id not in tool_results_by_id]
    orphan_results = [tc_id for tc_id in tool_results_by_id.keys() if tc_id not in tool_calls_by_id]

    sections_below_min = sorted(
        [
            (section_idx, count)
            for section_idx, count in finalized_sections.items()
            if count < min_tool_calls_per_section
        ],
        key=lambda x: x[0],
    )

    lines: List[str] = []
    lines.append("ReportAgent Log Audit")
    lines.append(f"- tool_calls: {len(tool_calls_by_id)} (no-id: {len(calls_without_id)})")
    lines.append(f"- tool_results: {len(tool_results_by_id)} (no-id: {len(results_without_id)})")
    lines.append(f"- missing tool_results (by tool_call_id): {len(missing_results)}")
    lines.append(f"- orphan tool_results (by tool_call_id): {len(orphan_results)}")
    lines.append(f"- finalized sections below min({min_tool_calls_per_section}): {len(sections_below_min)}")

    if missing_results:
        lines.append("")
        lines.append("Missing tool_result IDs:")
        for tc_id in missing_results[:50]:
            entry = tool_calls_by_id.get(tc_id) or {}
            details = entry.get("details") or {}
            lines.append(
                f"- {tc_id} section_index={entry.get('section_index')} tool={details.get('tool_name')} iteration={details.get('iteration')}"
            )
        if len(missing_results) > 50:
            lines.append(f"- ... ({len(missing_results) - 50} more)")

    if orphan_results:
        lines.append("")
        lines.append("Orphan tool_result IDs:")
        for tc_id in orphan_results[:50]:
            entry = tool_results_by_id.get(tc_id) or {}
            details = entry.get("details") or {}
            lines.append(
                f"- {tc_id} section_index={entry.get('section_index')} tool={details.get('tool_name')} iteration={details.get('iteration')}"
            )
        if len(orphan_results) > 50:
            lines.append(f"- ... ({len(orphan_results) - 50} more)")

    if sections_below_min:
        lines.append("")
        lines.append("Sections below minimum tool calls:")
        for section_idx, count in sections_below_min[:100]:
            lines.append(f"- section_index={section_idx} tool_calls_count={count}")
        if len(sections_below_min) > 100:
            lines.append(f"- ... ({len(sections_below_min) - 100} more)")

    has_issues = bool(missing_results or orphan_results or sections_below_min)
    exit_code = 1 if has_issues else 0
    return exit_code, "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit backend/uploads/reports/<report_id>/agent_log.jsonl")
    parser.add_argument("report_id", help="Report id (e.g. report_864e8454d0b2)")
    parser.add_argument(
        "--repo-root",
        default=os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")),
        help="Repository root path (default: auto-detected)",
    )
    parser.add_argument("--min-tool-calls", type=int, default=2, help="Minimum tool calls per section (default: 2)")
    args = parser.parse_args()

    log_path = _report_id_to_log_path(args.repo_root, args.report_id)
    if not os.path.exists(log_path):
        raise SystemExit(f"agent_log.jsonl not found: {log_path}")

    entries = _load_jsonl(log_path)
    exit_code, report = audit_agent_log(entries, min_tool_calls_per_section=args.min_tool_calls)
    print(report, end="")
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()

