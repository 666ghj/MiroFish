"""
Zep检索工具服务
封装图谱搜索、节点读取、边查询等工具，供Report Agent使用

核心检索工具（优化后）：
1. InsightForge（深度洞察检索）- 最强大的混合检索，自动生成子问题并多维度检索
2. PanoramaSearch（广度搜索）- 获取全貌，包括过期内容
3. QuickSearch（简单搜索）- 快速检索
"""

import time
import json
import math
import re
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field

from ..config import Config
from ..graph import get_graph_backend
from ..utils.embedding_client import EmbeddingClient
from ..utils.reranker_client import RerankerClient
from ..utils.logger import get_logger
from ..utils.llm_client import LLMClient

logger = get_logger('mirofish.zep_tools')


@dataclass
class SearchResult:
    """搜索结果"""
    facts: List[str]
    edges: List[Dict[str, Any]]
    nodes: List[Dict[str, Any]]
    query: str
    total_count: int
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "facts": self.facts,
            "edges": self.edges,
            "nodes": self.nodes,
            "query": self.query,
            "total_count": self.total_count
        }
    
    def to_text(self) -> str:
        """转换为文本格式，供LLM理解"""
        text_parts = [f"搜索查询: {self.query}", f"找到 {self.total_count} 条相关信息"]
        
        if self.facts:
            text_parts.append("\n### 相关事实:")
            for i, fact in enumerate(self.facts, 1):
                text_parts.append(f"{i}. {fact}")
        
        return "\n".join(text_parts)


@dataclass
class NodeInfo:
    """节点信息"""
    uuid: str
    name: str
    labels: List[str]
    summary: str
    attributes: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "uuid": self.uuid,
            "name": self.name,
            "labels": self.labels,
            "summary": self.summary,
            "attributes": self.attributes
        }
    
    def to_text(self) -> str:
        """转换为文本格式"""
        entity_type = next((l for l in self.labels if l not in ["Entity", "Node"]), "未知类型")
        return f"实体: {self.name} (类型: {entity_type})\n摘要: {self.summary}"


@dataclass
class EdgeInfo:
    """边信息"""
    uuid: str
    name: str
    fact: str
    source_node_uuid: str
    target_node_uuid: str
    source_node_name: Optional[str] = None
    target_node_name: Optional[str] = None
    # 时间信息
    created_at: Optional[str] = None
    valid_at: Optional[str] = None
    invalid_at: Optional[str] = None
    expired_at: Optional[str] = None
    
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
        """转换为文本格式"""
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
        """是否已过期"""
        return self.expired_at is not None
    
    @property
    def is_invalid(self) -> bool:
        """是否已失效"""
        return self.invalid_at is not None


@dataclass
class InsightForgeResult:
    """
    深度洞察检索结果 (InsightForge)
    包含多个子问题的检索结果，以及综合分析
    """
    query: str
    simulation_requirement: str
    sub_queries: List[str]
    
    # 各维度检索结果
    semantic_facts: List[str] = field(default_factory=list)  # 语义搜索结果
    entity_insights: List[Dict[str, Any]] = field(default_factory=list)  # 实体洞察
    relationship_chains: List[str] = field(default_factory=list)  # 关系链
    
    # 统计信息
    total_facts: int = 0
    total_entities: int = 0
    total_relationships: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "simulation_requirement": self.simulation_requirement,
            "sub_queries": self.sub_queries,
            "semantic_facts": self.semantic_facts,
            "entity_insights": self.entity_insights,
            "relationship_chains": self.relationship_chains,
            "total_facts": self.total_facts,
            "total_entities": self.total_entities,
            "total_relationships": self.total_relationships
        }
    
    def to_text(self) -> str:
        """转换为详细的文本格式，供LLM理解"""
        text_parts = [
            f"## 未来预测深度分析",
            f"分析问题: {self.query}",
            f"预测场景: {self.simulation_requirement}",
            f"\n### 预测数据统计",
            f"- 相关预测事实: {self.total_facts}条",
            f"- 涉及实体: {self.total_entities}个",
            f"- 关系链: {self.total_relationships}条"
        ]
        
        # 子问题
        if self.sub_queries:
            text_parts.append(f"\n### 分析的子问题")
            for i, sq in enumerate(self.sub_queries, 1):
                text_parts.append(f"{i}. {sq}")
        
        # 语义搜索结果
        if self.semantic_facts:
            text_parts.append(f"\n### 【关键事实】(请在报告中引用这些原文)")
            for i, fact in enumerate(self.semantic_facts, 1):
                text_parts.append(f"{i}. \"{fact}\"")
        
        # 实体洞察
        if self.entity_insights:
            text_parts.append(f"\n### 【核心实体】")
            for entity in self.entity_insights:
                text_parts.append(f"- **{entity.get('name', '未知')}** ({entity.get('type', '实体')})")
                if entity.get('summary'):
                    text_parts.append(f"  摘要: \"{entity.get('summary')}\"")
                if entity.get('related_facts'):
                    text_parts.append(f"  相关事实: {len(entity.get('related_facts', []))}条")
        
        # 关系链
        if self.relationship_chains:
            text_parts.append(f"\n### 【关系链】")
            for chain in self.relationship_chains:
                text_parts.append(f"- {chain}")
        
        return "\n".join(text_parts)


@dataclass
class PanoramaResult:
    """
    广度搜索结果 (Panorama)
    包含所有相关信息，包括过期内容
    """
    query: str
    
    # 全部节点
    all_nodes: List[NodeInfo] = field(default_factory=list)
    # 全部边（包括过期的）
    all_edges: List[EdgeInfo] = field(default_factory=list)
    # 当前有效的事实
    active_facts: List[str] = field(default_factory=list)
    # 已过期/失效的事实（历史记录）
    historical_facts: List[str] = field(default_factory=list)
    
    # 统计
    total_nodes: int = 0
    total_edges: int = 0
    active_count: int = 0
    historical_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "all_nodes": [n.to_dict() for n in self.all_nodes],
            "all_edges": [e.to_dict() for e in self.all_edges],
            "active_facts": self.active_facts,
            "historical_facts": self.historical_facts,
            "total_nodes": self.total_nodes,
            "total_edges": self.total_edges,
            "active_count": self.active_count,
            "historical_count": self.historical_count
        }
    
    def to_text(self) -> str:
        """转换为文本格式（完整版本，不截断）"""
        text_parts = [
            f"## 广度搜索结果（未来全景视图）",
            f"查询: {self.query}",
            f"\n### 统计信息",
            f"- 总节点数: {self.total_nodes}",
            f"- 总边数: {self.total_edges}",
            f"- 当前有效事实: {self.active_count}条",
            f"- 历史/过期事实: {self.historical_count}条"
        ]
        
        # 当前有效的事实（完整输出，不截断）
        if self.active_facts:
            text_parts.append(f"\n### 【当前有效事实】(模拟结果原文)")
            for i, fact in enumerate(self.active_facts, 1):
                text_parts.append(f"{i}. \"{fact}\"")
        
        # 历史/过期事实（完整输出，不截断）
        if self.historical_facts:
            text_parts.append(f"\n### 【历史/过期事实】(演变过程记录)")
            for i, fact in enumerate(self.historical_facts, 1):
                text_parts.append(f"{i}. \"{fact}\"")
        
        # 关键实体（完整输出，不截断）
        if self.all_nodes:
            text_parts.append(f"\n### 【涉及实体】")
            for node in self.all_nodes:
                entity_type = next((l for l in node.labels if l not in ["Entity", "Node"]), "实体")
                text_parts.append(f"- **{node.name}** ({entity_type})")
        
        return "\n".join(text_parts)


@dataclass
class AgentInterview:
    """单个Agent的采访结果"""
    agent_name: str
    agent_role: str  # 角色类型（如：学生、教师、媒体等）
    agent_bio: str  # 简介
    question: str  # 采访问题
    response: str  # 采访回答
    key_quotes: List[str] = field(default_factory=list)  # 关键引言
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "agent_role": self.agent_role,
            "agent_bio": self.agent_bio,
            "question": self.question,
            "response": self.response,
            "key_quotes": self.key_quotes
        }
    
    def to_text(self) -> str:
        text = f"**{self.agent_name}** ({self.agent_role})\n"
        # 显示完整的agent_bio，不截断
        text += f"_简介: {self.agent_bio}_\n\n"
        text += f"**Q:** {self.question}\n\n"
        text += f"**A:** {self.response}\n"
        if self.key_quotes:
            text += "\n**关键引言:**\n"
            for quote in self.key_quotes:
                # 清理各种引号
                clean_quote = quote.replace('\u201c', '').replace('\u201d', '').replace('"', '')
                clean_quote = clean_quote.replace('\u300c', '').replace('\u300d', '')
                clean_quote = clean_quote.strip()
                # 去掉开头的标点
                while clean_quote and clean_quote[0] in '，,；;：:、。！？\n\r\t ':
                    clean_quote = clean_quote[1:]
                # 过滤包含问题编号的垃圾内容（问题1-9）
                skip = False
                for d in '123456789':
                    if f'\u95ee\u9898{d}' in clean_quote:
                        skip = True
                        break
                if skip:
                    continue
                # 截断过长内容（按句号截断，而非硬截断）
                if len(clean_quote) > 150:
                    dot_pos = clean_quote.find('\u3002', 80)
                    if dot_pos > 0:
                        clean_quote = clean_quote[:dot_pos + 1]
                    else:
                        clean_quote = clean_quote[:147] + "..."
                if clean_quote and len(clean_quote) >= 10:
                    text += f'> "{clean_quote}"\n'
        return text


