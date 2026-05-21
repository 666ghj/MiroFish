"""
实体读取与过滤服务
从本地JSON图谱中读取节点，筛选出符合预定义实体类型的节点
"""

from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass, field

from ..config import Config
from ..utils.local_graph_store import LocalGraphStore
from ..utils.logger import get_logger

logger = get_logger('mirofish.zep_entity_reader')


@dataclass
class EntityNode:
    """实体节点数据结构"""
    uuid: str
    name: str
    labels: List[str]
    summary: str
    attributes: Dict[str, Any]
    related_edges: List[Dict[str, Any]] = field(default_factory=list)
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
        """获取实体类型（排除默认的Entity/Node标签）"""
        for label in self.labels:
            if label not in ("Entity", "Node"):
                return label
        return None


@dataclass
class FilteredEntities:
    """过滤后的实体集合"""
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
    实体读取与过滤服务

    主要功能：
    1. 从本地图谱读取所有节点
    2. 筛选出符合预定义实体类型的节点（Labels不只是Entity的节点）
    3. 获取每个实体的相关边和关联节点信息
    """

    def __init__(self, storage_dir: Optional[str] = None, api_key: Optional[str] = None):
        # api_key参数保留以兼容旧调用方式，但不再使用
        storage_dir = storage_dir or Config.GRAPH_STORAGE_DIR
        self.store = LocalGraphStore(storage_dir)

    def get_all_nodes(self, graph_id: str) -> List[Dict[str, Any]]:
        """获取图谱的所有节点"""
        logger.info(f"获取图谱 {graph_id} 的所有节点...")
        nodes = self.store.get_nodes(graph_id)
        logger.info(f"共获取 {len(nodes)} 个节点")
        return nodes

    def get_all_edges(self, graph_id: str) -> List[Dict[str, Any]]:
        """获取图谱的所有边"""
        logger.info(f"获取图谱 {graph_id} 的所有边...")
        edges = self.store.get_edges(graph_id)
        logger.info(f"共获取 {len(edges)} 条边")
        return edges

    def get_node_edges(self, graph_id: str, node_uuid: str) -> List[Dict[str, Any]]:
        """获取指定节点的所有相关边"""
        try:
            return self.store.get_node_edges(graph_id, node_uuid)
        except Exception as e:
            logger.warning(f"获取节点 {node_uuid} 的边失败: {e}")
            return []

    def filter_defined_entities(
        self,
        graph_id: str,
        defined_entity_types: Optional[List[str]] = None,
        enrich_with_edges: bool = True
    ) -> FilteredEntities:
        """
        筛选出符合预定义实体类型的节点

        筛选逻辑：
        - 节点的Labels包含除"Entity"和"Node"之外的标签 → 符合预定义类型，保留
        - 节点的Labels只有"Entity"/"Node" → 不符合，跳过

        Args:
            graph_id: 图谱ID
            defined_entity_types: 预定义实体类型列表（可选，若提供则只保留这些类型）
            enrich_with_edges: 是否获取每个实体的相关边信息
        """
        logger.info(f"开始筛选图谱 {graph_id} 的实体...")

        all_nodes = self.get_all_nodes(graph_id)
        total_count = len(all_nodes)

        all_edges = self.get_all_edges(graph_id) if enrich_with_edges else []

        node_map = {n["uuid"]: n for n in all_nodes}

        filtered_entities = []
        entity_types_found: Set[str] = set()

        for node in all_nodes:
            labels = node.get("labels") or []
            custom_labels = [l for l in labels if l not in ("Entity", "Node")]

            if not custom_labels:
                continue

            if defined_entity_types:
                matching = [l for l in custom_labels if l in defined_entity_types]
                if not matching:
                    continue
                entity_type = matching[0]
            else:
                entity_type = custom_labels[0]

            entity_types_found.add(entity_type)

            entity = EntityNode(
                uuid=node["uuid"],
                name=node.get("name", ""),
                labels=labels,
                summary=node.get("summary", ""),
                attributes=node.get("attributes", {}),
            )

            if enrich_with_edges:
                related_edges = []
                related_node_uuids: Set[str] = set()

                for edge in all_edges:
                    if edge.get("source_node_uuid") == node["uuid"]:
                        related_edges.append({
                            "direction": "outgoing",
                            "edge_name": edge.get("name", ""),
                            "fact": edge.get("fact", ""),
                            "target_node_uuid": edge.get("target_node_uuid", ""),
                        })
                        related_node_uuids.add(edge.get("target_node_uuid", ""))
                    elif edge.get("target_node_uuid") == node["uuid"]:
                        related_edges.append({
                            "direction": "incoming",
                            "edge_name": edge.get("name", ""),
                            "fact": edge.get("fact", ""),
                            "source_node_uuid": edge.get("source_node_uuid", ""),
                        })
                        related_node_uuids.add(edge.get("source_node_uuid", ""))

                entity.related_edges = related_edges

                related_nodes = []
                for related_uuid in related_node_uuids:
                    if related_uuid and related_uuid in node_map:
                        rn = node_map[related_uuid]
                        related_nodes.append({
                            "uuid": rn["uuid"],
                            "name": rn.get("name", ""),
                            "labels": rn.get("labels", []),
                            "summary": rn.get("summary", ""),
                        })
                entity.related_nodes = related_nodes

            filtered_entities.append(entity)

        logger.info(f"筛选完成: 总节点 {total_count}, 符合条件 {len(filtered_entities)}, "
                    f"实体类型: {entity_types_found}")

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
        """获取单个实体及其完整上下文（边和关联节点）"""
        try:
            node = self.store.get_node(graph_id, entity_uuid)
            if not node:
                return None

            edges = self.get_node_edges(graph_id, entity_uuid)
            all_nodes = self.get_all_nodes(graph_id)
            node_map = {n["uuid"]: n for n in all_nodes}

            related_edges = []
            related_node_uuids: Set[str] = set()

            for edge in edges:
                if edge.get("source_node_uuid") == entity_uuid:
                    related_edges.append({
                        "direction": "outgoing",
                        "edge_name": edge.get("name", ""),
                        "fact": edge.get("fact", ""),
                        "target_node_uuid": edge.get("target_node_uuid", ""),
                    })
                    related_node_uuids.add(edge.get("target_node_uuid", ""))
                else:
                    related_edges.append({
                        "direction": "incoming",
                        "edge_name": edge.get("name", ""),
                        "fact": edge.get("fact", ""),
                        "source_node_uuid": edge.get("source_node_uuid", ""),
                    })
                    related_node_uuids.add(edge.get("source_node_uuid", ""))

            related_nodes = []
            for related_uuid in related_node_uuids:
                if related_uuid and related_uuid in node_map:
                    rn = node_map[related_uuid]
                    related_nodes.append({
                        "uuid": rn["uuid"],
                        "name": rn.get("name", ""),
                        "labels": rn.get("labels", []),
                        "summary": rn.get("summary", ""),
                    })

            return EntityNode(
                uuid=node["uuid"],
                name=node.get("name", ""),
                labels=node.get("labels", []),
                summary=node.get("summary", ""),
                attributes=node.get("attributes", {}),
                related_edges=related_edges,
                related_nodes=related_nodes,
            )

        except Exception as e:
            logger.error(f"获取实体 {entity_uuid} 失败: {e}")
            return None

    def get_entities_by_type(
        self,
        graph_id: str,
        entity_type: str,
        enrich_with_edges: bool = True
    ) -> List[EntityNode]:
        """获取指定类型的所有实体"""
        result = self.filter_defined_entities(
            graph_id=graph_id,
            defined_entity_types=[entity_type],
            enrich_with_edges=enrich_with_edges
        )
        return result.entities
