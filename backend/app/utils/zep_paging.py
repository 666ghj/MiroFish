"""Zep Graph 分页读取工具。

Zep 的 node/edge 列表接口使用 UUID cursor 分页，
本模块封装自动翻页逻辑（含单页重试），对调用方透明地返回完整列表。
"""

from __future__ import annotations

import time
import re
from collections.abc import Callable
from typing import Any

from zep_cloud import InternalServerError
from zep_cloud.core.api_error import ApiError
from zep_cloud.client import Zep

from .logger import get_logger

logger = get_logger('mirofish.zep_paging')

_DEFAULT_PAGE_SIZE = 100
_MAX_NODES = 2000
_DEFAULT_MAX_RETRIES = 5
_DEFAULT_RETRY_DELAY = 2.0  # seconds, doubles each retry
_MAX_RETRY_DELAY = 60.0


def _is_rate_limit_error(error: Exception) -> bool:
    status_code = getattr(error, "status_code", None)
    if status_code == 429:
        return True

    body = getattr(error, "body", None)
    if isinstance(body, str) and "rate limit" in body.lower():
        return True

    text = str(error).lower()
    return "status_code: 429" in text or "rate limit" in text or "too many requests" in text


def _parse_retry_after(error: Exception) -> float | None:
    headers = getattr(error, "headers", None)
    if isinstance(headers, dict):
        retry_after = headers.get("retry-after") or headers.get("Retry-After")
        if retry_after:
            try:
                return max(float(retry_after), 0.0)
            except (TypeError, ValueError):
                pass

        reset = headers.get("x-ratelimit-reset") or headers.get("X-RateLimit-Reset")
        if reset:
            try:
                reset_seconds = float(reset)
                if reset_seconds > 1_000_000_000:
                    # Some providers return a unix timestamp instead of a delta.
                    wait_seconds = reset_seconds - time.time()
                else:
                    wait_seconds = reset_seconds
                if wait_seconds > 0:
                    return wait_seconds
            except (TypeError, ValueError):
                pass

    text = str(error)
    match = re.search(r"retry-after['\"]?\s*:\s*['\"]?(\d+(?:\.\d+)?)", text, re.IGNORECASE)
    if match:
        try:
            return max(float(match.group(1)), 0.0)
        except (TypeError, ValueError):
            pass

    return None


def _fetch_page_with_retry(
    api_call: Callable[..., list[Any]],
    *args: Any,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    retry_delay: float = _DEFAULT_RETRY_DELAY,
    page_description: str = "page",
    **kwargs: Any,
) -> list[Any]:
    """单页请求，失败时指数退避重试。仅重试网络/IO类瞬态错误。"""
    if max_retries < 1:
        raise ValueError("max_retries must be >= 1")

    last_exception: Exception | None = None
    delay = retry_delay

    for attempt in range(max_retries):
        try:
            return api_call(*args, **kwargs)
        except (ConnectionError, TimeoutError, OSError, InternalServerError, ApiError) as e:
            last_exception = e
            if attempt < max_retries - 1:
                if _is_rate_limit_error(e):
                    retry_after = _parse_retry_after(e)
                    if retry_after is not None:
                        delay = min(max(retry_after, retry_delay), _MAX_RETRY_DELAY)
                    else:
                        delay = min(max(delay, retry_delay), _MAX_RETRY_DELAY)
                else:
                    delay = min(delay, _MAX_RETRY_DELAY)

                if _is_rate_limit_error(e):
                    logger.warning(
                        f"Zep {page_description} rate limit hit (attempt {attempt + 1}/{max_retries}); "
                        f"retrying in {delay:.1f}s..."
                    )
                else:
                    logger.warning(
                        f"Zep {page_description} attempt {attempt + 1} failed: {str(e)[:100]}, retrying in {delay:.1f}s..."
                    )
                time.sleep(delay)
                if _is_rate_limit_error(e):
                    # Respect server-advised retry delays; keep the same delay or back off slightly.
                    delay = min(delay * 1.25, _MAX_RETRY_DELAY)
                else:
                    delay = min(delay * 2, _MAX_RETRY_DELAY)
            else:
                logger.error(f"Zep {page_description} failed after {max_retries} attempts: {str(e)}")

    assert last_exception is not None
    raise last_exception


def fetch_all_nodes(
    client: Zep,
    graph_id: str,
    page_size: int = _DEFAULT_PAGE_SIZE,
    max_items: int = _MAX_NODES,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    retry_delay: float = _DEFAULT_RETRY_DELAY,
) -> list[Any]:
    """分页获取图谱节点，最多返回 max_items 条（默认 2000）。每页请求自带重试。"""
    all_nodes: list[Any] = []
    cursor: str | None = None
    page_num = 0

    while True:
        kwargs: dict[str, Any] = {"limit": page_size}
        if cursor is not None:
            kwargs["uuid_cursor"] = cursor

        page_num += 1
        batch = _fetch_page_with_retry(
            client.graph.node.get_by_graph_id,
            graph_id,
            max_retries=max_retries,
            retry_delay=retry_delay,
            page_description=f"fetch nodes page {page_num} (graph={graph_id})",
            **kwargs,
        )
        if not batch:
            break

        all_nodes.extend(batch)
        if len(all_nodes) >= max_items:
            all_nodes = all_nodes[:max_items]
            logger.warning(f"Node count reached limit ({max_items}), stopping pagination for graph {graph_id}")
            break
        if len(batch) < page_size:
            break

        cursor = getattr(batch[-1], "uuid_", None) or getattr(batch[-1], "uuid", None)
        if cursor is None:
            logger.warning(f"Node missing uuid field, stopping pagination at {len(all_nodes)} nodes")
            break

    return all_nodes


def fetch_all_edges(
    client: Zep,
    graph_id: str,
    page_size: int = _DEFAULT_PAGE_SIZE,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    retry_delay: float = _DEFAULT_RETRY_DELAY,
) -> list[Any]:
    """分页获取图谱所有边，返回完整列表。每页请求自带重试。"""
    all_edges: list[Any] = []
    cursor: str | None = None
    page_num = 0

    while True:
        kwargs: dict[str, Any] = {"limit": page_size}
        if cursor is not None:
            kwargs["uuid_cursor"] = cursor

        page_num += 1
        batch = _fetch_page_with_retry(
            client.graph.edge.get_by_graph_id,
            graph_id,
            max_retries=max_retries,
            retry_delay=retry_delay,
            page_description=f"fetch edges page {page_num} (graph={graph_id})",
            **kwargs,
        )
        if not batch:
            break

        all_edges.extend(batch)
        if len(batch) < page_size:
            break

        cursor = getattr(batch[-1], "uuid_", None) or getattr(batch[-1], "uuid", None)
        if cursor is None:
            logger.warning(f"Edge missing uuid field, stopping pagination at {len(all_edges)} edges")
            break

    return all_edges
