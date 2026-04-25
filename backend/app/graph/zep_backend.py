"""Zep Cloud implementation of GraphBackend."""
import time
from typing import Any, Dict, List, Optional

from zep_cloud.client import Zep
from zep_cloud import InternalServerError

from .base import GraphBackend
from ..config import Config
from ..utils.logger import get_logger

logger = get_logger('mirofish.graph.zep')

_PAGE_SIZE = 100
_MAX_ITEMS = 2000
_MAX_RETRIES = 3
_RETRY_DELAY = 2.0


def _fetch_page_with_retry(api_call, *args, max_retries=_MAX_RETRIES, retry_delay=_RETRY_DELAY, **kwargs):
    for attempt in range(max_retries):
        try:
            return api_call(*args, **kwargs) or []
        except (ConnectionError, TimeoutError, OSError, InternalServerError):
            if attempt == max_retries - 1:
                raise
            time.sleep(retry_delay * (2 ** attempt))
    return []


def _fetch_all(list_fn, graph_id: str, cursor_key: str = "uuid_cursor") -> List[Any]:
    results, cursor = [], None
    while True:
        kwargs = {"limit": _PAGE_SIZE}
        if cursor:
            kwargs[cursor_key] = cursor
        batch = _fetch_page_with_retry(list_fn, graph_id, **kwargs)
        results.extend(batch)
        if not batch or len(batch) < _PAGE_SIZE or len(results) >= _MAX_ITEMS:
            break
        cursor = batch[-1].uuid_
    return results


class ZepBackend(GraphBackend):
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or Config.ZEP_API_KEY
        if not self.api_key:
            raise ValueError("ZEP_API_KEY is not configured")
        self._client = Zep(api_key=self.api_key)

    def create_graph(self, graph_id: str, name: str, description: str = "") -> None:
        self._client.graph.create(graph_id=graph_id, name=name, description=description)

    def set_ontology(self, graph_ids: List[str], entities: Dict[str, Any], edges: Dict[str, Any]) -> None:
        self._client.graph.set_ontology(graph_ids=graph_ids, entities=entities, edges=edges)

    def add_batch(self, graph_id: str, episodes: List[Any]) -> List[str]:
        from zep_cloud import EpisodeData
        ep_objects = [
            EpisodeData(data=ep["data"], type=ep.get("type", "text"))
            if isinstance(ep, dict) else ep
            for ep in episodes
        ]
        result = self._client.graph.add_batch(graph_id=graph_id, episodes=ep_objects)
        return [ep.uuid_ for ep in (result or [])]

    def get_episode(self, uuid_: str) -> Any:
        return self._client.graph.episode.get(uuid_=uuid_)

    def get_all_nodes(self, graph_id: str) -> List[Dict[str, Any]]:
        nodes = _fetch_all(self._client.graph.node.get_by_graph_id, graph_id)
        return [
            {
                "uuid": getattr(n, "uuid_", None) or getattr(n, "uuid", None),
                "name": getattr(n, "name", ""),
                "labels": list(getattr(n, "labels", []) or []),
                "summary": getattr(n, "summary", ""),
                "attributes": dict(getattr(n, "attributes", {}) or {}),
                "created_at": str(getattr(n, "created_at", "")),
            }
            for n in nodes
        ]

    def get_all_edges(self, graph_id: str) -> List[Dict[str, Any]]:
        edges = _fetch_all(self._client.graph.edge.get_by_graph_id, graph_id)
        return [
            {
                "uuid": getattr(e, "uuid_", None) or getattr(e, "uuid", None),
                "name": getattr(e, "name", ""),
                "fact": getattr(e, "fact", ""),
                "source_node_uuid": getattr(e, "source_node_uuid", None),
                "target_node_uuid": getattr(e, "target_node_uuid", None),
                "fact_type": getattr(e, "fact_type", None),
                "attributes": dict(getattr(e, "attributes", {}) or {}),
                "created_at": str(getattr(e, "created_at", "")),
                "valid_at": str(getattr(e, "valid_at", "")),
                "invalid_at": str(getattr(e, "invalid_at", "")),
                "expired_at": str(getattr(e, "expired_at", "")),
                "episodes": list(getattr(e, "episodes", []) or []),
            }
            for e in edges
        ]

    def get_node(self, uuid_: str) -> Dict[str, Any]:
        n = self._client.graph.node.get(uuid_=uuid_)
        return {
            "uuid": getattr(n, "uuid_", None) or getattr(n, "uuid", None),
            "name": getattr(n, "name", ""),
            "labels": list(getattr(n, "labels", []) or []),
            "summary": getattr(n, "summary", ""),
            "attributes": dict(getattr(n, "attributes", {}) or {}),
        }

    def get_node_edges(self, node_uuid: str) -> List[Dict[str, Any]]:
        for attempt in range(_MAX_RETRIES):
            try:
                edges = self._client.graph.node.get_entity_edges(node_uuid=node_uuid) or []
                return [
                    {
                        "uuid": getattr(e, "uuid_", None) or getattr(e, "uuid", None),
                        "name": getattr(e, "name", ""),
                        "fact": getattr(e, "fact", ""),
                        "source_node_uuid": getattr(e, "source_node_uuid", None),
                        "target_node_uuid": getattr(e, "target_node_uuid", None),
                    }
                    for e in edges
                ]
            except (ConnectionError, TimeoutError, OSError, InternalServerError):
                if attempt == _MAX_RETRIES - 1:
                    raise
                time.sleep(_RETRY_DELAY * (2 ** attempt))
        return []

    def search(self, graph_id: str, query: str, limit: int = 10, scope: str = "edges") -> Dict[str, Any]:
        result = self._client.graph.search(
            graph_id=graph_id,
            query=query,
            limit=limit,
            scope=scope,
            reranker="cross_encoder",
        )
        edges = getattr(result, "edges", []) or []
        nodes = getattr(result, "nodes", []) or []
        return {"edges": edges, "nodes": nodes}

    def add_text(self, graph_id: str, data: str) -> None:
        self._client.graph.add(graph_id=graph_id, type="text", data=data)

    def delete_graph(self, graph_id: str) -> None:
        self._client.graph.delete(graph_id=graph_id)