@dataclass
class InterviewResult:
    """
    采访结果 (Interview)
    包含多个模拟Agent的采访回答
    """
    interview_topic: str  # 采访主题
    interview_questions: List[str]  # 采访问题列表
    
    # 采访选择的Agent
    selected_agents: List[Dict[str, Any]] = field(default_factory=list)
    # 各Agent的采访回答
    interviews: List[AgentInterview] = field(default_factory=list)
    
    # 选择Agent的理由
    selection_reasoning: str = ""
    # 整合后的采访摘要
    summary: str = ""
    
    # 统计
    total_agents: int = 0
    interviewed_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "interview_topic": self.interview_topic,
            "interview_questions": self.interview_questions,
            "selected_agents": self.selected_agents,
            "interviews": [i.to_dict() for i in self.interviews],
            "selection_reasoning": self.selection_reasoning,
            "summary": self.summary,
            "total_agents": self.total_agents,
            "interviewed_count": self.interviewed_count
        }
    
    def to_text(self) -> str:
        """转换为详细的文本格式，供LLM理解和报告引用"""
        text_parts = [
            "## 深度采访报告",
            f"**采访主题:** {self.interview_topic}",
            f"**采访人数:** {self.interviewed_count} / {self.total_agents} 位模拟Agent",
            "\n### 采访对象选择理由",
            self.selection_reasoning or "（自动选择）",
            "\n---",
            "\n### 采访实录",
        ]

        if self.interviews:
            for i, interview in enumerate(self.interviews, 1):
                text_parts.append(f"\n#### 采访 #{i}: {interview.agent_name}")
                text_parts.append(interview.to_text())
                text_parts.append("\n---")
        else:
            text_parts.append("（无采访记录）\n\n---")

        text_parts.append("\n### 采访摘要与核心观点")
        text_parts.append(self.summary or "（无摘要）")

        return "\n".join(text_parts)


