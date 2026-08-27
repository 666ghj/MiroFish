from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from typing import Any, Iterable

import httpx

from .messages import build_responses_payload


@dataclass(frozen=True)
class DirectProviderResult:
    content: str
    model: str
    usage: dict | None
    provider: str = "chatgpt-direct-oauth"


def parse_responses_sse(lines: Iterable[str]) -> DirectProviderResult:
    parts = []
    completed = None
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith(":") or not line.startswith("data:"):
            continue
        data_text = line[5:].strip()
        if data_text == "[DONE]":
            continue
        try:
            event = json.loads(data_text)
        except json.JSONDecodeError:
            continue
        kind = event.get("type")
        if kind == "response.output_text.delta":
            parts.append(str(event.get("delta", "")))
        elif kind == "response.failed":
            raise RuntimeError("provider_failed")
        elif kind == "response.completed":
            completed = event.get("response") or {}
    if completed is None:
        raise RuntimeError("incomplete_response")
    content = "".join(parts)
    if not content.strip():
        raise RuntimeError("empty_response")
    return DirectProviderResult(content, completed.get("model", "unknown"), completed.get("usage"))


class ResponsesClient:
    def __init__(self, *, endpoint: str, model: str, token_manager: Any, http: httpx.Client | None = None, timeout: int = 600) -> None:
        self.endpoint = endpoint
        self.model = model
        self.token_manager = token_manager
        self.http = http or httpx.Client(timeout=httpx.Timeout(timeout, connect=30))
        self._slots = threading.BoundedSemaphore(2)

    def complete(self, request: dict) -> DirectProviderResult:
        with self._slots:
            tokens, metadata = self.token_manager.fresh()
            headers = {"Authorization": f"Bearer {tokens.access_token}", "ChatGPT-Account-Id": metadata["account_id"], "Accept": "text/event-stream", "Content-Type": "application/json", "originator": "mirofish-direct-oauth", "User-Agent": "mirofish-direct-oauth/0.1.0"}
            if metadata.get("residency"):
                headers["x-openai-internal-codex-residency"] = metadata["residency"]
            with self.http.stream("POST", self.endpoint, headers=headers, json=build_responses_payload(request, self.model)) as response:
                response.raise_for_status()
                return parse_responses_sse(response.iter_lines())
