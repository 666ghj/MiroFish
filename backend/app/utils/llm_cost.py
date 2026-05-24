"""
Centralized LLM cost tracking utility.

Responsibilities:
1. Calculate token cost per model.
2. Persist cost logs to logs/{project_id}/cost_{model_name}.log.
3. Persist structured JSONL records to logs/{project_id}/cost_{model_name}.jsonl.
4. Provide a single wrapped OpenAI chat-completion call so all components can reuse
   one cost-accounting flow.
"""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Optional


MODEL_COSTS_PER_1M_TOKENS: Dict[str, Dict[str, float]] = {
    "Qwen/Qwen3.5-27B": {"input": 0.5, "output": 3.0},
    "Qwen/Qwen3.6-27B": {"input": 0.5, "output": 3.0},
    "gemini-3-flash": {"input": 0.5, "output": 3.0},
    "gemini-3.1-flash-lite": {"input": 0.25, "output": 1.5},
}


_COUNTER_LOCK = threading.Lock()
_COUNTERS: Dict[str, Dict[str, Decimal]] = {}


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def _quantize_8(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)


def _safe_model_name(model_name: str) -> str:
    if not model_name:
        return "unknown_model"
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", model_name)
    return safe or "unknown_model"


def _resolve_project_id(metadata: Optional[Dict[str, Any]]) -> str:
    metadata = metadata or {}
    value = metadata.get("project_id")
    if value is not None and str(value).strip():
        return str(value).strip()
    return "global"


def _resolve_component(metadata: Optional[Dict[str, Any]]) -> str:
    metadata = metadata or {}
    component = metadata.get("component")
    if component is None:
        return "unknown_component"
    component = str(component).strip()
    return component if component else "unknown_component"


def _normalize_usage(usage: Any) -> Dict[str, int]:
    if usage is None:
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
    completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
    total_tokens = int(getattr(usage, "total_tokens", prompt_tokens + completion_tokens) or 0)

    return {
        "input_tokens": prompt_tokens,
        "output_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def _resolve_model_rates(model_name: str) -> Dict[str, Decimal]:
    env_in = os.environ.get("LLM_COST_INPUT_PER_1M")
    env_out = os.environ.get("LLM_COST_OUTPUT_PER_1M")
    if env_in is not None and env_out is not None:
        return {"input": _decimal(env_in), "output": _decimal(env_out)}

    rates = MODEL_COSTS_PER_1M_TOKENS.get(model_name, {"input": 0.0, "output": 0.0})
    return {"input": _decimal(rates.get("input", 0.0)), "output": _decimal(rates.get("output", 0.0))}


def _get_logs_root() -> str:
    # backend/app/utils -> backend/logs
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs")


def _ensure_project_log_dir(project_id: str) -> str:
    root = _get_logs_root()
    project_dir = os.path.join(root, project_id)
    os.makedirs(project_dir, exist_ok=True)
    return project_dir


def _build_log_paths(project_id: str, model_name: str) -> Dict[str, str]:
    project_dir = _ensure_project_log_dir(project_id)
    model_safe = _safe_model_name(model_name)
    return {
        "log": os.path.join(project_dir, f"cost_{model_safe}.log"),
        "jsonl": os.path.join(project_dir, f"cost_{model_safe}.jsonl"),
    }


def _update_counters(counter_key: str, request_cost: Decimal) -> Dict[str, Decimal]:
    with _COUNTER_LOCK:
        current = _COUNTERS.get(counter_key)
        if current is None:
            current = {
                "requests": Decimal("0"),
                "total_cost": Decimal("0"),
            }
        current["requests"] += Decimal("1")
        current["total_cost"] += request_cost
        _COUNTERS[counter_key] = current
        return {
            "requests": current["requests"],
            "total_cost": current["total_cost"],
        }


def record_llm_cost(
    *,
    model_name: str,
    usage: Any,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Calculate and persist LLM usage cost for one request.

    Returns a normalized cost payload that is also written into JSONL.
    """
    metadata = metadata or {}
    timestamp = datetime.now().isoformat()
    project_id = _resolve_project_id(metadata)
    component = _resolve_component(metadata)
    usage_dict = _normalize_usage(usage)

    rates = _resolve_model_rates(model_name)
    input_cost = _quantize_8(_decimal(usage_dict["input_tokens"]) * rates["input"] / _decimal(1_000_000))
    output_cost = _quantize_8(_decimal(usage_dict["output_tokens"]) * rates["output"] / _decimal(1_000_000))
    total_cost = _quantize_8(input_cost + output_cost)

    record = {
        "timestamp": timestamp,
        "model": model_name,
        "input_tokens": usage_dict["input_tokens"],
        "output_tokens": usage_dict["output_tokens"],
        "total_tokens": usage_dict["total_tokens"],
        "input_cost_usd": float(input_cost),
        "output_cost_usd": float(output_cost),
        "total_cost_usd": float(total_cost),
        "metadata": {
            "component": component,
            "simulation_id": metadata.get("simulation_id"),
            "platform": metadata.get("platform"),
            "phase": metadata.get("phase"),
            "project_id": project_id,
            "report_id": metadata.get("report_id"),
        },
    }

    paths = _build_log_paths(project_id=project_id, model_name=model_name)
    counter_key = f"{project_id}::{model_name}"
    counter = _update_counters(counter_key, total_cost)
    request_no = int(counter["requests"])
    cumulative_cost = _quantize_8(counter["total_cost"])

    line = (
        f"[{timestamp}] [Request {request_no}] [{component}] "
        f"Called model: {model_name}, "
        f"input_tokens: {usage_dict['input_tokens']} | "
        f"output_tokens: {usage_dict['output_tokens']} | "
        f"total_tokens: {usage_dict['total_tokens']} | "
        f"input_cost_usd: {float(input_cost):.8f} | "
        f"output_cost_usd: {float(output_cost):.8f} | "
        f"total_cost_usd: {float(total_cost):.8f} | "
        f"cumulative_total_cost_usd: {float(cumulative_cost):.8f}"
    )

    with open(paths["log"], "a", encoding="utf-8") as log_f:
        log_f.write(line + "\n")

    with open(paths["jsonl"], "a", encoding="utf-8") as jsonl_f:
        jsonl_f.write(json.dumps(record, ensure_ascii=False) + "\n")

    return record


def create_tracked_chat_completion(
    *,
    client: Any,
    model: str,
    messages: Any,
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Any:
    """
    Single entry-point for OpenAI-compatible chat completion + cost logging.

    All modules should call this wrapper instead of calling
    client.chat.completions.create directly.
    """
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        **kwargs,
    )
    record_llm_cost(model_name=model, usage=getattr(response, "usage", None), metadata=metadata)
    return response

