"""
OpenAI Chat Completions compatibility helpers.

This module keeps existing behavior for legacy models/providers while
gracefully adapting request parameters for GPT-5 family models.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple


logger = logging.getLogger(__name__)

JSON_OBJECT_RESPONSE_FORMAT: Dict[str, str] = {"type": "json_object"}

_UNSUPPORTED_RESPONSE_FORMAT_CODES = {
    "unsupported_parameter",
    "unsupported_value",
    "unknown_parameter",
    "invalid_parameter",
}
_UNSUPPORTED_RESPONSE_FORMAT_PHRASES = (
    "not support",
    "unsupported",
    "unknown parameter",
    "unrecognized parameter",
    # LM Studio: "'response_format.type' must be 'json_schema' or 'text'"
    "must be",
)


def is_gpt5_family(model: Optional[str]) -> bool:
    """Return True when model belongs to GPT-5 family aliases/snapshots."""
    if not model:
        return False
    return model.strip().lower().startswith("gpt-5")


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

    if response_format is not None:
        kwargs["response_format"] = response_format

    gpt5_family = is_gpt5_family(model)

    if temperature is not None and not gpt5_family:
        kwargs["temperature"] = temperature

    if max_tokens is not None:
        if gpt5_family:
            kwargs["max_completion_tokens"] = max_tokens
        else:
            kwargs["max_tokens"] = max_tokens

    return client.chat.completions.create(**kwargs)


def is_response_format_unsupported(error: Exception) -> bool:
    """Detect an explicit provider rejection of JSON response_format.

    Accepts OpenAI-style error objects as well as providers that report the
    error as a plain string, e.g. LM Studio's
    ``{"error": "'response_format.type' must be 'json_schema' or 'text'"}``
    (which the OpenAI SDK exposes as ``error.body == "<message>"``).
    """

    if getattr(error, "status_code", None) not in {400, 422}:
        return False

    details = getattr(error, "body", None)
    if isinstance(details, dict):
        details = details.get("error", details)
    if isinstance(details, str):
        details = {"message": details}
    if not isinstance(details, dict):
        return False

    param = str(details.get("param") or "").strip().lower()
    if param == "response_format" or param.startswith("response_format."):
        return True

    message = str(details.get("message") or "").lower()
    if "response_format" not in message:
        return False

    code = str(details.get("code") or "").lower()
    return code in _UNSUPPORTED_RESPONSE_FORMAT_CODES or any(
        phrase in message for phrase in _UNSUPPORTED_RESPONSE_FORMAT_PHRASES
    )


def create_json_chat_completion(
    client: Any,
    *,
    model: str,
    messages: List[Dict[str, Any]],
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    json_mode: bool = True,
) -> Tuple[Any, bool]:
    """
    Request a JSON object, degrading to prompt-only JSON guidance when the
    provider explicitly rejects ``response_format``.

    Returns ``(response, json_mode)``. Callers should pass the returned
    ``json_mode`` into their next request so a provider that rejected
    ``response_format`` is not asked again for every entity. Any other
    provider error is propagated unchanged.
    """
    if json_mode:
        try:
            response = create_chat_completion(
                client,
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=JSON_OBJECT_RESPONSE_FORMAT,
            )
            return response, True
        except Exception as error:
            if not is_response_format_unsupported(error):
                raise
            logger.warning(
                "LLM provider explicitly rejected response_format; "
                "retrying with prompt-only JSON guidance"
            )

    response = create_chat_completion(
        client,
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response, False


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
