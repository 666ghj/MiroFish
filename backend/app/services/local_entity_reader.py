"""
Local entity reader for Neo4j graph backend.

Implements the same high-level API as ZepEntityReader so the rest of the codebase
can keep using FilteredEntities/EntityNode data structures.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from ..utils.logger import get_logger
from .local_graph_store import LocalNeo4jGraphStore
from .entity_type_normalizer import canonicalize_entity_type
from .zep_entity_reader import EntityNode, FilteredEntities

logger = get_logger("mirofish.local_entity_reader")


class LocalEntityReader:
    def __init__(self):
        self.store = LocalNeo4jGraphStore()

    def filter_defined_entities(
        self,
        graph_id: str,
        defined_entity_types: Optional[List[str]] = None,
        enrich_with_edges: bool = True,
    ) -> FilteredEntities:
        graph_data = self.store.get_graph_data(graph_id)
        nodes = graph_data.get("nodes") or []
        edges = graph_data.get("edges") or []

        total_count = len(nodes)

        # Filter by entity type (label after "Entity")
        def _entity_type(node: Dict[str, Any]) -> Optional[str]:
            labels = node.get("labels") or []
            for label in labels:
                if label not in ["Entity", "Node"]:
                    return label
            return None

        filtered_nodes = []
        entity_types: Set[str] = set()
        defined_set = set(defined_entity_types or [])
        canonical_defined_set = {canonicalize_entity_type(t) for t in defined_set} if defined_set else set()
        for n in nodes:
            et = _entity_type(n)
            if et:
                entity_types.add(et)
            if defined_set:
                # Accept if canonical label matches canonicalized defined types,
                # OR if the node records any original extracted types matching the requested list.
                if et not in canonical_defined_set:
                    src_types = (n.get("attributes") or {}).get("source_entity_types") or []
                    if not (set(src_types) & defined_set):
                        continue
            filtered_nodes.append(n)

        filtered_uuids = {n.get("uuid") for n in filtered_nodes if n.get("uuid")}

        related_edges_by_uuid: Dict[str, List[Dict[str, Any]]] = {u: [] for u in filtered_uuids}
        related_nodes_by_uuid: Dict[str, List[Dict[str, Any]]] = {u: [] for u in filtered_uuids}

        if enrich_with_edges:
            for e in edges:
                su = e.get("source_node_uuid")
                tu = e.get("target_node_uuid")
                if su in filtered_uuids:
                    related_edges_by_uuid[su].append(e)
                if tu in filtered_uuids and tu != su:
                    related_edges_by_uuid[tu].append(e)

            # Build node lookup
            node_lookup = {n.get("uuid"): n for n in nodes if n.get("uuid")}
            for u in filtered_uuids:
                rel_nodes = set()
                for e in related_edges_by_uuid.get(u, []):
                    su = e.get("source_node_uuid")
                    tu = e.get("target_node_uuid")
                    other = tu if su == u else su
                    if other and other in node_lookup:
                        rel_nodes.add(other)
                related_nodes_by_uuid[u] = [node_lookup[oid] for oid in rel_nodes]

        entities: List[EntityNode] = []
        for n in filtered_nodes:
            uuid_ = n.get("uuid") or ""
            entities.append(
                EntityNode(
                    uuid=uuid_,
                    name=n.get("name") or "",
                    labels=n.get("labels") or ["Entity"],
                    summary=n.get("summary") or "",
                    attributes=n.get("attributes") or {},
                    related_edges=related_edges_by_uuid.get(uuid_, []),
                    related_nodes=related_nodes_by_uuid.get(uuid_, []),
                )
            )

        return FilteredEntities(
            entities=entities,
            entity_types=entity_types,
            total_count=total_count,
            filtered_count=len(entities),
        )

    def get_entity_with_context(self, graph_id: str, entity_uuid: str) -> Optional[EntityNode]:
        filtered = self.filter_defined_entities(
            graph_id=graph_id,
            defined_entity_types=None,
            enrich_with_edges=True,
        )
        for e in filtered.entities:
            if e.uuid == entity_uuid:
                return e
        return None

    def get_entities_by_type(
        self,
        graph_id: str,
        entity_type: str,
        enrich_with_edges: bool = True,
    ) -> List[EntityNode]:
        filtered = self.filter_defined_entities(
            graph_id=graph_id,
            defined_entity_types=[entity_type],
            enrich_with_edges=enrich_with_edges,
        )
        return filtered.entities
