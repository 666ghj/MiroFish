"""
LLM 文本提取 Pipeline
使用 LLM 将文本转换为结构化的实体和关系
替代 Zep Cloud 的 add_batch() 自动提取功能
"""

import json
import time
import uuid
from typing import Dict, Any, List, Optional, Callable, Tuple
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed

from ...config import Config
from ...utils.llm_client import LLMClient
from ...utils.logger import get_logger

logger = get_logger('mirofish.llm_extractor')


@dataclass
class ExtractedEntity:
    """提取的实体"""
    name: str
    entity_type: str  # e.g., "Student", "Person"
    summary: str = ""
    attributes: Dict[str, Any] = field(default_factory=dict)
    source_chunk: str = ""  # 来源文本块


@dataclass
class ExtractedEdge:
    """提取的关系"""
    name: str  # e.g., "STUDIES_AT", "COMMENTS_ON"
    source_name: str  # 源实体名称
    target_name: str  # 目标实体名称
    fact: str = ""  # 事实描述
    source_type: str = ""  # 源实体类型
    target_type: str = ""  # 目标实体类型
    attributes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtractionResult:
    """提取结果"""
    entities: List[ExtractedEntity]
    edges: List[ExtractedEdge]
    chunk_index: int = 0
    chunk_text: str = ""
    error: Optional[str] = None

    def is_valid(self) -> bool:
        return len(self.entities) > 0 or len(self.edges) > 0


