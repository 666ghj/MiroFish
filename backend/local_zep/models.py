from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class InternalServerError(RuntimeError):
    """Compatibility error used by paging helpers."""


@dataclass
class EpisodeData:
    data: str
    type: str = "text"
    created_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    source_description: str | None = None


@dataclass
class EntityEdgeSourceTarget:
    source: str = "Entity"
    target: str = "Entity"


@dataclass
class GraphRecord:
    graph_id: str
    name: str
    description: str = ""
    created_at: str | None = None


@dataclass
class GraphNode:
    uuid_: str
    graph_id: str
    name: str
    labels: list[str] = field(default_factory=list)
    summary: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None
    score: float | None = None
    relevance: float | None = None

    @property
    def uuid(self) -> str:
        return self.uuid_


@dataclass
class GraphEdge:
    uuid_: str
    graph_id: str
    name: str
    fact: str
    source_node_uuid: str
    target_node_uuid: str
    attributes: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None
    valid_at: str | None = None
    invalid_at: str | None = None
    expired_at: str | None = None
    episodes: list[str] = field(default_factory=list)
    score: float | None = None
    relevance: float | None = None

    @property
    def uuid(self) -> str:
        return self.uuid_

    @property
    def episode_ids(self) -> list[str]:
        return self.episodes


@dataclass
class GraphEpisode:
    uuid_: str
    graph_id: str
    data: str
    type: str = "text"
    processed: bool = False
    created_at: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    source_description: str | None = None
    role: str | None = None
    role_type: str | None = None
    thread_id: str | None = None
    task_id: str | None = None
    score: float | None = None
    relevance: float | None = None

    @property
    def uuid(self) -> str:
        return self.uuid_

    @property
    def content(self) -> str:
        return self.data

    @property
    def source(self) -> str:
        return self.type


@dataclass
class GraphSearchResults:
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    episodes: list[GraphEpisode] = field(default_factory=list)
