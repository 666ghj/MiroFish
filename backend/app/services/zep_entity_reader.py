"""
Zep Entity Reading and Filtering Service
Reads nodes from the Zep graph and filters those that match predefined entity types.
"""

from typing import Dict, Any, List, Optional, Set, Callable, TypeVar
from dataclasses import dataclass, field
from zep_cloud import NotFoundError

from ..config import Config
from ..utils.logger import get_logger
from ..utils.zep_paging import fetch_all_nodes, fetch_all_edges
from ..utils.zep import call_zep_read_with_retry, get_zep_client

logger = get_logger('mirofish.zep_entity_reader')

# For generic return types
T = TypeVar('T')


@dataclass
class EntityNode:
    """Entity node data structure"""
    uuid: str
    name: str
    labels: List[str]
    summary: str
    attributes: Dict[str, Any]
    # Related edge information
    related_edges: List[Dict[str, Any]] = field(default_factory=list)
    # Related node information
    related_nodes: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "uuid": self.uuid,
            "name": self.name,
            "labels": self.labels,
            "summary": self.summary,
            "attributes": self.attributes,
            "related_edges": self.related_edges,
            "related_nodes": self.related_nodes,
        }
    
    def get_entity_type(self) -> Optional[str]:
        """Get the entity type (excluding the default Entity label)"""
        for label in self.labels:
            if label not in ["Entity", "Node"]:
                return label
        return None


@dataclass
class FilteredEntities:
    """Filtered entity collection"""
    entities: List[EntityNode]
    entity_types: Set[str]
    total_count: int
    filtered_count: int
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "entities": [e.to_dict() for e in self.entities],
            "entity_types": list(self.entity_types),
            "total_count": self.total_count,
            "filtered_count": self.filtered_count,
        }


