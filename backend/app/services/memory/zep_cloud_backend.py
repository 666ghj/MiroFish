"""Zep Cloud implementation of :class:`MemoryBackend`.

Wraps the ``zep_cloud`` Python SDK so callers depend only on the
abstract interface in :mod:`app.services.memory.base`. Behavior is
preserved bit-for-bit from the previous direct-Zep code paths:
pagination via uuid cursor, dynamic Pydantic ontology classes built
from a dict spec, and exponential-backoff retries on transient
errors.

Configuration: requires ``ZEP_API_KEY`` to be set in the environment
(or in :class:`app.config.Config`).
"""

from __future__ import annotations

import time
import warnings
from collections.abc import Callable, Iterator
from typing import Any, Literal, Optional, TypeVar

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
    MemoryBackendQuotaExceeded,
    MemoryBackendRateLimited,
    MemoryBackendUnavailable,
)

logger = get_logger("mirofish.memory.zep_cloud")

_DEFAULT_PAGE_SIZE = 100
_DEFAULT_MAX_NODES = 2000
_DEFAULT_MAX_RETRIES = 3
_DEFAULT_RETRY_DELAY = 2.0

T = TypeVar("T")


def _get_uuid(obj: Any) -> str:
    """Zep returns ``uuid_`` on most objects but occasionally ``uuid``."""
    return getattr(obj, "uuid_", None) or getattr(obj, "uuid", "") or ""


def _stringify(value: Any) -> Optional[str]:
    return str(value) if value is not None else None


def _classify_zep_error(exc: BaseException) -> MemoryBackendError:
    """Translate a ``zep_cloud`` exception into a typed memory error.

    The cloud SDK raises HTTP-flavoured exceptions whose text contains
    ``"rate limit"`` for 429s and ``"episode usage limit"`` for the
    free-tier quota cap. Anything else maps to the generic unavailable
    error so callers can handle transient failure uniformly.
    """
    text = str(exc).lower()
    if "rate limit" in text or "429" in text:
        return MemoryBackendRateLimited(str(exc))
    if "episode usage limit" in text or "quota" in text:
        return MemoryBackendQuotaExceeded(str(exc))
    return MemoryBackendUnavailable(str(exc))