class LLMExtractionPipeline:
    """
    LLM 文本提取 Pipeline

    将非结构化文本通过 LLM 提取为结构化的实体和关系，
    适配 Neo4j 的节点和边格式。
    """

    # 每次 LLM 调用提取的实体/关系数量限制
    MAX_ENTITIES_PER_CALL = 15
    MAX_EDGES_PER_CALL = 10

    # 并行处理配置
    DEFAULT_PARALLEL_WORKERS = 3

    def __init__(self, llm_client: Optional[LLMClient] = None):
        """
        初始化提取 Pipeline

        Args:
            llm_client: LLM 客户端（可选，默认创建新实例）
        """
        self._llm_client = llm_client

    @property
    def llm(self) -> LLMClient:
        """延迟初始化 LLM 客户端"""
        if self._llm_client is None:
            self._llm_client = LLMClient()
        return self._llm_client

    def extract_from_chunks(
        self,
        chunks: List[str],
        ontology: Dict[str, Any],
        graph_id: str,
        progress_callback: Optional[Callable] = None,
        parallel_workers: int = None
    ) -> Tuple[List[ExtractedEntity], List[ExtractedEdge]]:
        """
        从多个文本块中提取实体和关系

        Args:
            chunks: 文本块列表
            ontology: 本体定义（包含 entity_types 和 edge_types）
            graph_id: 图谱ID（用于日志）
            progress_callback: 进度回调
            parallel_workers: 并行工作线程数

        Returns:
            (所有实体列表, 所有边列表)
        """
        parallel_workers = parallel_workers or self.DEFAULT_PARALLEL_WORKERS
        entity_types = ontology.get("entity_types", [])
        edge_types = ontology.get("edge_types", [])

        # 构建类型名称列表
        entity_type_names = [e["name"] for e in entity_types]
        edge_type_names = [e["name"] for e in edge_types]

        all_entities = []
        all_edges = []
        total_chunks = len(chunks)

        logger.info(f"开始 LLM 提取: {total_chunks} 个文本块, 并行数: {parallel_workers}")

        # 使用线程池并行处理
        with ThreadPoolExecutor(max_workers=parallel_workers) as executor:
            futures = {}

            for idx, chunk in enumerate(chunks):
                future = executor.submit(
                    self._extract_single_chunk,
                    chunk=chunk,
                    chunk_index=idx,
                    entity_type_names=entity_type_names,
                    edge_type_names=edge_type_names,
                    entity_types=entity_types,
                    edge_types=edge_types
                )
                futures[future] = idx

            completed = 0
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    result = future.result()
                    if result.is_valid():
                        all_entities.extend(result.entities)
                        all_edges.extend(result.edges)
                    completed += 1

                    if progress_callback:
                        progress = completed / total_chunks
                        progress_callback(
                            f"已处理 {completed}/{total_chunks} 个文本块",
                            progress
                        )

                except Exception as e:
                    logger.error(f"处理文本块 {idx} 失败: {e}")
                    completed += 1

        # 去重处理
        all_entities = self._deduplicate_entities(all_entities)
        all_edges = self._deduplicate_edges(all_edges)

        logger.info(f"LLM 提取完成: {len(all_entities)} 个实体, {len(all_edges)} 条边")

        return all_entities, all_edges

    def _extract_single_chunk(
        self,
        chunk: str,
        chunk_index: int,
        entity_type_names: List[str],
        edge_type_names: List[str],
        entity_types: List[Dict],
        edge_types: List[Dict]
    ) -> ExtractionResult:
        """
        从单个文本块提取实体和关系
        """
        try:
            result = self._call_llm_extraction(
                chunk=chunk,
                entity_type_names=entity_type_names,
                edge_type_names=edge_type_names
            )

            # 补充来源信息
            for entity in result.get("entities", []):
                entity["source_chunk"] = chunk[:200]  # 保留前200字符作为来源

            return ExtractionResult(
                entities=[
                    ExtractedEntity(
                        name=e.get("name", ""),
                        entity_type=e.get("entity_type", ""),
                        summary=e.get("summary", ""),
                        attributes=e.get("attributes", {}),
                        source_chunk=chunk[:200]
                    )
                    for e in result.get("entities", [])
                    if e.get("name") and e.get("entity_type")
                ],
                edges=[
                    ExtractedEdge(
                        name=e.get("name", ""),
                        source_name=e.get("source_name", ""),
                        target_name=e.get("target_name", ""),
                        fact=e.get("fact", ""),
                        source_type=e.get("source_type", ""),
                        target_type=e.get("target_type", ""),
                        attributes=e.get("attributes", {})
                    )
                    for e in result.get("edges", [])
                    if e.get("name") and e.get("source_name") and e.get("target_name")
                ],
                chunk_index=chunk_index,
                chunk_text=chunk
            )

        except Exception as e:
            logger.error(f"LLM 提取失败 (chunk {chunk_index}): {e}")
            return ExtractionResult(
                entities=[],
                edges=[],
                chunk_index=chunk_index,
                chunk_text=chunk,
                error=str(e)
            )

    def _call_llm_extraction(
        self,
        chunk: str,
        entity_type_names: List[str],
        edge_type_names: List[str]
    ) -> Dict[str, Any]:
        """
        调用 LLM 提取实体和关系
        """
        system_prompt = f"""你是一个专业的知识图谱提取专家。你的任务是从给定的文本中提取实体和关系。

实体类型（必须严格使用这些类型）:
{json.dumps(entity_type_names, ensure_ascii=False)}

关系类型（必须严格使用这些类型）:
{json.dumps(edge_type_names, ensure_ascii=False)}

提取规则：
1. 实体：只提取符合预定义类型之一的实体
2. 关系：只提取符合预定义关系类型之一的关系
3. 每个实体需要有 name（名称）和 entity_type（类型）
4. 每个关系需要有 name（关系类型）、source_name（源实体名）、target_name（目标实体名）
5. 实体描述（summary）应简洁明了，50字以内
6. 关系事实（fact）应描述性的句子，说明 source 和 target 之间的关系

返回JSON格式：
{{
    "entities": [
        {{"name": "实体名", "entity_type": "类型", "summary": "描述"}}
    ],
    "edges": [
        {{"name": "关系类型", "source_name": "源实体", "target_name": "目标实体", "fact": "事实描述"}}
    ]
}}

只返回有效的实体和关系，不要编造内容。"""

        user_prompt = f"""请从以下文本中提取实体和关系：

{chunk}

只返回JSON格式的结果，不要包含其他内容。"""

        try:
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1,  # 低温度保证一致性
                max_tokens=2000
            )

            # 确保返回格式正确
            return {
                "entities": response.get("entities", []),
                "edges": response.get("edges", [])
            }

        except Exception as e:
            logger.warning(f"LLM 调用失败: {e}")
            return {"entities": [], "edges": []}

    def _deduplicate_entities(
        self,
        entities: List[ExtractedEntity]
    ) -> List[ExtractedEntity]:
        """实体去重（按 name + entity_type 组合）"""
        seen = set()
        result = []

        for entity in entities:
            key = (entity.name, entity.entity_type)
            if key not in seen:
                seen.add(key)
                result.append(entity)

        return result

    def _deduplicate_edges(
        self,
        edges: List[ExtractedEdge]
    ) -> List[ExtractedEdge]:
        """边去重（按 name + source_name + target_name 组合）"""
        seen = set()
        result = []

        for edge in edges:
            key = (edge.name, edge.source_name, edge.target_name)
            if key not in seen:
                seen.add(key)
                result.append(edge)

        return result


