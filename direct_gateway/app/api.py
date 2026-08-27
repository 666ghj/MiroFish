from __future__ import annotations

import hmac
import time
import uuid

from flask import Flask, jsonify, request

from .provider import CircuitOpenError


def _error(message, status):
    return jsonify({"error": {"message": message, "type": "gateway_error"}}), status


def create_app(*, router, config, account_reader=None):
    app = Flask(__name__)

    def authorized():
        return hmac.compare_digest(request.headers.get("Authorization", ""), f"Bearer {config.internal_token}")

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "mirofish-direct-oauth-gateway"}

    @app.get("/account")
    def account():
        if not authorized():
            return _error("unauthorized", 401)
        return account_reader() if account_reader else {"authenticated": False}

    @app.post("/v1/chat/completions")
    def completions():
        if not authorized():
            return _error("unauthorized", 401)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or not isinstance(payload.get("messages"), list):
            return _error("messages must be a list", 400)
        if payload.get("stream") is True:
            return _error("stream=true is not supported", 400)
        try:
            result = router.complete(payload)
        except CircuitOpenError:
            return _error("provider circuit is open", 503)
        except ValueError as error:
            return _error(str(error), 400)
        except Exception as error:
            app.logger.error("direct provider failed error_type=%s status_code=%s", type(error).__name__, getattr(error, "status_code", None))
            return _error("LLM provider request failed", 502)
        response = jsonify({"id": f"chatcmpl-{uuid.uuid4().hex}", "object": "chat.completion", "created": int(time.time()), "model": result.model, "choices": [{"index": 0, "message": {"role": "assistant", "content": result.content}, "finish_reason": "stop"}], "usage": result.usage})
        response.headers["X-MiroFish-Provider"] = result.provider
        return response

    return app
