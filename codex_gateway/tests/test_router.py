from types import SimpleNamespace

from app.codex_provider import (
    CodexTurnError,
    CodexExecutionError,
    EmptyResponseError,
    InvalidStructuredResponseError,
    QueueFullError,
)
from app.router import CompletionRouter, should_fallback


class StatusError(RuntimeError):
    def __init__(self, status_code):
        super().__init__(f"status {status_code}")
        self.status_code = status_code


class ServerBusyError(RuntimeError):
    pass


def test_fallback_matrix():
    for error in (
        StatusError(401),
        StatusError(403),
        StatusError(429),
        TimeoutError(),
        ServerBusyError(),
        EmptyResponseError("empty"),
        InvalidStructuredResponseError("invalid JSON"),
        CodexTurnError("failed"),
        CodexExecutionError("runtime"),
    ):
        assert should_fallback(error) is True

    for error in (
        ValueError("invalid request"),
        QueueFullError("full"),
        StatusError(400),
        KeyboardInterrupt(),
    ):
        assert should_fallback(error) is False


def test_router_uses_codex_without_fallback():
    codex = SimpleNamespace(
        complete=lambda request: SimpleNamespace(
            content="codex", model="gpt-5.6-terra", usage=None
        )
    )
    fallback_calls = []
    fallback = SimpleNamespace(complete=lambda request: fallback_calls.append(request))

    result = CompletionRouter(codex=codex, fallback=fallback).complete({"messages": []})

    assert result.provider == "codex"
    assert result.content == "codex"
    assert fallback_calls == []


def test_router_falls_back_on_rate_limit():
    def fail(_request):
        raise StatusError(429)

    codex = SimpleNamespace(complete=fail)
    fallback = SimpleNamespace(
        complete=lambda request: SimpleNamespace(
            content="deepseek", model="deepseek-v4-flash", usage=None
        )
    )

    result = CompletionRouter(codex=codex, fallback=fallback).complete({"messages": []})

    assert result.provider == "deepseek"
    assert result.content == "deepseek"
    assert result.fallback_reason == "StatusError"


def test_router_does_not_fallback_on_invalid_request():
    def fail(_request):
        raise ValueError("invalid request")

    fallback_calls = []
    router = CompletionRouter(
        codex=SimpleNamespace(complete=fail),
        fallback=SimpleNamespace(complete=lambda request: fallback_calls.append(request)),
    )

    try:
        router.complete({"messages": []})
    except ValueError:
        pass
    else:
        raise AssertionError("invalid request must be returned to the caller")

    assert fallback_calls == []
