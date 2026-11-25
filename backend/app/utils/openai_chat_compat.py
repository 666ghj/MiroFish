"""
OpenAI Chat Completions compatibility helpers.

This module keeps existing behavior for legacy models/providers while
gracefully adapting request parameters for GPT-5 family models.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


CLAUDE_MIN_MAX_TOKENS = 4096


def is_gpt5_family(model: Optional[str]) -> bool:
    """Return True when model belongs to GPT-5 family aliases/snapshots."""
    if not model:
        return False
    return model.strip().lower().startswith("gpt-5")


def is_claude_family(model: Optional[str]) -> bool:
    """Return True for Anthropic Claude models served via the OpenAI-compatible API."""
    if not model:
        return False
    return model.strip().lower().startswith("claude")


def _claude_response_format(
    response_format: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Claude's compatibility endpoint accepts only json_schema; anything else is a 400.

    Dropping json_object/text leaves the prompt's own JSON instructions in charge,
    which is the same fallback LLMClient.chat_json uses for other providers.
    """
    if response_format and response_format.get("type") == "json_schema":
        return response_format
    return None


def create_chat_completion(
    client: Any,
    *,
    model: str,
    messages: List[Dict[str, Any]],
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    response_format: Optional[Dict[str, Any]] = None,
) -> Any:
    """
    Create a chat completion with model-specific request parameters.

    Compatibility strategy:
    - For GPT-5 family, avoid sending temperature by default.
    - For token limit, use `max_completion_tokens` on GPT-5, `max_tokens` otherwise.
    - Preserve the legacy request shape for every non-GPT-5 model/provider.
    - Propagate provider errors unchanged instead of guessing from message text.
    """
    kwargs: Dict[str, Any] = {
        "model": model,
        "messages": messages,
    }

    claude_family = is_claude_family(model)
    if claude_family:
        response_format = _claude_response_format(response_format)

    if response_format is not None:
        kwargs["response_format"] = response_format

    gpt5_family = is_gpt5_family(model)

    # Current Claude models reject any temperature below 1, so omit it for them.
    if temperature is not None and not gpt5_family and not claude_family:
        kwargs["temperature"] = temperature

    # Claude counts its hidden reasoning against max_tokens, so a small cap can
    # be used up before any visible text is produced and the reply comes back
    # empty. The floor only raises the ceiling; prompts still set the length.
    if claude_family and max_tokens is not None:
        max_tokens = max(max_tokens, CLAUDE_MIN_MAX_TOKENS)

    if max_tokens is not None:
        if gpt5_family:
            kwargs["max_completion_tokens"] = max_tokens
        else:
            kwargs["max_tokens"] = max_tokens

    return client.chat.completions.create(**kwargs)


def extract_chat_completion_text(response: Any) -> str:
    """Extract plain text from chat completion response across SDK content shapes."""
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""

    message = getattr(choices[0], "message", None)
    if message is None:
        return ""

    content = getattr(message, "content", "")

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        chunks: List[str] = []
        for item in content:
            if isinstance(item, dict):
                text_obj = item.get("text")
                if isinstance(text_obj, dict):
                    text_obj = text_obj.get("value")
                if isinstance(text_obj, str):
                    chunks.append(text_obj)
                elif isinstance(item.get("content"), str):
                    chunks.append(item["content"])
                continue

            text_obj = getattr(item, "text", None)
            if isinstance(text_obj, dict):
                text_obj = text_obj.get("value")
            if isinstance(text_obj, str):
                chunks.append(text_obj)
                continue

            content_obj = getattr(item, "content", None)
            if isinstance(content_obj, str):
                chunks.append(content_obj)

        return "".join(chunks).strip()

    return str(content or "")
