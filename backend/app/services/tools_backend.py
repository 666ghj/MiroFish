"""
Tools service backend factory.

Switches between ZepToolsService and LocalToolsService based on Config.GRAPH_BACKEND.
"""

from __future__ import annotations

from ..config import Config


def get_tools_service():
    if Config.GRAPH_BACKEND == "local":
        from .local_tools import LocalToolsService

        return LocalToolsService()

    from .zep_tools import ZepToolsService

    return ZepToolsService()
