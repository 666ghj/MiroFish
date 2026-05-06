"""Patch OpenAI chat completion calls in simulation scripts for centralized cost logging."""

from __future__ import annotations

import copy
from typing import Any, Dict, Optional

from app.utils.llm_cost import record_llm_cost


_PATCHED = False
_PATCH_CONTEXT: Dict[str, Any] = {}


def _build_metadata(model: str) -> Dict[str, Any]:
    metadata = copy.deepcopy(_PATCH_CONTEXT)
    metadata.setdefault("component", "scripts.simulation")
    metadata.setdefault("phase", "simulation_run")
    metadata.setdefault("model", model)
    return metadata


def _normalize_messages_for_qwen(messages: Any) -> Any:
    """Ensure Qwen-compatible ordering: a single system message at index 0."""
    if not isinstance(messages, list):
        return messages

    if not messages:
        return messages

    system_contents = []
    non_system_messages = []

    for item in messages:
        if isinstance(item, dict) and str(item.get("role", "")).lower() == "system":
            content = item.get("content")
            if content is not None and str(content).strip():
                system_contents.append(str(content))
            continue
        non_system_messages.append(item)

    # No system messages detected, keep original payload.
    if not system_contents:
        return messages

    merged_system = {
        "role": "system",
        "content": "\n\n".join(system_contents),
    }
    return [merged_system] + non_system_messages


def install_openai_cost_patch(
    *,
    simulation_id: Optional[str],
    project_id: Optional[str],
    platform: str,
    component: str,
    phase: str = "simulation_run",
) -> None:
    """
    Install monkey-patch for OpenAI SDK calls used indirectly by CAMEL/OASIS.

    The patch is process-scoped and idempotent.
    """
    global _PATCHED
    global _PATCH_CONTEXT

    _PATCH_CONTEXT = {
        "simulation_id": simulation_id,
        "project_id": project_id,
        "platform": platform,
        "component": component,
        "phase": phase,
    }

    if _PATCHED:
        return

    try:
        from openai.resources.chat.completions.completions import Completions, AsyncCompletions
    except Exception as exc:  # pragma: no cover
        print(f"[llm_cost_patch] Failed to import OpenAI completion classes: {exc}")
        return

    original_sync_create = Completions.create
    original_async_create = AsyncCompletions.create

    def sync_create_wrapper(self, *args, **kwargs):
        model = kwargs.get("model", "unknown_model")
        if "qwen" in str(model).lower() and "messages" in kwargs:
            kwargs = dict(kwargs)
            kwargs["messages"] = _normalize_messages_for_qwen(kwargs.get("messages"))
        response = original_sync_create(self, *args, **kwargs)
        try:
            record_llm_cost(
                model_name=model,
                usage=getattr(response, "usage", None),
                metadata=_build_metadata(model),
            )
        except Exception as exc:
            print(f"[llm_cost_patch] Failed to record sync cost: {exc}")
        return response

    async def async_create_wrapper(self, *args, **kwargs):
        model = kwargs.get("model", "unknown_model")
        if "qwen" in str(model).lower() and "messages" in kwargs:
            kwargs = dict(kwargs)
            kwargs["messages"] = _normalize_messages_for_qwen(kwargs.get("messages"))
        response = await original_async_create(self, *args, **kwargs)
        try:
            record_llm_cost(
                model_name=model,
                usage=getattr(response, "usage", None),
                metadata=_build_metadata(model),
            )
        except Exception as exc:
            print(f"[llm_cost_patch] Failed to record async cost: {exc}")
        return response

    Completions.create = sync_create_wrapper
    AsyncCompletions.create = async_create_wrapper
    _PATCHED = True
