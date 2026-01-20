"""
本地实体消歧模块

实现 Zep/Graphiti 风格的两阶段实体去重策略：
1. 确定性匹配：精确匹配 + 模糊匹配（基于规则）
2. LLM 消歧：可选，用于处理低置信度的候选

参考 Graphiti 的 dedup_helpers.py 实现。
"""

import re
from difflib import SequenceMatcher
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

from ..config import Config
from ..utils.logger import get_logger

logger = get_logger("mirofish.local_entity_resolver")


# 配置常量
EXACT_MATCH_THRESHOLD = 1.0       # 精确匹配阈值
FUZZY_MATCH_THRESHOLD = 0.85      # 模糊匹配阈值
MIN_NAME_LENGTH = 2               # 最小名称长度
LLM_DISAMBIGUATION_ENABLED = True  # 是否启用 LLM 消歧


def normalize_string(name: str) -> str:
    """
    归一化字符串：小写、去除多余空格
    
    Args:
        name: 原始名称
        
    Returns:
        归一化后的名称
    """
    if not name:
        return ""
    # 小写
    normalized = name.lower()
    # 合并多个空格为单个
    normalized = re.sub(r'\s+', ' ', normalized)
    # 去除首尾空格
    normalized = normalized.strip()
    return normalized


def normalize_for_fuzzy(name: str) -> str:
    """
    为模糊匹配进行更激进的归一化：
    - 只保留字母、数字、空格
    - 去除标点和特殊字符
    
    Args:
        name: 原始名称
        
    Returns:
        归一化后的名称
    """
    normalized = normalize_string(name)
    # 只保留字母数字和空格
    normalized = re.sub(r"[^a-z0-9\u4e00-\u9fff ]", " ", normalized)
    # 合并多个空格
    normalized = re.sub(r'\s+', ' ', normalized)
    return normalized.strip()


def calculate_similarity(s1: str, s2: str) -> float:
    """
    计算两个字符串的相似度
    
    使用 difflib.SequenceMatcher，效果类似于 Levenshtein 距离
    
    Args:
        s1: 字符串1
        s2: 字符串2
        
    Returns:
        相似度分数 (0.0 - 1.0)
    """
    if not s1 or not s2:
        return 0.0
    return SequenceMatcher(None, s1, s2).ratio()


def jaccard_similarity(s1: str, s2: str) -> float:
    """
    计算两个字符串的 Jaccard 相似度（基于字符集合）
    
    Args:
        s1: 字符串1
        s2: 字符串2
        
    Returns:
        Jaccard 相似度 (0.0 - 1.0)
    """
    if not s1 and not s2:
        return 1.0
    if not s1 or not s2:
        return 0.0
    
    set1 = set(s1)
    set2 = set(s2)
    
    intersection = len(set1 & set2)
    union = len(set1 | set2)
    
    return intersection / union if union > 0 else 0.0


def token_jaccard_similarity(s1: str, s2: str) -> float:
    """
    计算两个字符串的 Jaccard 相似度（基于词/token 集合）
    
    比字符级别的 Jaccard 更适合处理词序变化
    
    Args:
        s1: 字符串1
        s2: 字符串2
        
    Returns:
        Jaccard 相似度 (0.0 - 1.0)
    """
    if not s1 and not s2:
        return 1.0
    if not s1 or not s2:
        return 0.0
    
    # 分词
    tokens1 = set(s1.split())
    tokens2 = set(s2.split())
    
    if not tokens1 and not tokens2:
        return 1.0
    if not tokens1 or not tokens2:
        return 0.0
    
    intersection = len(tokens1 & tokens2)
    union = len(tokens1 | tokens2)
    
    return intersection / union if union > 0 else 0.0


@dataclass
class ResolvedEntity:
    """实体解析结果"""
    uuid: str                       # 解析后的 UUID（可能是已有实体的 UUID）
    name: str                       # 最佳名称
    entity_type: str                # 实体类型
    is_new: bool                    # 是否是新实体
    matched_uuid: Optional[str]     # 匹配到的已有实体 UUID（如果有）
    match_score: float              # 匹配分数
    should_update_summary: bool     # 是否需要更新摘要


