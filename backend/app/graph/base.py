"""Abstract graph backend interface."""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class GraphBackend(ABC):
    @abstractmethod
    def create_graph(self, graph_id: str, name: str, description: str = "") -> None: ...

    @abstractmethod
    def set_ontology(self, graph_ids: List[str], entities: Dict[str, Any], edges: Dict[str, Any]) -> None: ...

    @abstractmethod
    def add_batch(self, graph_id: str, episodes: List[Any]) -> List[str]: ...

    @abstractmethod
    def get_episode(self, uuid_: str) -> Any: ...

    @abstractmethod
    def get_all_nodes(self, graph_id: str) -> List[Dict[str, Any]]: ...

    @abstractmethod
    def get_all_edges(self, graph_id: str) -> List[Dict[str, Any]]: ...

    @abstractmethod
    def get_node(self, uuid_: str) -> Dict[str, Any]: ...

    @abstractmethod
    def get_node_edges(self, node_uuid: str) -> List[Dict[str, Any]]: ...

    @abstractmethod
    def search(self, graph_id: str, query: str, limit: int = 10, scope: str = "edges") -> Dict[str, Any]: ...

    @abstractmethod
    def add_text(self, graph_id: str, data: str) -> None: ...

    @abstractmethod
    def delete_graph(self, graph_id: str) -> None: ...
