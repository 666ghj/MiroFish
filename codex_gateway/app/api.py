"""OpenAI-compatible HTTP surface for the internal Codex Gateway."""

from __future__ import annotations

import hmac
import time
import uuid
from typing import Any, Callable

from flask import Flask, jsonify, request

from .codex_provider import QueueFullError


def _error(message: str, status: int):
    return jsonify({"error": {"message": message, "type": "gateway_error"}}), status


def _usage(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return value
    return None


def create_app(
    *,
    router: Any,
    config: Any,
    account_reader: Callable[[], dict[str, object]] | None = None,
) -> Flask:
    app = Flask(__name__)

    def authorized() -> bool:
        header = request.headers.get("Authorization", "")
        expected = f"Bearer {config.internal_token}"
        return hmac.compare_digest(header, expected)

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "mirofish-codex-gateway"}

    @app.get("/account")
    def account():
        if not authorized():
            return _error("unauthorized", 401)
        if account_reader is None:
            return {"authenticated": False, "email": None, "plan_type": None}
        return account_reader()

    @app.post("/v1/chat/completions")
    def chat_completions():
        if not authorized():
            return _error("unauthorized", 401)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return _error("request body must be a JSON object", 400)
        if payload.get("stream") is True:
            return _error("stream=true is not supported", 400)
        if not isinstance(payload.get("messages"), list):
            return _error("messages must be a list", 400)

        try:
            result = router.complete(payload)
        except QueueFullError:
            return _error("Codex request queue is full", 503)
        except ValueError as error:
            return _error(str(error), 400)
        except Exception as error:
            app.logger.error(
                "gateway provider request failed error_type=%s status_code=%s",
                type(error).__name__,
                getattr(error, "status_code", None),
            )
            return _error("LLM provider request failed", 502)

        response = jsonify(
            {
                "id": f"chatcmpl-{uuid.uuid4().hex}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": result.model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": result.content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": _usage(result.usage),
            }
        )
        response.headers["X-MiroFish-Provider"] = result.provider
        if result.fallback_reason:
            response.headers["X-MiroFish-Fallback-Reason"] = result.fallback_reason
        return response

    return app
