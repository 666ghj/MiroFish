"""Graph memory adapter contracts.

This module defines the narrow graph-memory surface Mirofish needs. Concrete
backends can implement it without leaking vendor SDK details into services.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Protocol


class GraphMemoryAdapter(ABC):
    """Backend-neutral graph memory interface used by Mirofish services."""

    @abstractmethod
    def create_graph(self, graph_id: str, name: str, description: str) -> Any:
        """Create a graph and return the backend response."""

    @abstractmethod
    def set_ontology(self, graph_id: str, ontology: dict[str, Any]) -> Any:
        """Apply ontology definitions for a graph."""

    @abstractmethod
    def add_text_batch(self, graph_id: str, chunks: list[str]) -> Any:
        """Add a batch of text episodes to a graph."""

    @abstractmethod
    def add_text(self, graph_id: str, text: str) -> Any:
        """Add a single text episode to a graph."""

    @abstractmethod
    def get_episode(self, episode_uuid: str) -> Any:
        """Return one episode by UUID."""

    @abstractmethod
    def get_all_nodes(self, graph_id: str) -> list[Any]:
        """Return all nodes for a graph."""

    @abstractmethod
    def get_all_edges(self, graph_id: str) -> list[Any]:
        """Return all edges for a graph."""

    @abstractmethod
    def search(self, graph_id: str, query: str, limit: int = 10, scope: str = "edges", **kwargs: Any) -> Any:
        """Search graph memory."""

    @abstractmethod
    def get_node(self, node_uuid: str) -> Any:
        """Return one node by UUID."""

    @abstractmethod
    def get_node_edges(self, node_uuid: str) -> list[Any]:
        """Return edges related to one node."""

    @abstractmethod
    def delete_graph(self, graph_id: str) -> Any:
        """Delete a graph."""


class SupportsRawClient(Protocol):
    """Compatibility escape hatch for legacy code not yet adapter-native."""

    @property
    def raw_client(self) -> Any:
        """Return the underlying SDK client."""
