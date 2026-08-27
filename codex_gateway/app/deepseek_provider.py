"""DeepSeek fallback provider."""

from __future__ import annotations

import copy
import json
from typing import Any

from .codex_provider import ProviderResult


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

    def complete(self, request: dict[str, Any]) -> ProviderResult:
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

        response = self._client.chat.completions.create(**kwargs)
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
