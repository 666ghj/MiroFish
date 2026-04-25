"""Graphiti + Neo4j implementation of GraphBackend."""
import asyncio
import threading
import uuid as uuid_mod
from typing import Any, Dict, List, Optional

from .base import GraphBackend
from ..config import Config
from ..utils.logger import get_logger

logger = get_logger('mirofish.graph.graphiti')


def _run_async(coro):
    """Run an async coroutine from a sync context using a dedicated thread loop."""
    loop = _get_event_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=120)


_loop: Optional[asyncio.AbstractEventLoop] = None
_loop_thread: Optional[threading.Thread] = None
_loop_lock = threading.Lock()


def _get_event_loop() -> asyncio.AbstractEventLoop:
    global _loop, _loop_thread
    with _loop_lock:
        if _loop is None or not _loop.is_running():
            _loop = asyncio.new_event_loop()
            _loop_thread = threading.Thread(target=_loop.run_forever, daemon=True)
            _loop_thread.start()
    return _loop


class GraphitiBackend(GraphBackend):
    def __init__(
        self,
        uri: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self._uri = uri or Config.NEO4J_URI
        self._user = user or Config.NEO4J_USER
        self._password = password or Config.NEO4J_PASSWORD
        if not self._password:
            raise ValueError("NEO4J_PASSWORD is not configured")
        self._client = self._build_client()

    def _build_client(self):
        from graphiti_core import Graphiti
        from graphiti_core.llm_client.openai_client import OpenAIClient
        from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
        from neo4j import AsyncGraphDatabase

        llm_client = OpenAIClient(
            api_key=Config.LLM_API_KEY,
            model=Config.LLM_MODEL_NAME,
            base_url=Config.LLM_BASE_URL,
        )
        embedder = OpenAIEmbedder(
            OpenAIEmbedderConfig(
                api_key=Config.LLM_API_KEY,
                base_url=Config.LLM_BASE_URL,
            )
        )
        driver = AsyncGraphDatabase.driver(
            self._uri, auth=(self._user, self._password)
        )
        return Graphiti(driver=driver, llm_client=llm_client, embedder=embedder)

    def create_graph(self, graph_id: str, name: str, description: str = "") -> None:
        logger.info(f"Graphiti graph namespace ready: {graph_id}")

    def set_ontology(self, graph_ids: List[str], entities: Dict[str, Any], edges: Dict[str, Any]) -> None:
        logger.info("Graphiti uses LLM-driven ontology extraction; set_ontology is a no-op.")

    def add_batch(self, graph_id: str, episodes: List[Any]) -> List[str]:
        from graphiti_core.nodes import EpisodeType
        ids = []
        for ep in episodes:
            data = ep["data"] if isinstance(ep, dict) else ep.data
            ep_id = str(uuid_mod.uuid4())
            _run_async(
                self._client.add_episode(
                    name=ep_id,
                    episode_body=data,
                    source=EpisodeType.text,
                    group_id=graph_id,
                )
            )
            ids.append(ep_id)
        return ids

    def get_episode(self, uuid_: str) -> Any:
        class _FakeEpisode:
            processed = True
        return _FakeEpisode()

    def get_all_nodes(self, graph_id: str) -> List[Dict[str, Any]]:
        results = _run_async(
            self._client.driver.execute_query(
                "MATCH (n {group_id: $gid}) RETURN n",
                {"gid": graph_id},
            )
        )
        nodes = []
        for record in results.records:
            n = record["n"]
            nodes.append({
                "uuid": n.get("uuid", str(n.id)),
                "name": n.get("name", ""),
                "labels": list(n.labels),
                "summary": n.get("summary", ""),
                "attributes": dict(n),
                "created_at": str(n.get("created_at", "")),
            })
        return nodes

    def get_all_edges(self, graph_id: str) -> List[Dict[str, Any]]:
        results = _run_async(
            self._client.driver.execute_query(
                "MATCH (s)-[r]->(t) WHERE r.group_id = $gid RETURN s, r, t",
                {"gid": graph_id},
            )
        )
        edges = []
        for record in results.records:
            r = record["r"]
            edges.append({
                "uuid": r.get("uuid", str(r.id)),
                "name": r.get("name", type(r).__name__),
                "fact": r.get("fact", ""),
                "source_node_uuid": record["s"].get("uuid", ""),
                "target_node_uuid": record["t"].get("uuid", ""),
                "fact_type": r.get("fact_type", ""),
                "attributes": dict(r),
                "created_at": str(r.get("created_at", "")),
                "valid_at": str(r.get("valid_at", "")),
                "invalid_at": str(r.get("invalid_at", "")),
                "expired_at": str(r.get("expired_at", "")),
                "episodes": [],
            })
        return edges

    def get_node(self, uuid_: str) -> Dict[str, Any]:
        results = _run_async(
            self._client.driver.execute_query(
                "MATCH (n {uuid: $uuid}) RETURN n LIMIT 1",
                {"uuid": uuid_},
            )
        )
        if not results.records:
            return {}
        n = results.records[0]["n"]
        return {
            "uuid": n.get("uuid", ""),
            "name": n.get("name", ""),
            "labels": list(n.labels),
            "summary": n.get("summary", ""),
            "attributes": dict(n),
        }

    def get_node_edges(self, node_uuid: str) -> List[Dict[str, Any]]:
        results = _run_async(
            self._client.driver.execute_query(
                "MATCH (n {uuid: $uuid})-[r]->(t) RETURN r, t "
                "UNION MATCH (s)-[r]->(n {uuid: $uuid}) RETURN r, s as t",
                {"uuid": node_uuid},
            )
        )
        edges = []
        for record in results.records:
            r = record["r"]
            edges.append({
                "uuid": r.get("uuid", str(r.id)),
                "name": r.get("name", ""),
                "fact": r.get("fact", ""),
                "source_node_uuid": r.get("source_node_uuid", node_uuid),
                "target_node_uuid": r.get("target_node_uuid", ""),
            })
        return edges

    def search(self, graph_id: str, query: str, limit: int = 10, scope: str = "edges") -> Dict[str, Any]:
        results = _run_async(
            self._client.search(query=query, group_ids=[graph_id], num_results=limit)
        )
        edges = [
            {
                "uuid": getattr(r, "uuid", ""),
                "name": getattr(r, "name", ""),
                "fact": getattr(r, "fact", ""),
                "source_node_uuid": getattr(r, "source_node_uuid", ""),
                "target_node_uuid": getattr(r, "target_node_uuid", ""),
            }
            for r in (results or [])
        ]
        return {"edges": edges, "nodes": []}

    def add_text(self, graph_id: str, data: str) -> None:
        ep_id = str(uuid_mod.uuid4())
        from graphiti_core.nodes import EpisodeType
        _run_async(
            self._client.add_episode(
                name=ep_id,
                episode_body=data,
                source=EpisodeType.text,
                group_id=graph_id,
            )
        )

    def delete_graph(self, graph_id: str) -> None:
        _run_async(
            self._client.driver.execute_query(
                "MATCH (n {group_id: $gid}) DETACH DELETE n",
                {"gid": graph_id},
            )
        )
