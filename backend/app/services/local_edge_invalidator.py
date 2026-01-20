"""
本地边失效检测模块

使用 LLM 检测新事实与已有事实之间的矛盾，
将矛盾的旧边标记为失效。

参考 Graphiti 的 invalidate_edges.py 实现。
"""

from typing import Dict, List, Any, Optional

from ..config import Config
from ..utils.logger import get_logger
from ..utils.llm_client import LLMClient

logger = get_logger("mirofish.local_edge_invalidator")


class LocalEdgeInvalidator:
    """
    使用 LLM 检测边矛盾并标记失效
    
    核心逻辑：
    1. 接收新边和已有边列表
    2. 使用 LLM 判断新边是否与已有边矛盾
    3. 返回需要失效的边 UUID 列表
    """
    
    def __init__(self, llm_client: Optional[LLMClient] = None):
        """
        初始化失效检测器
        
        Args:
            llm_client: 可选的 LLM 客户端，如不提供则使用默认配置创建
        """
        if llm_client:
            self._llm = llm_client
        else:
            # 使用 EXTRACT 系列配置（用于提取任务）
            self._llm = LLMClient(
                api_key=Config.EXTRACT_API_KEY,
                base_url=Config.EXTRACT_BASE_URL,
                model=Config.EXTRACT_MODEL_NAME,
            )
    
    def detect_contradictions(
        self,
        new_edge: Dict[str, Any],
        existing_edges: List[Dict[str, Any]],
    ) -> List[str]:
        """
        检测新边与已有边之间的矛盾
        
        Args:
            new_edge: 新边信息，包含 source_name, target_name, relation_name, fact
            existing_edges: 已有边列表，每条边包含 uuid, source_name, target_name, relation_name, fact
            
        Returns:
            需要失效的边 UUID 列表
        """
        if not existing_edges:
            return []
        
        # 格式化已有边为文本
        existing_edges_text = self._format_edges(existing_edges)
        new_edge_text = self._format_single_edge(new_edge)
        
        # 构建 prompt
        system_prompt = "你是一个专门判断事实矛盾的AI助手。"
        
        user_prompt = f"""
基于提供的【已有事实】和【新事实】，判断哪些已有事实与新事实存在矛盾。

矛盾的定义：
- 同一对实体之间，关系的语义相反（如"喜欢"与"讨厌"）
- 同一对实体之间，事实描述相互冲突（如"支持A产品"与"反对A产品"）
- 同一对实体之间，状态发生了变化（如"关注了"与"取消关注"）

不算矛盾的情况：
- 新事实是已有事实的补充或细化
- 新事实与已有事实描述不同方面
- 新事实只是新增信息，不否定已有信息

<已有事实>
{existing_edges_text}
</已有事实>

<新事实>
{new_edge_text}
</新事实>

请返回一个JSON对象，包含以下字段：
- contradicted_ids: 数组，包含所有与新事实矛盾的已有事实的ID（数字）。如果没有矛盾，返回空数组 []

示例输出：
{{"contradicted_ids": [1, 3]}}
或
{{"contradicted_ids": []}}
"""
        
        try:
            result = self._llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            
            contradicted_ids = result.get("contradicted_ids", [])
            
            # 将 ID 映射回 UUID
            contradicted_uuids = []
            for idx in contradicted_ids:
                if isinstance(idx, int) and 0 <= idx - 1 < len(existing_edges):
                    edge = existing_edges[idx - 1]  # ID 从 1 开始
                    if edge.get("uuid"):
                        contradicted_uuids.append(edge["uuid"])
            
            if contradicted_uuids:
                logger.info(f"检测到 {len(contradicted_uuids)} 条矛盾边需要失效")
                logger.debug(f"矛盾边UUIDs: {contradicted_uuids}")
            
            return contradicted_uuids
            
        except Exception as e:
            logger.warning(f"LLM 矛盾检测失败: {e}")
            return []
    
    def detect_contradictions_batch(
        self,
        new_edges: List[Dict[str, Any]],
        existing_edges: List[Dict[str, Any]],
    ) -> List[str]:
        """
        批量检测多条新边与已有边之间的矛盾
        
        Args:
            new_edges: 新边列表
            existing_edges: 已有边列表
            
        Returns:
            需要失效的边 UUID 列表（去重）
        """
        if not new_edges or not existing_edges:
            return []
        
        all_contradicted: set = set()
        
        for new_edge in new_edges:
            contradicted = self.detect_contradictions(new_edge, existing_edges)
            all_contradicted.update(contradicted)
        
        return list(all_contradicted)
    
    def _format_edges(self, edges: List[Dict[str, Any]]) -> str:
        """格式化边列表为文本"""
        lines = []
        for i, edge in enumerate(edges, 1):
            line = self._format_single_edge(edge, i)
            lines.append(line)
        return "\n".join(lines)
    
    def _format_single_edge(self, edge: Dict[str, Any], idx: Optional[int] = None) -> str:
        """格式化单条边为文本"""
        source = edge.get("source_name", edge.get("source", "?"))
        target = edge.get("target_name", edge.get("target", "?"))
        relation = edge.get("relation_name", edge.get("name", "RELATED_TO"))
        fact = edge.get("fact", "")
        
        if idx is not None:
            if fact:
                return f"[{idx}] {source} --{relation}--> {target}: {fact}"
            return f"[{idx}] {source} --{relation}--> {target}"
        else:
            if fact:
                return f"{source} --{relation}--> {target}: {fact}"
            return f"{source} --{relation}--> {target}"


