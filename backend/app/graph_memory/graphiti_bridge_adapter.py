"""HTTP adapter for the on-premise Graphiti bridge service."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .base import GraphMemoryAdapter
from ..config import Config


class GraphitiBridgeGraphMemoryAdapter(GraphMemoryAdapter):
    """Graph memory adapter backed by the local Graphiti bridge service."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.base_url = (base_url or Config.GRAPHITI_BRIDGE_URL).rstrip("/")
        self._node_graph_index: dict[str, str] = {}

    @property
    def raw_client(self) -> None:
        return None

    def create_graph(self, graph_id: str, name: str, description: str) -> Any:
        return self._to_namespace(self._request("POST", "/graphs", {"graph_id": graph_id, "name": name, "description": description}))

    def set_ontology(self, graph_id: str, ontology: dict[str, Any]) -> Any:
        return self._request("POST", f"/graphs/{quote(graph_id)}/ontology", ontology)

    def add_text_batch(self, graph_id: str, chunks: list[str]) -> list[Any]:
        data = self._request("POST", f"/graphs/{quote(graph_id)}/episodes", {"chunks": chunks})
        return [self._episode(item) for item in data.get("episodes", [])]

    def add_text(self, graph_id: str, text: str) -> Any:
        data = self._request("POST", f"/graphs/{quote(graph_id)}/episodes", {"text": text})
        episodes = data.get("episodes", [])
        return self._episode(episodes[0]) if episodes else self._episode({"uuid": None, "processed": True})

    def get_episode(self, episode_uuid: str) -> Any:
        return self._episode({"uuid": episode_uuid, "processed": True})

    def get_all_nodes(self, graph_id: str) -> list[Any]:
        data = self._request("GET", f"/graphs/{quote(graph_id)}/nodes")
        nodes = [self._node(item) for item in data.get("nodes", [])]
        for node in nodes:
            self._node_graph_index[node.uuid_] = graph_id
        return nodes

    def get_all_edges(self, graph_id: str) -> list[Any]:
        data = self._request("GET", f"/graphs/{quote(graph_id)}/edges")
        return [self._edge(item) for item in data.get("edges", [])]

    def search(self, graph_id: str, query: str, limit: int = 10, scope: str = "edges", **kwargs: Any) -> Any:
        data = self._request("POST", f"/graphs/{quote(graph_id)}/search", {"query": query, "limit": limit, "scope": scope})
        nodes = [self._node(item) for item in data.get("nodes", [])]
        for node in nodes:
            self._node_graph_index[node.uuid_] = graph_id
        return SimpleNamespace(edges=[self._edge(item) for item in data.get("edges", [])], nodes=nodes)

    def get_node(self, node_uuid: str) -> Any:
        graph_id = self._node_graph_index.get(node_uuid)
        if not graph_id:
            return None
        query = urlencode({"graph_id": graph_id})
        data = self._request("GET", f"/nodes/{quote(node_uuid)}?{query}")
        node = data.get("node")
        return self._node(node) if node else None

    def get_node_edges(self, node_uuid: str) -> list[Any]:
        graph_id = self._node_graph_index.get(node_uuid)
        if not graph_id:
            return []
        query = urlencode({"graph_id": graph_id})
        data = self._request("GET", f"/nodes/{quote(node_uuid)}/edges?{query}")
        return [self._edge(item) for item in data.get("edges", [])]

    def delete_graph(self, graph_id: str) -> Any:
        return self._request("DELETE", f"/graphs/{quote(graph_id)}")

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        req = Request(f"{self.base_url}{path}", data=body, headers=headers, method=method)
        try:
            with urlopen(req, timeout=120) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Graphiti bridge request failed: {exc.code} {error_body}") from exc

    def _episode(self, data: dict[str, Any]) -> Any:
        uuid = data.get("uuid") or data.get("uuid_")
        return SimpleNamespace(uuid_=uuid, uuid=uuid, processed=data.get("processed", True))

    def _node(self, data: dict[str, Any]) -> Any:
        uuid = data.get("uuid") or data.get("uuid_") or ""
        return SimpleNamespace(
            uuid_=uuid,
            uuid=uuid,
            name=data.get("name") or "",
            labels=data.get("labels") or [],
            summary=data.get("summary") or "",
            attributes=data.get("attributes") or {},
            created_at=data.get("created_at"),
        )

    def _edge(self, data: dict[str, Any]) -> Any:
        uuid = data.get("uuid") or data.get("uuid_") or ""
        return SimpleNamespace(
            uuid_=uuid,
            uuid=uuid,
            name=data.get("name") or "",
            fact=data.get("fact") or "",
            source_node_uuid=data.get("source_node_uuid") or "",
            target_node_uuid=data.get("target_node_uuid") or "",
            attributes=data.get("attributes") or {},
            created_at=data.get("created_at"),
            valid_at=data.get("valid_at"),
            invalid_at=data.get("invalid_at"),
            expired_at=data.get("expired_at"),
        )

    def _to_namespace(self, data: dict[str, Any]) -> Any:
        return SimpleNamespace(**data)
