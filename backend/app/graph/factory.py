"""
Graph backend factory.
"""

from __future__ import annotations

from typing import Optional

from ..config import Config
from .base import GraphBackend


def get_graph_backend(api_key: Optional[str] = None) -> GraphBackend:
    """Create the configured graph backend."""
    backend = (Config.GRAPH_BACKEND or "graphiti").lower()

    if backend in {"zep", "openzep"}:
        from .zep_backend import ZepGraphBackend

        return ZepGraphBackend(api_key=api_key)

    if backend == "graphiti":
        from .graphiti_backend import GraphitiBackend

        return GraphitiBackend(api_key=api_key)

    raise ValueError(f"不支持的 GRAPH_BACKEND: {backend}")
