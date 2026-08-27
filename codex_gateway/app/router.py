"""Route completions to Codex first and DeepSeek only on allowed failures."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from .codex_provider import (
    CodexExecutionError,
    CodexTurnError,
    EmptyResponseError,
    InvalidStructuredResponseError,
    QueueFullError,
)

logger = logging.getLogger("mirofish.codex_gateway.router")


_FALLBACK_ERROR_NAMES = {
    "AuthenticationError",
    "PermissionDeniedError",
    "RateLimitError",
    "ServerBusyError",
    "TransportClosedError",
    "UnauthenticatedError",
}


def should_fallback(error: BaseException) -> bool:
    if isinstance(
        error,
        (
            CodexExecutionError,
            CodexTurnError,
            EmptyResponseError,
            InvalidStructuredResponseError,
        ),
    ):
        return True
    if isinstance(error, (KeyboardInterrupt, QueueFullError, ValueError)):
        return False
    status_code = getattr(error, "status_code", None)
    if status_code in {401, 403, 429}:
        return True
    if status_code is not None:
        return False
    return isinstance(error, TimeoutError) or type(error).__name__ in _FALLBACK_ERROR_NAMES


@dataclass(frozen=True)
class RoutedResult:
    content: str
    model: str
    provider: str
    fallback_reason: str | None
    usage: Any = None


class CompletionRouter:
    def __init__(self, *, codex: Any, fallback: Any) -> None:
        self._codex = codex
        self._fallback = fallback

    def complete(self, request: dict[str, Any]) -> RoutedResult:
        try:
            result = self._codex.complete(request)
            return RoutedResult(
                content=result.content,
                model=result.model,
                provider="codex",
                fallback_reason=None,
                usage=result.usage,
            )
        except Exception as error:
            if not should_fallback(error):
                raise
            logger.warning(
                "gateway fallback provider=deepseek reason=%s status_code=%s",
                type(error).__name__,
                getattr(error, "status_code", None),
            )
            fallback_result = self._fallback.complete(request)
            return RoutedResult(
                content=fallback_result.content,
                model=fallback_result.model,
                provider="deepseek",
                fallback_reason=type(error).__name__,
                usage=fallback_result.usage,
            )