class ZepToolsService:
    """
    Zep检索工具服务
    
    【核心检索工具 - 优化后】
    1. insight_forge - 深度洞察检索（最强大，自动生成子问题，多维度检索）
    2. panorama_search - 广度搜索（获取全貌，包括过期内容）
    3. quick_search - 简单搜索（快速检索）
    4. interview_agents - 深度采访（采访模拟Agent，获取多视角观点）
    
    【基础工具】
    - search_graph - 图谱语义搜索
    - get_all_nodes - 获取图谱所有节点
    - get_all_edges - 获取图谱所有边（含时间信息）
    - get_node_detail - 获取节点详细信息
    - get_node_edges - 获取节点相关的边
    - get_entities_by_type - 按类型获取实体
    - get_entity_summary - 获取实体的关系摘要
    """
    
    # 重试配置
    MAX_RETRIES = 3
    RETRY_DELAY = 2.0
    
    def __init__(self, api_key: Optional[str] = None, llm_client: Optional[LLMClient] = None):
        self.api_key = Config.ZEP_API_KEY if api_key is None else api_key
        errors = Config.get_graph_backend_config_errors(api_key=self.api_key)
        if errors:
            raise ValueError("; ".join(errors))
        
        self.backend = get_graph_backend(api_key=self.api_key)
        # LLM客户端用于InsightForge生成子问题
        self._llm_client = llm_client
        self._search_embedder_client = None
        self._search_reranker_client = None
        logger.info("ZepToolsService 初始化完成")
    
    @property
    def llm(self) -> LLMClient:
        """延迟初始化LLM客户端"""
        if self._llm_client is None:
            self._llm_client = LLMClient()
        return self._llm_client
    
    def _call_with_retry(self, func, operation_name: str, max_retries: int = None):
        """带重试机制的API调用"""
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
                        t("console.zepRetryAttempt", operation=operation_name, attempt=attempt + 1, error=str(e)[:100], delay=f"{delay:.1f}")
                    )
                    time.sleep(delay)
                    delay *= 2
                else:
                    logger.error(t("console.zepAllRetriesFailed", operation=operation_name, retries=max_retries, error=str(e)))
        
        raise last_exception
    


    def _normalize_text(self, text: Optional[str]) -> str:
        """标准化文本，便于后续打分和去重。"""
        return " ".join(str(text or "").split())

    def _query_tokens(self, query: str) -> List[str]:
        """提取查询词，兼顾中英文。"""
        normalized = self._normalize_text(query).lower()
        tokens = set(re.findall(r"[a-z0-9_]+", normalized))

        for run in re.findall(r"[一-鿿]+", normalized):
            if len(run) <= 4:
                tokens.add(run)
                continue

            tokens.add(run)
            for size in (2, 3, 4):
                for idx in range(len(run) - size + 1):
                    tokens.add(run[idx:idx + size])

        return [token for token in tokens if len(token) > 1]

    def _score_texts(self, query_lower: str, query_tokens: List[str], *parts: str) -> int:
        """轻量级文本相关性打分，用于本地合并与退化检索。"""
        combined = self._normalize_text(" ".join(part for part in parts if part)).lower()
        if not combined:
            return 0

        score = 0
        if query_lower and query_lower in combined:
            score += 120

        for token in query_tokens:
            if token in combined:
                score += 12 if len(token) >= 3 else 5

        return score

    def _graph_search_app_reranker(self) -> str:
        """返回 app-side 检索重排模式。"""
        return (Config.GRAPH_SEARCH_APP_RERANKER or "lexical").strip().lower() or "lexical"

    def _get_search_embedder(self) -> Optional[EmbeddingClient]:
        """懒加载图搜索 embedding client。"""
        if self._search_embedder_client is False:
            return None
        if self._search_embedder_client is not None:
            return self._search_embedder_client

        embedder_config = Config.get_graph_search_embedder_config()
        base_url = embedder_config.get("base_url")
        model = embedder_config.get("model")
        if not base_url or not model:
            self._search_embedder_client = False
            return None

        try:
            self._search_embedder_client = EmbeddingClient(
                api_key=embedder_config.get("api_key") or "ollama",
                base_url=base_url,
                model=model,
                batch_size=Config.GRAPH_SEARCH_APP_EMBED_BATCH_SIZE,
            )
            logger.info(
                "图搜索语义重排已启用: mode=%s, model=%s",
                self._graph_search_app_reranker(),
                model,
            )
        except Exception as exc:
            logger.warning(f"图搜索 embedding reranker 初始化失败: {exc}")
            self._search_embedder_client = False
            return None

        return self._search_embedder_client

    def _edge_search_text(self, edge: Dict[str, Any]) -> str:
        """构建边候选的语义检索文本。"""
        return self._normalize_text(
            " ".join(
                part
                for part in [
                    edge.get("fact", ""),
                    edge.get("name", ""),
                    edge.get("source_node_name", ""),
                    edge.get("target_node_name", ""),
                ]
                if part
            )
        )

    def _node_search_text(self, node: Dict[str, Any]) -> str:
        """构建节点候选的语义检索文本。"""
        return self._normalize_text(
            " ".join(
                part
                for part in [
                    node.get("name", ""),
                    node.get("summary", ""),
                    " ".join(node.get("labels", [])),
                ]
                if part
            )
        )

    def _cosine_similarity(self, left: List[float], right: List[float]) -> float:
        """计算两个 embedding 向量的余弦相似度。"""
        if not left or not right or len(left) != len(right):
            return 0.0

        numerator = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(a * a for a in left))
        right_norm = math.sqrt(sum(b * b for b in right))
        if left_norm == 0 or right_norm == 0:
            return 0.0

        return numerator / (left_norm * right_norm)

    def _rrf_score(self, rank: int) -> float:
        """Reciprocal Rank Fusion score."""
        rank = max(1, int(rank))
        return 1.0 / (Config.GRAPH_SEARCH_APP_RERANK_FUSION_K + rank)

    def _sort_candidates(self, candidates: List[Dict[str, Any]], score_key: str) -> List[Dict[str, Any]]:
        """按分数倒序、原始召回顺序升序排序。"""
        return sorted(
            candidates,
            key=lambda item: (
                -float(item.get(score_key, 0.0) or 0.0),
                int(item.get("_backend_rank", 10**9)),
            ),
        )

    def _strip_candidate_meta(self, candidate: Dict[str, Any]) -> Dict[str, Any]:
        """移除仅用于本地重排的内部字段。"""
        return {key: value for key, value in candidate.items() if not key.startswith("_")}

    def _edge_candidate_key(self, edge: Dict[str, Any]) -> str:
        """生成边候选的稳定 key。"""
        return edge.get("uuid") or "|".join([
            edge.get("name", ""),
            edge.get("fact", ""),
            edge.get("source_node_uuid", ""),
            edge.get("target_node_uuid", ""),
        ])

    def _edge_info_to_candidate(self, edge: EdgeInfo) -> Dict[str, Any]:
        """将 EdgeInfo 转换为本地重排使用的候选字典。"""
        edge_candidate = {
            "uuid": edge.uuid,
            "name": edge.name,
            "fact": edge.fact,
            "source_node_uuid": edge.source_node_uuid,
            "target_node_uuid": edge.target_node_uuid,
            "source_node_name": edge.source_node_name or "",
            "target_node_name": edge.target_node_name or "",
        }
        edge_candidate["_candidate_key"] = self._edge_candidate_key(edge_candidate)
        return edge_candidate

    def _expand_edge_candidates_from_nodes(
        self,
        graph_id: str,
        ranked_nodes: List[Dict[str, Any]],
        candidate_edges: Dict[str, Dict[str, Any]],
        query_lower: str,
        query_tokens: List[str],
    ) -> None:
        """从高相关节点补抓相邻边，提升边召回率。"""
        if not Config.GRAPH_SEARCH_EXPAND_EDGES_FROM_NODES:
            return

        node_limit = Config.GRAPH_SEARCH_NODE_EDGE_EXPANSION_LIMIT
        per_node_limit = Config.GRAPH_SEARCH_NODE_EDGE_PER_NODE_LIMIT
        if node_limit <= 0 or per_node_limit <= 0 or not ranked_nodes:
            return

        expanded_node_count = 0
        added_edge_count = 0

        for node_rank, node in enumerate(ranked_nodes[:node_limit], start=1):
            node_uuid = node.get("uuid")
            if not node_uuid:
                continue

            related_edges = self.get_node_edges(graph_id, node_uuid)
            if not related_edges:
                continue

            expanded_node_count += 1
            scored_edges = []
            for edge in related_edges:
                edge_candidate = self._edge_info_to_candidate(edge)
                edge_key = edge_candidate.get("_candidate_key")
                if not edge_key or edge_key in candidate_edges:
                    continue

                lexical_score = self._score_texts(
                    query_lower,
                    query_tokens,
                    self._edge_search_text(edge_candidate),
                )
                scored_edges.append((lexical_score, node_rank, edge_candidate))

            scored_edges.sort(
                key=lambda item: (
                    -int(item[0]),
                    int(item[1]),
                    item[2].get("name", ""),
                    item[2].get("fact", ""),
                )
            )

            for _, _, edge_candidate in scored_edges[:per_node_limit]:
                edge_key = edge_candidate.get("_candidate_key")
                if edge_key and edge_key not in candidate_edges:
                    candidate_edges[edge_key] = edge_candidate
                    added_edge_count += 1

        if added_edge_count > 0:
            logger.info(
                "节点召回补边完成: expanded_nodes=%s, added_edges=%s",
                expanded_node_count,
                added_edge_count,
            )

    def _compute_semantic_scores(self, query: str, candidates: List[Dict[str, Any]]) -> Optional[Dict[str, float]]:
        """使用 embedding 计算 query 与候选文本的相似度。"""
        if len(candidates) < 2:
            return {}

        embedder = self._get_search_embedder()
        if embedder is None:
            return None

        keyed_texts = [
            (candidate.get("_candidate_key", ""), candidate.get("_search_text", ""))
            for candidate in candidates
            if candidate.get("_candidate_key") and candidate.get("_search_text")
        ]
        if not keyed_texts:
            return {}

        try:
            embeddings = embedder.embed_texts([query] + [candidate_text for _, candidate_text in keyed_texts])
        except Exception as exc:
            logger.warning(f"图搜索 embedding reranker 调用失败，回退到词面排序: {exc}")
            return None

        if len(embeddings) != len(keyed_texts) + 1:
            logger.warning("图搜索 embedding reranker 返回向量数量异常，回退到词面排序")
            return None

        query_vector = embeddings[0]
        scores: Dict[str, float] = {}
        for (candidate_key, _), vector in zip(keyed_texts, embeddings[1:]):
            scores[candidate_key] = self._cosine_similarity(query_vector, vector)

        return scores

    def _get_search_reranker(self) -> Optional[RerankerClient]:
        """懒加载图搜索 API reranker client。"""
        if self._search_reranker_client is False:
            return None
        if self._search_reranker_client is not None:
            return self._search_reranker_client

        reranker_config = Config.get_graph_search_reranker_config()
        base_url = reranker_config.get("base_url")
        if not base_url:
            self._search_reranker_client = False
            return None

        try:
            self._search_reranker_client = RerankerClient(
                api_key=reranker_config.get("api_key"),
                base_url=base_url,
                model=reranker_config.get("model"),
                provider=reranker_config.get("provider") or "auto",
                timeout=reranker_config.get("timeout") or 20.0,
            )
            logger.info(
                "图搜索 API reranker 已启用: mode=%s, provider=%s, model=%s",
                self._graph_search_app_reranker(),
                reranker_config.get("provider") or "auto",
                reranker_config.get("model"),
            )
        except Exception as exc:
            logger.warning(f"图搜索 API reranker 初始化失败: {exc}")
            self._search_reranker_client = False
            return None

        return self._search_reranker_client

    def _compute_api_rerank_scores(self, query: str, candidates: List[Dict[str, Any]]) -> Optional[Dict[str, float]]:
        """使用独立 reranker endpoint 计算 query 与候选文本的相关性。"""
        if len(candidates) < 2:
            return {}

        reranker = self._get_search_reranker()
        if reranker is None:
            return None

        keyed_texts = [
            (candidate.get("_candidate_key", ""), candidate.get("_search_text", ""))
            for candidate in candidates
            if candidate.get("_candidate_key") and candidate.get("_search_text")
        ]
        if not keyed_texts:
            return {}

        try:
            score_by_index = reranker.rerank(
                query=query,
                documents=[candidate_text for _, candidate_text in keyed_texts],
            )
        except Exception as exc:
            logger.warning(f"图搜索 API reranker 调用失败，回退到词面排序: {exc}")
            return None

        scores: Dict[str, float] = {}
        for index, (candidate_key, _) in enumerate(keyed_texts):
            scores[candidate_key] = float(score_by_index.get(index, 0.0))

        return scores

    def _apply_app_rerank(
        self,
        candidates: List[Dict[str, Any]],
        query_normalized: str,
        query_lower: str,
        query_tokens: List[str],
        text_builder: Callable[[Dict[str, Any]], str],
    ) -> List[Dict[str, Any]]:
        """对候选结果执行 app-side 重排。"""
        if not candidates:
            return []

        prepared: List[Dict[str, Any]] = []
        for backend_rank, original in enumerate(candidates, start=1):
            candidate = dict(original)
            candidate.setdefault(
                "_candidate_key",
                candidate.get("uuid") or candidate.get("name") or f"candidate_{backend_rank}",
            )
            candidate["_backend_rank"] = backend_rank
            candidate["_search_text"] = self._normalize_text(text_builder(candidate))
            candidate["_lexical_score"] = self._score_texts(
                query_lower,
                query_tokens,
                candidate.get("_search_text", ""),
            )
            prepared.append(candidate)

        mode = self._graph_search_app_reranker()
        lexical_ranked = self._sort_candidates(prepared, "_lexical_score")

        if mode in {"none", "off"}:
            return [self._strip_candidate_meta(candidate) for candidate in prepared]

        if mode in {"lexical", "keyword"}:
            return [self._strip_candidate_meta(candidate) for candidate in lexical_ranked]

        semantic_modes = {"embedding_rrf", "semantic_rrf", "hybrid", "embedding_similarity", "semantic", "semantic_similarity"}
        api_score_modes = {"api_rerank", "rerank_api", "cross_encoder", "cross_encoder_api"}
        api_rrf_modes = {"api_rrf", "rerank_rrf", "cross_encoder_rrf"}
        supported_modes = semantic_modes | api_score_modes | api_rrf_modes

        if mode not in supported_modes:
            logger.warning(f"未知 GRAPH_SEARCH_APP_RERANKER={mode}，回退到 lexical")
            return [self._strip_candidate_meta(candidate) for candidate in lexical_ranked]

        if mode in semantic_modes:
            semantic_scores = self._compute_semantic_scores(query_normalized, prepared)
            if semantic_scores is None:
                return [self._strip_candidate_meta(candidate) for candidate in lexical_ranked]

            for candidate in prepared:
                candidate["_semantic_score"] = float(semantic_scores.get(candidate["_candidate_key"], 0.0))

            semantic_ranked = self._sort_candidates(prepared, "_semantic_score")

            if mode in {"embedding_similarity", "semantic", "semantic_similarity"}:
                ranked = sorted(
                    prepared,
                    key=lambda item: (
                        -float(item.get("_semantic_score", 0.0) or 0.0),
                        -float(item.get("_lexical_score", 0.0) or 0.0),
                        int(item.get("_backend_rank", 10**9)),
                    ),
                )
                return [self._strip_candidate_meta(candidate) for candidate in ranked]

            backend_ranks = {candidate["_candidate_key"]: idx for idx, candidate in enumerate(prepared, start=1)}
            lexical_ranks = {candidate["_candidate_key"]: idx for idx, candidate in enumerate(lexical_ranked, start=1)}
            semantic_ranks = {candidate["_candidate_key"]: idx for idx, candidate in enumerate(semantic_ranked, start=1)}

            for candidate in prepared:
                candidate_key = candidate["_candidate_key"]
                candidate["_fusion_score"] = (
                    self._rrf_score(backend_ranks[candidate_key])
                    + self._rrf_score(lexical_ranks[candidate_key])
                    + (Config.GRAPH_SEARCH_APP_SEMANTIC_WEIGHT * self._rrf_score(semantic_ranks[candidate_key]))
                )

            ranked = sorted(
                prepared,
                key=lambda item: (
                    -float(item.get("_fusion_score", 0.0) or 0.0),
                    -float(item.get("_semantic_score", 0.0) or 0.0),
                    -float(item.get("_lexical_score", 0.0) or 0.0),
                    int(item.get("_backend_rank", 10**9)),
                ),
            )
            return [self._strip_candidate_meta(candidate) for candidate in ranked]

        api_scores = self._compute_api_rerank_scores(query_normalized, prepared)
        if api_scores is None:
            return [self._strip_candidate_meta(candidate) for candidate in lexical_ranked]

        for candidate in prepared:
            candidate["_api_rerank_score"] = float(api_scores.get(candidate["_candidate_key"], 0.0))

        api_ranked = self._sort_candidates(prepared, "_api_rerank_score")

        if mode in api_score_modes:
            ranked = sorted(
                prepared,
                key=lambda item: (
                    -float(item.get("_api_rerank_score", 0.0) or 0.0),
                    -float(item.get("_lexical_score", 0.0) or 0.0),
                    int(item.get("_backend_rank", 10**9)),
                ),
            )
            return [self._strip_candidate_meta(candidate) for candidate in ranked]

        backend_ranks = {candidate["_candidate_key"]: idx for idx, candidate in enumerate(prepared, start=1)}
        lexical_ranks = {candidate["_candidate_key"]: idx for idx, candidate in enumerate(lexical_ranked, start=1)}
        api_ranks = {candidate["_candidate_key"]: idx for idx, candidate in enumerate(api_ranked, start=1)}

        for candidate in prepared:
            candidate_key = candidate["_candidate_key"]
            candidate["_fusion_score"] = (
                self._rrf_score(backend_ranks[candidate_key])
                + self._rrf_score(lexical_ranks[candidate_key])
                + (Config.GRAPH_SEARCH_APP_SEMANTIC_WEIGHT * self._rrf_score(api_ranks[candidate_key]))
            )

        ranked = sorted(
            prepared,
            key=lambda item: (
                -float(item.get("_fusion_score", 0.0) or 0.0),
                -float(item.get("_api_rerank_score", 0.0) or 0.0),
                -float(item.get("_lexical_score", 0.0) or 0.0),
                int(item.get("_backend_rank", 10**9)),
            ),
        )
        return [self._strip_candidate_meta(candidate) for candidate in ranked]

    def _search_scope(self, graph_id: str, query: str, scope: str, limit: int) -> Any:
        """执行单个 scope 的后端检索。"""
        reranker = Config.GRAPH_SEARCH_RERANKER
        return self._call_with_retry(
            func=lambda: self.backend.search(
                graph_id=graph_id,
                query=query,
                limit=limit,
                scope=scope,
                reranker=reranker,
            ),
            operation_name=f"图谱搜索(graph={graph_id}, scope={scope})",
        )

    def _parse_search_edges(self, search_results: Any) -> List[Dict[str, Any]]:
        edges = []
        if hasattr(search_results, 'edges') and search_results.edges:
            for edge in search_results.edges:
                edges.append({
                    "uuid": getattr(edge, 'uuid_', None) or getattr(edge, 'uuid', ''),
                    "name": getattr(edge, 'name', ''),
                    "fact": getattr(edge, 'fact', ''),
                    "source_node_uuid": getattr(edge, 'source_node_uuid', ''),
                    "target_node_uuid": getattr(edge, 'target_node_uuid', ''),
                    "source_node_name": getattr(edge, 'source_node_name', ''),
                    "target_node_name": getattr(edge, 'target_node_name', ''),
                })
        return edges

    def _parse_search_nodes(self, search_results: Any) -> List[Dict[str, Any]]:
        nodes = []
        if hasattr(search_results, 'nodes') and search_results.nodes:
            for node in search_results.nodes:
                nodes.append({
                    "uuid": getattr(node, 'uuid_', None) or getattr(node, 'uuid', ''),
                    "name": getattr(node, 'name', ''),
                    "labels": getattr(node, 'labels', []),
                    "summary": getattr(node, 'summary', ''),
                })
        return nodes

    def search_graph(
        self,
        graph_id: str,
        query: str,
        limit: int = 10,
        scope: str = "edges"
    ) -> SearchResult:
        """
        图谱语义搜索。

        当前实现会优先召回边，再按配置补充节点摘要，避免只拿到零散 fact
        或在 OpenZep 上完全退化到本地关键词搜索。
        """
        logger.info(f"图谱搜索: graph_id={graph_id}, query={query[:50]}...")

        query_normalized = self._normalize_text(query)
        query_lower = query_normalized.lower()
        query_tokens = self._query_tokens(query_normalized)

        edge_limit = max(limit, limit * Config.GRAPH_SEARCH_EDGE_LIMIT_MULTIPLIER)
        node_limit = max(limit, limit * Config.GRAPH_SEARCH_NODE_LIMIT_MULTIPLIER)

        candidate_edges: Dict[str, Dict[str, Any]] = {}
        candidate_nodes: Dict[str, Dict[str, Any]] = {}
        search_errors: List[str] = []

        scopes_to_search: List[tuple[str, int]] = []
        if scope in {"edges", "both"}:
            scopes_to_search.append(("edges", edge_limit))
        if scope in {"nodes", "both"} or Config.GRAPH_SEARCH_INCLUDE_NODES:
            scopes_to_search.append(("nodes", node_limit))

        for search_scope, scoped_limit in scopes_to_search:
            try:
                search_results = self._search_scope(
                    graph_id=graph_id,
                    query=query_normalized,
                    scope=search_scope,
                    limit=scoped_limit,
                )
            except Exception as e:
                logger.warning(f"{search_scope} 检索失败: {str(e)}")
                search_errors.append(f"{search_scope}:{str(e)}")
                continue

            if search_scope == "edges":
                for edge in self._parse_search_edges(search_results):
                    edge_key = self._edge_candidate_key(edge)
                    if edge_key and edge_key not in candidate_edges:
                        edge["_candidate_key"] = edge_key
                        candidate_edges[edge_key] = edge
            else:
                for node in self._parse_search_nodes(search_results):
                    node_key = node["uuid"] or node.get("name", "")
                    if node_key and node_key not in candidate_nodes:
                        node["_candidate_key"] = node_key
                        candidate_nodes[node_key] = node

        if not candidate_edges and not candidate_nodes:
            if search_errors:
                logger.warning("后端图搜索不可用，降级为本地搜索")
            return self._local_search(graph_id, query_normalized, limit, scope)

        ranked_nodes = self._apply_app_rerank(
            list(candidate_nodes.values()),
            query_normalized=query_normalized,
            query_lower=query_lower,
            query_tokens=query_tokens,
            text_builder=self._node_search_text,
        )

        if scope in {"edges", "both"} and ranked_nodes:
            self._expand_edge_candidates_from_nodes(
                graph_id=graph_id,
                ranked_nodes=ranked_nodes,
                candidate_edges=candidate_edges,
                query_lower=query_lower,
                query_tokens=query_tokens,
            )

        ranked_edges = self._apply_app_rerank(
            list(candidate_edges.values()),
            query_normalized=query_normalized,
            query_lower=query_lower,
            query_tokens=query_tokens,
            text_builder=self._edge_search_text,
        )

        selected_edges = ranked_edges[:limit] if scope in {"edges", "both"} else []

        if scope == "nodes":
            selected_nodes = ranked_nodes[:limit]
        else:
            node_summary_limit = min(Config.GRAPH_SEARCH_NODE_SUMMARY_LIMIT, max(1, limit))
            related_node_uuids = {
                edge.get("source_node_uuid", "")
                for edge in selected_edges
                if edge.get("source_node_uuid")
            }
            related_node_uuids.update(
                edge.get("target_node_uuid", "")
                for edge in selected_edges
                if edge.get("target_node_uuid")
            )
            selected_nodes = []
            for node in ranked_nodes:
                if scope == "edges" and selected_edges and node.get("uuid") not in related_node_uuids:
                    continue
                selected_nodes.append(node)
                if len(selected_nodes) >= node_summary_limit:
                    break

        facts: List[str] = []
        seen_facts = set()

        for edge in selected_edges:
            fact = self._normalize_text(edge.get("fact", ""))
            if fact and fact not in seen_facts:
                facts.append(fact)
                seen_facts.add(fact)

        for node in selected_nodes:
            summary = self._normalize_text(node.get("summary", ""))
            if not summary:
                continue
            fact = f"[{node.get('name', '未知实体')}]: {summary}"
            if fact not in seen_facts:
                facts.append(fact)
                seen_facts.add(fact)

        logger.info(
            "搜索完成: edges=%s, nodes=%s, facts=%s, backend_reranker=%s, app_reranker=%s",
            len(selected_edges),
            len(selected_nodes),
            len(facts),
            Config.GRAPH_SEARCH_RERANKER,
            self._graph_search_app_reranker(),
        )

        return SearchResult(
            facts=facts,
            edges=selected_edges,
            nodes=selected_nodes,
            query=query_normalized,
            total_count=len(facts),
        )

    def _local_search(
        self,
        graph_id: str,
        query: str,
        limit: int = 10,
        scope: str = "edges"
    ) -> SearchResult:
        """
        本地关键词匹配搜索（作为后端 search 不可用时的降级方案）。
        """
        logger.info(f"使用本地搜索: query={query[:30]}...")

        facts: List[str] = []
        edges_result: List[Dict[str, Any]] = []
        nodes_result: List[Dict[str, Any]] = []

        query_normalized = self._normalize_text(query)
        query_lower = query_normalized.lower()
        query_tokens = self._query_tokens(query_normalized)

        try:
            node_map = {node.uuid: node for node in self.get_all_nodes(graph_id)}

            if scope in ["edges", "both"]:
                all_edges = self.get_all_edges(graph_id)
                scored_edges = []
                for edge in all_edges:
                    source_name = node_map.get(edge.source_node_uuid, NodeInfo('', '', [], '', {})).name
                    target_name = node_map.get(edge.target_node_uuid, NodeInfo('', '', [], '', {})).name
                    score = self._score_texts(
                        query_lower,
                        query_tokens,
                        edge.fact,
                        edge.name,
                        source_name,
                        target_name,
                    )
                    if score > 0:
                        scored_edges.append((score, edge, source_name, target_name))

                scored_edges.sort(key=lambda item: item[0], reverse=True)

                for score, edge, source_name, target_name in scored_edges[:limit]:
                    if edge.fact:
                        facts.append(edge.fact)
                    edges_result.append({
                        "uuid": edge.uuid,
                        "name": edge.name,
                        "fact": edge.fact,
                        "source_node_uuid": edge.source_node_uuid,
                        "target_node_uuid": edge.target_node_uuid,
                        "source_node_name": source_name,
                        "target_node_name": target_name,
                    })

            if scope in ["nodes", "both"] or Config.GRAPH_SEARCH_INCLUDE_NODES:
                all_nodes = list(node_map.values())
                scored_nodes = []
                for node in all_nodes:
                    score = self._score_texts(
                        query_lower,
                        query_tokens,
                        node.name,
                        node.summary,
                        " ".join(node.labels),
                    )
                    if score > 0:
                        scored_nodes.append((score, node))

                scored_nodes.sort(key=lambda item: item[0], reverse=True)

                node_limit = limit if scope == "nodes" else min(limit, Config.GRAPH_SEARCH_NODE_SUMMARY_LIMIT)
                for score, node in scored_nodes[:node_limit]:
                    nodes_result.append({
                        "uuid": node.uuid,
                        "name": node.name,
                        "labels": node.labels,
                        "summary": node.summary,
                    })
                    if node.summary:
                        facts.append(f"[{node.name}]: {node.summary}")

            facts = list(dict.fromkeys(facts))
            logger.info(f"本地搜索完成: 找到 {len(facts)} 条相关事实")

        except Exception as e:
            logger.error(f"本地搜索失败: {str(e)}")

        return SearchResult(
            facts=facts,
            edges=edges_result,
            nodes=nodes_result,
            query=query_normalized,
            total_count=len(facts)
        )

    def get_all_nodes(self, graph_id: str) -> List[NodeInfo]:
        """
        获取图谱的所有节点（分页获取）
        """
        logger.info(t("console.fetchingAllNodes", graphId=graph_id))

        nodes = self.backend.get_all_nodes(graph_id)

        result = []
        for node in nodes:
            node_uuid = getattr(node, 'uuid_', None) or getattr(node, 'uuid', None) or ""
            result.append(NodeInfo(
                uuid=str(node_uuid) if node_uuid else "",
                name=node.name or "",
                labels=node.labels or [],
                summary=node.summary or "",
                attributes=node.attributes or {}
            ))

        logger.info(t("console.fetchedNodes", count=len(result)))
        return result

    def get_all_edges(self, graph_id: str, include_temporal: bool = True) -> List[EdgeInfo]:
        """
        获取图谱的所有边（分页获取，包含时间信息）
        """
        logger.info(t("console.fetchingAllEdges", graphId=graph_id))

        edges = self.backend.get_all_edges(graph_id)

        result = []
        for edge in edges:
            edge_uuid = getattr(edge, 'uuid_', None) or getattr(edge, 'uuid', None) or ""
            edge_info = EdgeInfo(
                uuid=str(edge_uuid) if edge_uuid else "",
                name=edge.name or "",
                fact=edge.fact or "",
                source_node_uuid=edge.source_node_uuid or "",
                target_node_uuid=edge.target_node_uuid or ""
            )

            if include_temporal:
                edge_info.created_at = getattr(edge, 'created_at', None)
                edge_info.valid_at = getattr(edge, 'valid_at', None)
                edge_info.invalid_at = getattr(edge, 'invalid_at', None)
                edge_info.expired_at = getattr(edge, 'expired_at', None)

            result.append(edge_info)

        logger.info(t("console.fetchedEdges", count=len(result)))
        return result

    def get_node_detail(self, node_uuid: str) -> Optional[NodeInfo]:
        """获取单个节点的详细信息。"""
        logger.info(f"获取节点详情: {node_uuid[:8]}...")

        try:
            node = self._call_with_retry(
                func=lambda: self.backend.get_node(node_uuid),
                operation_name=f"获取节点详情(uuid={node_uuid[:8]}...)"
            )

            if not node:
                return None

            return NodeInfo(
                uuid=getattr(node, 'uuid_', None) or getattr(node, 'uuid', ''),
                name=node.name or "",
                labels=node.labels or [],
                summary=node.summary or "",
                attributes=node.attributes or {}
            )
        except Exception as e:
            logger.error(t("console.fetchNodeDetailFailed", error=str(e)))
            return None

    def get_node_edges(self, graph_id: str, node_uuid: str) -> List[EdgeInfo]:
        """获取节点相关的所有边。"""
        logger.info(f"获取节点 {node_uuid[:8]}... 的相关边")

        try:
            edges = self._call_with_retry(
                func=lambda: self.backend.get_node_edges(node_uuid),
                operation_name=f"获取节点边(uuid={node_uuid[:8]}...)"
            )

            result = []
            for edge in edges:
                edge_uuid = getattr(edge, 'uuid_', None) or getattr(edge, 'uuid', None) or ""
                result.append(EdgeInfo(
                    uuid=str(edge_uuid) if edge_uuid else "",
                    name=edge.name or "",
                    fact=edge.fact or "",
                    source_node_uuid=edge.source_node_uuid or "",
                    target_node_uuid=edge.target_node_uuid or "",
                    source_node_name=getattr(edge, 'source_node_name', None),
                    target_node_name=getattr(edge, 'target_node_name', None),
                    created_at=getattr(edge, 'created_at', None),
                    valid_at=getattr(edge, 'valid_at', None),
                    invalid_at=getattr(edge, 'invalid_at', None),
                    expired_at=getattr(edge, 'expired_at', None),
                ))

            logger.info(f"找到 {len(result)} 条与节点相关的边")
            return result

        except Exception as e:
            logger.warning(t("console.fetchNodeEdgesFailed", error=str(e)))
            return []

    def get_entities_by_type(
        self, 
        graph_id: str, 
        entity_type: str
    ) -> List[NodeInfo]:
        """
        按类型获取实体
        
        Args:
            graph_id: 图谱ID
            entity_type: 实体类型（如 Student, PublicFigure 等）
            
        Returns:
            符合类型的实体列表
        """
        logger.info(t("console.fetchingEntitiesByType", type=entity_type))
        
        all_nodes = self.get_all_nodes(graph_id)
        
        filtered = []
        for node in all_nodes:
            # 检查labels是否包含指定类型
            if entity_type in node.labels:
                filtered.append(node)
        
        logger.info(t("console.foundEntitiesByType", count=len(filtered), type=entity_type))
        return filtered
    
    def get_entity_summary(
        self, 
        graph_id: str, 
        entity_name: str
    ) -> Dict[str, Any]:
        """
        获取指定实体的关系摘要
        
        搜索与该实体相关的所有信息，并生成摘要
        
        Args:
            graph_id: 图谱ID
            entity_name: 实体名称
            
        Returns:
            实体摘要信息
        """
        logger.info(t("console.fetchingEntitySummary", name=entity_name))
        
        # 先搜索该实体相关的信息
        search_result = self.search_graph(
            graph_id=graph_id,
            query=entity_name,
            limit=20
        )
        
        # 尝试在所有节点中找到该实体
        all_nodes = self.get_all_nodes(graph_id)
        entity_node = None
        for node in all_nodes:
            if node.name.lower() == entity_name.lower():
                entity_node = node
                break
        
        related_edges = []
        if entity_node:
            # 传入graph_id参数
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
        logger.info(t("console.fetchingGraphStats", graphId=graph_id))
        
        nodes = self.get_all_nodes(graph_id)
        edges = self.get_all_edges(graph_id)
        
        # 统计实体类型分布
        entity_types = {}
        for node in nodes:
            for label in node.labels:
                if label not in ["Entity", "Node"]:
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
        simulation_requirement: str,
        limit: int = 30
    ) -> Dict[str, Any]:
        """
        获取模拟相关的上下文信息
        
        综合搜索与模拟需求相关的所有信息
        
        Args:
            graph_id: 图谱ID
            simulation_requirement: 模拟需求描述
            limit: 每类信息的数量限制
            
        Returns:
            模拟上下文信息
        """
        logger.info(t("console.fetchingSimContext", requirement=simulation_requirement[:50]))
        
        # 搜索与模拟需求相关的信息
        search_result = self.search_graph(
            graph_id=graph_id,
            query=simulation_requirement,
            limit=limit
        )
        
        # 获取图谱统计
        stats = self.get_graph_statistics(graph_id)
        
        # 获取所有实体节点
        all_nodes = self.get_all_nodes(graph_id)
        
        # 筛选有实际类型的实体（非纯Entity节点）
        entities = []
        for node in all_nodes:
            custom_labels = [l for l in node.labels if l not in ["Entity", "Node"]]
            if custom_labels:
                entities.append({
                    "name": node.name,
                    "type": custom_labels[0],
                    "summary": node.summary
                })
        
        return {
            "simulation_requirement": simulation_requirement,
            "related_facts": search_result.facts,
            "graph_statistics": stats,
            "entities": entities[:limit],  # 限制数量
            "total_entities": len(entities)
        }
    
    # ========== 核心检索工具（优化后） ==========
    


    def insight_forge(
        self,
        graph_id: str,
        query: str,
        simulation_requirement: str,
        report_context: str = "",
        max_sub_queries: int = 5
    ) -> InsightForgeResult:
        """
        【InsightForge - 深度洞察检索】
        """
        logger.info(f"InsightForge 深度洞察检索: {query[:50]}...")

        result = InsightForgeResult(
            query=query,
            simulation_requirement=simulation_requirement,
            sub_queries=[]
        )

        sub_queries = self._generate_sub_queries(
            query=query,
            simulation_requirement=simulation_requirement,
            report_context=report_context,
            max_queries=max_sub_queries
        )
        result.sub_queries = sub_queries
        logger.info(f"生成 {len(sub_queries)} 个子问题")

        all_facts: List[str] = []
        seen_facts = set()
        all_edges: Dict[str, Dict[str, Any]] = {}
        all_nodes: Dict[str, Dict[str, Any]] = {}
        entity_fact_map: Dict[str, List[str]] = defaultdict(list)

        def merge_search(search_result: SearchResult) -> None:
            for fact in search_result.facts:
                if fact not in seen_facts:
                    all_facts.append(fact)
                    seen_facts.add(fact)

            for edge in search_result.edges:
                edge_key = edge.get('uuid') or "|".join([
                    edge.get('name', ''),
                    edge.get('fact', ''),
                    edge.get('source_node_uuid', ''),
                    edge.get('target_node_uuid', ''),
                ])
                if edge_key and edge_key not in all_edges:
                    all_edges[edge_key] = edge

                fact = edge.get('fact', '')
                for node_uuid in (edge.get('source_node_uuid', ''), edge.get('target_node_uuid', '')):
                    if node_uuid and fact and fact not in entity_fact_map[node_uuid]:
                        entity_fact_map[node_uuid].append(fact)

            for node in search_result.nodes:
                node_uuid = node.get('uuid') or node.get('name')
                if node_uuid and node_uuid not in all_nodes:
                    all_nodes[node_uuid] = node

        for sub_query in sub_queries:
            merge_search(
                self.search_graph(
                    graph_id=graph_id,
                    query=sub_query,
                    limit=15,
                    scope="edges"
                )
            )

        merge_search(
            self.search_graph(
                graph_id=graph_id,
                query=query,
                limit=20,
                scope="edges"
            )
        )

        result.semantic_facts = all_facts
        result.total_facts = len(all_facts)

        entity_uuids = set(all_nodes.keys())
        for edge in all_edges.values():
            source_uuid = edge.get('source_node_uuid', '')
            target_uuid = edge.get('target_node_uuid', '')
            if source_uuid:
                entity_uuids.add(source_uuid)
            if target_uuid:
                entity_uuids.add(target_uuid)

        entity_insights = []
        node_map: Dict[str, NodeInfo] = {}

        for node_uuid in list(entity_uuids):
            if not node_uuid:
                continue

            search_node = all_nodes.get(node_uuid, {})
            node = self.get_node_detail(node_uuid)
            if node is None and search_node:
                node = NodeInfo(
                    uuid=search_node.get('uuid', node_uuid),
                    name=search_node.get('name', ''),
                    labels=search_node.get('labels', []),
                    summary=search_node.get('summary', ''),
                    attributes={},
                )

            if not node:
                continue

            node_map[node_uuid] = node
            entity_type = next((label for label in node.labels if label not in ["Entity", "Node"]), "实体")
            related_facts = list(dict.fromkeys(entity_fact_map.get(node_uuid, [])))
            if not related_facts and node.name:
                related_facts = [fact for fact in all_facts if node.name.lower() in fact.lower()]

            entity_insights.append({
                "uuid": node.uuid,
                "name": node.name,
                "type": entity_type,
                "summary": node.summary,
                "related_facts": related_facts,
            })

        result.entity_insights = entity_insights
        result.total_entities = len(entity_insights)

        relationship_chains = []
        for edge in all_edges.values():
            source_uuid = edge.get('source_node_uuid', '')
            target_uuid = edge.get('target_node_uuid', '')
            relation_name = edge.get('name', '')

            source_name = node_map.get(source_uuid, NodeInfo('', '', [], '', {})).name or edge.get('source_node_name', '') or source_uuid[:8]
            target_name = node_map.get(target_uuid, NodeInfo('', '', [], '', {})).name or edge.get('target_node_name', '') or target_uuid[:8]

            chain = f"{source_name} --[{relation_name}]--> {target_name}"
            if chain not in relationship_chains:
                relationship_chains.append(chain)

        result.relationship_chains = relationship_chains
        result.total_relationships = len(relationship_chains)

        logger.info(
            f"InsightForge完成: {result.total_facts}条事实, {result.total_entities}个实体, {result.total_relationships}条关系"
        )
        return result

    def _generate_sub_queries(
        self,
        query: str,
        simulation_requirement: str,
        report_context: str = "",
        max_queries: int = 5
    ) -> List[str]:
        """
        使用LLM生成子问题
        
        将复杂问题分解为多个可以独立检索的子问题
        """
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
            # 确保是字符串列表
            return [str(sq) for sq in sub_queries[:max_queries]]
            
        except Exception as e:
            logger.warning(t("console.generateSubQueriesFailed", error=str(e)))
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
    ) -> PanoramaResult:
        """
        【PanoramaSearch - 广度搜索】
        
        获取全貌视图，包括所有相关内容和历史/过期信息：
        1. 获取所有相关节点
        2. 获取所有边（包括已过期/失效的）
        3. 分类整理当前有效和历史信息
        
        这个工具适用于需要了解事件全貌、追踪演变过程的场景。
        
        Args:
            graph_id: 图谱ID
            query: 搜索查询（用于相关性排序）
            include_expired: 是否包含过期内容（默认True）
            limit: 返回结果数量限制
            
        Returns:
            PanoramaResult: 广度搜索结果
        """
        logger.info(t("console.panoramaSearchStart", query=query[:50]))
        
        result = PanoramaResult(query=query)
        
        # 获取所有节点
        all_nodes = self.get_all_nodes(graph_id)
        node_map = {n.uuid: n for n in all_nodes}
        result.all_nodes = all_nodes
        result.total_nodes = len(all_nodes)
        
        # 获取所有边（包含时间信息）
        all_edges = self.get_all_edges(graph_id, include_temporal=True)
        result.all_edges = all_edges
        result.total_edges = len(all_edges)
        
        # 分类事实
        active_facts = []
        historical_facts = []
        
        for edge in all_edges:
            if not edge.fact:
                continue
            
            # 为事实添加实体名称
            source_name = node_map.get(edge.source_node_uuid, NodeInfo('', '', [], '', {})).name or edge.source_node_uuid[:8]
            target_name = node_map.get(edge.target_node_uuid, NodeInfo('', '', [], '', {})).name or edge.target_node_uuid[:8]
            
            # 判断是否过期/失效
            is_historical = edge.is_expired or edge.is_invalid
            
            if is_historical:
                # 历史/过期事实，添加时间标记
                valid_at = edge.valid_at or "未知"
                invalid_at = edge.invalid_at or edge.expired_at or "未知"
                fact_with_time = f"[{valid_at} - {invalid_at}] {edge.fact}"
                historical_facts.append(fact_with_time)
            else:
                # 当前有效事实
                active_facts.append(edge.fact)
        
        # 基于查询进行相关性排序
        query_lower = query.lower()
        keywords = [w.strip() for w in query_lower.replace(',', ' ').replace('，', ' ').split() if len(w.strip()) > 1]
        
        def relevance_score(fact: str) -> int:
            fact_lower = fact.lower()
            score = 0
            if query_lower in fact_lower:
                score += 100
            for kw in keywords:
                if kw in fact_lower:
                    score += 10
            return score
        
        # 排序并限制数量
        active_facts.sort(key=relevance_score, reverse=True)
        historical_facts.sort(key=relevance_score, reverse=True)
        
        result.active_facts = active_facts[:limit]
        result.historical_facts = historical_facts[:limit] if include_expired else []
        result.active_count = len(active_facts)
        result.historical_count = len(historical_facts)
        
        logger.info(t("console.panoramaSearchComplete", active=result.active_count, historical=result.historical_count))
        return result
    
    def quick_search(
        self,
        graph_id: str,
        query: str,
        limit: int = 10
    ) -> SearchResult:
        """
        【QuickSearch - 简单搜索】
        
        快速、轻量级的检索工具：
        1. 直接调用Zep语义搜索
        2. 返回最相关的结果
        3. 适用于简单、直接的检索需求
        
        Args:
            graph_id: 图谱ID
            query: 搜索查询
            limit: 返回结果数量
            
        Returns:
            SearchResult: 搜索结果
        """
        logger.info(t("console.quickSearchStart", query=query[:50]))
        
        # 直接调用现有的search_graph方法
        result = self.search_graph(
            graph_id=graph_id,
            query=query,
            limit=limit,
            scope="edges"
        )
        
        logger.info(t("console.quickSearchComplete", count=result.total_count))
        return result
    
    def interview_agents(
        self,
        simulation_id: str,
        interview_requirement: str,
        simulation_requirement: str = "",
        max_agents: int = 5,
        custom_questions: List[str] = None
    ) -> InterviewResult:
        """
        【InterviewAgents - 深度采访】
        
        调用真实的OASIS采访API，采访模拟中正在运行的Agent：
        1. 自动读取人设文件，了解所有模拟Agent
        2. 使用LLM分析采访需求，智能选择最相关的Agent
        3. 使用LLM生成采访问题
        4. 调用 /api/simulation/interview/batch 接口进行真实采访（双平台同时采访）
        5. 整合所有采访结果，生成采访报告
        
        【重要】此功能需要模拟环境处于运行状态（OASIS环境未关闭）
        
        【使用场景】
        - 需要从不同角色视角了解事件看法
        - 需要收集多方意见和观点
        - 需要获取模拟Agent的真实回答（非LLM模拟）
        
        Args:
            simulation_id: 模拟ID（用于定位人设文件和调用采访API）
            interview_requirement: 采访需求描述（非结构化，如"了解学生对事件的看法"）
            simulation_requirement: 模拟需求背景（可选）
            max_agents: 最多采访的Agent数量
            custom_questions: 自定义采访问题（可选，若不提供则自动生成）
            
        Returns:
            InterviewResult: 采访结果
        """
        from .simulation_runner import SimulationRunner
        
        logger.info(t("console.interviewAgentsStart", requirement=interview_requirement[:50]))
        
        result = InterviewResult(
            interview_topic=interview_requirement,
            interview_questions=custom_questions or []
        )
        
        # Step 1: 读取人设文件
        profiles = self._load_agent_profiles(simulation_id)
        
        if not profiles:
            logger.warning(t("console.profilesNotFound", simId=simulation_id))
            result.summary = "未找到可采访的Agent人设文件"
            return result
        
        result.total_agents = len(profiles)
        logger.info(t("console.loadedProfiles", count=len(profiles)))
        
        # Step 2: 使用LLM选择要采访的Agent（返回agent_id列表）
        selected_agents, selected_indices, selection_reasoning = self._select_agents_for_interview(
            profiles=profiles,
            interview_requirement=interview_requirement,
            simulation_requirement=simulation_requirement,
            max_agents=max_agents
        )
        
        result.selected_agents = selected_agents
        result.selection_reasoning = selection_reasoning
        logger.info(t("console.selectedAgentsForInterview", count=len(selected_agents), indices=selected_indices))
        
        # Step 3: 生成采访问题（如果没有提供）
        if not result.interview_questions:
            result.interview_questions = self._generate_interview_questions(
                interview_requirement=interview_requirement,
                simulation_requirement=simulation_requirement,
                selected_agents=selected_agents
            )
            logger.info(t("console.generatedInterviewQuestions", count=len(result.interview_questions)))
        
        # 将问题合并为一个采访prompt
        combined_prompt = "\n".join([f"{i+1}. {q}" for i, q in enumerate(result.interview_questions)])
        
        # 添加优化前缀，约束Agent回复格式
        INTERVIEW_PROMPT_PREFIX = (
            "你正在接受一次采访。请结合你的人设、所有的过往记忆与行动，"
            "以纯文本方式直接回答以下问题。\n"
            "回复要求：\n"
            "1. 直接用自然语言回答，不要调用任何工具\n"
            "2. 不要返回JSON格式或工具调用格式\n"
            "3. 不要使用Markdown标题（如#、##、###）\n"
            "4. 按问题编号逐一回答，每个回答以「问题X：」开头（X为问题编号）\n"
            "5. 每个问题的回答之间用空行分隔\n"
            "6. 回答要有实质内容，每个问题至少回答2-3句话\n\n"
        )
        optimized_prompt = f"{INTERVIEW_PROMPT_PREFIX}{combined_prompt}"
        
        # Step 4: 调用真实的采访API（不指定platform，默认双平台同时采访）
        try:
            # 构建批量采访列表（不指定platform，双平台采访）
            interviews_request = []
            for agent_idx in selected_indices:
                interviews_request.append({
                    "agent_id": agent_idx,
                    "prompt": optimized_prompt  # 使用优化后的prompt
                    # 不指定platform，API会在twitter和reddit两个平台都采访
                })
            
            logger.info(t("console.callingBatchInterviewApi", count=len(interviews_request)))
            
            # 调用 SimulationRunner 的批量采访方法（不传platform，双平台采访）
            api_result = SimulationRunner.interview_agents_batch(
                simulation_id=simulation_id,
                interviews=interviews_request,
                platform=None,  # 不指定platform，双平台采访
                timeout=180.0   # 双平台需要更长超时
            )
            
            logger.info(t("console.interviewApiReturned", count=api_result.get('interviews_count', 0), success=api_result.get('success')))
            
            # 检查API调用是否成功
            if not api_result.get("success", False):
                error_msg = api_result.get("error", "未知错误")
                logger.warning(t("console.interviewApiReturnedFailure", error=error_msg))
                result.summary = f"采访API调用失败：{error_msg}。请检查OASIS模拟环境状态。"
                return result
            
            # Step 5: 解析API返回结果，构建AgentInterview对象
            # 双平台模式返回格式: {"twitter_0": {...}, "reddit_0": {...}, "twitter_1": {...}, ...}
            api_data = api_result.get("result", {})
            results_dict = api_data.get("results", {}) if isinstance(api_data, dict) else {}
            
            for i, agent_idx in enumerate(selected_indices):
                agent = selected_agents[i]
                agent_name = agent.get("realname", agent.get("username", f"Agent_{agent_idx}"))
                agent_role = agent.get("profession", "未知")
                agent_bio = agent.get("bio", "")
                
                # 获取该Agent在两个平台的采访结果
                twitter_result = results_dict.get(f"twitter_{agent_idx}", {})
                reddit_result = results_dict.get(f"reddit_{agent_idx}", {})
                
                twitter_response = twitter_result.get("response", "")
                reddit_response = reddit_result.get("response", "")

                # 清理可能的工具调用 JSON 包裹
                twitter_response = self._clean_tool_call_response(twitter_response)
                reddit_response = self._clean_tool_call_response(reddit_response)

                # 始终输出双平台标记
                twitter_text = twitter_response if twitter_response else "（该平台未获得回复）"
                reddit_text = reddit_response if reddit_response else "（该平台未获得回复）"
                response_text = f"【Twitter平台回答】\n{twitter_text}\n\n【Reddit平台回答】\n{reddit_text}"

                # 提取关键引言（从两个平台的回答中）
                import re
                combined_responses = f"{twitter_response} {reddit_response}"

                # 清理响应文本：去掉标记、编号、Markdown 等干扰
                clean_text = re.sub(r'#{1,6}\s+', '', combined_responses)
                clean_text = re.sub(r'\{[^}]*tool_name[^}]*\}', '', clean_text)
                clean_text = re.sub(r'[*_`|>~\-]{2,}', '', clean_text)
                clean_text = re.sub(r'问题\d+[：:]\s*', '', clean_text)
                clean_text = re.sub(r'【[^】]+】', '', clean_text)

                # 策略1（主）: 提取完整的有实质内容的句子
                sentences = re.split(r'[。！？]', clean_text)
                meaningful = [
                    s.strip() for s in sentences
                    if 20 <= len(s.strip()) <= 150
                    and not re.match(r'^[\s\W，,；;：:、]+', s.strip())
                    and not s.strip().startswith(('{', '问题'))
                ]
                meaningful.sort(key=len, reverse=True)
                key_quotes = [s + "。" for s in meaningful[:3]]

                # 策略2（补充）: 正确配对的中文引号「」内长文本
                if not key_quotes:
                    paired = re.findall(r'\u201c([^\u201c\u201d]{15,100})\u201d', clean_text)
                    paired += re.findall(r'\u300c([^\u300c\u300d]{15,100})\u300d', clean_text)
                    key_quotes = [q for q in paired if not re.match(r'^[，,；;：:、]', q)][:3]
                
                interview = AgentInterview(
                    agent_name=agent_name,
                    agent_role=agent_role,
                    agent_bio=agent_bio[:1000],  # 扩大bio长度限制
                    question=combined_prompt,
                    response=response_text,
                    key_quotes=key_quotes[:5]
                )
                result.interviews.append(interview)
            
            result.interviewed_count = len(result.interviews)
            
        except ValueError as e:
            # 模拟环境未运行
            logger.warning(t("console.interviewApiCallFailed", error=e))
            result.summary = f"采访失败：{str(e)}。模拟环境可能已关闭，请确保OASIS环境正在运行。"
            return result
        except Exception as e:
            logger.error(t("console.interviewApiCallException", error=e))
            import traceback
            logger.error(traceback.format_exc())
            result.summary = f"采访过程发生错误：{str(e)}"
            return result
        
        # Step 6: 生成采访摘要
        if result.interviews:
            result.summary = self._generate_interview_summary(
                interviews=result.interviews,
                interview_requirement=interview_requirement
            )
        
        logger.info(t("console.interviewAgentsComplete", count=result.interviewed_count))
        return result
    
    @staticmethod
    def _clean_tool_call_response(response: str) -> str:
        """清理 Agent 回复中的 JSON 工具调用包裹，提取实际内容"""
        if not response or not response.strip().startswith('{'):
            return response
        text = response.strip()
        if 'tool_name' not in text[:80]:
            return response
        import re as _re
        try:
            data = json.loads(text)
            if isinstance(data, dict) and 'arguments' in data:
                for key in ('content', 'text', 'body', 'message', 'reply'):
                    if key in data['arguments']:
                        return str(data['arguments'][key])
        except (json.JSONDecodeError, KeyError, TypeError):
            match = _re.search(r'"content"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
            if match:
                return match.group(1).replace('\\n', '\n').replace('\\"', '"')
        return response

    def _load_agent_profiles(self, simulation_id: str) -> List[Dict[str, Any]]:
        """加载模拟的Agent人设文件"""
        import os
        import csv
        
        # 构建人设文件路径
        sim_dir = os.path.join(
            os.path.dirname(__file__), 
            f'../../uploads/simulations/{simulation_id}'
        )
        
        profiles = []
        
        # 优先尝试读取Reddit JSON格式
        reddit_profile_path = os.path.join(sim_dir, "reddit_profiles.json")
        if os.path.exists(reddit_profile_path):
            try:
                with open(reddit_profile_path, 'r', encoding='utf-8') as f:
                    profiles = json.load(f)
                logger.info(t("console.loadedRedditProfiles", count=len(profiles)))
                return profiles
            except Exception as e:
                logger.warning(t("console.readRedditProfilesFailed", error=e))
        
        # 尝试读取Twitter CSV格式
        twitter_profile_path = os.path.join(sim_dir, "twitter_profiles.csv")
        if os.path.exists(twitter_profile_path):
            try:
                with open(twitter_profile_path, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        # CSV格式转换为统一格式
                        profiles.append({
                            "realname": row.get("name", ""),
                            "username": row.get("username", ""),
                            "bio": row.get("description", ""),
                            "persona": row.get("user_char", ""),
                            "profession": "未知"
                        })
                logger.info(t("console.loadedTwitterProfiles", count=len(profiles)))
                return profiles
            except Exception as e:
                logger.warning(t("console.readTwitterProfilesFailed", error=e))
        
        return profiles
    
    def _select_agents_for_interview(
        self,
        profiles: List[Dict[str, Any]],
        interview_requirement: str,
        simulation_requirement: str,
        max_agents: int
    ) -> tuple:
        """
        使用LLM选择要采访的Agent
        
        Returns:
            tuple: (selected_agents, selected_indices, reasoning)
                - selected_agents: 选中Agent的完整信息列表
                - selected_indices: 选中Agent的索引列表（用于API调用）
                - reasoning: 选择理由
        """
        
        # 构建Agent摘要列表
        agent_summaries = []
        for i, profile in enumerate(profiles):
            summary = {
                "index": i,
                "name": profile.get("realname", profile.get("username", f"Agent_{i}")),
                "profession": profile.get("profession", "未知"),
                "bio": profile.get("bio", "")[:200],
                "interested_topics": profile.get("interested_topics", [])
            }
            agent_summaries.append(summary)
        
        system_prompt = """你是一个专业的采访策划专家。你的任务是根据采访需求，从模拟Agent列表中选择最适合采访的对象。

选择标准：
1. Agent的身份/职业与采访主题相关
2. Agent可能持有独特或有价值的观点
3. 选择多样化的视角（如：支持方、反对方、中立方、专业人士等）
4. 优先选择与事件直接相关的角色

返回JSON格式：
{
    "selected_indices": [选中Agent的索引列表],
    "reasoning": "选择理由说明"
}"""

        user_prompt = f"""采访需求：
{interview_requirement}

模拟背景：
{simulation_requirement if simulation_requirement else "未提供"}

可选择的Agent列表（共{len(agent_summaries)}个）：
{json.dumps(agent_summaries, ensure_ascii=False, indent=2)}

请选择最多{max_agents}个最适合采访的Agent，并说明选择理由。"""

        try:
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3
            )
            
            selected_indices = response.get("selected_indices", [])[:max_agents]
            reasoning = response.get("reasoning", "基于相关性自动选择")
            
            # 获取选中的Agent完整信息
            selected_agents = []
            valid_indices = []
            for idx in selected_indices:
                if 0 <= idx < len(profiles):
                    selected_agents.append(profiles[idx])
                    valid_indices.append(idx)
            
            return selected_agents, valid_indices, reasoning
            
        except Exception as e:
            logger.warning(t("console.llmSelectAgentFailed", error=e))
            # 降级：选择前N个
            selected = profiles[:max_agents]
            indices = list(range(min(max_agents, len(profiles))))
            return selected, indices, "使用默认选择策略"
    
    def _generate_interview_questions(
        self,
        interview_requirement: str,
        simulation_requirement: str,
        selected_agents: List[Dict[str, Any]]
    ) -> List[str]:
        """使用LLM生成采访问题"""
        
        agent_roles = [a.get("profession", "未知") for a in selected_agents]
        
        system_prompt = """你是一个专业的记者/采访者。根据采访需求，生成3-5个深度采访问题。

问题要求：
1. 开放性问题，鼓励详细回答
2. 针对不同角色可能有不同答案
3. 涵盖事实、观点、感受等多个维度
4. 语言自然，像真实采访一样
5. 每个问题控制在50字以内，简洁明了
6. 直接提问，不要包含背景说明或前缀

返回JSON格式：{"questions": ["问题1", "问题2", ...]}"""

        user_prompt = f"""采访需求：{interview_requirement}

模拟背景：{simulation_requirement if simulation_requirement else "未提供"}

采访对象角色：{', '.join(agent_roles)}

请生成3-5个采访问题。"""

        try:
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.5
            )
            
            return response.get("questions", [f"关于{interview_requirement}，您有什么看法？"])
            
        except Exception as e:
            logger.warning(t("console.generateInterviewQuestionsFailed", error=e))
            return [
                f"关于{interview_requirement}，您的观点是什么？",
                "这件事对您或您所代表的群体有什么影响？",
                "您认为应该如何解决或改进这个问题？"
            ]
    
    def _generate_interview_summary(
        self,
        interviews: List[AgentInterview],
        interview_requirement: str
    ) -> str:
        """生成采访摘要"""
        
        if not interviews:
            return "未完成任何采访"
        
        # 收集所有采访内容
        interview_texts = []
        for interview in interviews:
            interview_texts.append(f"【{interview.agent_name}（{interview.agent_role}）】\n{interview.response[:500]}")
        
        quote_instruction = "引用受访者原话时使用中文引号「」" if get_locale() == 'zh' else 'Use quotation marks "" when quoting interviewees'
        system_prompt = f"""你是一个专业的新闻编辑。请根据多位受访者的回答，生成一份采访摘要。

摘要要求：
1. 提炼各方主要观点
2. 指出观点的共识和分歧
3. 突出有价值的引言
4. 客观中立，不偏袒任何一方
5. 控制在1000字内

格式约束（必须遵守）：
- 使用纯文本段落，用空行分隔不同部分
- 不要使用Markdown标题（如#、##、###）
- 不要使用分割线（如---、***）
- {quote_instruction}
- 可以使用**加粗**标记关键词，但不要使用其他Markdown语法"""

        user_prompt = f"""采访主题：{interview_requirement}

采访内容：
{"".join(interview_texts)}

请生成采访摘要。"""

        try:
            summary = self.llm.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3,
                max_tokens=800
            )
            return summary
            
        except Exception as e:
            logger.warning(t("console.generateInterviewSummaryFailed", error=e))
            # 降级：简单拼接
            return f"共采访了{len(interviews)}位受访者，包括：" + "、".join([i.agent_name for i in interviews])