class ZepEntityReader:
    """
    Zep Entity Reading and Filtering Service

    Main features:
    1. Read all nodes from the Zep graph
    2. Filter nodes that match predefined entity types (nodes whose Labels are not just "Entity")
    3. Retrieve related edges and associated node information for each entity
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or Config.ZEP_API_KEY
        if not self.api_key:
            raise ValueError("ZEP_API_KEY is not configured")
        
        self.client = get_zep_client(self.api_key)
    
    def _call_with_retry(
        self,
        func: Callable[[], T],
        operation_name: str,
        max_retries: int = 3,
        initial_delay: float = 2.0
    ) -> T:
        """
        Zep API call with retry mechanism.

        Args:
            func: Function to execute (a no-argument lambda or callable)
            operation_name: Operation name for logging
            max_retries: Maximum number of retries (default 3, i.e. at most 3 attempts)
            initial_delay: Initial delay in seconds

        Returns:
            API call result
        """
        return call_zep_read_with_retry(
            func,
            operation_name=operation_name,
            max_attempts=max_retries,
            initial_delay=initial_delay,
        )
    
    def get_all_nodes(self, graph_id: str) -> List[Dict[str, Any]]:
        """
        Get all nodes in the graph (paginated).

        Args:
            graph_id: Graph ID

        Returns:
            List of nodes
        """
        logger.info(f"Fetching all nodes for graph {graph_id}...")

        nodes = fetch_all_nodes(self.client, graph_id)

        nodes_data = []
        for node in nodes:
            nodes_data.append({
                "uuid": getattr(node, 'uuid_', None) or getattr(node, 'uuid', ''),
                "name": node.name or "",
                "labels": node.labels or [],
                "summary": node.summary or "",
                "attributes": node.attributes or {},
            })

        logger.info(f"Fetched {len(nodes_data)} nodes in total")
        return nodes_data

    def get_all_edges(self, graph_id: str) -> List[Dict[str, Any]]:
        """
        Get all edges in the graph (paginated).

        Args:
            graph_id: Graph ID

        Returns:
            List of edges
        """
        logger.info(f"Fetching all edges for graph {graph_id}...")

        edges = fetch_all_edges(self.client, graph_id)

        edges_data = []
        for edge in edges:
            edges_data.append({
                "uuid": getattr(edge, 'uuid_', None) or getattr(edge, 'uuid', ''),
                "name": edge.name or "",
                "fact": edge.fact or "",
                "source_node_uuid": edge.source_node_uuid,
                "target_node_uuid": edge.target_node_uuid,
                "attributes": edge.attributes or {},
            })

        logger.info(f"Fetched {len(edges_data)} edges in total")
        return edges_data
    
    def get_node_edges(
        self,
        node_uuid: str,
        *,
        graph_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get the edges connected to a node.

        In practice Zep Cloud 3.25's ``graph.node.get_edges`` only returns edges where the node is the
        source, even though the docs describe it as "all edges". When full context is needed,
        pass graph_id so the whole graph is paged and both incoming and outgoing edges are filtered.
        
        Args:
            node_uuid: node UUID
            graph_id: graph ID; when given, both edge directions are guaranteed
            
        Returns:
            List of edges
        """
        try:
            if graph_id:
                return [
                    edge
                    for edge in self.get_all_edges(graph_id)
                    if edge["source_node_uuid"] == node_uuid
                    or edge["target_node_uuid"] == node_uuid
                ]

            # Call the Zep API with retries
            edges = self._call_with_retry(
                func=lambda: self.client.graph.node.get_edges(node_uuid=node_uuid),
                operation_name=f"get node edges (node={node_uuid[:8]}...)"
            )
            
            edges_data = []
            for edge in edges:
                edges_data.append({
                    "uuid": getattr(edge, 'uuid_', None) or getattr(edge, 'uuid', ''),
                    "name": edge.name or "",
                    "fact": edge.fact or "",
                    "source_node_uuid": edge.source_node_uuid,
                    "target_node_uuid": edge.target_node_uuid,
                    "attributes": edge.attributes or {},
                })
            
            return edges_data
        except Exception as e:
            # An empty edge list is valid data. Authentication, permission and
            # transport failures must not be made indistinguishable from it.
            logger.error(f"Failed to get edges for node {node_uuid}: {str(e)}")
            raise
    
    def filter_defined_entities(
        self,
        graph_id: str,
        defined_entity_types: Optional[List[str]] = None,
        enrich_with_edges: bool = True
    ) -> FilteredEntities:
        """
        Filter nodes that match predefined entity types.

        Filter logic:
        - If a node's Labels contain only "Entity", the entity does not match our predefined types; skip it
        - If a node's Labels include labels other than "Entity" and "Node", it matches a predefined type; keep it

        Args:
            graph_id: Graph ID
            defined_entity_types: List of predefined entity types (optional; if provided, only these types are kept)
            enrich_with_edges: Whether to fetch related edge information for each entity

        Returns:
            FilteredEntities: Filtered entity collection
        """
        logger.info(f"Starting entity filtering for graph {graph_id}...")

        # Get all nodes
        all_nodes = self.get_all_nodes(graph_id)
        total_count = len(all_nodes)

        # Get all edges (for subsequent relationship lookups)
        all_edges = self.get_all_edges(graph_id) if enrich_with_edges else []

        # Build a mapping from node UUID to node data
        node_map = {n["uuid"]: n for n in all_nodes}

        # Filter entities that match the criteria
        filtered_entities = []
        entity_types_found = set()

        for node in all_nodes:
            labels = node.get("labels", [])

            # Filter logic: Labels must include labels other than "Entity" and "Node"
            custom_labels = [l for l in labels if l not in ["Entity", "Node"]]

            if not custom_labels:
                # Only default labels; skip
                continue

            # If predefined types are specified, check for a match
            if defined_entity_types:
                matching_labels = [l for l in custom_labels if l in defined_entity_types]
                if not matching_labels:
                    continue
                entity_type = matching_labels[0]
            else:
                entity_type = custom_labels[0]

            entity_types_found.add(entity_type)

            # Create the entity node object
            entity = EntityNode(
                uuid=node["uuid"],
                name=node["name"],
                labels=labels,
                summary=node["summary"],
                attributes=node["attributes"],
            )
            
            # Get related edges and nodes
            if enrich_with_edges:
                related_edges = []
                related_node_uuids = set()

                for edge in all_edges:
                    if edge["source_node_uuid"] == node["uuid"]:
                        related_edges.append({
                            "direction": "outgoing",
                            "edge_name": edge["name"],
                            "fact": edge["fact"],
                            "target_node_uuid": edge["target_node_uuid"],
                        })
                        related_node_uuids.add(edge["target_node_uuid"])
                    elif edge["target_node_uuid"] == node["uuid"]:
                        related_edges.append({
                            "direction": "incoming",
                            "edge_name": edge["name"],
                            "fact": edge["fact"],
                            "source_node_uuid": edge["source_node_uuid"],
                        })
                        related_node_uuids.add(edge["source_node_uuid"])

                entity.related_edges = related_edges

                # Get basic information for associated nodes
                related_nodes = []
                for related_uuid in related_node_uuids:
                    if related_uuid in node_map:
                        related_node = node_map[related_uuid]
                        related_nodes.append({
                            "uuid": related_node["uuid"],
                            "name": related_node["name"],
                            "labels": related_node["labels"],
                            "summary": related_node.get("summary", ""),
                        })

                entity.related_nodes = related_nodes
            
            filtered_entities.append(entity)
        
        logger.info(f"Filtering complete: total nodes {total_count}, matching {len(filtered_entities)}, "
                   f"entity types: {entity_types_found}")
        
        return FilteredEntities(
            entities=filtered_entities,
            entity_types=entity_types_found,
            total_count=total_count,
            filtered_count=len(filtered_entities),
        )
    
    def get_entity_with_context(
        self,
        graph_id: str,
        entity_uuid: str
    ) -> Optional[EntityNode]:
        """
        Get a single entity with its full context (edges and associated nodes, with retry mechanism).

        Args:
            graph_id: Graph ID
            entity_uuid: Entity UUID

        Returns:
            EntityNode or None
        """
        try:
            # Get node with retry
            node = self._call_with_retry(
                func=lambda: self.client.graph.node.get(uuid_=entity_uuid),
                operation_name=f"get_node_detail(uuid={entity_uuid[:8]}...)"
            )

            if not node:
                return None
            
            # Get the node's edges
            edges = self.get_node_edges(entity_uuid, graph_id=graph_id)
            
            # Get all nodes for related-entity lookup
            all_nodes = self.get_all_nodes(graph_id)
            node_map = {n["uuid"]: n for n in all_nodes}

            # Process related edges and nodes
            related_edges = []
            related_node_uuids = set()
            
            for edge in edges:
                if edge["source_node_uuid"] == entity_uuid:
                    related_edges.append({
                        "direction": "outgoing",
                        "edge_name": edge["name"],
                        "fact": edge["fact"],
                        "target_node_uuid": edge["target_node_uuid"],
                    })
                    related_node_uuids.add(edge["target_node_uuid"])
                else:
                    related_edges.append({
                        "direction": "incoming",
                        "edge_name": edge["name"],
                        "fact": edge["fact"],
                        "source_node_uuid": edge["source_node_uuid"],
                    })
                    related_node_uuids.add(edge["source_node_uuid"])
            
            # Get associated node information
            related_nodes = []
            for related_uuid in related_node_uuids:
                if related_uuid in node_map:
                    related_node = node_map[related_uuid]
                    related_nodes.append({
                        "uuid": related_node["uuid"],
                        "name": related_node["name"],
                        "labels": related_node["labels"],
                        "summary": related_node.get("summary", ""),
                    })
            
            return EntityNode(
                uuid=getattr(node, 'uuid_', None) or getattr(node, 'uuid', ''),
                name=node.name or "",
                labels=node.labels or [],
                summary=node.summary or "",
                attributes=node.attributes or {},
                related_edges=related_edges,
                related_nodes=related_nodes,
            )
            
        except NotFoundError:
            return None
        except Exception as e:
            # Only an actual Zep 404 means "entity not found". Propagate 401,
            # 403 and exhausted transport errors so callers cannot prepare a
            # simulation with silently incomplete graph context.
            logger.error(f"Failed to get entity {entity_uuid}: {str(e)}")
            raise
    
    def get_entities_by_type(
        self,
        graph_id: str,
        entity_type: str,
        enrich_with_edges: bool = True
    ) -> List[EntityNode]:
        """
        Get all entities of a specified type.

        Args:
            graph_id: Graph ID
            entity_type: Entity type (e.g. "Student", "PublicFigure")
            enrich_with_edges: Whether to fetch related edge information

        Returns:
            List of entities
        """
        result = self.filter_defined_entities(
            graph_id=graph_id,
            defined_entity_types=[entity_type],
            enrich_with_edges=enrich_with_edges
        )
        return result.entities
