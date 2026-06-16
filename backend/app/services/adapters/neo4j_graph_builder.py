"""
Neo4j 图谱构建器
实现 GraphAdapter 接口，替代 Zep Cloud 的 GraphBuilderService
"""

import os
import uuid
import time
import threading
import json
from typing import Dict, Any, List, Optional, Callable

from neo4j import Driver

from .graph_adapter import GraphAdapter, GraphInfo, GraphNode, GraphEdge, SearchResult
from .llm_extractor import LLMExtractionPipeline
from ...utils.neo4j.driver import get_neo4j_driver
from ...utils.neo4j.schema import Neo4jSchemaManager
from ...utils.logger import get_logger
from ...models.task import TaskManager, TaskStatus
from ...utils.locale import t, get_locale, set_locale

logger = get_logger('mirofish.neo4j_graph_builder')


def _safe_neo4j_identifier(value: str, fallback: str = "RELATED_TO") -> str:
    """Return a conservative Neo4j label/relationship identifier."""
    cleaned = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in str(value or ""))
    if not cleaned:
        cleaned = fallback
    if cleaned[0].isdigit():
        cleaned = f"_{cleaned}"
    return cleaned


class Neo4jGraphBuilder(GraphAdapter):
    """
    Neo4j 图谱构建器

    使用 LLM Extraction Pipeline + Neo4j 实现知识图谱构建，
    替代 Zep Cloud 的自动文本提取功能。
    """

    def __init__(
        self,
        driver: Optional[Driver] = None,
        llm_extractor: Optional[LLMExtractionPipeline] = None
    ):
        """
        初始化 Neo4j 图谱构建器

        Args:
            driver: Neo4j 驱动（可选，默认使用全局驱动）
            llm_extractor: LLM 提取器（可选，默认创建新实例）
        """
        self.driver = driver or get_neo4j_driver()
        self.extractor = llm_extractor or LLMExtractionPipeline()
        self.schema_manager = Neo4jSchemaManager(self.driver)
        self.task_manager = TaskManager()
        self._ontology_cache: Dict[str, Dict[str, Any]] = {}

    def create_graph(self, name: str) -> str:
        """
        创建新图谱

        Args:
            name: 图谱名称

        Returns:
            graph_id: 新创建的图谱ID
        """
        graph_id = f"mirofish_{uuid.uuid4().hex[:16]}"

        with self.driver.session() as session:
            # 创建图谱元数据节点
            cypher = """
            MERGE (g:_GraphMetadata {graph_id: $graph_id})
            ON CREATE SET
                g.name = $name,
                g.created_at = datetime(),
                g.entity_count = 0,
                g.edge_count = 0
            RETURN g.graph_id AS graph_id
            """
            result = session.run(cypher, graph_id=graph_id, name=name)
            created_id = result.single()["graph_id"]

        logger.info(f"创建 Neo4j 图谱: {graph_id}, 名称: {name}")
        return created_id

    def set_ontology(
        self,
        graph_id: str,
        entity_types,
        edge_types: Optional[List[Dict[str, Any]]] = None
    ) -> None:
        """
        设置图谱本体（Schema）

        Args:
            graph_id: 图谱ID
            entity_types: 实体类型定义列表
            edge_types: 关系类型定义列表
        """
        if isinstance(entity_types, dict):
            ontology = entity_types
            entity_types = ontology.get("entity_types", [])
            edge_types = ontology.get("edge_types", [])
        else:
            ontology = {
                "entity_types": entity_types or [],
                "edge_types": edge_types or [],
            }

        self._ontology_cache[graph_id] = ontology
        self.schema_manager.setup_graph_schema(graph_id, entity_types or [], edge_types or [])

        with self.driver.session() as session:
            session.run(
                """
                MERGE (g:_GraphMetadata {graph_id: $graph_id})
                SET g.ontology_json = $ontology_json,
                    g.updated_at = datetime()
                """,
                graph_id=graph_id,
                ontology_json=json.dumps(ontology, ensure_ascii=False)
            )
        logger.info(f"本体已设置: {graph_id}")

    def add_text_batches(
        self,
        graph_id: str,
        chunks: List[str],
        batch_size: int = 3,
        progress_callback: Optional[Callable] = None
    ) -> List[str]:
        """
        批量添加文本到图谱（通过 LLM 提取）

        Args:
            graph_id: 图谱ID
            chunks: 文本块列表
            batch_size: 批处理大小（LLM 并行数）
            progress_callback: 进度回调

        Returns:
            chunk_ids: 所有文本块的 ID 列表
        """
        # 构建 ontology 字典（用于 LLM 提取）
        ontology = self._build_ontology_for_extraction(graph_id)

        # 使用 LLM 提取实体和关系
        entities, edges = self.extractor.extract_from_chunks(
            chunks=chunks,
            ontology=ontology,
            graph_id=graph_id,
            progress_callback=progress_callback,
            parallel_workers=batch_size
        )

        # 将提取的结果写入 Neo4j
        self._write_extracted_data(graph_id, entities, edges)

        # 返回 chunk IDs（这里用索引代替 UUID）
        chunk_ids = [f"chunk_{i}" for i in range(len(chunks))]
        return chunk_ids

    def _build_ontology_for_extraction(self, graph_id: str) -> Dict[str, Any]:
        """从图谱 Schema 构建 LLM 提取用的 ontology"""
        if graph_id in self._ontology_cache:
            return self._ontology_cache[graph_id]

        with self.driver.session() as session:
            record = session.run(
                """
                MATCH (g:_GraphMetadata {graph_id: $graph_id})
                RETURN g.ontology_json AS ontology_json
                """,
                graph_id=graph_id
            ).single()

        if record and record["ontology_json"]:
            try:
                ontology = json.loads(record["ontology_json"])
                self._ontology_cache[graph_id] = ontology
                return ontology
            except json.JSONDecodeError:
                logger.warning(f"图谱本体解析失败，使用空本体: {graph_id}")

        return {"entity_types": [], "edge_types": []}

    def _write_extracted_data(
        self,
        graph_id: str,
        entities: List,
        edges: List
    ) -> None:
        """
        将提取的实体和关系写入 Neo4j

        Args:
            graph_id: 图谱ID
            entities: 实体列表
            edges: 边列表
        """
        with self.driver.session() as session:
            # 写入实体
            for entity in entities:
                self._write_node(session, graph_id, entity)

            # 写入关系
            # 先建立节点名称到UUID的映射
            name_to_uuid = self._get_name_to_uuid_mapping(session, graph_id)

            for edge in edges:
                self._write_edge(session, graph_id, edge, name_to_uuid)

            # 更新图谱统计
            self._update_graph_stats(session, graph_id, len(entities), len(edges))

    def _write_node(self, session, graph_id: str, entity) -> None:
        """写入单个节点"""
        entity_type = _safe_neo4j_identifier(entity.entity_type, "Entity")
        # Neo4j Label 格式：Entity_Student
        labels = ["Entity", f"Entity_{entity_type}"] if entity_type else ["Entity"]

        # 构建属性
        properties = {
            "uuid": str(uuid.uuid4()),
            "name": entity.name,
            "summary": entity.summary,
            "graph_id": graph_id,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "entity_type": entity_type
        }

        # 添加自定义属性
        for key, value in entity.attributes.items():
            properties[key] = value

        # 构建 MERGE 查询
        label_str = ":".join(labels)
        set_clause = ", ".join([f"n.{k} = ${k}" for k in properties.keys()])

        cypher = f"""
        MERGE (n:{label_str} {{name: $name, graph_id: $graph_id}})
        ON CREATE SET {set_clause}
        ON MATCH SET {set_clause}
        RETURN n.uuid AS uuid
        """

        try:
            session.run(cypher, **properties)
        except Exception as e:
            logger.warning(f"写入节点失败: {entity.name}, {e}")

    def _write_edge(
        self,
        session,
        graph_id: str,
        edge,
        name_to_uuid: Dict[str, str]
    ) -> None:
        """写入单条边"""
        source_uuid = name_to_uuid.get(edge.source_name)
        target_uuid = name_to_uuid.get(edge.target_name)

        if not source_uuid or not target_uuid:
            logger.debug(f"跳过边（找不到节点）: {edge.source_name} -> {edge.target_name}")
            return

        properties = {
            "uuid": str(uuid.uuid4()),
            "name": edge.name,
            "fact": edge.fact,
            "graph_id": graph_id,
            "source_node_uuid": source_uuid,
            "target_node_uuid": target_uuid,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S")
        }

        rel_type = _safe_neo4j_identifier(edge.name)
        cypher = f"""
        MATCH (source:Entity {{uuid: $source_node_uuid}})
        MATCH (target:Entity {{uuid: $target_node_uuid}})
        MERGE (source)-[rel:`{rel_type}` {{
            graph_id: $graph_id,
            source_node_uuid: $source_node_uuid,
            target_node_uuid: $target_node_uuid
        }}]->(target)
        SET rel.uuid = coalesce(rel.uuid, $uuid),
            rel.name = $name,
            rel.fact = $fact,
            rel.created_at = coalesce(rel.created_at, $created_at)
        RETURN rel.uuid AS uuid
        """

        try:
            session.run(cypher, **properties)
        except Exception as e:
            logger.warning(f"写入边失败: {edge.name}, {e}")

    def _get_name_to_uuid_mapping(
        self,
        session,
        graph_id: str
    ) -> Dict[str, str]:
        """获取节点名称到UUID的映射"""
        cypher = """
        MATCH (n:Entity)
        WHERE n.graph_id = $graph_id
        RETURN n.name AS name, n.uuid AS uuid
        """
        result = session.run(cypher, graph_id=graph_id)
        return {record["name"]: record["uuid"] for record in result}

    def _update_graph_stats(
        self,
        session,
        graph_id: str,
        entities_count: int,
        edges_count: int
    ) -> None:
        """更新图谱统计信息"""
        cypher = """
        MATCH (g:_GraphMetadata {graph_id: $graph_id})
        SET g.entity_count = g.entity_count + $entities,
            g.edge_count = g.edge_count + $edges,
            g.updated_at = datetime()
        """
        session.run(cypher, graph_id=graph_id, entities=entities_count, edges=edges_count)

    def get_all_nodes(self, graph_id: str) -> List[GraphNode]:
        """
        获取图谱的所有节点

        Args:
            graph_id: 图谱ID

        Returns:
            节点列表
        """
        nodes = []

        with self.driver.session() as session:
            cypher = """
            MATCH (n:Entity)
            WHERE n.graph_id = $graph_id
            RETURN n.uuid AS uuid, n.name AS name, labels(n) AS labels,
                   n.summary AS summary, n.entity_type AS entity_type,
                   n.created_at AS created_at,
                   properties(n) AS attributes
            """
            result = session.run(cypher, graph_id=graph_id)

            for record in result:
                # 过滤掉保留的 Label
                labels = [l for l in record["labels"] if l not in ("Entity", "Node")]

                nodes.append(GraphNode(
                    uuid=record["uuid"],
                    name=record["name"],
                    labels=labels,
                    summary=record["summary"] or "",
                    attributes=record["attributes"] or {},
                    created_at=record["created_at"]
                ))

        logger.info(f"获取节点: {graph_id}, 共 {len(nodes)} 个")
        return nodes

    def get_all_edges(self, graph_id: str) -> List[GraphEdge]:
        """
        获取图谱的所有边

        Args:
            graph_id: 图谱ID

        Returns:
            边列表
        """
        edges = []

        with self.driver.session() as session:
            cypher = """
            MATCH (source)-[r]->(target)
            WHERE r.graph_id = $graph_id
            RETURN r.uuid AS uuid, type(r) AS name, r.fact AS fact,
                   coalesce(r.source_node_uuid, source.uuid) AS source_node_uuid,
                   coalesce(r.target_node_uuid, target.uuid) AS target_node_uuid,
                   r.created_at AS created_at, r.valid_at AS valid_at,
                   r.invalid_at AS invalid_at, r.expired_at AS expired_at,
                   properties(r) AS attributes
            """
            result = session.run(cypher, graph_id=graph_id)

            for record in result:
                edges.append(GraphEdge(
                    uuid=record["uuid"],
                    name=record["name"],
                    fact=record["fact"] or "",
                    source_node_uuid=record["source_node_uuid"],
                    target_node_uuid=record["target_node_uuid"],
                    attributes=record["attributes"] or {},
                    created_at=record["created_at"],
                    valid_at=record["valid_at"],
                    invalid_at=record["invalid_at"],
                    expired_at=record["expired_at"]
                ))

        logger.info(f"获取边: {graph_id}, 共 {len(edges)} 条")
        return edges

    def get_node(self, node_uuid: str) -> Optional[GraphNode]:
        """
        获取单个节点

        Args:
            node_uuid: 节点UUID

        Returns:
            节点对象或None
        """
        with self.driver.session() as session:
            cypher = """
            MATCH (n:Entity)
            WHERE n.uuid = $uuid
            RETURN n.uuid AS uuid, n.name AS name, labels(n) AS labels,
                   n.summary AS summary, n.entity_type AS entity_type,
                   n.created_at AS created_at, properties(n) AS attributes
            """
            result = session.run(cypher, uuid=node_uuid)
            record = result.single()

            if not record:
                return None

            labels = [l for l in record["labels"] if l not in ("Entity", "Node")]

            return GraphNode(
                uuid=record["uuid"],
                name=record["name"],
                labels=labels,
                summary=record["summary"] or "",
                attributes=record["attributes"] or {},
                created_at=record["created_at"]
            )

    def get_node_edges(self, node_uuid: str) -> List[GraphEdge]:
        """
        获取指定节点的所有相关边

        Args:
            node_uuid: 节点UUID

        Returns:
            边列表
        """
        edges = []

        with self.driver.session() as session:
            cypher = """
            MATCH (source)-[r]->(target)
            WHERE r.source_node_uuid = $uuid OR r.target_node_uuid = $uuid
               OR source.uuid = $uuid OR target.uuid = $uuid
            RETURN r.uuid AS uuid, type(r) AS name, r.fact AS fact,
                   coalesce(r.source_node_uuid, source.uuid) AS source_node_uuid,
                   coalesce(r.target_node_uuid, target.uuid) AS target_node_uuid,
                   r.created_at AS created_at, properties(r) AS attributes
            """
            result = session.run(cypher, uuid=node_uuid)

            for record in result:
                edges.append(GraphEdge(
                    uuid=record["uuid"],
                    name=record["name"],
                    fact=record["fact"] or "",
                    source_node_uuid=record["source_node_uuid"],
                    target_node_uuid=record["target_node_uuid"],
                    attributes=record["attributes"] or {},
                    created_at=record["created_at"]
                ))

        return edges

    def search(
        self,
        graph_id: str,
        query: str,
        limit: int = 10,
        scope: str = "edges"
    ) -> SearchResult:
        """
        图谱搜索

        使用 Neo4j 的全文索引或标签/属性搜索

        Args:
            graph_id: 图谱ID
            query: 搜索查询
            limit: 返回结果数量
            scope: 搜索范围 ("edges" / "nodes" / "both")

        Returns:
            SearchResult: 搜索结果
        """
        facts = []
        edges_result = []
        nodes_result = []

        with self.driver.session() as session:
            if scope in ("edges", "both"):
                # 搜索边（通过 fact 属性）
                edge_cypher = """
                MATCH (source)-[r]->(target)
                WHERE r.graph_id = $graph_id
                    AND (r.fact CONTAINS $query OR r.name CONTAINS $query)
                RETURN r.uuid AS uuid, type(r) AS name, r.fact AS fact,
                       coalesce(r.source_node_uuid, source.uuid) AS source_node_uuid,
                       coalesce(r.target_node_uuid, target.uuid) AS target_node_uuid,
                       source.name AS source_name, target.name AS target_name,
                       properties(r) AS attributes
                LIMIT $limit
                """
                result = session.run(edge_cypher, graph_id=graph_id, query=query, limit=limit)

                for record in result:
                    if record["fact"]:
                        facts.append(record["fact"])
                    edges_result.append({
                        "uuid": record["uuid"],
                        "name": record["name"],
                        "fact": record["fact"],
                        "source_node_uuid": record["source_node_uuid"],
                        "target_node_uuid": record["target_node_uuid"],
                    })

            if scope in ("nodes", "both"):
                # 搜索节点
                node_cypher = """
                MATCH (n:Entity)
                WHERE n.graph_id = $graph_id
                    AND (n.name CONTAINS $query OR n.summary CONTAINS $query)
                RETURN n.uuid AS uuid, n.name AS name, labels(n) AS labels,
                       n.summary AS summary, n.entity_type AS entity_type,
                       properties(n) AS attributes
                LIMIT $limit
                """
                result = session.run(node_cypher, graph_id=graph_id, query=query, limit=limit)

                for record in result:
                    labels = [l for l in record["labels"] if l not in ("Entity", "Node")]
                    if record["summary"]:
                        facts.append(f"[{record['name']}]: {record['summary']}")
                    nodes_result.append({
                        "uuid": record["uuid"],
                        "name": record["name"],
                        "labels": labels,
                        "summary": record["summary"],
                    })

        return SearchResult(
            facts=facts,
            edges=edges_result,
            nodes=nodes_result,
            query=query,
            total_count=len(facts)
        )

    def add_activities(
        self,
        graph_id: str,
        activities: List[str]
    ) -> None:
        """
        添加活动记录到图谱

        将活动文本作为新的文本块处理，提取实体和关系

        Args:
            graph_id: 图谱ID
            activities: 活动描述文本列表
        """
        # 将活动文本当作新的文本块，使用 LLM 提取
        ontology = self._build_ontology_for_extraction(graph_id)

        # 并行提取
        entities, edges = self.extractor.extract_from_chunks(
            chunks=activities,
            ontology=ontology,
            graph_id=graph_id,
            parallel_workers=1  # 活动添加通常较小，单线程即可
        )

        # 写入 Neo4j
        self._write_extracted_data(graph_id, entities, edges)

        logger.info(f"添加活动: {graph_id}, {len(activities)} 条")

    def _wait_for_episodes(
        self,
        episode_uuids: List[str],
        progress_callback: Optional[Callable] = None,
        timeout: int = 600
    ) -> None:
        """
        Neo4j 写入是同步完成的；保留该方法以兼容原 Zep 构建流程。
        """
        if progress_callback:
            progress_callback("Neo4j 图谱写入已完成", 1.0)

    def get_graph_data(self, graph_id: str) -> Dict[str, Any]:
        """
        获取完整图谱数据，返回格式与 GraphBuilderService 保持一致。
        """
        nodes = self.get_all_nodes(graph_id)

        with self.driver.session() as session:
            cypher = """
            MATCH (source)-[r]->(target)
            WHERE r.graph_id = $graph_id
            RETURN r.uuid AS uuid, type(r) AS name, r.fact AS fact,
                   coalesce(r.source_node_uuid, source.uuid) AS source_node_uuid,
                   coalesce(r.target_node_uuid, target.uuid) AS target_node_uuid,
                   source.name AS source_node_name,
                   target.name AS target_node_name,
                   r.created_at AS created_at,
                   r.valid_at AS valid_at,
                   r.invalid_at AS invalid_at,
                   r.expired_at AS expired_at,
                   properties(r) AS attributes
            """
            edge_records = list(session.run(cypher, graph_id=graph_id))

        nodes_data = [
            {
                "uuid": node.uuid,
                "name": node.name,
                "labels": node.labels,
                "summary": node.summary,
                "attributes": node.attributes,
                "created_at": str(node.created_at) if node.created_at else None,
            }
            for node in nodes
        ]

        edges_data = []
        for record in edge_records:
            created_at = record["created_at"]
            valid_at = record["valid_at"]
            invalid_at = record["invalid_at"]
            expired_at = record["expired_at"]
            edge_name = record["name"] or ""

            edges_data.append({
                "uuid": record["uuid"],
                "name": edge_name,
                "fact": record["fact"] or "",
                "fact_type": edge_name,
                "source_node_uuid": record["source_node_uuid"],
                "target_node_uuid": record["target_node_uuid"],
                "source_node_name": record["source_node_name"] or "",
                "target_node_name": record["target_node_name"] or "",
                "attributes": record["attributes"] or {},
                "created_at": str(created_at) if created_at else None,
                "valid_at": str(valid_at) if valid_at else None,
                "invalid_at": str(invalid_at) if invalid_at else None,
                "expired_at": str(expired_at) if expired_at else None,
                "episodes": [],
            })

        return {
            "graph_id": graph_id,
            "nodes": nodes_data,
            "edges": edges_data,
            "node_count": len(nodes_data),
            "edge_count": len(edges_data),
        }

    def delete_graph(self, graph_id: str) -> None:
        """
        删除图谱

        Args:
            graph_id: 图谱ID
        """
        self.schema_manager.drop_graph_data(graph_id)
        logger.info(f"删除图谱: {graph_id}")

    def health_check(self) -> bool:
        """
        健康检查

        Returns:
            True 如果连接正常
        """
        try:
            with self.driver.session() as session:
                result = session.run("RETURN 1 AS test")
                result.single()
            return True
        except Exception as e:
            logger.error(f"Neo4j 健康检查失败: {e}")
            return False