class LLMEntityEnricher:
    """
    LLM 实体增强器

    用于在生成 Agent Profile 时，对单个实体进行深度检索和上下文丰富。
    这个功能替代了 Zep 的 entity enrichment 能力。
    """

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self._llm_client = llm_client

    @property
    def llm(self) -> LLMClient:
        if self._llm_client is None:
            self._llm_client = LLMClient()
        return self._llm_client

    def enrich_entity(
        self,
        entity_name: str,
        entity_type: str,
        related_facts: List[str],
        related_nodes: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        增强单个实体的上下文信息

        Args:
            entity_name: 实体名称
            entity_type: 实体类型
            related_facts: 相关事实列表
            related_nodes: 相关节点列表

        Returns:
            增强后的实体信息，包含更丰富的上下文描述
        """
        facts_text = "\n".join([f"- {f}" for f in related_facts[:10]]) if related_facts else "无相关事实"
        nodes_text = "\n".join([
            f"- {n.get('name', '未知')} ({n.get('type', '未知')})"
            for n in related_nodes[:5]
        ]) if related_nodes else "无关联实体"

        system_prompt = """你是一个角色设定专家。根据给定的实体信息和关联内容，为该实体生成一个丰富的人设描述。

要求：
1. 结合实体的基本信息和关联内容，生成符合社交媒体场景的人设描述
2. 人设描述应该包含：基本信息、性格特点、可能的立场观点、社交媒体行为特征
3. 如果实体是人物类型，应包含 MBTI 性格、年龄范围、国家/地区等
4. 如果实体是组织类型，应包含组织性质、规模、立场等
5. 描述应简洁但有信息量，总长度200-500字
6. 只基于提供的信息生成，不要编造额外细节"""

        user_prompt = f"""实体信息：
- 名称：{entity_name}
- 类型：{entity_type}

相关事实：
{facts_text}

关联实体：
{nodes_text}

请生成该实体的人设描述，包含性格特点、可能观点、行为特征等。"""

        try:
            description = self.llm.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.5,
                max_tokens=500
            )

            return {
                "name": entity_name,
                "entity_type": entity_type,
                "enriched_description": description,
                "related_facts_count": len(related_facts),
                "related_nodes_count": len(related_nodes)
            }

        except Exception as e:
            logger.warning(f"实体增强失败 {entity_name}: {e}")
            return {
                "name": entity_name,
                "entity_type": entity_type,
                "enriched_description": "",
                "related_facts_count": len(related_facts),
                "related_nodes_count": len(related_nodes),
                "error": str(e)
            }
