"""Memory backend abstract base class and provider-neutral DTOs.

This module defines the contract every memory backend must satisfy.
Consumers depend on these types only — never on Zep / Graphiti / Neo4j
SDK objects directly.

Design notes
------------
* All DTOs are :func:`@dataclass` instances with explicit fields. They
  carry the union of fields that any consumer in the codebase reads,
  so backends can populate them without forcing callers to do
  provider-specific attribute lookups.
* The :class:`MemoryBackend` ABC exposes only the operations MiroFish
  actually uses (Interface Segregation Principle). New operations are
  added here only when a real consumer requires them.
* All methods are synchronous from the caller's perspective. Backends
  that wrap an async client are responsible for hiding that fact (for
  example by running async calls in a per-call event loop).
* Bitemporal fields (``valid_at`` / ``invalid_at`` / ``expired_at``)
  are present on :class:`Edge` because some consumers display them in
  the report UI. Backends that lack temporal validity may set them to
  ``None``.
"""

from __future__ import annotations

import abc
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Optional

EpisodeType = Literal["text", "message", "json"]


@dataclass(frozen=True)
class EpisodeInput:
    """A single episode (raw text or message) to be ingested.

    ``content`` is the body to extract entities from. ``source_description``
    is shown in the UI and used by some retrieval paths to disambiguate
    where a fact came from. ``reference_time`` is optional; if absent
    the backend uses ingest time.
    """

    content: str
    episode_type: EpisodeType = "text"
    source_description: str = ""
    reference_time: Optional[datetime] = None


@dataclass
class EpisodeRef:
    """Lightweight handle to an ingested episode.

    Consumers poll ``processed`` to know when downstream entity / edge
    extraction has finished. Backends that ingest synchronously set
    ``processed=True`` on first return.
    """

    uuid: str
    processed: bool = True
    content: Optional[str] = None
    source_description: Optional[str] = None
    created_at: Optional[str] = None


@dataclass
class Node:
    """An entity node in the memory graph.

    ``labels`` is the list of entity types attached to the node.
    Provider conventions vary (Zep adds ``"Entity"``, ``"Node"``;
    Graphiti adds ``"Entity"``); call :meth:`custom_labels` to get
    only the user-defined types.
    """

    uuid: str
    name: str
    labels: list[str] = field(default_factory=list)
    summary: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)
    created_at: Optional[str] = None

    _GENERIC_LABELS = frozenset({"Entity", "Node"})

    def custom_labels(self) -> list[str]:
        """Return labels excluding the generic ``Entity`` / ``Node`` markers."""
        return [label for label in self.labels if label not in self._GENERIC_LABELS]

    def primary_type(self) -> Optional[str]:
        """Return the first user-defined entity type, or ``None``."""
        custom = self.custom_labels()
        return custom[0] if custom else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "uuid": self.uuid,
            "name": self.name,
            "labels": list(self.labels),
            "summary": self.summary,
            "attributes": dict(self.attributes),
            "created_at": self.created_at,
        }


@dataclass
class Edge:
    """A fact / relationship edge in the memory graph.

    ``name`` is the relation type (e.g. ``COMPETES_WITH``).
    ``fact`` is the natural-language statement extracted from text
    (e.g. ``"Chordinia competes with Chordify"``).

    Bitemporal fields (``valid_at`` / ``invalid_at`` / ``expired_at``)
    track when the fact became true and when it stopped being true.
    They may be ``None`` when the backend does not track validity.
    """

    uuid: str
    name: str
    fact: str
    source_node_uuid: str
    target_node_uuid: str
    attributes: dict[str, Any] = field(default_factory=dict)
    fact_type: Optional[str] = None
    created_at: Optional[str] = None
    valid_at: Optional[str] = None
    invalid_at: Optional[str] = None
    expired_at: Optional[str] = None
    episodes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "uuid": self.uuid,
            "name": self.name,
            "fact": self.fact,
            "fact_type": self.fact_type or self.name,
            "source_node_uuid": self.source_node_uuid,
            "target_node_uuid": self.target_node_uuid,
            "attributes": dict(self.attributes),
            "created_at": self.created_at,
            "valid_at": self.valid_at,
            "invalid_at": self.invalid_at,
            "expired_at": self.expired_at,
            "episodes": list(self.episodes),
        }


@dataclass
class SearchResult:
    """Result of a graph search query."""

    edges: list[Edge] = field(default_factory=list)
    nodes: list[Node] = field(default_factory=list)


@dataclass(frozen=True)
class _AttributeSpec:
    name: str
    description: str = ""


@dataclass(frozen=True)
class _EntityTypeSpec:
    name: str
    description: str = ""
    attributes: tuple[_AttributeSpec, ...] = ()


@dataclass(frozen=True)
class _SourceTargetSpec:
    source: str = "Entity"
    target: str = "Entity"


@dataclass(frozen=True)
class _EdgeTypeSpec:
    name: str
    description: str = ""
    attributes: tuple[_AttributeSpec, ...] = ()
    source_targets: tuple[_SourceTargetSpec, ...] = ()


