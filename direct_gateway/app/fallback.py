from __future__ import annotations

import copy
import json
import threading

from .responses_client import DirectProviderResult


class FallbackUnavailableError(RuntimeError):
    pass


class DeepSeekProvider:
    def __init__(self, *, client, model: str) -> None:
        self.client = client
        self.model = model
        self._disabled = False
        self._lock = threading.Lock()

    def complete(self, request: dict) -> DirectProviderResult:
        with self._lock:
            if self._disabled:
                raise FallbackUnavailableError("insufficient_balance")
        payload = copy.deepcopy(request)
        response_format = payload.get("response_format") or {"type": "text"}
        if response_format.get("type") == "json_schema":
            schema = (response_format.get("json_schema") or {}).get("schema")
            payload["messages"][-1]["content"] += "\n仅返回符合以下 JSON Schema 的 JSON：" + json.dumps(schema, ensure_ascii=False)
            payload["response_format"] = {"type": "json_object"}
        try:
            response = self.client.chat.completions.create(model=self.model, messages=payload["messages"], response_format=payload.get("response_format"))
        except Exception as error:
            if getattr(error, "status_code", None) == 402:
                with self._lock:
                    self._disabled = True
                raise FallbackUnavailableError("insufficient_balance") from error
            raise
        content = response.choices[0].message.content or ""
        if response_format.get("type") in {"json_object", "json_schema"}:
            json.loads(content)
        return DirectProviderResult(content, response.model, getattr(response, "usage", None), provider="deepseek-fallback")
