"""Graph backend factory — returns singleton based on GRAPH_BACKEND env var."""
from typing import Optional

from .base import GraphBackend
from ..utils.logger import get_logger

logger = get_logger('mirofish.graph.factory')

_backend_instance: Optional[GraphBackend] = None


def get_graph_backend() -> GraphBackend:
    """Return the configured graph backend singleton."""
    global _backend_instance
    if _backend_instance is not None:
        return _backend_instance

    from ..config import Config
    backend_type = Config.GRAPH_BACKEND
    logger.info(f"Initializing graph backend: {backend_type}")

    if backend_type == "zep":
        from .zep_backend import ZepBackend
        _backend_instance = ZepBackend()
    elif backend_type == "graphiti":
        from .graphiti_backend import GraphitiBackend
        _backend_instance = GraphitiBackend()
    else:
        raise ValueError(
            f"Unknown GRAPH_BACKEND='{backend_type}'. Valid values: 'zep', 'graphiti'."
        )

    return _backend_instance


def reset_graph_backend() -> None:
    """Reset singleton (useful for testing)."""
    global _backend_instance
    _backend_instance = None
