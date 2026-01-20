"""
Graph backend factory.

Provides a unified way to obtain the graph builder based on Config.GRAPH_BACKEND.
"""

from __future__ import annotations

from ..config import Config


def get_graph_builder():
    if Config.GRAPH_BACKEND == "local":
        from app.services.local.local_graph_builder import LocalGraphBuilderService

        return LocalGraphBuilderService()

    # Default: Zep
    from .graph_builder import GraphBuilderService

    return GraphBuilderService(api_key=Config.ZEP_API_KEY)