@dataclass(frozen=True)
class OntologySpec:
    """Provider-neutral description of the entity / edge type schema.

    Built from the dict shape MiroFish already uses:

    .. code-block:: python

        {
            "entity_types": [
                {"name": "Person", "description": "...",
                 "attributes": [{"name": "occupation", "description": "..."}]},
            ],
            "edge_types": [
                {"name": "COMPETES_WITH", "description": "...",
                 "attributes": [...],
                 "source_targets": [{"source": "App", "target": "App"}]},
            ],
        }
    """

    entity_types: tuple[_EntityTypeSpec, ...] = ()
    edge_types: tuple[_EdgeTypeSpec, ...] = ()

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> OntologySpec:
        """Build an :class:`OntologySpec` from the dict format used in callers."""

        def _attrs(items: list[dict[str, Any]] | None) -> tuple[_AttributeSpec, ...]:
            if not items:
                return ()
            return tuple(
                _AttributeSpec(name=a["name"], description=a.get("description", ""))
                for a in items
            )

        entity_types = tuple(
            _EntityTypeSpec(
                name=e["name"],
                description=e.get("description", ""),
                attributes=_attrs(e.get("attributes")),
            )
            for e in raw.get("entity_types", [])
        )
        edge_types = tuple(
            _EdgeTypeSpec(
                name=e["name"],
                description=e.get("description", ""),
                attributes=_attrs(e.get("attributes")),
                source_targets=tuple(
                    _SourceTargetSpec(
                        source=st.get("source", "Entity"),
                        target=st.get("target", "Entity"),
                    )
                    for st in e.get("source_targets", [])
                ),
            )
            for e in raw.get("edge_types", [])
        )
        return cls(entity_types=entity_types, edge_types=edge_types)


class MemoryBackend(abc.ABC):
    """Abstract base class every memory backend must implement.

    Implementations MUST:

    * Translate provider-specific exceptions into the typed errors in
      :mod:`app.services.memory.exceptions`.
    * Return :class:`Node`, :class:`Edge`, :class:`EpisodeRef` and
      :class:`SearchResult` instances — never raw SDK objects.
    * Be safe to construct lazily (defer connection until first use
      where possible) so import-time failure is avoided.
    """

    # ---- Lifecycle ------------------------------------------------------

    @abc.abstractmethod
    def name(self) -> str:
        """Return the backend identifier (``"zep"`` / ``"graphiti"``)."""

    @abc.abstractmethod
    def create_graph(
        self,
        graph_id: str,
        *,
        display_name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> None:
        """Create a new graph / namespace.

        Backends that do not have an explicit graph creation step (e.g.
        Graphiti, where ``group_id`` is just a tag attached at write
        time) MAY make this a no-op.
        """

    @abc.abstractmethod
    def delete_graph(self, graph_id: str) -> None:
        """Delete the graph and every node / edge / episode under it."""

    @abc.abstractmethod
    def set_ontology(self, graph_id: str, ontology: OntologySpec) -> None:
        """Set the entity / edge type schema for ``graph_id``.

        Backends that pass ontology per-call (Graphiti) MUST store the
        spec internally and apply it on every subsequent write.
        """

    # ---- Episode ingest -------------------------------------------------

    @abc.abstractmethod
    def add_episode(self, graph_id: str, episode: EpisodeInput) -> EpisodeRef:
        """Ingest a single episode."""

    @abc.abstractmethod
    def add_episodes_bulk(
        self, graph_id: str, episodes: list[EpisodeInput]
    ) -> list[EpisodeRef]:
        """Ingest a batch of episodes. Order of return matches input."""

    @abc.abstractmethod
    def get_episode(self, episode_uuid: str) -> Optional[EpisodeRef]:
        """Fetch a single episode by uuid, or return ``None`` if absent."""

    # ---- Graph reads ----------------------------------------------------

    @abc.abstractmethod
    def search(
        self,
        graph_id: str,
        query: str,
        *,
        limit: int = 10,
        scope: Literal["edges", "nodes"] = "edges",
    ) -> SearchResult:
        """Search the graph by natural-language query.

        ``scope`` selects whether to return matching edges (facts) or
        matching nodes (entities). Some backends may populate both
        regardless of the value; consumers should check the field
        relevant to them.
        """

    @abc.abstractmethod
    def get_node(self, node_uuid: str) -> Optional[Node]:
        """Fetch a single node by uuid, or return ``None`` if absent."""

    @abc.abstractmethod
    def get_nodes_by_graph(
        self, graph_id: str, *, page_size: int = 100, max_items: int = 2000
    ) -> Iterator[Node]:
        """Yield every node in ``graph_id`` (paged)."""

    @abc.abstractmethod
    def get_edges_by_graph(
        self, graph_id: str, *, page_size: int = 100
    ) -> Iterator[Edge]:
        """Yield every edge in ``graph_id`` (paged)."""

    @abc.abstractmethod
    def get_node_edges(self, node_uuid: str) -> list[Edge]:
        """Return every edge incident to the node with ``node_uuid``."""

    # ---- Convenience ----------------------------------------------------

    def get_all_nodes(self, graph_id: str) -> list[Node]:
        """Materialise :meth:`get_nodes_by_graph` into a list."""
        return list(self.get_nodes_by_graph(graph_id))

    def get_all_edges(self, graph_id: str) -> list[Edge]:
        """Materialise :meth:`get_edges_by_graph` into a list."""
        return list(self.get_edges_by_graph(graph_id))
