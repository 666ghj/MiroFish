"""
Neo4j 实体读取器
从 Neo4j 图谱中读取和过滤实体
替代 ZepEntityReader
"""

import time
from typing import Dict, Any, List, Optional, Set, Callable, TypeVar, TYPE_CHECKING

if TYPE_CHECKING:
    from neo4j import Driver

from .graph_adapter import GraphAdapter, GraphNode, GraphEdge
from ...utils.logger import get_logger

logger = get_logger('mirofish.neo4j_entity_reader')

T = TypeVar('T')


def _domain_label(label: str) -> str:
    """Map Neo4j storage labels like Entity_Student back to Student."""
    if label.startswith("Entity_"):
        return label[len("Entity_"):]
    return label


class EntityNode:
    """
    实体节点数据结构

    与原始的 ZepEntityReader.EntityNode 保持兼容
    """
    uuid: str
    name: str
    labels: List[str]
    summary: str
    attributes: Dict[str, Any]
    related_edges: List[Dict[str, Any]]
    related_nodes: List[Dict[str, Any]]

    def __init__(
        self,
        uuid: str,
        name: str,
        labels: List[str],
        summary: str,
        attributes: Dict[str, Any],
        related_edges: List[Dict[str, Any]] = None,
        related_nodes: List[Dict[str, Any]] = None
    ):
        self.uuid = uuid
        self.name = name
        self.labels = labels
        self.summary = summary
        self.attributes = attributes
        self.related_edges = related_edges or []
        self.related_nodes = related_nodes or []

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
        """获取实体类型（排除默认的 Entity 标签）"""
        for label in self.labels:
            if label not in ("Entity", "Node"):
                return _domain_label(label)
        return None


class FilteredEntities:
    """过滤后的实体集合"""
    entities: List[EntityNode]
    entity_types: Set[str]
    total_count: int
    filtered_count: int

    def __init__(
        self,
        entities: List[EntityNode],
        entity_types: Set[str],
        total_count: int,
        filtered_count: int
    ):
        self.entities = entities
        self.entity_types = entity_types
        self.total_count = total_count
        self.filtered_count = filtered_count

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entities": [e.to_dict() for e in self.entities],
            "entity_types": list(self.entity_types),
            "total_count": self.total_count,
            "filtered_count": self.filtered_count,
        }


