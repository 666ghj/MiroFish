"""Self-hosted Graphiti implementation of :class:`MemoryBackend`.

Talks to a local Neo4j database via the ``graphiti-core`` library so
MiroFish can run with no external memory provider. Designed to be a
drop-in replacement for :class:`ZepCloudBackend`: the same DTOs come
out, the same ontology dict goes in, and the same call sites work.

The Graphiti library is async-only. We hide that behind a private
event loop running on a daemon thread, so callers continue to use a
synchronous interface. One loop per backend instance keeps the cost
of marshaling minimal.

Environment variables (all read at construction time):

* ``NEO4J_URI``       – default ``bolt://localhost:7687``
* ``NEO4J_USER``      – default ``neo4j``
* ``NEO4J_PASSWORD``  – default ``mirofish-local``
* ``GRAPHITI_LLM_API_KEY``  – optional override; falls back to
  ``LLM_API_KEY`` (the existing OpenRouter / OpenAI-compatible key)
* ``GRAPHITI_LLM_BASE_URL`` – optional override; falls back to ``LLM_BASE_URL``
* ``GRAPHITI_LLM_MODEL``    – optional override; falls back to ``LLM_MODEL_NAME``
* ``GRAPHITI_EMBEDDING_MODEL`` – default ``text-embedding-3-small``
"""

from __future__ import annotations

import asyncio
import os
import threading
import uuid as uuid_lib
from collections.abc import Iterator
from concurrent.futures import Future
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from ...config import Config
from ...utils.logger import get_logger
from .base import (
    Edge,
    EpisodeInput,
    EpisodeRef,
    MemoryBackend,
    Node,
    OntologySpec,
    SearchResult,
)
from .exceptions import (
    MemoryBackendError,
    MemoryBackendNotConfigured,
    MemoryBackendUnavailable,
)

logger = get_logger("mirofish.memory.graphiti")

_DEFAULT_NEO4J_URI = "bolt://localhost:7687"
_DEFAULT_NEO4J_USER = "neo4j"
_DEFAULT_NEO4J_PASSWORD = "mirofish-local"
_DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
_DEFAULT_LOCAL_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


# --------------------------------------------------------------------------
# Async-to-sync adapter
# --------------------------------------------------------------------------


class _LoopThread:
    """Owns a background asyncio event loop on a daemon thread.

    Provides :meth:`run` which submits a coroutine and blocks on the
    result. We keep one loop per backend instance so successive Cypher
    queries reuse the same Neo4j connection pool.
    """

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop, name="graphiti-loop", daemon=True
        )
        self._thread.start()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def run(self, coro: Any, *, timeout: Optional[float] = None) -> Any:
        """Submit a coroutine to the background loop and block on its result.

        ``timeout`` (seconds) bounds the wait. ``None`` means wait
        forever. Always pass a finite timeout from cleanup paths to
        avoid hanging interpreter shutdown if the loop is wedged.
        """
        future: Future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    def close(self) -> None:
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)
        try:
            self._loop.close()
        except Exception:  # noqa: BLE001
            pass


# --------------------------------------------------------------------------
# Pydantic ontology builders
# --------------------------------------------------------------------------


def _build_ontology_models(
    ontology: OntologySpec,
) -> tuple[dict[str, type], dict[str, type], dict[tuple[str, str], list[str]]]:
    """Translate :class:`OntologySpec` into Graphiti-shaped types.

    Returns ``(entity_types, edge_types, edge_type_map)`` where:

    * ``entity_types`` maps type name → dynamic Pydantic model.
    * ``edge_types`` maps relation name → dynamic Pydantic model.
    * ``edge_type_map`` constrains which edges may exist between which
      entity-type pairs (``(source, target) → [edge names]``).
    """
    from pydantic import BaseModel, Field

    reserved = {"uuid", "name", "group_id", "name_embedding", "summary", "created_at"}

    def safe_attr(name: str) -> str:
        return f"entity_{name}" if name.lower() in reserved else name

    entity_types: dict[str, type] = {}
    for ent in ontology.entity_types:
        attrs: dict[str, Any] = {"__doc__": ent.description or f"A {ent.name} entity."}
        annotations: dict[str, Any] = {}
        for a in ent.attributes:
            key = safe_attr(a.name)
            attrs[key] = Field(description=a.description or key, default=None)
            annotations[key] = Optional[str]
        attrs["__annotations__"] = annotations
        entity_types[ent.name] = type(ent.name, (BaseModel,), attrs)

    edge_types: dict[str, type] = {}
    edge_type_map: dict[tuple[str, str], list[str]] = {}
    for edge in ontology.edge_types:
        attrs = {"__doc__": edge.description or f"A {edge.name} relationship."}
        annotations = {}
        for a in edge.attributes:
            key = safe_attr(a.name)
            attrs[key] = Field(description=a.description or key, default=None)
            annotations[key] = Optional[str]
        attrs["__annotations__"] = annotations
        cls_name = "".join(w.capitalize() for w in edge.name.split("_"))
        edge_types[edge.name] = type(cls_name, (BaseModel,), attrs)

        for st in edge.source_targets:
            edge_type_map.setdefault((st.source, st.target), []).append(edge.name)

    return entity_types, edge_types, edge_type_map


