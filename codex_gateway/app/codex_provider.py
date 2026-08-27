"""Official Codex SDK provider for OpenAI-compatible chat requests."""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from typing import Any

from .messages import build_codex_input


@dataclass(frozen=True)
class ProviderResult:
    content: str
    model: str
    turn_id: str | None
    usage: Any = None


class QueueFullError(RuntimeError):
    pass


class EmptyResponseError(RuntimeError):
    pass


class InvalidStructuredResponseError(RuntimeError):
    pass


class CodexTurnError(RuntimeError):
    pass


class CodexExecutionError(RuntimeError):
    pass


def _normalize_output_schema(value: Any) -> Any:
    if isinstance(value, dict):
        normalized = {
            key: _normalize_output_schema(item)
            for key, item in value.items()
            if key != "default"
        }
        schema_type = normalized.get("type")
        if schema_type == "object" or (
            isinstance(schema_type, list) and "object" in schema_type
        ):
            normalized.setdefault("additionalProperties", False)
            properties = normalized.get("properties")
            if isinstance(properties, dict):
                normalized["required"] = list(properties.keys())
        return normalized
    if isinstance(value, list):
        return [_normalize_output_schema(item) for item in value]
    return value


class CodexProvider:
    def __init__(
        self,
        *,
        codex: Any,
        model: str,
        approval_mode: Any = None,
        sandbox: Any = None,
        max_concurrency: int = 1,
        queue_size: int = 20,
        request_timeout_seconds: float = 300,
    ) -> None:
        if approval_mode is None or sandbox is None:
            from openai_codex import ApprovalMode, Sandbox

            approval_mode = approval_mode or ApprovalMode.deny_all
            sandbox = sandbox or Sandbox.read_only

        self._codex = codex
        self._model = model
        self._approval_mode = approval_mode
        self._sandbox = sandbox
        self._slots = threading.BoundedSemaphore(max_concurrency)
        self._queue_size = queue_size
        self._waiting = 0
        self._waiting_lock = threading.Lock()
        self._request_timeout_seconds = request_timeout_seconds
        self._executor = ThreadPoolExecutor(
            max_workers=max_concurrency,
            thread_name_prefix="codex-turn",
        )

    def complete(self, request: dict[str, Any]) -> ProviderResult:
        acquired = self._slots.acquire(blocking=False)
        if not acquired:
            with self._waiting_lock:
                if self._waiting >= self._queue_size:
                    raise QueueFullError("Codex request queue is full")
                self._waiting += 1
            try:
                self._slots.acquire()
                acquired = True
            finally:
                with self._waiting_lock:
                    self._waiting -= 1

        try:
            return self._complete(request)
        finally:
            if acquired:
                self._slots.release()

    def _complete(self, request: dict[str, Any]) -> ProviderResult:
        converted = build_codex_input(request.get("messages") or [])
        response_format = request.get("response_format") or {"type": "text"}
        response_type = response_format.get("type", "text")
        output_schema = None
        prompt = converted.turn_text

        if response_type == "json_schema":
            output_schema = (response_format.get("json_schema") or {}).get("schema")
            if not isinstance(output_schema, dict):
                raise ValueError("json_schema response format requires a schema")
            output_schema = _normalize_output_schema(output_schema)
        elif response_type == "json_object":
            prompt += "\nReturn only one valid JSON object with no markdown."
        elif response_type != "text":
            raise ValueError(f"unsupported response format: {response_type}")

        try:
            thread = self._codex.thread_start(
                ephemeral=True,
                model=self._model,
                approval_mode=self._approval_mode,
                sandbox=self._sandbox,
                base_instructions=converted.base_instructions,
                developer_instructions=converted.developer_instructions,
                config={
                    "approval_policy": "never",
                    "sandbox_mode": "read-only",
                    "mcp_servers": {},
                    "hooks": {},
                },
            )
        except Exception as error:
            raise CodexExecutionError("Codex thread start failed") from error
        turn_kwargs = {
            "output_schema": output_schema,
            "sandbox": self._sandbox,
            "approval_mode": self._approval_mode,
        }
        if hasattr(thread, "turn"):
            try:
                handle = thread.turn(prompt, **turn_kwargs)
            except Exception as error:
                raise CodexExecutionError("Codex turn start failed") from error
            future = self._executor.submit(handle.run)
            try:
                result = future.result(timeout=self._request_timeout_seconds)
            except FutureTimeoutError as error:
                handle.interrupt()
                raise TimeoutError("Codex turn timed out") from error
            except Exception as error:
                raise CodexExecutionError("Codex turn execution failed") from error
        else:
            try:
                result = thread.run(prompt, **turn_kwargs)
            except Exception as error:
                raise CodexExecutionError("Codex turn execution failed") from error
        status = getattr(result.status, "value", result.status)
        if status not in {"completed", "success"}:
            raise CodexTurnError(f"Codex turn failed: {status}")

        content = result.final_response or ""
        if not content.strip():
            raise EmptyResponseError("Codex returned an empty response")
        if response_type in {"json_object", "json_schema"}:
            try:
                json.loads(content)
            except json.JSONDecodeError as error:
                raise InvalidStructuredResponseError(
                    "Codex returned invalid JSON"
                ) from error

        return ProviderResult(
            content=content,
            model=self._model,
            turn_id=getattr(result, "id", None),
            usage=getattr(result, "usage", None),
        )