class Neo4jEntityReader:
    """
    Neo4j 实体读取与过滤服务

    主要功能：
    1. 从 Neo4j 图谱读取所有节点
    2. 筛选出符合预定义实体类型的节点
    3. 获取每个实体的相关边和关联节点信息
    """

    # 重试配置
    MAX_RETRIES = 3
    RETRY_DELAY = 2.0

    def __init__(self, driver: 'Driver' = None):
        """
        初始化读取器

        Args:
            driver: Neo4j 驱动（可选，默认使用全局驱动）
        """
        from ...utils.neo4j.driver import get_neo4j_driver

        self.driver = driver or get_neo4j_driver()

    def _call_with_retry(
        self,
        func: Callable[[], T],
        operation_name: str,
        max_retries: int = None,
        initial_delay: float = None
    ) -> T:
        """
        带重试机制的 Neo4j 查询

        Args:
            func: 要执行的函数
            operation_name: 操作名称，用于日志
            max_retries: 最大重试次数
            initial_delay: 初始延迟秒数

        Returns:
            查询结果
        """
        max_retries = max_retries or self.MAX_RETRIES
        initial_delay = initial_delay or self.RETRY_DELAY
        last_exception = None
        delay = initial_delay

        for attempt in range(max_retries):
            try:
                return func()
            except Exception as e:
                last_exception = e
                if attempt < max_retries - 1:
                    logger.warning(
                        f"Neo4j {operation_name} 第 {attempt + 1} 次尝试失败: {str(e)[:100]}, "
                        f"{delay:.1f}秒后重试..."
                    )
                    time.sleep(delay)
                    delay *= 2
                else:
                    logger.error(
                        f"Neo4j {operation_name} 在 {max_retries} 次尝试后仍失败: {str(e)}"
                    )

        raise last_exception

    def get_all_nodes(self, graph_id: str) -> List[Dict[str, Any]]:
        """
        获取图谱的所有节点（分页获取）

        Args:
            graph_id: 图谱ID

        Returns:
            节点列表
        """
        logger.info(f"获取图谱 {graph_id} 的所有节点...")

        def _query():
            nodes = []
            with self.driver.session() as session:
                cypher = """
                MATCH (n:Entity)
                WHERE n.graph_id = $graph_id
                RETURN n.uuid AS uuid, n.name AS name, labels(n) AS labels,
                       n.summary AS summary, n.entity_type AS entity_type,
                       n.created_at AS created_at, properties(n) AS attributes
                """
                result = session.run(cypher, graph_id=graph_id)
                for record in result:
                    nodes.append({
                        "uuid": record["uuid"],
                        "name": record["name"],
                        "labels": record["labels"],
                        "summary": record["summary"] or "",
                        "entity_type": record.get("entity_type"),
                        "attributes": record["attributes"] or {},
                    })
            return nodes

        nodes = self._call_with_retry(_query, f"获取所有节点({graph_id})")
        logger.info(f"共获取 {len(nodes)} 个节点")
        return nodes

    def get_all_edges(self, graph_id: str) -> List[Dict[str, Any]]:
        """
        获取图谱的所有边

        Args:
            graph_id: 图谱ID

        Returns:
            边列表
        """
        logger.info(f"获取图谱 {graph_id} 的所有边...")

        def _query():
            edges = []
            with self.driver.session() as session:
                cypher = """
                MATCH (source)-[r]->(target)
                WHERE r.graph_id = $graph_id
                RETURN r.uuid AS uuid, type(r) AS name, r.fact AS fact,
                       r.source_node_uuid AS source_node_uuid,
                       r.target_node_uuid AS target_node_uuid,
                       r.created_at AS created_at, properties(r) AS attributes
                """
                result = session.run(cypher, graph_id=graph_id)
                for record in result:
                    edges.append({
                        "uuid": record["uuid"],
                        "name": record["name"],
                        "fact": record["fact"] or "",
                        "source_node_uuid": record["source_node_uuid"],
                        "target_node_uuid": record["target_node_uuid"],
                        "attributes": record["attributes"] or {},
                    })
            return edges

        edges = self._call_with_retry(_query, f"获取所有边({graph_id})")
        logger.info(f"共获取 {len(edges)} 条边")
        return edges

    def get_node_edges(self, node_uuid: str) -> List[Dict[str, Any]]:
        """
        获取指定节点的所有相关边

        Args:
            node_uuid: 节点UUID

        Returns:
            边列表
        """
        def _query():
            edges = []
            with self.driver.session() as session:
                cypher = """
                MATCH (source)-[r]->(target)
                WHERE r.source_node_uuid = $uuid OR r.target_node_uuid = $uuid
                RETURN r.uuid AS uuid, type(r) AS name, r.fact AS fact,
                       r.source_node_uuid AS source_node_uuid,
                       r.target_node_uuid AS target_node_uuid,
                       source.name AS source_name, target.name AS target_name,
                       properties(r) AS attributes
                """
                result = session.run(cypher, uuid=node_uuid)
                for record in result:
                    edges.append({
                        "uuid": record["uuid"],
                        "name": record["name"],
                        "fact": record["fact"] or "",
                        "source_node_uuid": record["source_node_uuid"],
                        "target_node_uuid": record["target_node_uuid"],
                        "attributes": record["attributes"] or {},
                    })
            return edges

        return self._call_with_retry(
            _query, f"获取节点边({node_uuid[:8]}...)"
        )

    def filter_defined_entities(
        self,
        graph_id: str,
        defined_entity_types: Optional[List[str]] = None,
        enrich_with_edges: bool = True
    ) -> FilteredEntities:
        """
        筛选出符合预定义实体类型的节点

        筛选逻辑：
        - 如果节点的 Labels 只有一个 "Entity"，说明这个实体不符合预定义类型，跳过
        - 如果节点的 Labels 包含除 "Entity" 和 "Node" 之外的标签，说明符合预定义类型，保留

        Args:
            graph_id: 图谱ID
            defined_entity_types: 预定义的实体类型列表（可选）
            enrich_with_edges: 是否获取每个实体的相关边信息

        Returns:
            FilteredEntities: 过滤后的实体集合
        """
        logger.info(f"开始筛选图谱 {graph_id} 的实体...")

        # 获取所有节点
        all_nodes = self.get_all_nodes(graph_id)
        total_count = len(all_nodes)

        # 获取所有边（用于后续关联查找）
        all_edges = self.get_all_edges(graph_id) if enrich_with_edges else []

        # 构建节点UUID到节点数据的映射
        node_map = {n["uuid"]: n for n in all_nodes}

        # 筛选符合条件的实体
        filtered_entities = []
        entity_types_found = set()

        for node in all_nodes:
            labels = node.get("labels", [])

            # 筛选逻辑：Labels 必须包含除 "Entity" 和 "Node" 之外的标签
            custom_labels = [_domain_label(l) for l in labels if l not in ("Entity", "Node")]

            if not custom_labels:
                continue

            # 如果指定了预定义类型，检查是否匹配
            if defined_entity_types:
                matching_labels = [l for l in custom_labels if l in defined_entity_types]
                if not matching_labels:
                    continue
                entity_type = matching_labels[0]
            else:
                entity_type = custom_labels[0]

            entity_types_found.add(entity_type)

            # 创建实体节点对象
            display_labels = ["Entity", *custom_labels]

            entity = EntityNode(
                uuid=node["uuid"],
                name=node["name"],
                labels=display_labels,
                summary=node["summary"],
                attributes=node["attributes"],
            )

            # 获取相关边和节点
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

                # 获取关联节点的基本信息
                related_nodes = []
                for related_uuid in related_node_uuids:
                    if related_uuid in node_map:
                        related_node = node_map[related_uuid]
                        related_labels = [
                            _domain_label(l)
                            for l in related_node["labels"]
                            if l not in ("Entity", "Node")
                        ]
                        related_nodes.append({
                            "uuid": related_node["uuid"],
                            "name": related_node["name"],
                            "labels": ["Entity", *related_labels],
                            "summary": related_node.get("summary", ""),
                        })

                entity.related_nodes = related_nodes

            filtered_entities.append(entity)

        logger.info(
            f"筛选完成: 总节点 {total_count}, 符合条件 {len(filtered_entities)}, "
            f"实体类型: {entity_types_found}"
        )

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
        获取单个实体及其完整上下文（边和关联节点）

        Args:
            graph_id: 图谱ID
            entity_uuid: 实体UUID

        Returns:
            EntityNode 或 None
        """
        def _query():
            with self.driver.session() as session:
                # 获取节点
                cypher = """
                MATCH (n:Entity)
                WHERE n.uuid = $uuid AND n.graph_id = $graph_id
                RETURN n.uuid AS uuid, n.name AS name, labels(n) AS labels,
                       n.summary AS summary, n.entity_type AS entity_type,
                       properties(n) AS attributes
                """
                result = session.run(cypher, uuid=entity_uuid, graph_id=graph_id)
                record = result.single()

                if not record:
                    return None

                # 获取节点的边
                edges_cypher = """
                MATCH (source)-[r]->(target)
                WHERE (r.source_node_uuid = $uuid OR r.target_node_uuid = $uuid)
                      AND r.graph_id = $graph_id
                RETURN r.uuid AS uuid, type(r) AS name, r.fact AS fact,
                       r.source_node_uuid AS source_node_uuid,
                       r.target_node_uuid AS target_node_uuid
                """
                edges_result = session.run(edges_cypher, uuid=entity_uuid, graph_id=graph_id)

                edges = []
                for edge_record in edges_result:
                    edges.append({
                        "uuid": edge_record["uuid"],
                        "name": edge_record["name"],
                        "fact": edge_record["fact"] or "",
                        "source_node_uuid": edge_record["source_node_uuid"],
                        "target_node_uuid": edge_record["target_node_uuid"],
                    })

                return record, edges

        try:
            result = self._call_with_retry(
                _query,
                f"获取实体详情({entity_uuid[:8]}...)"
            )

            if not result:
                return None

            record, edges = result

            # 获取所有节点用于关联查找
            all_nodes = self.get_all_nodes(graph_id)
            node_map = {n["uuid"]: n for n in all_nodes}

            # 处理相关边和节点
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

            # 获取关联节点信息
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

            labels = record["labels"] or []
            custom_labels = [_domain_label(l) for l in labels if l not in ("Entity", "Node")]

            return EntityNode(
                uuid=record["uuid"],
                name=record["name"],
                labels=["Entity", *custom_labels],
                summary=record["summary"] or "",
                attributes=record["attributes"] or {},
                related_edges=related_edges,
                related_nodes=related_nodes,
            )

        except Exception as e:
            logger.error(f"获取实体 {entity_uuid} 失败: {str(e)}")
            return None

    def get_entities_by_type(
        self,
        graph_id: str,
        entity_type: str,
        enrich_with_edges: bool = True
    ) -> List[EntityNode]:
        """
        获取指定类型的所有实体

        Args:
            graph_id: 图谱ID
            entity_type: 实体类型（如 "Student", "PublicFigure" 等）
            enrich_with_edges: 是否获取相关边信息

        Returns:
            实体列表
        """
        result = self.filter_defined_entities(
            graph_id=graph_id,
            defined_entity_types=[entity_type],
            enrich_with_edges=enrich_with_edges
        )
        return result.entities
