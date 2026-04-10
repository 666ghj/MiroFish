"""
Graph backend abstractions.
"""

from .base import GraphBackend
from .factory import get_graph_backend

__all__ = ["GraphBackend", "get_graph_backend"]
