"""DeepSeek fallback provider."""

from __future__ import annotations

import copy
import json
import threading
from typing import Any

from .codex_provider import ProviderResult


class FallbackUnavailableError(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(f"fallback unavailable: {reason}")
        self.reason = reason


class DeepSeekProvider:
    _SUPPORTED_FIELDS = {
        "messages",
        "temperature",
        "max_tokens",
        "response_format",
        "tools",
        "tool_choice",
        "stop",
    }

    def __init__(self, *, client: Any, model: str) -> None:
        self._client = client
        self._model = model
        self._circuit_reason: str | None = None
        self._circuit_lock = threading.Lock()

    def complete(self, request: dict[str, Any]) -> ProviderResult:
        with self._circuit_lock:
            if self._circuit_reason is not None:
                raise FallbackUnavailableError(self._circuit_reason)

        kwargs = {
            key: value
            for key, value in request.items()
            if key in self._SUPPORTED_FIELDS and value is not None
        }
        kwargs["model"] = self._model
        response_format = kwargs.get("response_format") or {"type": "text"}
        if response_format.get("type") == "json_schema":
            schema = (response_format.get("json_schema") or {}).get("schema")
            if not isinstance(schema, dict):
                raise ValueError("json_schema response format requires a schema")
            messages = copy.deepcopy(kwargs.get("messages") or [])
            instruction = (
                "\nReturn only valid JSON matching this JSON Schema exactly:\n"
                + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
            )
            for message in reversed(messages):
                if message.get("role") == "user":
                    message["content"] = str(message.get("content") or "") + instruction
                    break
            else:
                messages.append({"role": "user", "content": instruction.lstrip()})
            kwargs["messages"] = messages
            kwargs["response_format"] = {"type": "json_object"}

        try:
            response = self._client.chat.completions.create(**kwargs)
        except Exception as error:
            if getattr(error, "status_code", None) == 402:
                with self._circuit_lock:
                    self._circuit_reason = "insufficient_balance"
                raise FallbackUnavailableError("insufficient_balance") from error
            raise
        content = response.choices[0].message.content or ""
        if not content.strip():
            raise ValueError("DeepSeek returned an empty response")
        if response_format.get("type") in {"json_object", "json_schema"}:
            try:
                json.loads(content)
            except json.JSONDecodeError as error:
                raise ValueError("DeepSeek returned invalid JSON") from error
        return ProviderResult(
            content=content,
            model=response.model,
            turn_id=None,
            usage=getattr(response, "usage", None),
        )
