"""
Neo4j Schema 管理器
处理 Label、Relationship Type、Index 的创建和管理
"""

from typing import Dict, Any, List, Optional

from neo4j import Driver, Session

from .driver import get_neo4j_driver
from ..logger import get_logger

logger = get_logger('mirofish.neo4j.schema')


class Neo4jSchemaManager:
    """
    Neo4j Schema 管理器

    负责创建和管理：
    1. 节点 Label
    2. 关系类型 (Relationship Type)
    3. 索引 (Index)
    4. 约束 (Constraint)
    """

    # 保留的 Label 名称（不能用作自定义实体类型）
    RESERVED_LABELS = {"Entity", "Node", "_GraphMetadata"}

    def __init__(self, driver: Optional[Driver] = None):
        self.driver = driver or get_neo4j_driver()

    def setup_graph_schema(
        self,
        graph_id: str,
        entity_types: List[Dict[str, Any]],
        edge_types: List[Dict[str, Any]]
    ) -> None:
        """
        设置图谱的 Schema（本体）

        Args:
            graph_id: 图谱ID
            entity_types: 实体类型定义列表
            edge_types: 关系类型定义列表
        """
        with self.driver.session() as session:
            # 1. 创建图谱根节点（用于隔离不同图谱的数据）
            self._create_graph_root_node(session, graph_id)

            # 2. 创建实体 Label（以 Entity 开头）
            for entity_def in entity_types:
                label_name = entity_def["name"]
                if label_name in self.RESERVED_LABELS:
                    logger.warning(f"实体类型 {label_name} 是保留名称，跳过")
                    continue

                full_label = f"Entity_{label_name}"
                self._create_entity_label(session, full_label, entity_def)

            # 3. 创建关系类型
            for edge_def in edge_types:
                rel_type = edge_def["name"]
                self._create_relationship_type(session, rel_type, edge_def)

            # 4. 创建索引
            self._create_indexes(session, graph_id)

        logger.info(
            f"Schema 设置完成: {len(entity_types)} 个实体类型, "
            f"{len(edge_types)} 个关系类型"
        )

    def _create_graph_root_node(self, session: Session, graph_id: str) -> None:
        """创建图谱根节点，用于数据隔离"""
        cypher = """
        MERGE (g:_GraphMetadata {graph_id: $graph_id})
        ON CREATE SET
            g.created_at = datetime(),
            g.entity_count = 0,
            g.edge_count = 0
        RETURN g
        """
        session.run(cypher, graph_id=graph_id)

    def _create_entity_label(
        self,
        session: Session,
        label: str,
        entity_def: Dict[str, Any]
    ) -> None:
        """
        创建实体 Label

        Args:
            session: Neo4j 会话
            label: Label 名称 (e.g., "Entity_Student")
            entity_def: 实体定义
        """
        description = entity_def.get("description", f"A {label} entity")

        # 构建属性定义
        properties = entity_def.get("attributes", [])

        # 基本属性始终存在
        base_props = {
            "uuid": "STRING",
            "name": "STRING",
            "summary": "STRING",
            "graph_id": "STRING",
            "created_at": "STRING"
        }

        # 构建 CREATE LABEL 语句（Neo4j 不支持程序化创建 Label，
        # 所以我们在节点创建时直接使用动态 Label）
        # 这里主要是记录日志
        logger.debug(f"实体 Label: {label}, 描述: {description}")

    def _create_relationship_type(
        self,
        session: Session,
        rel_type: str,
        edge_def: Dict[str, Any]
    ) -> None:
        """
        创建关系类型

        Args:
            session: Neo4j 会话
            rel_type: 关系类型名称 (e.g., "STUDIES_AT")
            edge_def: 关系定义
        """
        description = edge_def.get("description", f"A {rel_type} relationship")
        logger.debug(f"关系类型: {rel_type}, 描述: {description}")

    def _create_indexes(self, session: Session, graph_id: str) -> None:
        """
        创建索引

        为常用的查询字段创建索引以提高性能
        """
        indexes = [
            # 节点索引
            ("entity_uuid_index", "INDEX FOR (n:Entity) ON (n.uuid)"),
            ("entity_name_index", "INDEX FOR (n:Entity) ON (n.name)"),
            ("entity_graph_id_index", "INDEX FOR (n:Entity) ON (n.graph_id)"),

            # 关系索引
            ("rel_source_index", "INDEX FOR ()-[r]-() ON (r.source_node_uuid)"),
            ("rel_target_index", "INDEX FOR ()-[r]-() ON (r.target_node_uuid)"),
        ]

        for index_name, index_query in indexes:
            try:
                # 使用 IF NOT EXISTS 避免重复创建
                session.run(f"CREATE INDEX {index_name} IF NOT EXISTS FOR {index_query.split(' FOR ')[1]}")
                logger.debug(f"索引已创建: {index_name}")
            except Exception as e:
                # 忽略已存在的索引错误
                logger.debug(f"索引 {index_name} 创建跳过: {e}")

    def create_fulltext_index(self, index_name: str, node_labels: List[str], properties: List[str]) -> None:
        """
        创建全文索引

        Args:
            index_name: 索引名称
            node_labels: 节点 Label 列表
            properties: 属性列表
        """
        with self.driver.session() as session:
            labels_str = ":".join(node_labels)
            props_str = ", ".join([f"n.{p}" for p in properties])

            cypher = f"""
            CREATE FULLTEXT INDEX {index_name}
            FOR (n:{labels_str}) ON EACH [{props_str}]
            """
            try:
                session.run(cypher)
                logger.info(f"全文索引已创建: {index_name}")
            except Exception as e:
                logger.warning(f"全文索引创建失败: {index_name}, {e}")

    def drop_graph_data(self, graph_id: str) -> None:
        """
        删除图谱的所有数据（保留 Schema）

        Args:
            graph_id: 图谱ID
        """
        with self.driver.session() as session:
            # 删除该图谱的所有节点（级联删除关系）
            cypher = """
            MATCH (n:Entity)
            WHERE n.graph_id = $graph_id
            DETACH DELETE n
            """
            result = session.run(cypher, graph_id=graph_id)
            summary = result.consume()
            nodes_deleted = summary.counters.nodes_deleted

            # 更新图谱元数据
            cypher2 = """
            MATCH (g:_GraphMetadata {graph_id: $graph_id})
            SET g.entity_count = 0, g.edge_count = 0, g.deleted_at = datetime()
            """
            session.run(cypher2, graph_id=graph_id)

            logger.info(f"图谱数据已删除: {graph_id}, 删除了 {nodes_deleted} 个节点")

    def get_graph_stats(self, graph_id: str) -> Dict[str, Any]:
        """
        获取图谱统计信息

        Args:
            graph_id: 图谱ID

        Returns:
            统计信息字典
        """
        with self.driver.session() as session:
            # 统计节点
            node_cypher = """
            MATCH (n:Entity)
            WHERE n.graph_id = $graph_id
            RETURN count(n) AS node_count
            """
            node_record = session.run(node_cypher, graph_id=graph_id).single()
            node_count = node_record["node_count"] if node_record else 0

            # 统计边
            edge_cypher = """
            MATCH ()-[r]->()
            WHERE r.graph_id = $graph_id
            RETURN count(r) AS edge_count
            """
            edge_record = session.run(edge_cypher, graph_id=graph_id).single()
            edge_count = edge_record["edge_count"] if edge_record else 0

            # 统计实体类型分布
            type_cypher = """
            MATCH (n:Entity)
            WHERE n.graph_id = $graph_id
            WITH labels(n) AS lbs, count(*) AS cnt
            UNWIND lbs AS label
            WITH label, cnt WHERE NOT label IN ['Entity', 'Node']
            RETURN label AS entity_type, sum(cnt) AS count
            """
            type_result = session.run(type_cypher, graph_id=graph_id)
            entity_types = {record["entity_type"]: record["count"] for record in type_result}

            return {
                "graph_id": graph_id,
                "node_count": node_count,
                "edge_count": edge_count,
                "entity_types": entity_types
            }
