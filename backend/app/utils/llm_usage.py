"""
LLM usage log aggregation.

We write per-request usage records to `llm_usage.jsonl` files (JSON lines).
This module provides helpers to aggregate those logs for the UI.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Iterator, List, Optional, Tuple

from ..config import Config


def find_usage_log_paths(root_dir: Optional[str] = None) -> List[str]:
    base = root_dir or Config.UPLOAD_FOLDER
    paths: List[str] = []
    if not base or not os.path.exists(base):
        return paths
    for dirpath, _dirnames, filenames in os.walk(base):
        if "llm_usage.jsonl" in filenames:
            paths.append(os.path.join(dirpath, "llm_usage.jsonl"))
    paths.sort()
    return paths


def iter_usage_records(paths: List[str], *, max_records: Optional[int] = None) -> Iterator[Dict[str, Any]]:
    remaining = max_records
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    if remaining is not None and remaining <= 0:
                        return
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(record, dict):
                        yield record
                        if remaining is not None:
                            remaining -= 1
        except OSError:
            continue


def _extract_tokens(usage: Any) -> Tuple[int, int, int]:
    if not isinstance(usage, dict):
        return 0, 0, 0

    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    total = usage.get("total_tokens")

    # Some gateways use input/output naming.
    if prompt is None and "input_tokens" in usage:
        prompt = usage.get("input_tokens")
    if completion is None and "output_tokens" in usage:
        completion = usage.get("output_tokens")

    try:
        prompt_i = int(prompt or 0)
    except Exception:
        prompt_i = 0
    try:
        completion_i = int(completion or 0)
    except Exception:
        completion_i = 0

    if total is None:
        total_i = prompt_i + completion_i
    else:
        try:
            total_i = int(total or 0)
        except Exception:
            total_i = prompt_i + completion_i

    return prompt_i, completion_i, total_i


def aggregate_usage(records: Iterator[Dict[str, Any]]) -> Dict[str, Any]:
    totals_by_model: Dict[str, Dict[str, int]] = {}
    totals_by_stage: Dict[str, Dict[str, int]] = {}
    total_requests = 0
    total_errors = 0

    for r in records:
        model = str(r.get("model") or "unknown")
        stage = str(r.get("stage") or "unknown")
        usage = r.get("usage")
        prompt_t, completion_t, total_t = _extract_tokens(usage)
        is_error = str(r.get("event") or "") == "error" or not isinstance(usage, dict)

        total_requests += 1
        if is_error:
            total_errors += 1

        m = totals_by_model.setdefault(
            model,
            {"requests": 0, "errors": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        )
        m["requests"] += 1
        if is_error:
            m["errors"] += 1
        m["prompt_tokens"] += prompt_t
        m["completion_tokens"] += completion_t
        m["total_tokens"] += total_t

        s = totals_by_stage.setdefault(
            stage,
            {"requests": 0, "errors": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        )
        s["requests"] += 1
        if is_error:
            s["errors"] += 1
        s["prompt_tokens"] += prompt_t
        s["completion_tokens"] += completion_t
        s["total_tokens"] += total_t

    return {
        "total_requests": total_requests,
        "total_errors": total_errors,
        "totals_by_model": totals_by_model,
        "totals_by_stage": totals_by_stage,
    }
