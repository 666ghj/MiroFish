"""
Neo4j 检索工具服务
封装图谱搜索、节点读取、边查询等工具，供 Report Agent 使用
替代 ZepToolsService
"""

import json
import re
import time
from typing import Dict, Any, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from neo4j import Driver

from .graph_adapter import SearchResult
from .neo4j_entity_reader import Neo4jEntityReader, EntityNode
from ...utils.llm_client import LLMClient
from ...utils.logger import get_logger
from ...utils.locale import get_locale

logger = get_logger('mirofish.neo4j_search')


class NodeInfo:
    """节点信息"""
    uuid: str
    name: str
    labels: List[str]
    summary: str
    attributes: Dict[str, Any]

    def __init__(
        self,
        uuid: str,
        name: str,
        labels: List[str],
        summary: str,
        attributes: Dict[str, Any]
    ):
        self.uuid = uuid
        self.name = name
        self.labels = labels
        self.summary = summary
        self.attributes = attributes

    def to_dict(self) -> Dict[str, Any]:
        return {
            "uuid": self.uuid,
            "name": self.name,
            "labels": self.labels,
            "summary": self.summary,
            "attributes": self.attributes
        }

    def to_text(self) -> str:
        entity_type = next(
            (l for l in self.labels if l not in ("Entity", "Node")),
            "未知类型"
        )
        return f"实体: {self.name} (类型: {entity_type})\n摘要: {self.summary}"


class EdgeInfo:
    """边信息"""
    uuid: str
    name: str
    fact: str
    source_node_uuid: str
    target_node_uuid: str
    source_node_name: Optional[str] = None
    target_node_name: Optional[str] = None
    created_at: Optional[str] = None
    valid_at: Optional[str] = None
    invalid_at: Optional[str] = None
    expired_at: Optional[str] = None

    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "uuid": self.uuid,
            "name": self.name,
            "fact": self.fact,
            "source_node_uuid": self.source_node_uuid,
            "target_node_uuid": self.target_node_uuid,
            "source_node_name": self.source_node_name,
            "target_node_name": self.target_node_name,
            "created_at": self.created_at,
            "valid_at": self.valid_at,
            "invalid_at": self.invalid_at,
            "expired_at": self.expired_at
        }

    def to_text(self, include_temporal: bool = False) -> str:
        source = self.source_node_name or self.source_node_uuid[:8]
        target = self.target_node_name or self.target_node_uuid[:8]
        base_text = f"关系: {source} --[{self.name}]--> {target}\n事实: {self.fact}"

        if include_temporal:
            valid_at = self.valid_at or "未知"
            invalid_at = self.invalid_at or "至今"
            base_text += f"\n时效: {valid_at} - {invalid_at}"
            if self.expired_at:
                base_text += f" (已过期: {self.expired_at})"

        return base_text

    @property
    def is_expired(self) -> bool:
        return self.expired_at is not None

    @property
    def is_invalid(self) -> bool:
        return self.invalid_at is not None