# --------------------------------------------------------------------------
# Backend
# --------------------------------------------------------------------------


class GraphitiBackend(MemoryBackend):
    """Self-hosted Graphiti + Neo4j-backed implementation."""

    # Per-graph ontology cache: graph_id -> (entity_types, edge_types, edge_type_map)
    _ontology_cache: dict[str, tuple[dict[str, type], dict[str, type], dict[tuple[str, str], list[str]]]]

    def __init__(self) -> None:
        self._neo4j_uri = os.environ.get("NEO4J_URI", _DEFAULT_NEO4J_URI)
        self._neo4j_user = os.environ.get("NEO4J_USER", _DEFAULT_NEO4J_USER)
        self._neo4j_password = os.environ.get(
            "NEO4J_PASSWORD", _DEFAULT_NEO4J_PASSWORD
        )

        # Defer heavy imports until first construction so callers using
        # the Zep backend never need graphiti-core installed.
        try:
            from graphiti_core import Graphiti
        except ImportError as e:
            raise MemoryBackendNotConfigured(
                "graphiti-core is not installed. Run `uv add graphiti-core` "
                "(or pip install graphiti-core) to use MEMORY_BACKEND=graphiti."
            ) from e

        self._loop = _LoopThread()
        self._ontology_cache = {}

        llm_client, embedder, cross_encoder = self._build_llm_clients()

        try:
            self._graphiti = Graphiti(
                uri=self._neo4j_uri,
                user=self._neo4j_user,
                password=self._neo4j_password,
                llm_client=llm_client,
                embedder=embedder,
                cross_encoder=cross_encoder,
            )
        except Exception as e:  # noqa: BLE001
            raise MemoryBackendUnavailable(
                f"Failed to connect to Neo4j at {self._neo4j_uri}: {e}"
            ) from e

        # Build indices / constraints on first use. This is idempotent
        # and cheap when the schema already exists.
        try:
            self._loop.run(self._graphiti.build_indices_and_constraints())
        except Exception as e:  # noqa: BLE001
            logger.warning("build_indices_and_constraints failed (non-fatal): %s", e)

        logger.info(
            "GraphitiBackend ready: neo4j=%s user=%s", self._neo4j_uri, self._neo4j_user
        )

    # ------------------------------------------------------------------
    # LLM / embedder configuration
    # ------------------------------------------------------------------

    def _build_llm_clients(self) -> tuple[Any, Any, Any]:
        """Build LLM + embedder + cross-encoder clients all pointing at
        our existing OpenAI-compatible setup, so operators don't need a
        separate ``OPENAI_API_KEY``.

        Returns ``(llm_client, embedder, cross_encoder)``. Any of them
        may be ``None`` to fall back to Graphiti's library defaults
        (which require ``OPENAI_API_KEY``).
        """
        api_key = (
            os.environ.get("GRAPHITI_LLM_API_KEY")
            or Config.LLM_API_KEY
            or os.environ.get("OPENAI_API_KEY")
        )
        base_url = (
            os.environ.get("GRAPHITI_LLM_BASE_URL")
            or Config.LLM_BASE_URL
            or "https://api.openai.com/v1"
        )
        model = (
            os.environ.get("GRAPHITI_LLM_MODEL")
            or Config.LLM_MODEL_NAME
            or "gpt-4o-mini"
        )
        embedding_model = os.environ.get(
            "GRAPHITI_EMBEDDING_MODEL", _DEFAULT_EMBEDDING_MODEL
        )

        if not api_key:
            logger.warning(
                "No LLM API key configured; Graphiti will fall back to "
                "OPENAI_API_KEY environment variable for entity extraction."
            )
            return None, None, None

        # Embedding source selection.
        #
        # Most OpenAI-compatible chat providers (OpenRouter included)
        # do NOT expose ``/embeddings``. Default to a fully local
        # sentence-transformers embedder so the self-hosted setup
        # works without an external embedding key. Operators who do
        # have a real embedding endpoint can opt back in by setting
        # ``GRAPHITI_EMBEDDING_PROVIDER=openai``.
        embedding_provider = os.environ.get(
            "GRAPHITI_EMBEDDING_PROVIDER", "local"
        ).lower()

        try:
            from graphiti_core.cross_encoder.openai_reranker_client import (
                OpenAIRerankerClient,
            )
            from graphiti_core.llm_client.config import LLMConfig
            from graphiti_core.llm_client.openai_generic_client import (
                OpenAIGenericClient,
            )

            llm_config = LLMConfig(
                api_key=api_key,
                base_url=base_url,
                model=model,
            )
            llm_client = OpenAIGenericClient(config=llm_config)

            if embedding_provider == "openai":
                from graphiti_core.embedder.openai import (
                    OpenAIEmbedder,
                    OpenAIEmbedderConfig,
                )

                embedder_config = OpenAIEmbedderConfig(
                    api_key=api_key,
                    base_url=base_url,
                    embedding_model=embedding_model,
                )
                embedder = OpenAIEmbedder(config=embedder_config)
            else:
                from .local_embedder import (
                    LocalEmbedderConfig,
                    LocalSentenceTransformerEmbedder,
                )

                local_model = os.environ.get(
                    "GRAPHITI_LOCAL_EMBEDDING_MODEL",
                    _DEFAULT_LOCAL_EMBEDDING_MODEL,
                )
                embedder = LocalSentenceTransformerEmbedder(
                    config=LocalEmbedderConfig(embedding_model=local_model)
                )
                logger.info(
                    "Using local sentence-transformers embedder: %s", local_model
                )

            # The cross-encoder reranker also defaults to OpenAI direct,
            # which fails for self-hosted users without OPENAI_API_KEY.
            # Wire it through the same config so reranking uses our LLM.
            cross_encoder = OpenAIRerankerClient(config=llm_config)

            return llm_client, embedder, cross_encoder
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "Could not build OpenAI-compatible Graphiti clients (%s); "
                "falling back to library defaults.",
                e,
            )
            return None, None, None

    # ------------------------------------------------------------------
    # Identification
    # ------------------------------------------------------------------

    def name(self) -> str:
        return "graphiti"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def create_graph(
        self,
        graph_id: str,
        *,
        display_name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> None:
        # Graphiti has no explicit graph creation step — group_id is a
        # property attached to nodes/edges at write time. This call is
        # intentionally a no-op so the surrounding refactor does not
        # need a special case.
        logger.debug(
            "Graphiti create_graph(%s) is a no-op; group_id assigned at write time",
            graph_id,
        )

    def delete_graph(self, graph_id: str) -> None:
        async def _delete() -> None:
            for label in ("Entity", "Episodic", "Community"):
                await self._graphiti.driver.execute_query(
                    f"MATCH (n:{label} {{group_id: $group_id}}) DETACH DELETE n",
                    group_id=graph_id,
                )

        try:
            self._loop.run(_delete())
        except Exception as e:  # noqa: BLE001
            raise MemoryBackendUnavailable(f"delete_graph failed: {e}") from e
        self._ontology_cache.pop(graph_id, None)

    def set_ontology(self, graph_id: str, ontology: OntologySpec) -> None:
        # Graphiti accepts ontology per-call to add_episode rather than
        # storing it server-side. We cache the compiled types and apply
        # them on every subsequent ingest.
        self._ontology_cache[graph_id] = _build_ontology_models(ontology)

    # ------------------------------------------------------------------
    # Episode ingest
    # ------------------------------------------------------------------

    def add_episode(self, graph_id: str, episode: EpisodeInput) -> EpisodeRef:
        return self._add_episode_blocking(graph_id, episode)

    def add_episodes_bulk(
        self, graph_id: str, episodes: list[EpisodeInput]
    ) -> list[EpisodeRef]:
        # Graphiti's add_episode_bulk has stricter input shape; the
        # naive per-episode loop is identical in cost because the
        # library serialises LLM extraction internally anyway, and
        # this approach avoids a partial-failure cliff.
        return [self._add_episode_blocking(graph_id, ep) for ep in episodes]

    def _add_episode_blocking(self, graph_id: str, episode: EpisodeInput) -> EpisodeRef:
        from graphiti_core.nodes import EpisodeType as GraphitiEpisodeType

        type_map = {
            "text": GraphitiEpisodeType.text,
            "message": GraphitiEpisodeType.message,
            "json": GraphitiEpisodeType.json,
        }
        graphiti_type = type_map.get(episode.episode_type, GraphitiEpisodeType.message)

        ontology = self._ontology_cache.get(graph_id)
        entity_types = ontology[0] if ontology else None
        edge_types = ontology[1] if ontology else None
        edge_type_map = ontology[2] if ontology else None

        ref_time = episode.reference_time or datetime.now(timezone.utc)
        episode_name = f"episode-{uuid_lib.uuid4().hex[:8]}"

        async def _ingest() -> Any:
            # graphiti-core 0.9.x supports entity_types only; the
            # edge_types / edge_type_map parameters were added in 0.20+
            # which is currently incompatible with camel-oasis. Edge
            # type guidance is therefore communicated to the LLM only
            # via the system prompts that include the ontology summary.
            return await self._graphiti.add_episode(
                name=episode_name,
                episode_body=episode.content,
                source=graphiti_type,
                source_description=episode.source_description or "",
                reference_time=ref_time,
                group_id=graph_id,
                entity_types=entity_types,
            )

        try:
            result = self._loop.run(_ingest())
        except Exception as e:  # noqa: BLE001
            raise MemoryBackendUnavailable(f"add_episode failed: {e}") from e

        ep_node = getattr(result, "episode", None) or result
        ep_uuid = getattr(ep_node, "uuid", "") or ""
        return EpisodeRef(
            uuid=ep_uuid,
            processed=True,  # Graphiti is synchronous — done when returned
            content=episode.content,
            source_description=episode.source_description,
            created_at=ref_time.isoformat(),
        )

    def get_episode(self, episode_uuid: str) -> Optional[EpisodeRef]:
        async def _get() -> Optional[dict[str, Any]]:
            records, _, _ = await self._graphiti.driver.execute_query(
                """
                MATCH (e:Episodic {uuid: $uuid})
                RETURN e.uuid AS uuid, e.content AS content,
                       e.source_description AS source_description,
                       e.created_at AS created_at
                """,
                uuid=episode_uuid,
            )
            return records[0] if records else None

        try:
            row = self._loop.run(_get())
        except Exception as e:  # noqa: BLE001
            logger.debug("Graphiti get_episode(%s) failed: %s", episode_uuid, e)
            return None
        if not row:
            return None
        return EpisodeRef(
            uuid=row.get("uuid") or "",
            processed=True,
            content=row.get("content"),
            source_description=row.get("source_description"),
            created_at=str(row.get("created_at")) if row.get("created_at") else None,
        )

    # ------------------------------------------------------------------
    # Graph reads
    # ------------------------------------------------------------------

    def search(
        self,
        graph_id: str,
        query: str,
        *,
        limit: int = 10,
        scope: Literal["edges", "nodes"] = "edges",
    ) -> SearchResult:
        async def _search() -> Any:
            return await self._graphiti.search(
                query=query,
                group_ids=[graph_id],
                num_results=limit,
            )

        try:
            edge_objs = self._loop.run(_search())
        except Exception as e:  # noqa: BLE001
            raise MemoryBackendUnavailable(f"search failed: {e}") from e

        edges = [self._edge_from_graphiti(e) for e in (edge_objs or [])]
        # Graphiti's basic search returns edges only. If the caller
        # asked for nodes specifically, derive them from the edge
        # endpoints to satisfy the contract.
        nodes: list[Node] = []
        if scope == "nodes" and edges:
            uuids = {uid for e in edges for uid in (e.source_node_uuid, e.target_node_uuid) if uid}
            for uid in uuids:
                node = self.get_node(uid)
                if node is not None:
                    nodes.append(node)
        return SearchResult(edges=edges, nodes=nodes)

    def get_node(self, node_uuid: str) -> Optional[Node]:
        async def _get() -> Optional[dict[str, Any]]:
            records, _, _ = await self._graphiti.driver.execute_query(
                """
                MATCH (n:Entity {uuid: $uuid})
                RETURN n.uuid AS uuid, n.name AS name, labels(n) AS labels,
                       n.summary AS summary, n.attributes AS attributes,
                       n.created_at AS created_at
                """,
                uuid=node_uuid,
            )
            return records[0] if records else None

        try:
            row = self._loop.run(_get())
        except Exception as e:  # noqa: BLE001
            logger.debug("Graphiti get_node(%s) failed: %s", node_uuid, e)
            return None
        return self._node_from_record(row) if row else None

    def get_nodes_by_graph(
        self, graph_id: str, *, page_size: int = 100, max_items: int = 2000
    ) -> Iterator[Node]:
        async def _all() -> list[dict[str, Any]]:
            records, _, _ = await self._graphiti.driver.execute_query(
                """
                MATCH (n:Entity {group_id: $group_id})
                RETURN n.uuid AS uuid, n.name AS name, labels(n) AS labels,
                       n.summary AS summary, n.attributes AS attributes,
                       n.created_at AS created_at
                LIMIT $max
                """,
                group_id=graph_id,
                max=max_items,
            )
            return list(records)

        try:
            rows = self._loop.run(_all())
        except Exception as e:  # noqa: BLE001
            raise MemoryBackendUnavailable(f"get_nodes_by_graph failed: {e}") from e

        for row in rows:
            node = self._node_from_record(row)
            if node is not None:
                yield node

    def get_edges_by_graph(
        self, graph_id: str, *, page_size: int = 100
    ) -> Iterator[Edge]:
        async def _all() -> list[dict[str, Any]]:
            records, _, _ = await self._graphiti.driver.execute_query(
                """
                MATCH (s:Entity)-[r:RELATES_TO {group_id: $group_id}]->(t:Entity)
                RETURN r.uuid AS uuid, r.name AS name, r.fact AS fact,
                       r.fact_type AS fact_type,
                       s.uuid AS source_node_uuid, t.uuid AS target_node_uuid,
                       r.attributes AS attributes,
                       r.created_at AS created_at, r.valid_at AS valid_at,
                       r.invalid_at AS invalid_at, r.expired_at AS expired_at,
                       r.episodes AS episodes
                """,
                group_id=graph_id,
            )
            return list(records)

        try:
            rows = self._loop.run(_all())
        except Exception as e:  # noqa: BLE001
            raise MemoryBackendUnavailable(f"get_edges_by_graph failed: {e}") from e

        for row in rows:
            yield self._edge_from_record(row)

    def get_node_edges(self, node_uuid: str) -> list[Edge]:
        async def _all() -> list[dict[str, Any]]:
            records, _, _ = await self._graphiti.driver.execute_query(
                """
                MATCH (n:Entity {uuid: $uuid})-[r:RELATES_TO]-(other:Entity)
                RETURN r.uuid AS uuid, r.name AS name, r.fact AS fact,
                       r.fact_type AS fact_type,
                       startNode(r).uuid AS source_node_uuid,
                       endNode(r).uuid AS target_node_uuid,
                       r.attributes AS attributes,
                       r.created_at AS created_at, r.valid_at AS valid_at,
                       r.invalid_at AS invalid_at, r.expired_at AS expired_at,
                       r.episodes AS episodes
                """,
                uuid=node_uuid,
            )
            return list(records)

        try:
            rows = self._loop.run(_all())
        except Exception as e:  # noqa: BLE001
            logger.debug("Graphiti get_node_edges(%s) failed: %s", node_uuid, e)
            return []
        return [self._edge_from_record(row) for row in rows]

    # ------------------------------------------------------------------
    # Record / SDK → DTO mappers
    # ------------------------------------------------------------------

    @staticmethod
    def _node_from_record(row: dict[str, Any]) -> Optional[Node]:
        if not row or not row.get("uuid"):
            return None
        attributes = row.get("attributes") or {}
        if isinstance(attributes, str):
            # Neo4j may return JSON-as-string for free-form attribute maps
            import json

            try:
                attributes = json.loads(attributes)
            except Exception:  # noqa: BLE001
                attributes = {}
        labels = row.get("labels") or []
        return Node(
            uuid=row["uuid"],
            name=row.get("name") or "",
            labels=list(labels),
            summary=row.get("summary") or "",
            attributes=dict(attributes),
            created_at=str(row["created_at"]) if row.get("created_at") else None,
        )

    @staticmethod
    def _edge_from_record(row: dict[str, Any]) -> Edge:
        attributes = row.get("attributes") or {}
        if isinstance(attributes, str):
            import json

            try:
                attributes = json.loads(attributes)
            except Exception:  # noqa: BLE001
                attributes = {}

        episodes_raw = row.get("episodes")
        if episodes_raw is None:
            episode_list: list[str] = []
        elif isinstance(episodes_raw, list):
            episode_list = [str(e) for e in episodes_raw]
        else:
            episode_list = [str(episodes_raw)]

        return Edge(
            uuid=row.get("uuid") or "",
            name=row.get("name") or "",
            fact=row.get("fact") or "",
            fact_type=row.get("fact_type") or row.get("name") or "",
            source_node_uuid=row.get("source_node_uuid") or "",
            target_node_uuid=row.get("target_node_uuid") or "",
            attributes=dict(attributes),
            created_at=str(row["created_at"]) if row.get("created_at") else None,
            valid_at=str(row["valid_at"]) if row.get("valid_at") else None,
            invalid_at=str(row["invalid_at"]) if row.get("invalid_at") else None,
            expired_at=str(row["expired_at"]) if row.get("expired_at") else None,
            episodes=episode_list,
        )

    @staticmethod
    def _edge_from_graphiti(edge_obj: Any) -> Edge:
        episodes = getattr(edge_obj, "episodes", None) or []
        if not isinstance(episodes, list):
            episodes = [episodes]
        attributes = getattr(edge_obj, "attributes", None) or {}
        return Edge(
            uuid=getattr(edge_obj, "uuid", "") or "",
            name=getattr(edge_obj, "name", "") or "",
            fact=getattr(edge_obj, "fact", "") or "",
            fact_type=getattr(edge_obj, "fact_type", None)
            or getattr(edge_obj, "name", None)
            or "",
            source_node_uuid=getattr(edge_obj, "source_node_uuid", "") or "",
            target_node_uuid=getattr(edge_obj, "target_node_uuid", "") or "",
            attributes=dict(attributes),
            created_at=str(getattr(edge_obj, "created_at", None))
            if getattr(edge_obj, "created_at", None)
            else None,
            valid_at=str(getattr(edge_obj, "valid_at", None))
            if getattr(edge_obj, "valid_at", None)
            else None,
            invalid_at=str(getattr(edge_obj, "invalid_at", None))
            if getattr(edge_obj, "invalid_at", None)
            else None,
            expired_at=str(getattr(edge_obj, "expired_at", None))
            if getattr(edge_obj, "expired_at", None)
            else None,
            episodes=[str(e) for e in episodes],
        )

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Release the background loop and Neo4j driver.

        Call explicitly when shutting down a long-running process.
        Cleanup is bounded so interpreter shutdown cannot hang on a
        wedged event loop.
        """
        try:
            if hasattr(self, "_graphiti"):
                self._loop.run(self._graphiti.close(), timeout=3.0)
        except Exception:  # noqa: BLE001
            pass
        try:
            if hasattr(self, "_loop"):
                self._loop.close()
        except Exception:  # noqa: BLE001
            pass

    def __del__(self) -> None:
        # Best-effort cleanup. We deliberately do NOT await the
        # async ``close`` here — interpreter shutdown can race with
        # the background loop and a hung await would freeze the whole
        # process for the user. The OS will reclaim Neo4j sockets
        # cleanly when the process exits.
        try:
            if hasattr(self, "_loop"):
                # Stop the loop without joining the thread or running
                # async cleanup. Daemon thread dies with the process.
                self._loop._loop.call_soon_threadsafe(  # type: ignore[attr-defined]
                    self._loop._loop.stop  # type: ignore[attr-defined]
                )
        except Exception:
            pass