class ZepCloudBackend(MemoryBackend):
    """Zep Cloud-backed implementation of :class:`MemoryBackend`."""

    def __init__(self, api_key: Optional[str] = None) -> None:
        self._api_key = api_key or Config.ZEP_API_KEY
        if not self._api_key:
            raise MemoryBackendNotConfigured(
                "ZEP_API_KEY is not set; cannot initialise ZepCloudBackend"
            )
        # Defer the import so installations that switch to graphiti
        # are not forced to keep zep_cloud installed.
        from zep_cloud.client import Zep

        self._client = Zep(api_key=self._api_key)
        # Dependent helpers (zep_paging) still expect the raw SDK
        # client; expose it under a clearly underscored name so the
        # leak is obvious if anyone reaches for it from new code.
        self._raw_client = self._client

    # ------------------------------------------------------------------
    # Identification
    # ------------------------------------------------------------------

    def name(self) -> str:
        return "zep"

    @property
    def raw_client(self) -> Any:
        """Expose the underlying ``zep_cloud`` client.

        Provided as a transitional escape hatch for code paths that
        have not yet been ported to the abstract interface. New code
        MUST NOT use this.
        """
        return self._raw_client

    # ------------------------------------------------------------------
    # Internal retry helper (mirrors the pattern previously inlined in
    # ZepEntityReader and ZepGraphMemoryUpdater)
    # ------------------------------------------------------------------

    def _call_with_retry(
        self,
        func: Callable[[], T],
        *,
        operation: str,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        initial_delay: float = _DEFAULT_RETRY_DELAY,
    ) -> T:
        last_exc: Optional[BaseException] = None
        delay = initial_delay
        for attempt in range(max_retries):
            try:
                return func()
            except Exception as e:  # noqa: BLE001 — Zep SDK uses bare Exception
                last_exc = e
                if attempt < max_retries - 1:
                    logger.warning(
                        "Zep %s attempt %d failed: %s; retrying in %.1fs",
                        operation,
                        attempt + 1,
                        str(e)[:120],
                        delay,
                    )
                    time.sleep(delay)
                    delay *= 2
                else:
                    logger.error(
                        "Zep %s failed after %d attempts: %s",
                        operation,
                        max_retries,
                        str(e),
                    )
        assert last_exc is not None
        raise _classify_zep_error(last_exc) from last_exc

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
        try:
            self._client.graph.create(
                graph_id=graph_id,
                name=display_name or graph_id,
                description=description or "MiroFish Social Simulation Graph",
            )
        except Exception as e:  # noqa: BLE001
            raise _classify_zep_error(e) from e

    def delete_graph(self, graph_id: str) -> None:
        try:
            self._client.graph.delete(graph_id=graph_id)
        except Exception as e:  # noqa: BLE001
            raise _classify_zep_error(e) from e

    def set_ontology(self, graph_id: str, ontology: OntologySpec) -> None:
        from typing import Optional as _Optional

        from pydantic import Field
        from zep_cloud import EntityEdgeSourceTarget
        from zep_cloud.external_clients.ontology import (
            EdgeModel,
            EntityModel,
            EntityText,
        )

        # Pydantic v2 emits a noisy UserWarning when Field(default=None)
        # is used dynamically; the Zep SDK requires it. Suppress.
        warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")

        reserved = {
            "uuid",
            "name",
            "group_id",
            "name_embedding",
            "summary",
            "created_at",
        }

        def safe_attr_name(attr: str) -> str:
            return f"entity_{attr}" if attr.lower() in reserved else attr

        entity_classes: dict[str, Any] = {}
        for ent in ontology.entity_types:
            attrs: dict[str, Any] = {"__doc__": ent.description or f"A {ent.name} entity."}
            annotations: dict[str, Any] = {}
            for a in ent.attributes:
                key = safe_attr_name(a.name)
                attrs[key] = Field(description=a.description or key, default=None)
                annotations[key] = _Optional[EntityText]
            attrs["__annotations__"] = annotations
            cls = type(ent.name, (EntityModel,), attrs)
            cls.__doc__ = ent.description
            entity_classes[ent.name] = cls

        edge_definitions: dict[str, Any] = {}
        for edge in ontology.edge_types:
            attrs = {"__doc__": edge.description or f"A {edge.name} relationship."}
            annotations = {}
            for a in edge.attributes:
                key = safe_attr_name(a.name)
                attrs[key] = Field(description=a.description or key, default=None)
                annotations[key] = _Optional[str]
            attrs["__annotations__"] = annotations
            cls_name = "".join(w.capitalize() for w in edge.name.split("_"))
            edge_cls = type(cls_name, (EdgeModel,), attrs)
            edge_cls.__doc__ = edge.description

            source_targets = [
                EntityEdgeSourceTarget(source=st.source, target=st.target)
                for st in edge.source_targets
            ]
            if source_targets:
                edge_definitions[edge.name] = (edge_cls, source_targets)

        if not entity_classes and not edge_definitions:
            return

        try:
            self._client.graph.set_ontology(
                graph_ids=[graph_id],
                entities=entity_classes or None,
                edges=edge_definitions or None,
            )
        except Exception as e:  # noqa: BLE001
            raise _classify_zep_error(e) from e

    # ------------------------------------------------------------------
    # Episode ingest
    # ------------------------------------------------------------------

    def add_episode(self, graph_id: str, episode: EpisodeInput) -> EpisodeRef:
        from zep_cloud import EpisodeData

        try:
            result = self._client.graph.add(
                graph_id=graph_id,
                data=episode.content,
                type=episode.episode_type,
                source_description=episode.source_description or None,
            )
        except Exception as e:  # noqa: BLE001
            raise _classify_zep_error(e) from e

        return EpisodeRef(
            uuid=_get_uuid(result),
            processed=bool(getattr(result, "processed", False)),
            content=episode.content,
            source_description=episode.source_description,
        )

    def add_episodes_bulk(
        self, graph_id: str, episodes: list[EpisodeInput]
    ) -> list[EpisodeRef]:
        from zep_cloud import EpisodeData

        if not episodes:
            return []

        payload = [
            EpisodeData(
                data=ep.content,
                type=ep.episode_type,
                source_description=ep.source_description or None,
            )
            for ep in episodes
        ]

        try:
            batch = self._client.graph.add_batch(graph_id=graph_id, episodes=payload)
        except Exception as e:  # noqa: BLE001
            raise _classify_zep_error(e) from e

        if not batch:
            return []

        refs: list[EpisodeRef] = []
        for ep_obj, source in zip(batch, episodes):
            refs.append(
                EpisodeRef(
                    uuid=_get_uuid(ep_obj),
                    processed=bool(getattr(ep_obj, "processed", False)),
                    content=source.content,
                    source_description=source.source_description,
                )
            )
        return refs

    def get_episode(self, episode_uuid: str) -> Optional[EpisodeRef]:
        try:
            ep = self._client.graph.episode.get(uuid_=episode_uuid)
        except Exception as e:  # noqa: BLE001
            logger.debug("Zep get_episode(%s) failed: %s", episode_uuid, e)
            return None
        if not ep:
            return None
        return EpisodeRef(
            uuid=_get_uuid(ep),
            processed=bool(getattr(ep, "processed", False)),
            content=getattr(ep, "data", None) or getattr(ep, "content", None),
            source_description=getattr(ep, "source_description", None),
            created_at=_stringify(getattr(ep, "created_at", None)),
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
        try:
            raw = self._call_with_retry(
                lambda: self._client.graph.search(
                    graph_id=graph_id,
                    query=query,
                    limit=limit,
                    scope=scope,
                ),
                operation=f"search(graph={graph_id}, scope={scope})",
            )
        except MemoryBackendError:
            raise

        edges = [self._edge_from_sdk(e) for e in (getattr(raw, "edges", None) or [])]
        nodes = [self._node_from_sdk(n) for n in (getattr(raw, "nodes", None) or [])]
        return SearchResult(edges=edges, nodes=nodes)

    def get_node(self, node_uuid: str) -> Optional[Node]:
        try:
            raw = self._call_with_retry(
                lambda: self._client.graph.node.get(uuid_=node_uuid),
                operation=f"get_node({node_uuid[:8]}…)",
            )
        except MemoryBackendError:
            return None
        if raw is None:
            return None
        return self._node_from_sdk(raw)

    def get_nodes_by_graph(
        self, graph_id: str, *, page_size: int = _DEFAULT_PAGE_SIZE, max_items: int = _DEFAULT_MAX_NODES
    ) -> Iterator[Node]:
        # Re-use the existing battle-tested pager so behavior is
        # identical to the legacy code path.
        from ...utils.zep_paging import fetch_all_nodes

        nodes = fetch_all_nodes(
            self._client,
            graph_id,
            page_size=page_size,
            max_items=max_items,
        )
        for n in nodes:
            yield self._node_from_sdk(n)

    def get_edges_by_graph(
        self, graph_id: str, *, page_size: int = _DEFAULT_PAGE_SIZE
    ) -> Iterator[Edge]:
        from ...utils.zep_paging import fetch_all_edges

        edges = fetch_all_edges(self._client, graph_id, page_size=page_size)
        for e in edges:
            yield self._edge_from_sdk(e)

    def get_node_edges(self, node_uuid: str) -> list[Edge]:
        try:
            raw = self._call_with_retry(
                lambda: self._client.graph.node.get_entity_edges(node_uuid=node_uuid),
                operation=f"get_node_edges({node_uuid[:8]}…)",
            )
        except MemoryBackendError:
            return []
        return [self._edge_from_sdk(e) for e in (raw or [])]

    # ------------------------------------------------------------------
    # SDK → DTO mappers
    # ------------------------------------------------------------------

    @staticmethod
    def _node_from_sdk(raw: Any) -> Node:
        return Node(
            uuid=_get_uuid(raw),
            name=getattr(raw, "name", "") or "",
            labels=list(getattr(raw, "labels", None) or []),
            summary=getattr(raw, "summary", "") or "",
            attributes=dict(getattr(raw, "attributes", None) or {}),
            created_at=_stringify(getattr(raw, "created_at", None)),
        )

    @staticmethod
    def _edge_from_sdk(raw: Any) -> Edge:
        episodes = getattr(raw, "episodes", None) or getattr(raw, "episode_ids", None)
        if episodes is None:
            episode_list: list[str] = []
        elif isinstance(episodes, list):
            episode_list = [str(e) for e in episodes]
        else:
            episode_list = [str(episodes)]

        return Edge(
            uuid=_get_uuid(raw),
            name=getattr(raw, "name", "") or "",
            fact=getattr(raw, "fact", "") or "",
            fact_type=getattr(raw, "fact_type", None) or getattr(raw, "name", None) or "",
            source_node_uuid=getattr(raw, "source_node_uuid", "") or "",
            target_node_uuid=getattr(raw, "target_node_uuid", "") or "",
            attributes=dict(getattr(raw, "attributes", None) or {}),
            created_at=_stringify(getattr(raw, "created_at", None)),
            valid_at=_stringify(getattr(raw, "valid_at", None)),
            invalid_at=_stringify(getattr(raw, "invalid_at", None)),
            expired_at=_stringify(getattr(raw, "expired_at", None)),
            episodes=episode_list,
        )
