"""
Entity reader backend factory.

Switches between ZepEntityReader and LocalEntityReader based on Config.GRAPH_BACKEND.
"""

from __future__ import annotations

from ..config import Config


def get_entity_reader():
    if Config.GRAPH_BACKEND == "local":
        from .local_entity_reader import LocalEntityReader

        return LocalEntityReader()

    from .zep_entity_reader import ZepEntityReader

    return ZepEntityReader()
