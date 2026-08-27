"""Redact credentials and prompt bodies before structured logging."""

from __future__ import annotations

from typing import Any


_SENSITIVE_KEY_PARTS = (
    "authorization",
    "access_token",
    "refresh_token",
    "api_key",
    "password",
    "secret",
)


def redact_log_value(value: Any) -> Any:
    if isinstance(value, dict):
        if "role" in value and "content" in value:
            return {
                "role": value.get("role"),
                "content_length": len(str(value.get("content") or "")),
            }
        redacted = {}
        for key, item in value.items():
            normalized = str(key).lower()
            if any(part in normalized for part in _SENSITIVE_KEY_PARTS):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = redact_log_value(item)
        return redacted
    if isinstance(value, list):
        return [redact_log_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_log_value(item) for item in value)
    return value
