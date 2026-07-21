from __future__ import annotations

from typing import Any

from .models import EntityEdgeSourceTarget, EpisodeData, GraphSearchResults
from .store import LocalZepStore


_DEFAULT_STORE: LocalZepStore | None = None


def get_default_store() -> LocalZepStore:
    global _DEFAULT_STORE
    if _DEFAULT_STORE is None:
        _DEFAULT_STORE = LocalZepStore()
    return _DEFAULT_STORE


def _model_fields_to_attributes(model_cls: Any) -> list[dict[str, str]]:
    fields = getattr(model_cls, "model_fields", {}) or {}
    result = []
    for field_name, field_info in fields.items():
        result.append(
            {
                "name": field_name,
                "description": getattr(field_info, "description", None) or field_name,
            }
        )
    return result


def _compat_ontology_from_models(
    entities: dict[str, Any] | None,
    edges: dict[str, Any] | None,
) -> dict[str, Any]:
    ontology = {"entity_types": [], "edge_types": []}

    for entity_name, entity_cls in (entities or {}).items():
        ontology["entity_types"].append(
            {
                "name": entity_name,
                "description": getattr(entity_cls, "__doc__", "") or f"A {entity_name} entity.",
                "attributes": _model_fields_to_attributes(entity_cls),
            }
        )

    for edge_name, edge_value in (edges or {}).items():
        edge_cls, source_targets = edge_value
        formatted_targets = []
        for pair in source_targets or []:
            if isinstance(pair, EntityEdgeSourceTarget):
                formatted_targets.append({"source": pair.source, "target": pair.target})
            else:
                formatted_targets.append(
                    {
                        "source": getattr(pair, "source", "Entity"),
                        "target": getattr(pair, "target", "Entity"),
                    }
                )
        ontology["edge_types"].append(
            {
                "name": edge_name,
                "description": getattr(edge_cls, "__doc__", "") or f"A {edge_name} relationship.",
                "attributes": _model_fields_to_attributes(edge_cls),
                "source_targets": formatted_targets,
            }
        )

    return ontology


class EpisodeManager:
    def __init__(self, store: LocalZepStore) -> None:
        self.store = store

    def get(self, uuid_: str):
        return self.store.get_episode(uuid_)

    def get_by_graph_id(self, graph_id: str, lastn: int | None = None):
        return self.store.get_episodes_by_graph_id(graph_id=graph_id, lastn=lastn)


class NodeManager:
    def __init__(self, store: LocalZepStore) -> None:
        self.store = store

    def get_by_graph_id(self, graph_id: str, limit: int = 100, uuid_cursor: str | None = None):
        return self.store.get_nodes_page(graph_id=graph_id, limit=limit, uuid_cursor=uuid_cursor)

    def get_by_user_id(self, user_id: str, limit: int = 100, uuid_cursor: str | None = None):
        return self.get_by_graph_id(graph_id=user_id, limit=limit, uuid_cursor=uuid_cursor)

    def get(self, uuid_: str):
        return self.store.get_node(uuid_)

    def get_entity_edges(self, node_uuid: str):
        return self.store.get_entity_edges(node_uuid)

    def get_edges(self, node_uuid: str):
        return self.get_entity_edges(node_uuid)


class EdgeManager:
    def __init__(self, store: LocalZepStore) -> None:
        self.store = store

    def get_by_graph_id(self, graph_id: str, limit: int = 100, uuid_cursor: str | None = None):
        return self.store.get_edges_page(graph_id=graph_id, limit=limit, uuid_cursor=uuid_cursor)

    def get_by_user_id(self, user_id: str, limit: int = 100, uuid_cursor: str | None = None):
        return self.get_by_graph_id(graph_id=user_id, limit=limit, uuid_cursor=uuid_cursor)

    def get(self, uuid_: str):
        return self.store.get_edge(uuid_)


class GraphManager:
    def __init__(self, store: LocalZepStore) -> None:
        self.store = store
        self.node = NodeManager(store)
        self.edge = EdgeManager(store)
        self.episode = EpisodeManager(store)

    def create(self, graph_id: str, name: str = "", description: str = ""):
        return self.store.create_graph(graph_id=graph_id, name=name, description=description)

    def get(self, graph_id: str):
        return self.store.get_graph(graph_id=graph_id)

    def delete(self, graph_id: str):
        self.store.delete_graph(graph_id=graph_id)

    def set_ontology(
        self,
        graph_ids: list[str] | None = None,
        user_ids: list[str] | None = None,
        entities: dict[str, Any] | None = None,
        edges: dict[str, Any] | None = None,
        ontology: dict[str, Any] | None = None,
        **_: Any,
    ):
        graph_ids = graph_ids or user_ids or []
        parsed = ontology or _compat_ontology_from_models(entities, edges)
        for graph_id in graph_ids:
            self.store.set_ontology(graph_id=graph_id, ontology=parsed)

    def add(
        self,
        graph_id: str | None = None,
        data: str = "",
        type: str = "text",
        user_id: str | None = None,
        created_at: str | None = None,
        metadata: dict[str, Any] | None = None,
        source_description: str | None = None,
        **extra: Any,
    ):
        graph_id = graph_id or user_id or extra.get("graphId") or extra.get("userId")
        if not graph_id:
            raise ValueError("graph_id or user_id is required")
        return self.store.add(
            graph_id=graph_id,
            data=data,
            type_=type,
            created_at=created_at or extra.get("createdAt"),
            metadata=metadata,
            source_description=source_description or extra.get("sourceDescription"),
        )

    def add_batch(self, graph_id: str | None = None, episodes: list[EpisodeData] | None = None, user_id: str | None = None, **extra: Any):
        graph_id = graph_id or user_id or extra.get("graphId") or extra.get("userId")
        if not graph_id:
            raise ValueError("graph_id or user_id is required")
        return self.store.add_batch(graph_id=graph_id, episodes=episodes or [])

    def search(
        self,
        graph_id: str | None = None,
        query: str = "",
        limit: int = 10,
        scope: str = "edges",
        user_id: str | None = None,
        reranker: str = "rrf",
        mmr_lambda: float | None = None,
        center_node_uuid: str | None = None,
        search_filters: Any = None,
        bfs_origin_node_uuids: list[str] | None = None,
        **extra: Any,
    ) -> GraphSearchResults:
        graph_id = graph_id or user_id or extra.get("graphId") or extra.get("userId")
        if not graph_id:
            return GraphSearchResults()
        if mmr_lambda is None:
            mmr_lambda = extra.get("mmrLambda")
        if center_node_uuid is None:
            center_node_uuid = extra.get("centerNodeUuid")
        if search_filters is None:
            search_filters = extra.get("searchFilters")
        if bfs_origin_node_uuids is None:
            bfs_origin_node_uuids = extra.get("bfsOriginNodeUuids")
        return self.store.search(
            graph_id=graph_id,
            query=query,
            limit=limit,
            scope=scope,
            reranker=reranker,
            mmr_lambda=mmr_lambda,
            center_node_uuid=center_node_uuid,
            search_filters=search_filters,
            bfs_origin_node_uuids=bfs_origin_node_uuids,
        )


class Zep:
    def __init__(self, api_key: str | None = None, **_: Any) -> None:
        del api_key
        self._store = get_default_store()
        self.graph = GraphManager(self._store)
