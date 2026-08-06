"""Complete Zep Graph node/edge pagination using opaque response cursors."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from zep_cloud.client import Zep

from .logger import get_logger
from .zep import call_zep_read_with_retry

logger = get_logger("mirofish.zep_paging")

_DEFAULT_PAGE_SIZE = 100
_DEFAULT_MAX_RETRIES = 3
_DEFAULT_RETRY_DELAY = 2.0
_NEXT_CURSOR_HEADER = "zep-next-cursor"


def _fetch_page_with_retry(
    api_call: Callable[..., Any],
    *args: Any,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    retry_delay: float = _DEFAULT_RETRY_DELAY,
    page_description: str = "page",
    **kwargs: Any,
) -> Any:
    """Fetch one read-only page with the shared transient-error policy."""

    return call_zep_read_with_retry(
        lambda: api_call(*args, **kwargs),
        operation_name=page_description,
        max_attempts=max_retries,
        initial_delay=retry_delay,
    )


def _header_value(headers: Any, name: str) -> str | None:
    if not headers:
        return None
    direct = headers.get(name)
    if direct is not None:
        return str(direct)
    return next(
        (
            str(value)
            for header_name, value in headers.items()
            if str(header_name).lower() == name.lower()
        ),
        None,
    )


def _fetch_all(
    api_call: Callable[..., Any],
    graph_id: str,
    *,
    item_name: str,
    page_size: int,
    max_items: int | None,
    max_retries: int,
    retry_delay: float,
) -> list[Any]:
    if not 1 <= page_size <= 100:
        raise ValueError("page_size must be between 1 and 100")
    if max_items is not None and max_items < 1:
        raise ValueError("max_items must be at least 1 when provided")

    all_items: list[Any] = []
    cursor: str | None = None
    seen_cursors: set[str] = set()
    page_number = 0

    while True:
        kwargs: dict[str, Any] = {"limit": page_size}
        if cursor is not None:
            kwargs["cursor"] = cursor

        page_number += 1
        response = _fetch_page_with_retry(
            api_call,
            graph_id,
            max_retries=max_retries,
            retry_delay=retry_delay,
            page_description=(
                f"fetch {item_name} page {page_number} (graph={graph_id})"
            ),
            **kwargs,
        )
        batch = list(getattr(response, "data", None) or [])
        all_items.extend(batch)

        if max_items is not None and len(all_items) >= max_items:
            if len(all_items) > max_items:
                all_items = all_items[:max_items]
            logger.warning(
                "Zep %s pagination reached explicit max_items=%s for graph %s",
                item_name,
                max_items,
                graph_id,
            )
            break

        next_cursor = _header_value(
            getattr(response, "headers", None),
            _NEXT_CURSOR_HEADER,
        )
        if next_cursor is None:
            break
        if next_cursor in seen_cursors or next_cursor == cursor:
            raise RuntimeError(
                f"Zep {item_name} pagination cursor did not advance for graph {graph_id}"
            )
        seen_cursors.add(next_cursor)
        cursor = next_cursor

    return all_items


def fetch_all_nodes(
    client: Zep,
    graph_id: str,
    page_size: int = _DEFAULT_PAGE_SIZE,
    max_items: int | None = None,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    retry_delay: float = _DEFAULT_RETRY_DELAY,
) -> list[Any]:
    """Fetch every graph node unless the caller supplies an explicit cap."""

    return _fetch_all(
        client.graph.node.with_raw_response.get_by_graph_id,
        graph_id,
        item_name="nodes",
        page_size=page_size,
        max_items=max_items,
        max_retries=max_retries,
        retry_delay=retry_delay,
    )


def fetch_all_edges(
    client: Zep,
    graph_id: str,
    page_size: int = _DEFAULT_PAGE_SIZE,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    retry_delay: float = _DEFAULT_RETRY_DELAY,
    max_items: int | None = None,
) -> list[Any]:
    """Fetch every graph edge unless the caller supplies an explicit cap."""

    return _fetch_all(
        client.graph.edge.with_raw_response.get_by_graph_id,
        graph_id,
        item_name="edges",
        page_size=page_size,
        max_items=max_items,
        max_retries=max_retries,
        retry_delay=retry_delay,
    )
