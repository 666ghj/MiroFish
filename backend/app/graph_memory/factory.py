"""Graph memory adapter factory."""

from __future__ import annotations

from typing import Optional

from ..config import Config
from .base import GraphMemoryAdapter
from .zep_cloud_adapter import ZepCloudGraphMemoryAdapter


def create_graph_memory_adapter(api_key: Optional[str] = None, backend: Optional[str] = None) -> GraphMemoryAdapter:
    selected_backend = (backend or Config.GRAPH_MEMORY_BACKEND).strip().lower()

    if selected_backend in {"zep", "zep_cloud", "zep-cloud"}:
        return ZepCloudGraphMemoryAdapter(api_key=api_key or Config.ZEP_API_KEY)

    if selected_backend in {"graphiti", "graphiti_core", "graphiti-core", "graphiti_bridge", "graphiti-bridge"}:
        from .graphiti_bridge_adapter import GraphitiBridgeGraphMemoryAdapter

        return GraphitiBridgeGraphMemoryAdapter(api_key=api_key or Config.LLM_API_KEY)

    raise ValueError(f"Unsupported GRAPH_MEMORY_BACKEND: {selected_backend}")
