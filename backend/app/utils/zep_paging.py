"""Tiện ích đọc phân trang cho Knowledge Graph (Graphiti + Neo4j backend).

Thay thế Zep SDK bằng graphiti_core:
  - client.graph.node.get_by_graph_id  →  EntityNode.get_by_group_ids
  - client.graph.edge.get_by_graph_id  →  EntityEdge.get_by_group_ids

Callers truyền `driver` (GraphDriver) thay cho `client` (Zep) trước đây.
"""

from __future__ import annotations

import asyncio
from typing import Any

from graphiti_core.driver.driver import GraphDriver
from graphiti_core.edges import EntityEdge
from graphiti_core.errors import GroupsEdgesNotFoundError
from graphiti_core.nodes import EntityNode

from .graphiti_client import run_async
from .logger import get_logger

logger = get_logger('mirofish.graph_paging')

_DEFAULT_PAGE_SIZE = 100
_MAX_NODES = 2000
_DEFAULT_MAX_RETRIES = 3
_DEFAULT_RETRY_DELAY = 2.0


async def _fetch_all_nodes_async(
    driver: GraphDriver,
    graph_id: str,
    page_size: int,
    max_items: int,
    max_retries: int,
    retry_delay: float,
) -> list[Any]:
    all_nodes: list[Any] = []
    cursor: str | None = None
    page_num = 0

    while True:
        page_num += 1
        delay = retry_delay
        batch: list[Any] = []

        for attempt in range(max_retries):
            try:
                batch = await EntityNode.get_by_group_ids(
                    driver,
                    group_ids=[graph_id],
                    limit=page_size,
                    uuid_cursor=cursor,
                )
                break
            except (ConnectionError, TimeoutError, OSError) as e:
                if attempt < max_retries - 1:
                    logger.warning(f"fetch nodes page {page_num} (graph={graph_id}) attempt {attempt + 1} failed: {str(e)[:100]}, retrying in {delay:.1f}s...")
                    await asyncio.sleep(delay)
                    delay *= 2
                else:
                    logger.error(f"fetch nodes page {page_num} (graph={graph_id}) failed after {max_retries} attempts")
                    raise

        if not batch:
            break

        all_nodes.extend(batch)
        if len(all_nodes) >= max_items:
            all_nodes = all_nodes[:max_items]
            logger.warning(f"Node count reached limit ({max_items}), stopping pagination for graph {graph_id}")
            break
        if len(batch) < page_size:
            break

        cursor = getattr(batch[-1], "uuid", None)
        if cursor is None:
            logger.warning(f"Node missing uuid field, stopping pagination at {len(all_nodes)} nodes")
            break

    return all_nodes


async def _fetch_all_edges_async(
    driver: GraphDriver,
    graph_id: str,
    page_size: int,
    max_retries: int,
    retry_delay: float,
) -> list[Any]:
    all_edges: list[Any] = []
    cursor: str | None = None
    page_num = 0

    while True:
        page_num += 1
        delay = retry_delay
        batch: list[Any] = []

        for attempt in range(max_retries):
            try:
                batch = await EntityEdge.get_by_group_ids(
                    driver,
                    group_ids=[graph_id],
                    limit=page_size,
                    uuid_cursor=cursor,
                )
                break
            except GroupsEdgesNotFoundError:
                batch = []
                break
            except (ConnectionError, TimeoutError, OSError) as e:
                if attempt < max_retries - 1:
                    logger.warning(f"fetch edges page {page_num} (graph={graph_id}) attempt {attempt + 1} failed: {str(e)[:100]}, retrying in {delay:.1f}s...")
                    await asyncio.sleep(delay)
                    delay *= 2
                else:
                    logger.error(f"fetch edges page {page_num} (graph={graph_id}) failed after {max_retries} attempts")
                    raise

        if not batch:
            break

        all_edges.extend(batch)
        if len(batch) < page_size:
            break

        cursor = getattr(batch[-1], "uuid", None)
        if cursor is None:
            logger.warning(f"Edge missing uuid field, stopping pagination at {len(all_edges)} edges")
            break

    return all_edges


def fetch_all_nodes(
    driver: GraphDriver,
    graph_id: str,
    page_size: int = _DEFAULT_PAGE_SIZE,
    max_items: int = _MAX_NODES,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    retry_delay: float = _DEFAULT_RETRY_DELAY,
) -> list[Any]:
    """Lấy toàn bộ EntityNode theo group_id, tối đa max_items (mặc định 2000)."""
    # run_async (loop thread-local) thay vì asyncio.run (loop mới) để Neo4j driver
    # luôn chạy trên cùng event loop đã gắn — tránh "Future attached to a different loop".
    return run_async(_fetch_all_nodes_async(driver, graph_id, page_size, max_items, max_retries, retry_delay))


def fetch_all_edges(
    driver: GraphDriver,
    graph_id: str,
    page_size: int = _DEFAULT_PAGE_SIZE,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    retry_delay: float = _DEFAULT_RETRY_DELAY,
) -> list[Any]:
    """Lấy toàn bộ EntityEdge theo group_id."""
    return run_async(_fetch_all_edges_async(driver, graph_id, page_size, max_retries, retry_delay))