class Neo4jSearchService:
    """
    Neo4j 检索工具服务

    提供图谱搜索、节点查询、边查询等功能，
    适配 Report Agent 的工具调用需求。
    """

    MAX_RETRIES = 3
    RETRY_DELAY = 2.0
    STOPWORDS = {
        "的", "了", "和", "与", "及", "或", "在", "对", "中", "为", "是",
        "分析", "结果", "预测", "模拟", "引擎", "机制", "方法", "能力",
        "the", "and", "or", "of", "for", "to", "in", "on", "with",
    }

    def __init__(
        self,
        driver: 'Driver' = None,
        llm_client: Optional[LLMClient] = None
    ):
        """
        初始化检索服务

        Args:
            driver: Neo4j 驱动
            llm_client: LLM 客户端（用于 InsightForge 等需要 LLM 的功能）
        """
        from ...utils.neo4j.driver import get_neo4j_driver

        self.driver = driver or get_neo4j_driver()
        self.entity_reader = Neo4jEntityReader(driver=self.driver)
        self._llm_client = llm_client

    @property
    def llm(self) -> LLMClient:
        """延迟初始化 LLM 客户端"""
        if self._llm_client is None:
            self._llm_client = LLMClient()
        return self._llm_client

    def _call_with_retry(self, func, operation_name: str, max_retries: int = None):
        """带重试机制的查询"""
        max_retries = max_retries or self.MAX_RETRIES
        last_exception = None
        delay = self.RETRY_DELAY

        for attempt in range(max_retries):
            try:
                return func()
            except Exception as e:
                last_exception = e
                if attempt < max_retries - 1:
                    logger.warning(
                        f"Neo4j {operation_name} 第 {attempt + 1} 次尝试失败: "
                        f"{str(e)[:100]}, {delay:.1f}秒后重试..."
                    )
                    time.sleep(delay)
                    delay *= 2
                else:
                    logger.error(
                        f"Neo4j {operation_name} 在 {max_retries} 次尝试后仍失败: {str(e)}"
                    )

        raise last_exception

    def _extract_search_terms(self, query: str) -> List[str]:
        """Split an LLM-style long query into useful searchable terms."""
        raw_terms = re.findall(r"[A-Za-z0-9_.+-]+|[\u4e00-\u9fff]{2,}", query or "")
        terms: List[str] = []
        for term in raw_terms:
            normalized = term.strip()
            if not normalized:
                continue
            lower = normalized.lower()
            if lower in self.STOPWORDS or len(normalized) < 2:
                continue
            terms.append(normalized)

        # Add short Chinese fragments for long concatenated phrases.
        for term in list(terms):
            if re.fullmatch(r"[\u4e00-\u9fff]{3,}", term):
                for size in (2, 3, 4):
                    for index in range(0, len(term) - size + 1):
                        fragment = term[index:index + size]
                        if fragment not in self.STOPWORDS:
                            terms.append(fragment)

        deduped: List[str] = []
        seen = set()
        for term in terms:
            key = term.lower()
            if key not in seen:
                seen.add(key)
                deduped.append(term)
        return deduped[:40]

    def search_graph(
        self,
        graph_id: str,
        query: str,
        limit: int = 10,
        scope: str = "edges"
    ) -> SearchResult:
        """
        图谱语义搜索

        Args:
            graph_id: 图谱ID
            query: 搜索查询
            limit: 返回结果数量
            scope: 搜索范围 ("edges" / "nodes" / "both")

        Returns:
            SearchResult: 搜索结果
        """
        logger.info(f"搜索图谱 {graph_id}: query={query[:50]}")

        facts = []
        edges_result = []
        nodes_result = []
        terms = self._extract_search_terms(query)

        with self.driver.session() as session:
            if scope in ("edges", "both"):
                # 搜索边
                edge_cypher = """
                MATCH (source)-[r]->(target)
                WHERE r.graph_id = $graph_id
                    AND (
                        toLower(coalesce(r.fact, '')) CONTAINS toLower($search_query)
                        OR toLower(coalesce(r.name, '')) CONTAINS toLower($search_query)
                        OR any(term IN $terms WHERE
                            toLower(coalesce(r.fact, '')) CONTAINS toLower(term)
                            OR toLower(coalesce(r.name, '')) CONTAINS toLower(term)
                            OR toLower(coalesce(source.name, '')) CONTAINS toLower(term)
                            OR toLower(coalesce(target.name, '')) CONTAINS toLower(term)
                        )
                    )
                RETURN r.uuid AS uuid, type(r) AS name, r.fact AS fact,
                       coalesce(r.source_node_uuid, source.uuid) AS source_node_uuid,
                       coalesce(r.target_node_uuid, target.uuid) AS target_node_uuid,
                       source.name AS source_name, target.name AS target_name,
                       properties(r) AS attributes,
                       reduce(score = 0, term IN $terms |
                           score
                           + CASE WHEN toLower(coalesce(r.fact, '')) CONTAINS toLower(term) THEN 10 ELSE 0 END
                           + CASE WHEN toLower(coalesce(r.name, '')) CONTAINS toLower(term) THEN 5 ELSE 0 END
                           + CASE WHEN toLower(coalesce(source.name, '')) CONTAINS toLower(term) THEN 3 ELSE 0 END
                           + CASE WHEN toLower(coalesce(target.name, '')) CONTAINS toLower(term) THEN 3 ELSE 0 END
                       ) AS score
                ORDER BY score DESC
                LIMIT $limit
                """
                result = session.run(
                    edge_cypher,
                    graph_id=graph_id,
                    search_query=query,
                    terms=terms,
                    limit=limit
                )

                for record in result:
                    if record["fact"]:
                        facts.append(record["fact"])
                    edges_result.append({
                        "uuid": record["uuid"],
                        "name": record["name"],
                        "fact": record["fact"],
                        "source_node_uuid": record["source_node_uuid"],
                        "target_node_uuid": record["target_node_uuid"],
                        "source_name": record["source_name"],
                        "target_name": record["target_name"],
                    })

            if scope in ("nodes", "both"):
                # 搜索节点
                node_cypher = """
                MATCH (n:Entity)
                WHERE n.graph_id = $graph_id
                    AND (
                        toLower(coalesce(n.name, '')) CONTAINS toLower($search_query)
                        OR toLower(coalesce(n.summary, '')) CONTAINS toLower($search_query)
                        OR any(term IN $terms WHERE
                            toLower(coalesce(n.name, '')) CONTAINS toLower(term)
                            OR toLower(coalesce(n.summary, '')) CONTAINS toLower(term)
                            OR toLower(coalesce(n.entity_type, '')) CONTAINS toLower(term)
                        )
                    )
                RETURN n.uuid AS uuid, n.name AS name, labels(n) AS labels,
                       n.summary AS summary, n.entity_type AS entity_type,
                       properties(n) AS attributes,
                       reduce(score = 0, term IN $terms |
                           score
                           + CASE WHEN toLower(coalesce(n.name, '')) CONTAINS toLower(term) THEN 10 ELSE 0 END
                           + CASE WHEN toLower(coalesce(n.summary, '')) CONTAINS toLower(term) THEN 6 ELSE 0 END
                           + CASE WHEN toLower(coalesce(n.entity_type, '')) CONTAINS toLower(term) THEN 3 ELSE 0 END
                       ) AS score
                ORDER BY score DESC
                LIMIT $limit
                """
                result = session.run(
                    node_cypher,
                    graph_id=graph_id,
                    search_query=query,
                    terms=terms,
                    limit=limit
                )

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

            if not facts and not edges_result and not nodes_result:
                fallback_cypher = """
                MATCH (n:Entity)
                WHERE n.graph_id = $graph_id AND coalesce(n.summary, '') <> ''
                RETURN n.uuid AS uuid, n.name AS name, labels(n) AS labels,
                       n.summary AS summary, properties(n) AS attributes
                LIMIT $limit
                """
                result = session.run(fallback_cypher, graph_id=graph_id, limit=limit)
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

        logger.info(f"搜索完成: {len(facts)} 条相关结果")

        return SearchResult(
            facts=facts,
            edges=edges_result,
            nodes=nodes_result,
            query=query,
            total_count=len(facts) or (len(edges_result) + len(nodes_result))
        )

    def get_all_nodes(self, graph_id: str) -> List[NodeInfo]:
        """
        获取图谱的所有节点

        Args:
            graph_id: 图谱ID

        Returns:
            节点列表
        """
        logger.info(f"获取图谱 {graph_id} 的所有节点")

        def _query():
            nodes = []
            with self.driver.session() as session:
                cypher = """
                MATCH (n:Entity)
                WHERE n.graph_id = $graph_id
                RETURN n.uuid AS uuid, n.name AS name, labels(n) AS labels,
                       n.summary AS summary, properties(n) AS attributes
                """
                result = session.run(cypher, graph_id=graph_id)
                for record in result:
                    nodes.append(NodeInfo(
                        uuid=record["uuid"],
                        name=record["name"],
                        labels=record["labels"],
                        summary=record["summary"] or "",
                        attributes=record["attributes"] or {}
                    ))
            return nodes

        return self._call_with_retry(_query, f"获取所有节点({graph_id})")

    def get_all_edges(self, graph_id: str, include_temporal: bool = True) -> List[EdgeInfo]:
        """
        获取图谱的所有边

        Args:
            graph_id: 图谱ID
            include_temporal: 是否包含时间信息

        Returns:
            边列表
        """
        logger.info(f"获取图谱 {graph_id} 的所有边")

        def _query():
            edges = []
            with self.driver.session() as session:
                cypher = """
                MATCH (source)-[r]->(target)
                WHERE r.graph_id = $graph_id
                RETURN r.uuid AS uuid, type(r) AS name, r.fact AS fact,
                       coalesce(r.source_node_uuid, source.uuid) AS source_node_uuid,
                       coalesce(r.target_node_uuid, target.uuid) AS target_node_uuid,
                       source.name AS source_node_name,
                       target.name AS target_node_name,
                       properties(r) AS attributes
                """
                result = session.run(cypher, graph_id=graph_id)
                for record in result:
                    attributes = record["attributes"] or {}
                    edges.append(EdgeInfo(
                        uuid=record["uuid"],
                        name=record["name"],
                        fact=record["fact"] or "",
                        source_node_uuid=record["source_node_uuid"],
                        target_node_uuid=record["target_node_uuid"],
                        source_node_name=record.get("source_node_name"),
                        target_node_name=record.get("target_node_name"),
                        created_at=str(attributes.get("created_at")) if attributes.get("created_at") else None,
                        valid_at=str(attributes.get("valid_at")) if attributes.get("valid_at") else None,
                        invalid_at=str(attributes.get("invalid_at")) if attributes.get("invalid_at") else None,
                        expired_at=str(attributes.get("expired_at")) if attributes.get("expired_at") else None,
                        attributes=attributes
                    ))
            return edges

        return self._call_with_retry(_query, f"获取所有边({graph_id})")

    def get_node_detail(self, node_uuid: str) -> Optional[NodeInfo]:
        """
        获取单个节点的详细信息

        Args:
            node_uuid: 节点UUID

        Returns:
            节点信息或 None
        """
        def _query():
            with self.driver.session() as session:
                cypher = """
                MATCH (n:Entity)
                WHERE n.uuid = $uuid
                RETURN n.uuid AS uuid, n.name AS name, labels(n) AS labels,
                       n.summary AS summary, properties(n) AS attributes
                """
                result = session.run(cypher, uuid=node_uuid)
                record = result.single()

                if not record:
                    return None

                return NodeInfo(
                    uuid=record["uuid"],
                    name=record["name"],
                    labels=record["labels"],
                    summary=record["summary"] or "",
                    attributes=record["attributes"] or {}
                )

        try:
            return self._call_with_retry(_query, f"获取节点详情({node_uuid[:8]}...)")
        except Exception as e:
            logger.error(f"获取节点详情失败: {e}")
            return None

    def get_node_edges(self, graph_id: str, node_uuid: str) -> List[EdgeInfo]:
        """
        获取节点相关的所有边

        Args:
            graph_id: 图谱ID
            node_uuid: 节点UUID

        Returns:
            边列表
        """
        def _query():
            edges = []
            with self.driver.session() as session:
                cypher = """
                MATCH (source)-[r]->(target)
                WHERE (r.source_node_uuid = $uuid OR r.target_node_uuid = $uuid
                       OR source.uuid = $uuid OR target.uuid = $uuid)
                      AND r.graph_id = $graph_id
                RETURN r.uuid AS uuid, type(r) AS name, r.fact AS fact,
                       coalesce(r.source_node_uuid, source.uuid) AS source_node_uuid,
                       coalesce(r.target_node_uuid, target.uuid) AS target_node_uuid,
                       source.name AS source_node_name,
                       target.name AS target_node_name,
                       r.created_at AS created_at
                """
                result = session.run(cypher, uuid=node_uuid, graph_id=graph_id)
                for record in result:
                    edges.append(EdgeInfo(
                        uuid=record["uuid"],
                        name=record["name"],
                        fact=record["fact"] or "",
                        source_node_uuid=record["source_node_uuid"],
                        target_node_uuid=record["target_node_uuid"],
                        source_node_name=record.get("source_node_name"),
                        target_node_name=record.get("target_node_name"),
                        created_at=str(record["created_at"]) if record.get("created_at") else None,
                    ))
            return edges

        return self._call_with_retry(
            _query, f"获取节点边({node_uuid[:8]}...)"
        )

    def get_entities_by_type(
        self,
        graph_id: str,
        entity_type: str
    ) -> List[NodeInfo]:
        """
        按类型获取实体

        Args:
            graph_id: 图谱ID
            entity_type: 实体类型

        Returns:
            符合类型的实体列表
        """
        all_nodes = self.get_all_nodes(graph_id)
        filtered = [n for n in all_nodes if entity_type in n.labels]
        logger.info(f"按类型 {entity_type} 获取实体: {len(filtered)} 个")
        return filtered

    def get_entity_summary(
        self,
        graph_id: str,
        entity_name: str
    ) -> Dict[str, Any]:
        """
        获取指定实体的关系摘要

        Args:
            graph_id: 图谱ID
            entity_name: 实体名称

        Returns:
            实体摘要信息
        """
        logger.info(f"获取实体摘要: {entity_name}")

        # 搜索相关实体
        search_result = self.search_graph(
            graph_id=graph_id,
            query=entity_name,
            limit=20
        )

        # 在所有节点中查找该实体
        all_nodes = self.get_all_nodes(graph_id)
        entity_node = None
        for node in all_nodes:
            if node.name.lower() == entity_name.lower():
                entity_node = node
                break

        # 获取关联边
        related_edges = []
        if entity_node:
            related_edges = self.get_node_edges(graph_id, entity_node.uuid)

        return {
            "entity_name": entity_name,
            "entity_info": entity_node.to_dict() if entity_node else None,
            "related_facts": search_result.facts,
            "related_edges": [e.to_dict() for e in related_edges],
            "total_relations": len(related_edges)
        }

    def get_graph_statistics(self, graph_id: str) -> Dict[str, Any]:
        """
        获取图谱的统计信息

        Args:
            graph_id: 图谱ID

        Returns:
            统计信息
        """
        logger.info(f"获取图谱统计: {graph_id}")

        nodes = self.get_all_nodes(graph_id)
        edges = self.get_all_edges(graph_id)

        # 统计实体类型分布
        entity_types = {}
        for node in nodes:
            for label in node.labels:
                if label not in ("Entity", "Node"):
                    entity_types[label] = entity_types.get(label, 0) + 1

        # 统计关系类型分布
        relation_types = {}
        for edge in edges:
            relation_types[edge.name] = relation_types.get(edge.name, 0) + 1

        return {
            "graph_id": graph_id,
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "entity_types": entity_types,
            "relation_types": relation_types
        }

    def get_simulation_context(
        self,
        graph_id: str,
        simulation_requirement: str = "",
        max_facts: int = 80
    ) -> Dict[str, Any]:
        """
        构建报告生成所需的图谱上下文，兼容 ZepToolsService。
        """
        stats = self.get_graph_statistics(graph_id)
        edges = self.get_all_edges(graph_id)
        nodes = self.get_all_nodes(graph_id)

        facts = [edge.fact for edge in edges if edge.fact][:max_facts]

        return {
            "graph_id": graph_id,
            "simulation_requirement": simulation_requirement,
            "statistics": stats,
            "summary": (
                f"图谱包含 {stats.get('total_nodes', 0)} 个实体、"
                f"{stats.get('total_edges', 0)} 条关系。"
            ),
            "key_facts": facts,
            "entity_types": stats.get("entity_types", {}),
            "relation_types": stats.get("relation_types", {}),
            "sample_entities": [node.to_dict() for node in nodes[:20]],
        }

    def interview_agents(
        self,
        graph_id: str = None,
        question: str = None,
        entity_names: Optional[List[str]] = None,
        max_agents: int = 5,
        simulation_id: str = None,
        interview_requirement: str = None,
        simulation_requirement: str = "",
        custom_questions: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        报告工具兼容方法。真实采访由 simulation_runner 负责，这里提供图谱上下文降级。
        """
        question = question or interview_requirement or ""
        targets = entity_names or []
        if not targets:
            targets = [node.name for node in self.get_all_nodes(graph_id)[:max_agents]]

        responses = []
        for name in targets[:max_agents]:
            summary = self.get_entity_summary(graph_id, name)
            responses.append({
                "agent": name,
                "question": question,
                "response": summary,
                "source": "neo4j_graph_context"
            })

        return {
            "question": question,
            "responses": responses,
            "count": len(responses)
        }

    def insight_forge(
        self,
        graph_id: str,
        query: str,
        simulation_requirement: str,
        report_context: str = "",
        max_sub_queries: int = 5
    ) -> Dict[str, Any]:
        """
        深度洞察检索

        使用 LLM 将问题分解为多个子问题，然后对每个子问题进行搜索

        Args:
            graph_id: 图谱ID
            query: 用户问题
            simulation_requirement: 模拟需求描述
            report_context: 报告上下文
            max_sub_queries: 最大子问题数量

        Returns:
            深度洞察检索结果
        """
        logger.info(f"InsightForge: query={query[:50]}")

        # Step 1: 生成子问题
        sub_queries = self._generate_sub_queries(
            query=query,
            simulation_requirement=simulation_requirement,
            report_context=report_context,
            max_queries=max_sub_queries
        )

        # Step 2: 对每个子问题进行搜索
        all_facts = []
        all_edges = []
        seen_facts = set()

        for sub_query in sub_queries:
            result = self.search_graph(
                graph_id=graph_id,
                query=sub_query,
                limit=15,
                scope="both"
            )

            for fact in result.facts:
                if fact not in seen_facts:
                    all_facts.append(fact)
                    seen_facts.add(fact)

            all_edges.extend(result.edges)

        # 对原始问题也进行搜索
        main_result = self.search_graph(
            graph_id=graph_id,
            query=query,
            limit=20,
            scope="both"
        )

        for fact in main_result.facts:
            if fact not in seen_facts:
                all_facts.append(fact)
                seen_facts.add(fact)
        all_edges.extend(main_result.edges)

        if not all_facts:
            panorama = self.panorama_search(
                graph_id=graph_id,
                query=query,
                include_expired=True,
                limit=20
            )
            for fact in panorama.get("active_facts", []) + panorama.get("historical_facts", []):
                if fact not in seen_facts:
                    all_facts.append(fact)
                    seen_facts.add(fact)
            for node in panorama.get("all_nodes", [])[:20]:
                summary = node.get("summary") or ""
                name = node.get("name") or "未知实体"
                if summary:
                    fact = f"{name}: {summary}"
                    if fact not in seen_facts:
                        all_facts.append(fact)
                        seen_facts.add(fact)

        # Step 3: 获取相关实体
        entity_uuids = set()
        for edge_data in all_edges:
            if isinstance(edge_data, dict):
                entity_uuids.add(edge_data.get('source_node_uuid', ''))
                entity_uuids.add(edge_data.get('target_node_uuid', ''))

        entity_insights = []
        for uuid in entity_uuids:
            if not uuid:
                continue
            node = self.get_node_detail(uuid)
            if node:
                related_facts = [f for f in all_facts if node.name.lower() in f.lower()]
                entity_insights.append({
                    "uuid": node.uuid,
                    "name": node.name,
                    "type": next((l for l in node.labels if l not in ("Entity", "Node")), "实体"),
                    "summary": node.summary,
                    "related_facts": related_facts
                })

        # Step 4: 构建关系链
        relationship_chains = []
        node_map = {e["uuid"]: e for e in entity_insights}

        for edge_data in all_edges:
            if isinstance(edge_data, dict):
                source_uuid = edge_data.get('source_node_uuid', '')
                target_uuid = edge_data.get('target_node_uuid', '')
                relation_name = edge_data.get('name', '')

                source_name = node_map.get(source_uuid, {}).get('name', '') or source_uuid[:8]
                target_name = node_map.get(target_uuid, {}).get('name', '') or target_uuid[:8]

                chain = f"{source_name} --[{relation_name}]--> {target_name}"
                if chain not in relationship_chains:
                    relationship_chains.append(chain)

        return {
            "query": query,
            "simulation_requirement": simulation_requirement,
            "sub_queries": sub_queries,
            "semantic_facts": all_facts,
            "entity_insights": entity_insights,
            "relationship_chains": relationship_chains,
            "total_facts": len(all_facts),
            "total_entities": len(entity_insights),
            "total_relationships": len(relationship_chains)
        }

    def _generate_sub_queries(
        self,
        query: str,
        simulation_requirement: str,
        report_context: str = "",
        max_queries: int = 5
    ) -> List[str]:
        """使用 LLM 生成子问题"""
        system_prompt = """你是一个专业的问题分析专家。你的任务是将一个复杂问题分解为多个可以在模拟世界中独立观察的子问题。

要求：
1. 每个子问题应该足够具体，可以在模拟世界中找到相关的Agent行为或事件
2. 子问题应该覆盖原问题的不同维度（如：谁、什么、为什么、怎么样、何时、何地）
3. 子问题应该与模拟场景相关
4. 返回JSON格式：{"sub_queries": ["子问题1", "子问题2", ...]}"""

        user_prompt = f"""模拟需求背景：
{simulation_requirement}

{f"报告上下文：{report_context[:500]}" if report_context else ""}

请将以下问题分解为{max_queries}个子问题：
{query}

返回JSON格式的子问题列表。"""

        try:
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3
            )

            sub_queries = response.get("sub_queries", [])
            return [str(sq) for sq in sub_queries[:max_queries]]

        except Exception as e:
            logger.warning(f"生成子问题失败: {e}")
            # 降级：返回基于原问题的变体
            return [
                query,
                f"{query} 的主要参与者",
                f"{query} 的原因和影响",
                f"{query} 的发展过程"
            ][:max_queries]

    def panorama_search(
        self,
        graph_id: str,
        query: str,
        include_expired: bool = True,
        limit: int = 50
    ) -> Dict[str, Any]:
        """
        广度搜索

        获取全貌视图，包括所有相关内容和历史/过期信息

        Args:
            graph_id: 图谱ID
            query: 搜索查询
            include_expired: 是否包含过期内容
            limit: 返回结果数量限制

        Returns:
            广度搜索结果
        """
        logger.info(f"PanoramaSearch: query={query[:50]}")

        # 获取所有节点
        all_nodes = self.get_all_nodes(graph_id)
        node_map = {n.uuid: n for n in all_nodes}

        # 获取所有边
        all_edges = self.get_all_edges(graph_id, include_temporal=True)

        # 分类事实
        active_facts = []
        historical_facts = []

        for edge in all_edges:
            if not edge.fact:
                continue

            # 判断是否过期/失效
            is_historical = edge.is_expired or edge.is_invalid

            if is_historical:
                valid_at = edge.valid_at or "未知"
                invalid_at = edge.invalid_at or edge.expired_at or "未知"
                fact_with_time = f"[{valid_at} - {invalid_at}] {edge.fact}"
                historical_facts.append(fact_with_time)
            else:
                active_facts.append(edge.fact)

        # 排序并限制数量
        active_facts.sort(key=lambda x: query.lower() in x.lower(), reverse=True)
        historical_facts.sort(key=lambda x: query.lower() in x.lower(), reverse=True)

        return {
            "query": query,
            "all_nodes": [n.to_dict() for n in all_nodes],
            "all_edges": [e.to_dict() for e in all_edges],
            "active_facts": active_facts[:limit],
            "historical_facts": historical_facts[:limit] if include_expired else [],
            "total_nodes": len(all_nodes),
            "total_edges": len(all_edges),
            "active_count": len(active_facts),
            "historical_count": len(historical_facts)
        }

    def quick_search(
        self,
        graph_id: str,
        query: str,
        limit: int = 10
    ) -> SearchResult:
        """
        快速搜索

        Args:
            graph_id: 图谱ID
            query: 搜索查询
            limit: 返回结果数量

        Returns:
            搜索结果
        """
        logger.info(f"QuickSearch: query={query[:50]}")
        return self.search_graph(graph_id=graph_id, query=query, limit=limit, scope="both")
