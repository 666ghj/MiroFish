"""Shared Zep Cloud client, request limits, and retry policy."""

from __future__ import annotations

import os
import time
from functools import lru_cache
from typing import Any, Callable, TypeVar

import httpx
from zep_cloud.client import Zep
from zep_cloud.core.api_error import ApiError as ZepApiError

from ..config import Config
from .logger import get_logger

logger = get_logger("sosim.zep")

T = TypeVar("T")

ZEP_CLOUD_BASE_URL = "https://api.getzep.com/api/v2"

# Keep request behavior aligned with the zep-cloud 3.25.0 SDK default that
# SoSim used before introducing the shared client. This is an internal
# integration policy, not a deployment setting users need to tune.
ZEP_HTTP_REQUEST_TIMEOUT_SECONDS = float(
    os.environ.get("ZEP_HTTP_REQUEST_TIMEOUT_SECONDS") or 60.0
)
# Zep ingestion is asynchronous and may take several minutes.
# UXE fork: made configurable. Cloud ingests in well under 600s, but a local
# LLM extracting entities from a few hundred chunks will not — and blowing this
# deadline raises TimeoutError in GraphBuilder._wait_for_batch even though the
# ingest is still progressing. Raise it substantially for local inference.
ZEP_INGESTION_WAIT_TIMEOUT_SECONDS = int(
    os.environ.get("ZEP_INGESTION_WAIT_TIMEOUT_SECONDS") or 600
)
MAX_ZEP_SEARCH_QUERY_CHARS = 400
MAX_ZEP_SEARCH_RESULTS = 50


def normalize_zep_search_query(query: Any) -> str:
    """Return a non-empty query within Zep Cloud's endpoint limit."""

    if not isinstance(query, str):
        raise ValueError("Zep search query must be a string")
    normalized = query.strip()
    if not normalized:
        raise ValueError("Zep search query must not be empty")
    return normalized[:MAX_ZEP_SEARCH_QUERY_CHARS]


def normalize_zep_search_limit(limit: Any) -> int:
    """Clamp a search result limit to the current Zep Cloud contract."""

    try:
        normalized = int(limit)
    except (TypeError, ValueError) as exc:
        raise ValueError("Zep search limit must be an integer") from exc
    if normalized < 1:
        raise ValueError("Zep search limit must be at least 1")
    return min(normalized, MAX_ZEP_SEARCH_RESULTS)


def resolve_zep_base_url() -> str:
    """Return the endpoint this process should talk to.

    UXE fork: ZEP_BASE_URL points the SDK at a self-hosted, Zep-compatible
    service — the Graphiti-backed shim under third_party/graphiti. Unset means
    Zep Cloud, so existing deployments are unaffected.

    This is deliberately NOT the SDK's own ZEP_API_URL variable, which the SDK
    honours over an explicit base_url; that one stays rejected in
    get_zep_client so no stray env var can silently redirect traffic.
    """

    return (os.environ.get("ZEP_BASE_URL") or "").strip() or ZEP_CLOUD_BASE_URL


@lru_cache(maxsize=4)
def _cached_zep_client(api_key: str, base_url: str, timeout: float) -> Zep:
    return Zep(
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
    )


def get_zep_client(api_key: str | None = None, timeout: float | None = None) -> Zep:
    """Return a process-shared, explicitly configured Zep client.

    Targets Zep Cloud by default, or ZEP_BASE_URL when set (UXE fork).
    """

    # zep-cloud gives ZEP_API_URL precedence even when base_url is explicit.
    # Keep rejecting it: ZEP_BASE_URL is the supported way to retarget, and
    # allowing both would make the effective endpoint ambiguous.
    if os.environ.get("ZEP_API_URL"):
        raise ValueError(
            "ZEP_API_URL is unsupported; use ZEP_BASE_URL to target a local endpoint"
        )

    normalized_key = (api_key or Config.ZEP_API_KEY or "").strip()
    if not normalized_key:
        raise ValueError("ZEP_API_KEY is not configured.")

    request_timeout = float(
        timeout if timeout is not None else ZEP_HTTP_REQUEST_TIMEOUT_SECONDS
    )
    if request_timeout <= 0:
        raise ValueError("Zep request timeout must be greater than 0")
    return _cached_zep_client(
        normalized_key, resolve_zep_base_url(), request_timeout
    )


def clear_zep_client_cache() -> None:
    """Clear cached clients. Intended for tests and controlled reconfiguration."""

    _cached_zep_client.cache_clear()


def is_retryable_zep_error(error: BaseException) -> bool:
    """Return whether a failed *read* is safe and useful to retry."""

    if isinstance(error, (httpx.TimeoutException, httpx.TransportError)):
        return True
    if isinstance(error, (ConnectionError, TimeoutError, OSError)):
        return True
    if isinstance(error, ZepApiError):
        status_code = error.status_code
        return status_code in {408, 429} or (
            status_code is not None and 500 <= status_code <= 599
        )
    return False


def _retry_after_seconds(error: BaseException) -> float | None:
    if not isinstance(error, ZepApiError) or not error.headers:
        return None
    value = next(
        (
            header_value
            for header_name, header_value in error.headers.items()
            if header_name.lower() == "retry-after"
        ),
        None,
    )
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return None


def call_zep_read_with_retry(
    operation: Callable[[], T],
    *,
    operation_name: str,
    max_attempts: int = 3,
    initial_delay: float = 2.0,
    max_delay: float = 60.0,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Retry a safe Zep read only for transport, 408, 429, or 5xx errors."""

    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    for attempt in range(1, max_attempts + 1):
        try:
            return operation()
        except Exception as error:
            if attempt == max_attempts or not is_retryable_zep_error(error):
                raise

            retry_after = _retry_after_seconds(error)
            delay = min(
                retry_after if retry_after is not None else initial_delay * (2 ** (attempt - 1)),
                max_delay,
            )
            logger.warning(
                "Zep %s attempt %s/%s failed (%s); retrying in %.1fs",
                operation_name,
                attempt,
                max_attempts,
                type(error).__name__,
                delay,
            )
            sleep(delay)

    raise AssertionError("unreachable")