class RuleBasedEdgeInvalidator:
    """
    基于规则的边失效检测器（不使用 LLM）
    
    用于快速检测明显的矛盾关系，适用于：
    1. 高频场景，减少 LLM 调用
    2. 离线场景
    3. 预筛选后再用 LLM 精确判断
    """
    
    # 互斥关系对
    CONTRADICTING_RELATIONS = {
        # 情感类
        "LIKES": {"DISLIKES", "HATES", "OPPOSES"},
        "DISLIKES": {"LIKES", "LOVES", "SUPPORTS"},
        "LOVES": {"HATES", "DISLIKES"},
        "HATES": {"LOVES", "LIKES"},
        
        # 态度类
        "SUPPORTS": {"OPPOSES", "AGAINST", "REJECTS"},
        "OPPOSES": {"SUPPORTS", "FOR", "ENDORSES"},
        "TRUSTS": {"DISTRUSTS", "MISTRUSTS"},
        "DISTRUSTS": {"TRUSTS"},
        
        # 观点类
        "AGREES_WITH": {"DISAGREES_WITH", "OPPOSES"},
        "DISAGREES_WITH": {"AGREES_WITH", "SUPPORTS"},
        
        # 社交类
        "FOLLOWS": {"UNFOLLOWS", "BLOCKS"},
        "UNFOLLOWS": {"FOLLOWS"},
        "BLOCKS": {"FOLLOWS", "UNBLOCKS"},
        "UNBLOCKS": {"BLOCKS"},
        
        # 动作类
        "JOINED": {"LEFT", "QUIT"},
        "LEFT": {"JOINED", "REJOINED"},
    }
    
    def detect_contradictions(
        self,
        new_edge: Dict[str, Any],
        existing_edges: List[Dict[str, Any]],
    ) -> List[str]:
        """
        基于规则检测矛盾
        
        只检测同一对实体之间的互斥关系
        """
        if not existing_edges:
            return []
        
        new_source = new_edge.get("source_name", "").lower()
        new_target = new_edge.get("target_name", "").lower()
        new_relation = new_edge.get("relation_name", "").upper()
        
        contradicting = self.CONTRADICTING_RELATIONS.get(new_relation, set())
        if not contradicting:
            return []
        
        contradicted_uuids = []
        
        for edge in existing_edges:
            edge_source = edge.get("source_name", "").lower()
            edge_target = edge.get("target_name", "").lower()
            edge_relation = edge.get("relation_name", edge.get("name", "")).upper()
            
            # 检查是否是同一对实体
            if edge_source == new_source and edge_target == new_target:
                if edge_relation in contradicting:
                    if edge.get("uuid"):
                        contradicted_uuids.append(edge["uuid"])
        
        return contradicted_uuids


class HybridEdgeInvalidator:
    """
    混合边失效检测器
    
    先使用规则快速筛选，再用 LLM 精确判断
    """
    
    def __init__(self, llm_client: Optional[LLMClient] = None):
        self._rule_based = RuleBasedEdgeInvalidator()
        self._llm_based = LocalEdgeInvalidator(llm_client)
    
    def detect_contradictions(
        self,
        new_edge: Dict[str, Any],
        existing_edges: List[Dict[str, Any]],
        use_llm: bool = True,
    ) -> List[str]:
        """
        混合检测矛盾
        
        Args:
            new_edge: 新边
            existing_edges: 已有边
            use_llm: 是否使用 LLM 进行精确判断
            
        Returns:
            需要失效的边 UUID 列表
        """
        # 先用规则快速检测
        rule_result = self._rule_based.detect_contradictions(new_edge, existing_edges)
        
        if not use_llm:
            return rule_result
        
        # 如果规则检测到了矛盾，直接返回
        if rule_result:
            return rule_result
        
        # 否则用 LLM 进行更精确的判断
        return self._llm_based.detect_contradictions(new_edge, existing_edges)
