"""
Zep / OpenZep graph backend implementation.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from zep_cloud.client import Zep

from ..config import Config
from ..utils.zep_paging import fetch_all_edges, fetch_all_nodes
from .base import GraphBackend


class ZepGraphBackend(GraphBackend):
    """Graph backend backed by Zep Cloud or OpenZep."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = Config.ZEP_API_KEY if api_key is None else api_key
        errors = Config.get_zep_config_errors(api_key=self.api_key)
        if errors:
            raise ValueError("; ".join(errors))

        self.client = Zep(**Config.get_zep_client_kwargs(api_key=self.api_key))

    @property
    def raw_client(self) -> Zep:
        return self.client

    def create_graph(self, graph_id: str, name: str, description: str) -> None:
        self.client.graph.create(
            graph_id=graph_id,
            name=name,
            description=description,
        )

    def set_ontology(
        self,
        graph_id: str,
        entities: Any = None,
        edges: Any = None,
    ) -> None:
        self.client.graph.set_ontology(
            graph_ids=[graph_id],
            entities=entities,
            edges=edges,
        )

    def add_batch(self, graph_id: str, episodes: List[Any]) -> List[Any]:
        return self.client.graph.add_batch(graph_id=graph_id, episodes=episodes)

    def add_text(self, graph_id: str, data: str) -> Any:
        return self.client.graph.add(graph_id=graph_id, type="text", data=data)

    def get_episode(self, episode_uuid: str) -> Any:
        return self.client.graph.episode.get(uuid_=episode_uuid)

    def search(
        self,
        graph_id: str,
        query: str,
        limit: int = 10,
        scope: str = "edges",
        reranker: Optional[str] = None,
    ) -> Any:
        kwargs = {
            "graph_id": graph_id,
            "query": query,
            "limit": limit,
            "scope": scope,
        }
        if reranker:
            kwargs["reranker"] = reranker
        return self.client.graph.search(**kwargs)

    def get_all_nodes(self, graph_id: str) -> List[Any]:
        return fetch_all_nodes(self.client, graph_id)

    def get_all_edges(self, graph_id: str) -> List[Any]:
        return fetch_all_edges(self.client, graph_id)

    def get_node(self, node_uuid: str) -> Any:
        return self.client.graph.node.get(uuid_=node_uuid)

    def get_node_edges(self, node_uuid: str) -> List[Any]:
        return self.client.graph.node.get_entity_edges(node_uuid=node_uuid)

    def delete_graph(self, graph_id: str) -> None:
        self.client.graph.delete(graph_id=graph_id)

    def get_live_graph_statistics(self, graph_id: str) -> Optional[Dict[str, int]]:
        if not Config.ZEP_BASE_URL:
            return None

        base_url = Config.ZEP_BASE_URL.rstrip("/")
        request = Request(f"{base_url}/graph/{graph_id}/statistics")
        if self.api_key:
            request.add_header("Authorization", f"Bearer {self.api_key}")

        try:
            with urlopen(request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError):
            return None

        return {
            "node_count": max(0, int(payload.get("node_count", 0) or 0)),
            "edge_count": max(0, int(payload.get("edge_count", 0) or 0)),
            "episode_count": max(0, int(payload.get("episode_count", 0) or 0)),
        }