class Neo4jAsyncGraphBuilder(Neo4jGraphBuilder):
    """
    Neo4j 异步图谱构建器

    支持异步操作，适用于大规模图谱构建
    """

    async def build_graph_async(
        self,
        text: str,
        ontology: Dict[str, Any],
        graph_name: str = "MiroFish Graph",
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        batch_size: int = 3
    ) -> str:
        """
        异步构建图谱

        Args:
            text: 输入文本
            ontology: 本体定义
            graph_name: 图谱名称
            chunk_size: 文本块大小
            chunk_overlap: 块重叠大小
            batch_size: LLM 并行处理数

        Returns:
            task_id: 任务ID
        """
        from ...utils.text_processor import TextProcessor

        # 创建任务
        task_id = self.task_manager.create_task(
            task_type="neo4j_graph_build",
            metadata={
                "graph_name": graph_name,
                "chunk_size": chunk_size,
                "text_length": len(text),
            }
        )

        # 在后台线程执行
        thread = threading.Thread(
            target=self._build_graph_worker,
            args=(
                task_id, text, ontology, graph_name,
                chunk_size, chunk_overlap, batch_size,
                get_locale()
            )
        )
        thread.daemon = True
        thread.start()

        return task_id

    def _build_graph_worker(
        self,
        task_id: str,
        text: str,
        ontology: Dict[str, Any],
        graph_name: str,
        chunk_size: int,
        chunk_overlap: int,
        batch_size: int,
        locale: str
    ):
        """图谱构建工作线程"""
        set_locale(locale)
        try:
            self.task_manager.update_task(
                task_id,
                status=TaskStatus.PROCESSING,
                progress=5,
                message=t('progress.startBuildingGraph')
            )

            # 1. 创建图谱
            graph_id = self.create_graph(graph_name)
            self.task_manager.update_task(
                task_id,
                progress=10,
                message=t('progress.graphCreated', graphId=graph_id)
            )

            # 2. 设置本体
            self.set_ontology(
                graph_id,
                ontology.get("entity_types", []),
                ontology.get("edge_types", [])
            )
            self.task_manager.update_task(
                task_id,
                progress=15,
                message=t('progress.ontologySet')
            )

            # 3. 文本分块
            from ...utils.text_processor import TextProcessor
            chunks = TextProcessor.split_text(text, chunk_size, chunk_overlap)
            total_chunks = len(chunks)
            self.task_manager.update_task(
                task_id,
                progress=20,
                message=t('progress.textSplit', count=total_chunks)
            )

            # 4. 提取并写入
            self.task_manager.update_task(
                task_id,
                progress=30,
                message=t('progress.extractingEntities')
            )

            # 定义进度回调
            def progress_callback(msg: str, prog: float):
                self.task_manager.update_task(
                    task_id,
                    progress=30 + int(prog * 50),  # 30-80%
                    message=msg
                )

            self.add_text_batches(
                graph_id, chunks, batch_size, progress_callback
            )

            # 5. 完成
            self.task_manager.update_task(
                task_id,
                progress=95,
                message=t('progress.fetchingGraphInfo')
            )

            graph_info = self._get_graph_info(graph_id)

            self.task_manager.complete_task(task_id, {
                "graph_id": graph_id,
                "graph_info": graph_info.to_dict(),
                "chunks_processed": total_chunks,
            })

        except Exception as e:
            import traceback
            error_msg = f"{str(e)}\n{traceback.format_exc()}"
            self.task_manager.fail_task(task_id, error_msg)

    def _get_graph_info(self, graph_id: str) -> GraphInfo:
        """获取图谱信息"""
        stats = self.schema_manager.get_graph_stats(graph_id)

        entity_types = list(stats.get("entity_types", {}).keys())

        return GraphInfo(
            graph_id=graph_id,
            node_count=stats.get("node_count", 0),
            edge_count=stats.get("edge_count", 0),
            entity_types=entity_types
        )
