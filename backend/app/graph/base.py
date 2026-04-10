"""
Common graph backend interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class GraphBackend(ABC):
    """Minimal graph backend interface used by the application services."""

    @property
    def raw_client(self) -> Any:
        """Return the underlying SDK client when a service still needs it."""
        return None

    @abstractmethod
    def create_graph(self, graph_id: str, name: str, description: str) -> None:
        """Create a graph."""

    @abstractmethod
    def set_ontology(
        self,
        graph_id: str,
        entities: Any = None,
        edges: Any = None,
    ) -> None:
        """Set graph ontology."""

    @abstractmethod
    def add_batch(self, graph_id: str, episodes: List[Any]) -> List[Any]:
        """Add a batch of episodes."""

    @abstractmethod
    def add_text(self, graph_id: str, data: str) -> Any:
        """Add a single text episode."""

    @abstractmethod
    def get_episode(self, episode_uuid: str) -> Any:
        """Fetch a single episode."""

    @abstractmethod
    def search(
        self,
        graph_id: str,
        query: str,
        limit: int = 10,
        scope: str = "edges",
        reranker: Optional[str] = None,
    ) -> Any:
        """Search the graph."""

    @abstractmethod
    def get_all_nodes(self, graph_id: str) -> List[Any]:
        """Fetch all nodes."""

    @abstractmethod
    def get_all_edges(self, graph_id: str) -> List[Any]:
        """Fetch all edges."""

    @abstractmethod
    def get_node(self, node_uuid: str) -> Any:
        """Fetch a node by UUID."""

    @abstractmethod
    def get_node_edges(self, node_uuid: str) -> List[Any]:
        """Fetch edges for a node."""

    @abstractmethod
    def delete_graph(self, graph_id: str) -> None:
        """Delete a graph."""

    def get_ontology_spec(self, graph_id: str) -> Optional[Dict[str, Any]]:
        """Fetch backend ontology metadata when available."""
        return None

    def get_live_graph_statistics(self, graph_id: str) -> Optional[Dict[str, int]]:
        """Fetch backend-specific live statistics when available."""
        return None
