"""Zep Cloud graph memory adapter."""

from __future__ import annotations

import warnings
from typing import Any, Optional

from pydantic import Field
from zep_cloud import EpisodeData, EntityEdgeSourceTarget
from zep_cloud.client import Zep
from zep_cloud.external_clients.ontology import EntityModel, EntityText, EdgeModel

from .base import GraphMemoryAdapter
from ..utils.zep_paging import fetch_all_edges, fetch_all_nodes


class ZepCloudGraphMemoryAdapter(GraphMemoryAdapter):
    """Adapter preserving the existing Zep Cloud behavior."""

    RESERVED_NAMES = {"uuid", "name", "group_id", "name_embedding", "summary", "created_at"}

    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("ZEP_API_KEY 未配置")
        self._client = Zep(api_key=api_key)

    @property
    def raw_client(self) -> Zep:
        return self._client

    def create_graph(self, graph_id: str, name: str, description: str) -> Any:
        return self._client.graph.create(graph_id=graph_id, name=name, description=description)

    def set_ontology(self, graph_id: str, ontology: dict[str, Any]) -> Any:
        warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")

        entity_types: dict[str, type[EntityModel]] = {}
        for entity_def in ontology.get("entity_types", []):
            name = entity_def["name"]
            description = entity_def.get("description", f"A {name} entity.")
            attrs: dict[str, Any] = {"__doc__": description}
            annotations: dict[str, Any] = {}

            for attr_def in entity_def.get("attributes", []):
                attr_name = self._safe_attr_name(attr_def["name"])
                attr_desc = attr_def.get("description", attr_name)
                attrs[attr_name] = Field(description=attr_desc, default=None)
                annotations[attr_name] = Optional[EntityText]

            attrs["__annotations__"] = annotations
            entity_class = type(name, (EntityModel,), attrs)
            entity_class.__doc__ = description
            entity_types[name] = entity_class

        edge_definitions: dict[str, tuple[type[EdgeModel], list[EntityEdgeSourceTarget]]] = {}
        for edge_def in ontology.get("edge_types", []):
            name = edge_def["name"]
            description = edge_def.get("description", f"A {name} relationship.")
            attrs = {"__doc__": description}
            annotations = {}

            for attr_def in edge_def.get("attributes", []):
                attr_name = self._safe_attr_name(attr_def["name"])
                attr_desc = attr_def.get("description", attr_name)
                attrs[attr_name] = Field(description=attr_desc, default=None)
                annotations[attr_name] = Optional[str]

            attrs["__annotations__"] = annotations
            class_name = "".join(word.capitalize() for word in name.split("_"))
            edge_class = type(class_name, (EdgeModel,), attrs)
            edge_class.__doc__ = description

            source_targets = [
                EntityEdgeSourceTarget(source=st.get("source", "Entity"), target=st.get("target", "Entity"))
                for st in edge_def.get("source_targets", [])
            ]
            if source_targets:
                edge_definitions[name] = (edge_class, source_targets)

        if not entity_types and not edge_definitions:
            return None

        return self._client.graph.set_ontology(
            graph_ids=[graph_id],
            entities=entity_types if entity_types else None,
            edges=edge_definitions if edge_definitions else None,
        )

    def add_text_batch(self, graph_id: str, chunks: list[str]) -> Any:
        episodes = [EpisodeData(data=chunk, type="text") for chunk in chunks]
        return self._client.graph.add_batch(graph_id=graph_id, episodes=episodes)

    def add_text(self, graph_id: str, text: str) -> Any:
        return self._client.graph.add(graph_id=graph_id, type="text", data=text)

    def get_episode(self, episode_uuid: str) -> Any:
        return self._client.graph.episode.get(uuid_=episode_uuid)

    def get_all_nodes(self, graph_id: str) -> list[Any]:
        return fetch_all_nodes(self._client, graph_id)

    def get_all_edges(self, graph_id: str) -> list[Any]:
        return fetch_all_edges(self._client, graph_id)

    def search(self, graph_id: str, query: str, limit: int = 10, scope: str = "edges", **kwargs: Any) -> Any:
        return self._client.graph.search(graph_id=graph_id, query=query, limit=limit, scope=scope, **kwargs)

    def get_node(self, node_uuid: str) -> Any:
        return self._client.graph.node.get(uuid_=node_uuid)

    def get_node_edges(self, node_uuid: str) -> list[Any]:
        return self._client.graph.node.get_entity_edges(node_uuid=node_uuid)

    def delete_graph(self, graph_id: str) -> Any:
        return self._client.graph.delete(graph_id=graph_id)

    @classmethod
    def _safe_attr_name(cls, attr_name: str) -> str:
        if attr_name.lower() in cls.RESERVED_NAMES:
            return f"entity_{attr_name}"
        return attr_name
