"""
本地边失效检测模块

使用 LLM 检测新事实与已有事实之间的矛盾，
将矛盾的旧边标记为失效。

参考 Graphiti 的 invalidate_edges.py 实现。
"""

from typing import Dict, List, Any, Optional

from app.config import Config
from app.utils.logger import get_logger
from app.utils.llm_client import LLMClient

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
        "SUPPORTS": {"OPPOSES", "AGAINST", "REJECTS", "CRITICIZES"},
        "OPPOSES": {"SUPPORTS", "FOR", "ENDORSES", "ADVOCATES"},
        "TRUSTS": {"DISTRUSTS", "MISTRUSTS"},
        "DISTRUSTS": {"TRUSTS"},
        "ENDORSES": {"OPPOSES", "REJECTS", "CRITICIZES"},
        "REJECTS": {"ACCEPTS", "ENDORSES", "SUPPORTS"},
        "ACCEPTS": {"REJECTS", "REFUSES"},
        "REFUSES": {"ACCEPTS", "AGREES_TO"},
        
        # 观点类
        "AGREES_WITH": {"DISAGREES_WITH", "OPPOSES"},
        "DISAGREES_WITH": {"AGREES_WITH", "SUPPORTS"},
        "CRITICIZES": {"PRAISES", "SUPPORTS", "ENDORSES"},
        "PRAISES": {"CRITICIZES", "OPPOSES"},
        
        # 社交类
        "FOLLOWS": {"UNFOLLOWS", "BLOCKS"},
        "UNFOLLOWS": {"FOLLOWS"},
        "BLOCKS": {"FOLLOWS", "UNBLOCKS"},
        "UNBLOCKS": {"BLOCKS"},
        
        # 动作类
        "JOINED": {"LEFT", "QUIT", "RESIGNED_FROM"},
        "LEFT": {"JOINED", "REJOINED"},
        "QUIT": {"JOINED", "REJOINED"},
        "RESIGNED_FROM": {"JOINED", "HIRED_BY"},
        "HIRED_BY": {"FIRED_FROM", "RESIGNED_FROM", "LEFT"},
        "FIRED_FROM": {"HIRED_BY", "WORKS_FOR"},
        
        # 商业/所有权类
        "OWNS": {"SOLD", "DIVESTED", "LOST"},
        "SOLD": {"OWNS", "ACQUIRED", "BOUGHT"},
        "ACQUIRED": {"SOLD", "DIVESTED"},
        "DIVESTED": {"ACQUIRED", "OWNS", "INVESTED_IN"},
        "INVESTED_IN": {"DIVESTED_FROM", "WITHDREW_FROM"},
        "DIVESTED_FROM": {"INVESTED_IN", "INVESTS_IN"},
        "WITHDREW_FROM": {"INVESTED_IN", "INVESTS_IN"},
        "INVESTS_IN": {"DIVESTED_FROM", "WITHDREW_FROM"},
        
        # 合作/竞争类
        "COLLABORATES_WITH": {"COMPETES_WITH", "CONFLICTS_WITH"},
        "COMPETES_WITH": {"COLLABORATES_WITH", "PARTNERS_WITH"},
        "PARTNERS_WITH": {"COMPETES_WITH", "BREAKS_WITH"},
        "WORKS_WITH": {"CONFLICTS_WITH", "OPPOSES"},
        "CONFLICTS_WITH": {"COLLABORATES_WITH", "WORKS_WITH"},
        
        # 状态变化类
        "STARTED": {"STOPPED", "ENDED", "CANCELLED"},
        "STOPPED": {"STARTED", "RESUMED", "CONTINUED"},
        "ENDED": {"STARTED", "BEGAN"},
        "BEGAN": {"ENDED", "STOPPED"},
        "CANCELLED": {"CONFIRMED", "APPROVED"},
        "CONFIRMED": {"CANCELLED", "DENIED"},
        "APPROVED": {"REJECTED", "DENIED", "CANCELLED"},
        "DENIED": {"APPROVED", "CONFIRMED"},
    }
    
    # 语义矛盾关键词对（用于检测同一关系类型中的语义矛盾）
    SEMANTIC_CONTRADICTION_PAIRS = [
        # (正面词, 反面词) - 如果旧事实包含正面词，新事实包含反面词，则矛盾
        ({"支持", "赞成", "同意", "support", "supports", "favor", "approve", "endorse"},
         {"反对", "不赞成", "不同意", "oppose", "opposes", "against", "reject", "disapprove"}),
        ({"喜欢", "喜爱", "爱", "like", "likes", "love", "loves", "enjoy"},
         {"讨厌", "厌恶", "恨", "hate", "hates", "dislike", "dislikes", "detest"}),
        ({"信任", "相信", "trust", "trusts", "believe", "believes"},
         {"不信任", "怀疑", "distrust", "distrusts", "doubt", "doubts", "mistrust"}),
        ({"合作", "协作", "collaborate", "collaborates", "cooperate", "partner"},
         {"竞争", "对抗", "compete", "competes", "rival", "conflict"}),
        ({"接受", "同意", "accept", "accepts", "agree", "agrees"},
         {"拒绝", "否决", "reject", "rejects", "refuse", "refuses", "decline"}),
        ({"加入", "join", "joins", "joined", "enter", "entered"},
         {"退出", "离开", "leave", "leaves", "left", "quit", "quits", "exit"}),
        ({"买", "购买", "收购", "buy", "buys", "bought", "acquire", "acquires", "acquired"},
         {"卖", "出售", "sell", "sells", "sold", "divest", "divests"}),
        ({"开始", "启动", "start", "starts", "started", "begin", "begins", "began", "launch"},
         {"结束", "停止", "stop", "stops", "stopped", "end", "ends", "ended", "terminate"}),
    ]
    
    def detect_contradictions(
        self,
        new_edge: Dict[str, Any],
        existing_edges: List[Dict[str, Any]],
    ) -> List[str]:
        """
        基于规则检测矛盾
        
        检测策略：
        1. 关系类型互斥：新关系与旧关系在预定义的互斥对中
        2. 语义矛盾：同一关系类型，但事实描述包含相反语义的关键词
        """
        if not existing_edges:
            return []
        
        new_source = new_edge.get("source_name", "").lower()
        new_target = new_edge.get("target_name", "").lower()
        new_relation = new_edge.get("relation_name", "").upper()
        new_fact = new_edge.get("fact", "").lower()
        
        contradicted_uuids = []
        
        # 策略1: 关系类型互斥
        contradicting = self.CONTRADICTING_RELATIONS.get(new_relation, set())
        
        for edge in existing_edges:
            edge_source = edge.get("source_name", "").lower()
            edge_target = edge.get("target_name", "").lower()
            edge_relation = edge.get("relation_name", edge.get("name", "")).upper()
            edge_fact = edge.get("fact", "").lower()
            edge_uuid = edge.get("uuid")
            
            if not edge_uuid:
                continue
            
            # 检查是否是同一对实体
            if edge_source != new_source or edge_target != new_target:
                continue
            
            # 检查关系类型互斥
            if edge_relation in contradicting:
                contradicted_uuids.append(edge_uuid)
                continue
            
            # 策略2: 语义矛盾（同一关系类型，事实语义相反）
            if edge_relation == new_relation and new_fact and edge_fact:
                if self._check_semantic_contradiction(edge_fact, new_fact):
                    contradicted_uuids.append(edge_uuid)
        
        return contradicted_uuids
    
    def _check_semantic_contradiction(self, old_fact: str, new_fact: str) -> bool:
        """
        检查两个事实描述是否存在语义矛盾
        
        Args:
            old_fact: 旧事实描述（已转小写）
            new_fact: 新事实描述（已转小写）
            
        Returns:
            是否存在语义矛盾
        """
        for positive_set, negative_set in self.SEMANTIC_CONTRADICTION_PAIRS:
            # 检查：旧事实包含正面词 + 新事实包含反面词
            old_has_positive = any(word in old_fact for word in positive_set)
            new_has_negative = any(word in new_fact for word in negative_set)
            if old_has_positive and new_has_negative:
                return True
            
            # 检查：旧事实包含反面词 + 新事实包含正面词
            old_has_negative = any(word in old_fact for word in negative_set)
            new_has_positive = any(word in new_fact for word in positive_set)
            if old_has_negative and new_has_positive:
                return True
        
        return False


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
