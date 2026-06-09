"""Graph pagination helpers (replaces zep_paging.py).

FalkorDB returns nodes/edges in a single query (we cap at 5000 in the adapter),
so there's no real pagination here — but the call sites in graph_builder.py and
zep_entity_reader.py import `fetch_all_nodes` / `fetch_all_edges`, so we keep
those names as adapters over GraphitiAdapter.
"""
from __future__ import annotations

import logging
from typing import Any, List

from .logger import get_logger

logger = get_logger('mirofish.zep_paging')


def fetch_all_nodes(
    client: Any,  # ignored — kept for signature compat with Zep call sites
    graph_id: str,
    page_size: int = 100,  # ignored
    max_items: int = 2000,
    max_retries: int = 3,  # ignored
    retry_delay: float = 2.0,  # ignored
) -> List[Any]:
    """Return all nodes in `graph_id` (FalkorDB capped at max_items, default 2000)."""
    from ..services.graphiti_service import get_graphiti_adapter
    adapter = get_graphiti_adapter()
    nodes = adapter.get_all_nodes(graph_id)
    if len(nodes) > max_items:
        logger.warning(f"Node count {len(nodes)} > max_items {max_items}, truncating")
        nodes = nodes[:max_items]
    return nodes


def fetch_all_edges(
    client: Any,
    graph_id: str,
    page_size: int = 100,
    max_retries: int = 3,
    retry_delay: float = 2.0,
) -> List[Any]:
    """Return all edges in `graph_id`."""
    from ..services.graphiti_service import get_graphiti_adapter
    adapter = get_graphiti_adapter()
    return adapter.get_all_edges(graph_id, include_temporal=True)