class LocalEntityResolver:
    """
    本地实体消歧器
    
    实现两阶段去重策略：
    1. 确定性匹配：精确匹配 + 模糊匹配
    2. LLM 消歧（可选）
    """
    
    def __init__(
        self,
        graph_store,
        fuzzy_threshold: float = FUZZY_MATCH_THRESHOLD,
        enable_llm: bool = LLM_DISAMBIGUATION_ENABLED,
    ):
        """
        初始化解析器
        
        Args:
            graph_store: LocalNeo4jGraphStore 实例
            fuzzy_threshold: 模糊匹配阈值
            enable_llm: 是否启用 LLM 消歧
        """
        self._graph_store = graph_store
        self._fuzzy_threshold = fuzzy_threshold
        self._enable_llm = enable_llm
        
        # 缓存已解析的实体，避免同一批次内重复查询
        self._resolution_cache: Dict[str, ResolvedEntity] = {}
    
    def clear_cache(self):
        """清空解析缓存（每批次处理后应调用）"""
        self._resolution_cache.clear()
    
    def resolve(
        self,
        graph_id: str,
        name: str,
        entity_type: str,
        summary: str = "",
        attributes: Optional[Dict] = None,
    ) -> ResolvedEntity:
        """
        解析单个实体，判断是否与已有实体重复
        
        Args:
            graph_id: 图谱 ID
            name: 实体名称
            entity_type: 实体类型
            summary: 实体摘要
            attributes: 实体属性
            
        Returns:
            ResolvedEntity 对象，包含解析结果
        """
        if not name or len(name.strip()) < MIN_NAME_LENGTH:
            # 名称太短，直接创建新实体
            return self._create_new_entity_result(name, entity_type)
        
        # 归一化名称用于查找
        normalized_name = normalize_string(name)
        
        # 检查缓存
        cache_key = f"{graph_id}:{normalized_name}"
        if cache_key in self._resolution_cache:
            return self._resolution_cache[cache_key]
        
        # 阶段1：确定性匹配
        result = self._deterministic_resolve(graph_id, name, entity_type, summary)
        
        # 阶段2：LLM 消歧（如果启用且未找到匹配）
        if result.is_new and self._enable_llm and result.match_score > 0.5:
            # 有低置信度候选，可以尝试 LLM 消歧
            # TODO: 实现 LLM 消歧
            pass
        
        # 缓存结果
        self._resolution_cache[cache_key] = result
        
        return result
    
    def _deterministic_resolve(
        self,
        graph_id: str,
        name: str,
        entity_type: str,
        summary: str = "",
    ) -> ResolvedEntity:
        """
        确定性解析：使用规则进行匹配
        
        策略：
        1. 精确匹配：归一化名称完全相同
        2. 模糊匹配：相似度超过阈值
        """
        normalized_name = normalize_string(name)
        fuzzy_name = normalize_for_fuzzy(name)
        
        # 从图谱中获取候选实体
        candidates = self._graph_store.search_similar_entities(graph_id, name, limit=20)
        
        if not candidates:
            # 没有候选，创建新实体
            return self._create_new_entity_result(name, entity_type)
        
        best_match: Optional[Dict] = None
        best_score: float = 0.0
        
        for candidate in candidates:
            candidate_name = candidate.get("name", "")
            candidate_normalized = normalize_string(candidate_name)
            candidate_fuzzy = normalize_for_fuzzy(candidate_name)
            
            # 1. 精确匹配检查
            if normalized_name == candidate_normalized:
                # 完美匹配
                return ResolvedEntity(
                    uuid=candidate.get("uuid"),
                    name=self._select_best_name(name, candidate_name),
                    entity_type=entity_type,
                    is_new=False,
                    matched_uuid=candidate.get("uuid"),
                    match_score=1.0,
                    should_update_summary=bool(summary),
                )
            
            # 2. 模糊匹配
            # 使用多种相似度指标，取最高分
            seq_score = calculate_similarity(normalized_name, candidate_normalized)
            fuzzy_seq_score = calculate_similarity(fuzzy_name, candidate_fuzzy)
            token_jaccard = token_jaccard_similarity(fuzzy_name, candidate_fuzzy)
            
            # 综合评分：取最高值
            score = max(seq_score, fuzzy_seq_score, token_jaccard)
            
            if score > best_score:
                best_score = score
                best_match = candidate
        
        # 检查最佳匹配是否超过阈值
        if best_match and best_score >= self._fuzzy_threshold:
            logger.debug(
                f"模糊匹配成功: '{name}' -> '{best_match.get('name')}' (score={best_score:.3f})"
            )
            return ResolvedEntity(
                uuid=best_match.get("uuid"),
                name=self._select_best_name(name, best_match.get("name", "")),
                entity_type=entity_type,
                is_new=False,
                matched_uuid=best_match.get("uuid"),
                match_score=best_score,
                should_update_summary=bool(summary),
            )
        
        # 没有找到足够相似的匹配
        return self._create_new_entity_result(
            name, entity_type, 
            match_score=best_score if best_match else 0.0
        )
    
    def _create_new_entity_result(
        self,
        name: str,
        entity_type: str,
        match_score: float = 0.0,
    ) -> ResolvedEntity:
        """创建新实体的解析结果"""
        # 生成新 UUID（使用与 LocalEntity 相同的逻辑）
        from .local_graph_store import _stable_entity_uuid
        
        # 注意：这里使用空 project_id，实际 UUID 会在 upsert 时重新计算
        new_uuid = _stable_entity_uuid("", entity_type, name)
        
        return ResolvedEntity(
            uuid=new_uuid,
            name=name,
            entity_type=entity_type,
            is_new=True,
            matched_uuid=None,
            match_score=match_score,
            should_update_summary=False,
        )
    
    def _select_best_name(self, new_name: str, existing_name: str) -> str:
        """
        选择最佳名称
        
        策略：选择更完整/更长的名称
        """
        if not existing_name:
            return new_name
        if not new_name:
            return existing_name
        
        # 去除空格后比较长度
        new_clean = new_name.replace(" ", "")
        existing_clean = existing_name.replace(" ", "")
        
        # 选择更长的名称（通常更完整）
        if len(new_clean) > len(existing_clean):
            return new_name
        return existing_name
    
    def resolve_batch(
        self,
        graph_id: str,
        entities: List[Dict[str, Any]],
    ) -> Dict[str, ResolvedEntity]:
        """
        批量解析实体
        
        Args:
            graph_id: 图谱 ID
            entities: 实体列表，每个实体包含 name, type, summary 等字段
            
        Returns:
            {(name:type): ResolvedEntity} 映射
        """
        results: Dict[str, ResolvedEntity] = {}
        
        for entity in entities:
            name = entity.get("name", "").strip()
            entity_type = entity.get("type", "Entity").strip()
            summary = entity.get("summary", "")
            attributes = entity.get("attributes")
            
            if not name:
                continue
            
            key = f"{name}:{entity_type}"
            result = self.resolve(graph_id, name, entity_type, summary, attributes)
            results[key] = result
        
        return results


class LLMEntityResolver:
    """
    使用 LLM 进行实体消歧
    
    当规则匹配无法确定时，使用 LLM 判断两个实体是否相同
    """
    
    def __init__(self, llm_client=None):
        """
        初始化 LLM 解析器
        
        Args:
            llm_client: LLM 客户端，如不提供则使用默认配置
        """
        if llm_client:
            self._llm = llm_client
        else:
            from ..utils.llm_client import LLMClient
            self._llm = LLMClient(
                api_key=Config.EXTRACT_API_KEY,
                base_url=Config.EXTRACT_BASE_URL,
                model=Config.EXTRACT_MODEL_NAME,
            )
    
    def disambiguate(
        self,
        new_entity: Dict[str, Any],
        candidates: List[Dict[str, Any]],
        context: str = "",
    ) -> Optional[int]:
        """
        使用 LLM 判断新实体是否与候选实体之一相同
        
        Args:
            new_entity: 新提取的实体
            candidates: 候选已有实体列表
            context: 提取上下文（消息内容）
            
        Returns:
            匹配的候选索引，如果没有匹配则返回 None
        """
        if not candidates:
            return None
        
        # 格式化候选列表
        candidates_text = "\n".join([
            f"[{i}] {c.get('name', '')} (类型: {c.get('entity_type', 'Entity')}, 摘要: {c.get('summary', '无')})"
            for i, c in enumerate(candidates)
        ])
        
        system_prompt = "你是一个判断实体是否相同的助手。"
        
        user_prompt = f"""
判断以下【新实体】是否与【候选实体】中的某一个是同一个实体。

<上下文>
{context}
</上下文>

<新实体>
名称: {new_entity.get('name', '')}
类型: {new_entity.get('type', 'Entity')}
</新实体>

<候选实体>
{candidates_text}
</候选实体>

判断规则：
- 只有当两个实体指向现实世界中同一个对象/概念时才算相同
- 相关但不同的实体不算相同
- 名称相似但代表不同个体的不算相同

请返回一个 JSON 对象：
- 如果找到匹配，返回: {{"duplicate_idx": <候选索引>}}
- 如果没有匹配，返回: {{"duplicate_idx": -1}}
"""
        
        try:
            result = self._llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            
            duplicate_idx = result.get("duplicate_idx", -1)
            if isinstance(duplicate_idx, int) and 0 <= duplicate_idx < len(candidates):
                return duplicate_idx
            return None
            
        except Exception as e:
            logger.warning(f"LLM 实体消歧失败: {e}")
            return None
