"""
模拟配置智能生成器
使用LLM根据模拟需求、文档内容、图谱信息自动生成细致的模拟参数
实现全程自动化，无需人工设置参数

采用分步生成策略，避免一次性生成过长内容导致失败：
1. 生成时间配置
2. 生成事件配置
3. 分批生成Agent配置
4. 生成平台配置
"""

import json
import math
import re
import time
from typing import Dict, Any, Iterable, List, Optional, Callable
from dataclasses import dataclass, field, asdict
from datetime import datetime

import httpx
from openai import APITimeoutError, OpenAI

from ..config import Config
from ..utils.logger import get_logger
from ..utils.locale import get_language_instruction, get_locale, t
from ..utils.llm_client import clean_chat_text
from ..utils.openai_chat_compat import create_chat_completion, extract_chat_completion_text
from .zep_entity_reader import EntityNode, ZepEntityReader

logger = get_logger('mirofish.simulation_config')

# 中国作息时间配置（北京时间）
CHINA_TIMEZONE_CONFIG = {
    # 深夜时段（几乎无人活动）
    "dead_hours": [0, 1, 2, 3, 4, 5],
    # 早间时段（逐渐醒来）
    "morning_hours": [6, 7, 8],
    # 工作时段
    "work_hours": [9, 10, 11, 12, 13, 14, 15, 16, 17, 18],
    # 晚间高峰（最活跃）
    "peak_hours": [19, 20, 21, 22],
    # 夜间时段（活跃度下降）
    "night_hours": [23],
    # 活跃度系数
    "activity_multipliers": {
        "dead": 0.05,      # 凌晨几乎无人
        "morning": 0.4,    # 早间逐渐活跃
        "work": 0.7,       # 工作时段中等
        "peak": 1.5,       # 晚间高峰
        "night": 0.5       # 深夜下降
    }
}


@dataclass
class AgentActivityConfig:
    """单个Agent的活动配置"""
    agent_id: int
    entity_uuid: str
    entity_name: str
    entity_type: str
    
    # 活跃度配置 (0.0-1.0)
    activity_level: float = 0.5  # 整体活跃度
    
    # 发言频率（每小时预期发言次数）
    posts_per_hour: float = 1.0
    comments_per_hour: float = 2.0
    
    # 活跃时间段（24小时制，0-23）
    active_hours: List[int] = field(default_factory=lambda: list(range(8, 23)))
    
    # 响应速度（对热点事件的反应延迟，单位：模拟分钟）
    response_delay_min: int = 5
    response_delay_max: int = 60
    
    # 情感倾向 (-1.0到1.0，负面到正面)
    sentiment_bias: float = 0.0
    
    # 立场（对特定话题的态度）
    stance: str = "neutral"  # supportive, opposing, neutral, observer
    
    # 影响力权重（决定其发言被其他Agent看到的概率）
    influence_weight: float = 1.0


@dataclass  
class TimeSimulationConfig:
    """时间模拟配置（基于中国人作息习惯）"""
    # 模拟总时长（模拟小时数）
    total_simulation_hours: int = 72  # 默认模拟72小时（3天）
    
    # 每轮代表的时间（模拟分钟）- 默认60分钟（1小时），加快时间流速
    minutes_per_round: int = 60
    
    # 每小时激活的Agent数量范围
    agents_per_hour_min: int = 5
    agents_per_hour_max: int = 20
    
    # 高峰时段（晚间19-22点，中国人最活跃的时间）
    peak_hours: List[int] = field(default_factory=lambda: [19, 20, 21, 22])
    peak_activity_multiplier: float = 1.5
    
    # 低谷时段（凌晨0-5点，几乎无人活动）
    off_peak_hours: List[int] = field(default_factory=lambda: [0, 1, 2, 3, 4, 5])
    off_peak_activity_multiplier: float = 0.05  # 凌晨活跃度极低
    
    # 早间时段
    morning_hours: List[int] = field(default_factory=lambda: [6, 7, 8])
    morning_activity_multiplier: float = 0.4
    
    # 工作时段
    work_hours: List[int] = field(default_factory=lambda: [9, 10, 11, 12, 13, 14, 15, 16, 17, 18])
    work_activity_multiplier: float = 0.7


@dataclass
class EventConfig:
    """事件配置"""
    # 初始事件（模拟开始时的触发事件）
    initial_posts: List[Dict[str, Any]] = field(default_factory=list)

    # 定时事件（用户编写的、在特定模拟小时触发的发帖）。
    # 生成器永远不会自动填入：让LLM凭空编造未来事件，会把虚构的事实注入预测。
    # 条目格式：{"id", "at_sim_hour", "poster_agent_id", "poster_type", "content",
    #            "source": "user|llm_suggested", "enabled"}
    scheduled_events: List[Dict[str, Any]] = field(default_factory=list)

    # LLM 给出的候选事件（最多3条）。始终是 enabled=False、source="llm_suggested"，
    # 仅供用户参考/采纳，绝不会被运行器执行。
    suggested_events: List[Dict[str, Any]] = field(default_factory=list)

    # 热点话题关键词（运行时仅用于指标中的关键词提及统计，不会注入Agent）
    hot_topics: List[str] = field(default_factory=list)

    # 议题短语（≤15词），用于 Agent 的行为指令（"关于<议题>，你目前倾向..."）
    topic: str = ""

    # 生成器对舆论走向的"假设"。不会给到任何 Agent（否则预测会变成循环论证），
    # 只作为待检验的假设交给报告 Agent。
    narrative_direction: str = ""


@dataclass
class PlatformConfig:
    """平台特定配置

    recency_weight / popularity_weight / relevance_weight / viral_threshold 只是为了
    能读取旧配置而保留：OASIS 的推荐系统没有这些旋钮，运行器从不读取它们，所以 v2
    配置不再生成它们。echo_chamber_strength 现在真正生效（决定播种关注图的同立场聚集度）。
    """
    platform: str  # twitter or reddit

    # 推荐算法权重（旧配置，v2 不再生成）
    recency_weight: float = 0.4  # 时间新鲜度
    popularity_weight: float = 0.3  # 热度
    relevance_weight: float = 0.3  # 相关性

    # 病毒传播阈值（旧配置，v2 不再生成）
    viral_threshold: int = 10

    # 回声室效应强度（相似观点聚集程度，决定播种关注图的同立场偏好）
    echo_chamber_strength: float = 0.5


#: 平台配置里仅旧版本才有的键（v2 配置不输出）
LEGACY_PLATFORM_KEYS = ("recency_weight", "popularity_weight", "relevance_weight", "viral_threshold")

#: 当前生成器输出的行为版本（运行器据此决定使用 v1 还是 v2 语义）
CURRENT_BEHAVIOR_VERSION = 2

VALID_STANCES = ("supportive", "opposing", "neutral", "observer")
TOPIC_MAX_WORDS = 15
TOPIC_MAX_CHARS = 120
MAX_SUGGESTED_EVENTS = 3


@dataclass
class SimulationParameters:
    """完整的模拟参数配置"""
    # 基础信息
    simulation_id: str
    project_id: str
    graph_id: str
    simulation_requirement: str
    
    # 时间配置
    time_config: TimeSimulationConfig = field(default_factory=TimeSimulationConfig)
    
    # Agent配置列表
    agent_configs: List[AgentActivityConfig] = field(default_factory=list)
    
    # 事件配置
    event_config: EventConfig = field(default_factory=EventConfig)
    
    # 平台配置
    twitter_config: Optional[PlatformConfig] = None
    reddit_config: Optional[PlatformConfig] = None
    
    # LLM配置
    llm_model: str = ""
    llm_base_url: str = ""

    # 生成元数据
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    generation_reasoning: str = ""  # LLM的推理说明

    # 行为版本：缺省/低于2 的配置按旧语义运行（见 scripts/sim_behavior.py）
    behavior_version: int = CURRENT_BEHAVIOR_VERSION
    # 生成配置时的界面语言；行为指令使用同一种语言
    locale: str = ""
    # 运行块：种子等在启动时写入（scripts 与 SimulationRunner 共用）
    run: Dict[str, Any] = field(default_factory=lambda: {
        "seed": None,
        "replicate_index": None,
        "ensemble_id": None,
    })

    def _platform_dict(self, platform_config: Optional[PlatformConfig]) -> Optional[Dict[str, Any]]:
        if platform_config is None:
            return None
        data = asdict(platform_config)
        if self.behavior_version >= CURRENT_BEHAVIOR_VERSION:
            # 这些旋钮在 OASIS 里不存在，运行器从不读取，所以不再输出
            for key in LEGACY_PLATFORM_KEYS:
                data.pop(key, None)
        return data

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        time_dict = asdict(self.time_config)
        return {
            "simulation_id": self.simulation_id,
            "project_id": self.project_id,
            "graph_id": self.graph_id,
            "simulation_requirement": self.simulation_requirement,
            "behavior_version": self.behavior_version,
            "locale": self.locale,
            "run": dict(self.run),
            "time_config": time_dict,
            "agent_configs": [asdict(a) for a in self.agent_configs],
            "event_config": asdict(self.event_config),
            "twitter_config": self._platform_dict(self.twitter_config),
            "reddit_config": self._platform_dict(self.reddit_config),
            "llm_model": self.llm_model,
            "llm_base_url": self.llm_base_url,
            "generated_at": self.generated_at,
            "generation_reasoning": self.generation_reasoning,
        }
    
    def to_json(self, indent: int = 2) -> str:
        """转换为JSON字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


#: 清洗后的 Agent 字段默认值（LLM 漏填或填错时使用）
AGENT_FIELD_DEFAULTS = {
    "activity_level": 0.5,
    "posts_per_hour": 0.5,
    "comments_per_hour": 1.0,
    "response_delay_min": 5,
    "response_delay_max": 60,
    "sentiment_bias": 0.0,
    "stance": "neutral",
    "influence_weight": 1.0,
}
DEFAULT_ACTIVE_HOURS = list(range(9, 23))
#: 每小时发帖/评论频率上限（再大也没有意义：激活概率本来就封顶 0.95）
MAX_RATE_PER_HOUR = 100.0


def _as_float(value: Any, default: float) -> float:
    """宽松地转成有限浮点数；失败返回默认值"""
    if isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(number) or math.isinf(number):
        return default
    return number


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _sanitize_agent_config(cfg: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """校验并钳制 LLM（或规则）生成的 Agent 行为字段。

    运行器现在会真正使用这些字段，所以坏值（超范围的情感倾向、未知的立场、
    min > max 的响应延迟 ...）必须在这里被修正，而不是进入模拟。

    - stance 必须是 supportive/opposing/neutral/observer，否则为 neutral
    - activity_level 在 [0, 1]；sentiment_bias 在 [-1, 1]；influence_weight 在 [0.1, 5]
    - posts_per_hour / comments_per_hour >= 0
    - 0 <= response_delay_min <= response_delay_max（分钟）
    - active_hours 是 0-23 的整数列表（空/非法则用默认时段）
    """
    cfg = cfg or {}
    d = AGENT_FIELD_DEFAULTS

    stance = str(cfg.get("stance") or d["stance"]).strip().lower()
    if stance not in VALID_STANCES:
        stance = d["stance"]

    delay_min = max(0.0, _as_float(cfg.get("response_delay_min"), d["response_delay_min"]))
    delay_max = max(delay_min, _as_float(cfg.get("response_delay_max"), d["response_delay_max"]))

    raw_hours = cfg.get("active_hours")
    hours = set()
    if isinstance(raw_hours, (list, tuple, set)):
        for hour in raw_hours:
            number = _as_float(hour, -1)
            if number == int(number) and 0 <= number <= 23:
                hours.add(int(number))
    active_hours = sorted(hours) if hours else list(DEFAULT_ACTIVE_HOURS)

    return {
        "activity_level": _clamp(_as_float(cfg.get("activity_level"), d["activity_level"]), 0.0, 1.0),
        "posts_per_hour": _clamp(_as_float(cfg.get("posts_per_hour"), d["posts_per_hour"]), 0.0, MAX_RATE_PER_HOUR),
        "comments_per_hour": _clamp(_as_float(cfg.get("comments_per_hour"), d["comments_per_hour"]), 0.0, MAX_RATE_PER_HOUR),
        "active_hours": active_hours,
        "response_delay_min": int(round(delay_min)),
        "response_delay_max": int(round(delay_max)),
        "sentiment_bias": _clamp(_as_float(cfg.get("sentiment_bias"), d["sentiment_bias"]), -1.0, 1.0),
        "stance": stance,
        "influence_weight": _clamp(_as_float(cfg.get("influence_weight"), d["influence_weight"]), 0.1, 5.0),
    }


def clean_topic(topic: Any, simulation_requirement: str) -> str:
    """议题短语：≤15个词、≤120个字符；LLM 没给出可用值时退回需求原文的前120个字符。"""
    if isinstance(topic, str):
        words = topic.split()
        if words:
            cleaned = " ".join(words[:TOPIC_MAX_WORDS])
            return cleaned[:TOPIC_MAX_CHARS].strip()
    return (simulation_requirement or "").strip()[:TOPIC_MAX_CHARS]


def sanitize_suggested_events(
    events: Any, total_hours: float
) -> List[Dict[str, Any]]:
    """把 LLM 给出的候选事件清洗成最多3条、禁用、来源为 llm_suggested 的条目。"""
    if not isinstance(events, list):
        return []
    last_hour = max(0.0, float(total_hours or 0) - 1)
    cleaned: List[Dict[str, Any]] = []
    for item in events:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        hour = _clamp(_as_float(item.get("at_sim_hour"), 0.0), 0.0, last_hour)
        cleaned.append({
            "id": f"sug_{len(cleaned) + 1}",
            "at_sim_hour": int(hour) if hour == int(hour) else hour,
            "poster_type": str(item.get("poster_type") or "Unknown"),
            "content": content.strip(),
            "source": "llm_suggested",
            "enabled": False,
        })
        if len(cleaned) >= MAX_SUGGESTED_EVENTS:
            break
    return cleaned


def _agent_field(agent: Any, name: str, default: Any = None) -> Any:
    """读取 Agent 配置字段（兼容 dataclass 对象和字典）"""
    if isinstance(agent, dict):
        return agent.get(name, default)
    return getattr(agent, name, default)


# 配置里的 LLM_REQUEST_TIMEOUT 无效（<=0）时使用
DEFAULT_LLM_REQUEST_TIMEOUT = 300.0

# 太短的字符串（如 "gov"）做包含匹配会误伤别的类型/实体，只对不短于此长度的字符串启用
MIN_FUZZY_MATCH_CHARS = 5

# 类型映射表（处理 LLM 可能输出的不同格式）；键和值都是 _compact() 之后的形式
POSTER_TYPE_ALIASES = {
    "official": ["official", "university", "governmentagency", "government"],
    "university": ["university", "official"],
    "mediaoutlet": ["mediaoutlet", "media"],
    "student": ["student", "person"],
    "professor": ["professor", "expert", "teacher"],
    "alumni": ["alumni", "person"],
    "organization": ["organization", "ngo", "company", "group"],
    "person": ["person", "student", "alumni"],
}


def _compact(text: Any) -> str:
    """小写并去掉空格、下划线和标点，使 'Government Official'、'government_official'、'GovernmentOfficial' 相等"""
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(text or "").lower())


def _long_enough(compact_text: str) -> bool:
    """包含匹配的最短长度（汉字信息密度高，2个字即可）"""
    if re.search(r"[\u4e00-\u9fff]", compact_text):
        return len(compact_text) >= 2
    return len(compact_text) >= MIN_FUZZY_MATCH_CHARS


def _match_by_entity_name(
    poster_type: str, agent_configs: List[Any], exact_only: bool
) -> Optional[Any]:
    """poster_type 写成了某个实体的名字（模型经常这样做）时，直接选中那个实体；返回 agent_id"""
    best = None
    best_score = 0
    for agent in agent_configs:
        name = _compact(_agent_field(agent, "entity_name", ""))
        if not name:
            continue
        if name == poster_type:
            score = 3
        elif (
            not exact_only
            and _long_enough(min(name, poster_type, key=len))
            and (name in poster_type or poster_type in name)
        ):
            score = 2
        else:
            continue
        if score > best_score:  # 分数相同时先出现的 Agent 优先
            best, best_score = agent, score
    return None if best is None else _agent_field(best, "agent_id")


def _match_type_by_containment(
    poster_type: str, agents_by_type: Dict[str, List[Any]]
) -> Optional[str]:
    """'official' 对 'governmentofficial'、'corporate' 对 'corporateentity' 这类包含关系；返回类型键"""
    for type_key in agents_by_type:
        if not type_key:
            continue
        if (
            _long_enough(min(type_key, poster_type, key=len))
            and (type_key in poster_type or poster_type in type_key)
        ):
            return type_key
    return None


def assign_poster_agents(
    posts: List[Dict[str, Any]],
    agent_configs: List[Any],
    preserve_fields: bool = False,
) -> List[Dict[str, Any]]:
    """
    为帖子/事件分配发布者 Agent（根据 poster_type 匹配最合适的 agent_id）

    初始帖子、候选事件和用户新增的定时事件共用这一套匹配逻辑。agent_configs 可以是
    AgentActivityConfig 对象，也可以是 simulation_config.json 里的字典。
    preserve_fields=False 时只保留 content / poster_type / poster_agent_id（初始帖子的旧格式）；
    为 True 时保留条目的所有其他字段。

    匹配顺序（大小写、空格、下划线都不敏感）：
    1. 与某个实体类型完全相同（同类型有多个 Agent 时轮流使用）
    2. 别名（如 Media -> MediaOutlet）
    3. 与某个实体名称完全相同
    4. 与某个实体类型互相包含（如 Official -> GovernmentOfficial）
    5. 与某个实体名称互相包含（如 'Department of Telecommunications' -> 'Department of Telecommunications (DoT)'）
    6. 都不匹配时，按影响力从高到低轮流选 Agent，而不是让所有帖子都落在同一个 Agent 上
    """
    if not posts:
        return []

    # 按实体类型建立 agent 索引
    agents_by_type: Dict[str, List[Any]] = {}
    for agent in agent_configs:
        etype = _compact(_agent_field(agent, "entity_type", ""))
        agents_by_type.setdefault(etype, []).append(agent)

    # 影响力从高到低；权重相同时保持原有顺序
    by_influence = sorted(
        agent_configs,
        key=lambda a: _as_float(_agent_field(a, "influence_weight", 1.0), 1.0),
        reverse=True,
    )

    # 记录每种类型已使用的 agent 索引，避免重复使用同一个 agent
    used_indices: Dict[str, int] = {}
    fallback_count = 0

    def take_from_type(type_key: str) -> Any:
        agents = agents_by_type[type_key]
        idx = used_indices.get(type_key, 0) % len(agents)
        used_indices[type_key] = idx + 1
        return _agent_field(agents[idx], "agent_id")

    updated_posts = []
    for post in posts:
        raw_type = post.get("poster_type", "") or ""
        poster_type = _compact(raw_type)
        content = post.get("content", "")

        matched_agent_id = None

        if poster_type:
            # 1. 直接匹配
            if poster_type in agents_by_type:
                matched_agent_id = take_from_type(poster_type)

            # 2. 使用别名匹配
            if matched_agent_id is None:
                for alias_key, aliases in POSTER_TYPE_ALIASES.items():
                    if poster_type in aliases or alias_key == poster_type:
                        for alias in aliases:
                            if alias in agents_by_type:
                                matched_agent_id = take_from_type(alias)
                                break
                    if matched_agent_id is not None:
                        break

            # 3. 写成了实体名称
            if matched_agent_id is None:
                matched_agent_id = _match_by_entity_name(poster_type, agent_configs, exact_only=True)

            # 4. 与实体类型互相包含
            if matched_agent_id is None:
                type_key = _match_type_by_containment(poster_type, agents_by_type)
                if type_key is not None:
                    matched_agent_id = take_from_type(type_key)

            # 5. 与实体名称互相包含
            if matched_agent_id is None:
                matched_agent_id = _match_by_entity_name(poster_type, agent_configs, exact_only=False)

        # 6. 仍未找到：按影响力轮流选择
        if matched_agent_id is None:
            if by_influence:
                matched_agent_id = _agent_field(by_influence[fallback_count % len(by_influence)], "agent_id")
                fallback_count += 1
            else:
                matched_agent_id = 0
            known_types = sorted({
                str(_agent_field(a, "entity_type", "") or "") for a in agent_configs
            })
            logger.warning(
                f"未找到类型 '{raw_type}' 的匹配 Agent（可用类型: {', '.join(known_types)}），"
                f"改用影响力排名靠前的 Agent {matched_agent_id}"
            )

        if preserve_fields:
            updated = dict(post)
            updated["poster_agent_id"] = matched_agent_id
        else:
            updated = {
                "content": content,
                "poster_type": post.get("poster_type", "Unknown"),
                "poster_agent_id": matched_agent_id,
            }
        updated_posts.append(updated)

        logger.info(f"帖子分配: poster_type='{raw_type}' -> agent_id={matched_agent_id}")

    return updated_posts


# --- 模型返回的 Agent 配置 -----------------------------------------------------

def _as_agent_id(value: Any) -> Optional[int]:
    """模型返回的 agent_id 可能是 3、3.0 或 "3"；其他情况（含缺失、布尔值）返回 None"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and re.fullmatch(r"\s*\d+\s*", value):
        return int(value)
    return None


def index_agent_configs(result: Any, expected_ids: Iterable[int]) -> Dict[int, Dict[str, Any]]:
    """
    把模型返回的 agent_configs 按 agent_id 建索引。

    不是对象、缺少 agent_id、或 agent_id 不属于本批 Agent 的条目只会被丢弃，其余条目照常使用；
    丢弃条目对应的 Agent 之后由规则生成配置，而不是让整批配置作废。
    """
    entries = result.get("agent_configs") if isinstance(result, dict) else None
    if not isinstance(entries, list):
        return {}
    expected = set(expected_ids)
    indexed: Dict[int, Dict[str, Any]] = {}
    dropped = 0
    for entry in entries:
        agent_id = _as_agent_id(entry.get("agent_id")) if isinstance(entry, dict) else None
        if agent_id is None or agent_id not in expected:
            dropped += 1
            continue
        indexed[agent_id] = entry
    if dropped:
        logger.warning(f"模型返回的 agent_configs 中有 {dropped} 个条目缺少有效的 agent_id，已忽略")
    return indexed


class SimulationConfigGenerator:
    """
    模拟配置智能生成器
    
    使用LLM分析模拟需求、文档内容、图谱实体信息，
    自动生成最佳的模拟参数配置
    
    采用分步生成策略：
    1. 生成时间配置和事件配置（轻量级）
    2. 分批生成Agent配置（每批10-20个）
    3. 生成平台配置
    """
    
    # 上下文最大字符数
    MAX_CONTEXT_LENGTH = 50000
    # 每批生成的Agent数量
    AGENTS_PER_BATCH = 15
    
    # 各步骤的上下文截断长度（字符数）
    TIME_CONFIG_CONTEXT_LENGTH = 10000   # 时间配置
    EVENT_CONFIG_CONTEXT_LENGTH = 8000   # 事件配置
    ENTITY_SUMMARY_LENGTH = 300          # 实体摘要
    AGENT_SUMMARY_LENGTH = 300           # Agent配置中的实体摘要
    ENTITIES_PER_TYPE_DISPLAY = 20       # 每类实体显示数量
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None,
        request_timeout: Optional[float] = None,
    ):
        prep = Config.prep_llm()
        self.api_key = api_key or prep["api_key"]
        self.base_url = base_url or prep["base_url"]
        self.model_name = model_name or prep["model_name"]
        timeout = float(request_timeout or Config.LLM_REQUEST_TIMEOUT)
        self.request_timeout = timeout if timeout > 0 else DEFAULT_LLM_REQUEST_TIMEOUT
        # 供界面显示重试/等待状态；由 generate_config 设置
        self._status_note: Optional[Callable[[str], None]] = None

        if not self.api_key:
            raise ValueError("LLM_API_KEY 未配置")

        # 单次请求最长等待 request_timeout 秒；SDK 自带的静默重试关闭，
        # 由 _call_llm_with_retry 自己重试并把原因写进日志和进度信息
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=httpx.Timeout(self.request_timeout, connect=min(15.0, self.request_timeout)),
            max_retries=0,
        )
    
    def generate_config(
        self,
        simulation_id: str,
        project_id: str,
        graph_id: str,
        simulation_requirement: str,
        document_text: str,
        entities: List[EntityNode],
        enable_twitter: bool = True,
        enable_reddit: bool = True,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> SimulationParameters:
        """
        智能生成完整的模拟配置（分步生成）
        
        Args:
            simulation_id: 模拟ID
            project_id: 项目ID
            graph_id: 图谱ID
            simulation_requirement: 模拟需求描述
            document_text: 原始文档内容
            entities: 过滤后的实体列表
            enable_twitter: 是否启用Twitter
            enable_reddit: 是否启用Reddit
            progress_callback: 进度回调函数(current_step, total_steps, message)
            
        Returns:
            SimulationParameters: 完整的模拟参数
        """
        logger.info(f"开始智能生成模拟配置: simulation_id={simulation_id}, 实体数={len(entities)}")
        
        # 计算总步骤数
        num_batches = math.ceil(len(entities) / self.AGENTS_PER_BATCH)
        total_steps = 3 + num_batches  # 时间配置 + 事件配置 + N批Agent + 平台配置
        current_step = 0
        current_message = ""

        def report_progress(step: int, message: str):
            nonlocal current_step, current_message
            current_step = step
            current_message = message
            if progress_callback:
                progress_callback(step, total_steps, message)
            logger.info(f"[{step}/{total_steps}] {message}")

        def report_wait_note(note: str):
            """同一步骤内的状态（例如模型超时后重试），只更新进度信息"""
            if progress_callback:
                progress_callback(current_step, total_steps, f"{current_message} ({note})")

        self._status_note = report_wait_note
        
        # 1. 构建基础上下文信息
        context = self._build_context(
            simulation_requirement=simulation_requirement,
            document_text=document_text,
            entities=entities
        )
        
        reasoning_parts = []
        
        # ========== 步骤1: 生成时间配置 ==========
        report_progress(1, t('progress.generatingTimeConfig'))
        num_entities = len(entities)
        time_config_result = self._generate_time_config(context, num_entities)
        time_config = self._parse_time_config(time_config_result, num_entities)
        reasoning_parts.append(f"{t('progress.timeConfigLabel')}: {time_config_result.get('reasoning', t('common.success'))}")
        
        # ========== 步骤2: 生成事件配置 ==========
        report_progress(2, t('progress.generatingEventConfig'))
        event_config_result = self._generate_event_config(context, simulation_requirement, entities)
        event_config = self._parse_event_config(
            event_config_result,
            simulation_requirement=simulation_requirement,
            total_hours=time_config.total_simulation_hours,
        )
        reasoning_parts.append(f"{t('progress.eventConfigLabel')}: {event_config_result.get('reasoning', t('common.success'))}")
        
        # ========== 步骤3-N: 分批生成Agent配置 ==========
        all_agent_configs = []
        for batch_idx in range(num_batches):
            start_idx = batch_idx * self.AGENTS_PER_BATCH
            end_idx = min(start_idx + self.AGENTS_PER_BATCH, len(entities))
            batch_entities = entities[start_idx:end_idx]
            
            report_progress(
                3 + batch_idx,
                t('progress.generatingAgentConfig', start=start_idx + 1, end=end_idx, total=len(entities))
            )
            
            batch_configs = self._generate_agent_configs_batch(
                context=context,
                entities=batch_entities,
                start_idx=start_idx,
                simulation_requirement=simulation_requirement
            )
            all_agent_configs.extend(batch_configs)
        
        reasoning_parts.append(t('progress.agentConfigResult', count=len(all_agent_configs)))
        
        # ========== 为初始帖子分配发布者 Agent ==========
        logger.info("为初始帖子分配合适的发布者 Agent...")
        event_config = self._assign_initial_post_agents(event_config, all_agent_configs)
        # 候选事件同样提前匹配好发布者，用户采纳时无需再选
        event_config.suggested_events = assign_poster_agents(
            event_config.suggested_events, all_agent_configs, preserve_fields=True
        )
        assigned_count = len([p for p in event_config.initial_posts if p.get("poster_agent_id") is not None])
        reasoning_parts.append(t('progress.postAssignResult', count=assigned_count))
        
        # ========== 最后一步: 生成平台配置 ==========
        report_progress(total_steps, t('progress.generatingPlatformConfig'))
        twitter_config = None
        reddit_config = None
        
        if enable_twitter:
            twitter_config = PlatformConfig(
                platform="twitter",
                recency_weight=0.4,
                popularity_weight=0.3,
                relevance_weight=0.3,
                viral_threshold=10,
                echo_chamber_strength=0.5
            )
        
        if enable_reddit:
            reddit_config = PlatformConfig(
                platform="reddit",
                recency_weight=0.3,
                popularity_weight=0.4,
                relevance_weight=0.3,
                viral_threshold=15,
                echo_chamber_strength=0.6
            )
        
        # 构建最终参数
        params = SimulationParameters(
            simulation_id=simulation_id,
            project_id=project_id,
            graph_id=graph_id,
            simulation_requirement=simulation_requirement,
            time_config=time_config,
            agent_configs=all_agent_configs,
            event_config=event_config,
            twitter_config=twitter_config,
            reddit_config=reddit_config,
            llm_model=self.model_name,
            llm_base_url=self.base_url,
            generation_reasoning=" | ".join(reasoning_parts),
            behavior_version=CURRENT_BEHAVIOR_VERSION,
            locale=get_locale(),
        )
        
        logger.info(f"模拟配置生成完成: {len(params.agent_configs)} 个Agent配置")

        self._status_note = None
        return params
    
    def _build_context(
        self,
        simulation_requirement: str,
        document_text: str,
        entities: List[EntityNode]
    ) -> str:
        """构建LLM上下文，截断到最大长度"""
        
        # 实体摘要
        entity_summary = self._summarize_entities(entities)
        
        # 构建上下文
        context_parts = [
            f"## 模拟需求\n{simulation_requirement}",
            f"\n## 实体信息 ({len(entities)}个)\n{entity_summary}",
        ]
        
        current_length = sum(len(p) for p in context_parts)
        remaining_length = self.MAX_CONTEXT_LENGTH - current_length - 500  # 留500字符余量
        
        if remaining_length > 0 and document_text:
            doc_text = document_text[:remaining_length]
            if len(document_text) > remaining_length:
                doc_text += "\n...(文档已截断)"
            context_parts.append(f"\n## 原始文档内容\n{doc_text}")
        
        return "\n".join(context_parts)
    
    def _summarize_entities(self, entities: List[EntityNode]) -> str:
        """生成实体摘要"""
        lines = []
        
        # 按类型分组
        by_type: Dict[str, List[EntityNode]] = {}
        for e in entities:
            t = e.get_entity_type() or "Unknown"
            if t not in by_type:
                by_type[t] = []
            by_type[t].append(e)
        
        for entity_type, type_entities in by_type.items():
            lines.append(f"\n### {entity_type} ({len(type_entities)}个)")
            # 使用配置的显示数量和摘要长度
            display_count = self.ENTITIES_PER_TYPE_DISPLAY
            summary_len = self.ENTITY_SUMMARY_LENGTH
            for e in type_entities[:display_count]:
                summary_preview = (e.summary[:summary_len] + "...") if len(e.summary) > summary_len else e.summary
                lines.append(f"- {e.name}: {summary_preview}")
            if len(type_entities) > display_count:
                lines.append(f"  ... 还有 {len(type_entities) - display_count} 个")
        
        return "\n".join(lines)
    
    # 重试前的停顿（秒）；服务商限流（HTTP 402/429）时多等一会儿
    RETRY_PAUSES = (2, 4)
    THROTTLED_RETRY_PAUSES = (5, 15)

    def _note(self, text: str) -> None:
        """把状态写进进度信息；进度汇报出错绝不能影响配置生成"""
        if self._status_note is None:
            return
        try:
            self._status_note(text)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug(f"进度信息更新失败: {exc}")

    def _call_llm_with_retry(self, prompt: str, system_prompt: str) -> Dict[str, Any]:
        """带重试的LLM调用，包含JSON修复逻辑。单次请求最多等待 request_timeout 秒。"""
        max_attempts = 3
        last_error = None
        reason = ""
        pauses = self.RETRY_PAUSES

        for attempt in range(max_attempts):
            if attempt:
                self._note(t('progress.llmRetrying', attempt=attempt + 1, total=max_attempts, reason=reason))
            logger.info(
                f"调用模型生成配置 (第 {attempt + 1}/{max_attempts} 次，最长等待 {self.request_timeout:.0f} 秒)"
            )
            started = time.monotonic()
            try:
                response = create_chat_completion(
                    self.client,
                    model=self.model_name,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.7 - (attempt * 0.1),  # 每次重试降低温度
                    # 不设置max_tokens，让LLM自由发挥
                )

                # reasoning models (Gemma <thought>, DeepSeek <think>) answer after their notes
                content = clean_chat_text(extract_chat_completion_text(response))
                finish_reason = response.choices[0].finish_reason

                # 检查是否被截断
                if finish_reason == 'length':
                    logger.warning(f"LLM输出被截断 (attempt {attempt+1})")
                    content = self._fix_truncated_json(content)

                # 尝试解析JSON
                try:
                    parsed = json.loads(content)
                except json.JSONDecodeError as e:
                    logger.warning(f"JSON解析失败 (attempt {attempt+1}): {str(e)[:80]}")

                    # 尝试修复JSON
                    parsed = self._try_fix_config_json(content)
                    if parsed is None:
                        last_error = e
                        reason = t('progress.llmBadJson')

                if parsed is not None:
                    # Callers read the result with .get(); a reply that is a list
                    # (often the object wrapped in [ ]) must not reach them.
                    if isinstance(parsed, list) and len(parsed) == 1:
                        parsed = parsed[0]
                    if isinstance(parsed, dict):
                        return parsed
                    last_error = ValueError(f"model returned {type(parsed).__name__}, expected a JSON object")
                    logger.warning(f"模型返回的不是JSON对象 (attempt {attempt+1}): {type(parsed).__name__}")
                    reason = t('progress.llmBadJson')

            except Exception as e:
                elapsed = time.monotonic() - started
                if isinstance(e, APITimeoutError):
                    reason = t('progress.llmNoReply', seconds=int(self.request_timeout))
                    logger.warning(
                        f"LLM调用超时 (attempt {attempt+1}/{max_attempts}): {elapsed:.0f} 秒内没有收到完整回复"
                    )
                else:
                    reason = str(e)[:200]
                    logger.warning(f"LLM调用失败 (attempt {attempt+1}/{max_attempts}, {elapsed:.0f}s): {reason}")
                    if getattr(e, "status_code", None) in (402, 429):
                        pauses = self.THROTTLED_RETRY_PAUSES
                last_error = e
                if attempt + 1 < max_attempts:
                    time.sleep(pauses[min(attempt, len(pauses) - 1)])

        raise last_error or Exception("LLM调用失败")

    def _fix_truncated_json(self, content: str) -> str:
        """修复被截断的JSON"""
        content = content.strip()
        
        # 计算未闭合的括号
        open_braces = content.count('{') - content.count('}')
        open_brackets = content.count('[') - content.count(']')
        
        # 检查是否有未闭合的字符串
        if content and content[-1] not in '",}]':
            content += '"'
        
        # 闭合括号
        content += ']' * open_brackets
        content += '}' * open_braces
        
        return content
    
    def _try_fix_config_json(self, content: str) -> Optional[Dict[str, Any]]:
        """尝试修复配置JSON"""
        import re
        
        # 修复被截断的情况
        content = self._fix_truncated_json(content)
        
        # 提取JSON部分
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            json_str = json_match.group()
            
            # 移除字符串中的换行符
            def fix_string(match):
                s = match.group(0)
                s = s.replace('\n', ' ').replace('\r', ' ')
                s = re.sub(r'\s+', ' ', s)
                return s
            
            json_str = re.sub(r'"[^"\\]*(?:\\.[^"\\]*)*"', fix_string, json_str)
            
            try:
                return json.loads(json_str)
            except:
                # 尝试移除所有控制字符
                json_str = re.sub(r'[\x00-\x1f\x7f-\x9f]', ' ', json_str)
                json_str = re.sub(r'\s+', ' ', json_str)
                try:
                    return json.loads(json_str)
                except:
                    pass
        
        return None
    
    def _generate_time_config(self, context: str, num_entities: int) -> Dict[str, Any]:
        """生成时间配置"""
        # 使用配置的上下文截断长度
        context_truncated = context[:self.TIME_CONFIG_CONTEXT_LENGTH]
        
        # 计算最大允许值（80%的agent数）
        max_agents_allowed = max(1, int(num_entities * 0.9))
        
        prompt = f"""基于以下模拟需求，生成时间模拟配置。

{context_truncated}

## 任务
请生成时间配置JSON。

### 基本原则（仅供参考，需根据具体事件和参与群体灵活调整）：
- 请根据模拟场景推断目标用户群体所在时区和作息习惯，以下为东八区(UTC+8)的参考示例
- 凌晨0-5点几乎无人活动（活跃度系数0.05）
- 早上6-8点逐渐活跃（活跃度系数0.4）
- 工作时间9-18点中等活跃（活跃度系数0.7）
- 晚间19-22点是高峰期（活跃度系数1.5）
- 23点后活跃度下降（活跃度系数0.5）
- 一般规律：凌晨低活跃、早间渐增、工作时段中等、晚间高峰
- **重要**：以下示例值仅供参考，你需要根据事件性质、参与群体特点来调整具体时段
  - 例如：学生群体高峰可能是21-23点；媒体全天活跃；官方机构只在工作时间
  - 例如：突发热点可能导致深夜也有讨论，off_peak_hours 可适当缩短

### 返回JSON格式（不要markdown）

示例：
{{
    "total_simulation_hours": 72,
    "minutes_per_round": 60,
    "agents_per_hour_min": 5,
    "agents_per_hour_max": 50,
    "peak_hours": [19, 20, 21, 22],
    "off_peak_hours": [0, 1, 2, 3, 4, 5],
    "morning_hours": [6, 7, 8],
    "work_hours": [9, 10, 11, 12, 13, 14, 15, 16, 17, 18],
    "reasoning": "针对该事件的时间配置说明"
}}

字段说明：
- total_simulation_hours (int): 模拟总时长，24-168小时，突发事件短、持续话题长
- minutes_per_round (int): 每轮时长，30-120分钟，建议60分钟
- agents_per_hour_min (int): 每小时最少激活Agent数（取值范围: 1-{max_agents_allowed}）
- agents_per_hour_max (int): 每小时最多激活Agent数（取值范围: 1-{max_agents_allowed}）
- peak_hours (int数组): 高峰时段，根据事件参与群体调整
- off_peak_hours (int数组): 低谷时段，通常深夜凌晨
- morning_hours (int数组): 早间时段
- work_hours (int数组): 工作时段
- reasoning (string): 简要说明为什么这样配置"""

        system_prompt = "你是社交媒体模拟专家。返回纯JSON格式，时间配置需符合模拟场景中目标用户群体的作息习惯。"
        system_prompt = f"{system_prompt}\n\n{get_language_instruction()}"

        try:
            return self._call_llm_with_retry(prompt, system_prompt)
        except Exception as e:
            logger.warning(f"时间配置LLM生成失败: {e}, 使用默认配置")
            return self._get_default_time_config(num_entities)
    
    def _get_default_time_config(self, num_entities: int) -> Dict[str, Any]:
        """获取默认时间配置（中国人作息）"""
        return {
            "total_simulation_hours": 72,
            "minutes_per_round": 60,  # 每轮1小时，加快时间流速
            "agents_per_hour_min": max(1, num_entities // 15),
            "agents_per_hour_max": max(5, num_entities // 5),
            "peak_hours": [19, 20, 21, 22],
            "off_peak_hours": [0, 1, 2, 3, 4, 5],
            "morning_hours": [6, 7, 8],
            "work_hours": [9, 10, 11, 12, 13, 14, 15, 16, 17, 18],
            "reasoning": "使用默认中国人作息配置（每轮1小时）"
        }
    
    def _parse_time_config(self, result: Dict[str, Any], num_entities: int) -> TimeSimulationConfig:
        """解析时间配置结果，并验证agents_per_hour值不超过总agent数"""
        # 获取原始值
        agents_per_hour_min = result.get("agents_per_hour_min", max(1, num_entities // 15))
        agents_per_hour_max = result.get("agents_per_hour_max", max(5, num_entities // 5))
        
        # 验证并修正：确保不超过总agent数
        if agents_per_hour_min > num_entities:
            logger.warning(f"agents_per_hour_min ({agents_per_hour_min}) 超过总Agent数 ({num_entities})，已修正")
            agents_per_hour_min = max(1, num_entities // 10)
        
        if agents_per_hour_max > num_entities:
            logger.warning(f"agents_per_hour_max ({agents_per_hour_max}) 超过总Agent数 ({num_entities})，已修正")
            agents_per_hour_max = max(agents_per_hour_min + 1, num_entities // 2)
        
        # 确保 min < max
        if agents_per_hour_min >= agents_per_hour_max:
            agents_per_hour_min = max(1, agents_per_hour_max // 2)
            logger.warning(f"agents_per_hour_min >= max，已修正为 {agents_per_hour_min}")
        
        return TimeSimulationConfig(
            total_simulation_hours=result.get("total_simulation_hours", 72),
            minutes_per_round=result.get("minutes_per_round", 60),  # 默认每轮1小时
            agents_per_hour_min=agents_per_hour_min,
            agents_per_hour_max=agents_per_hour_max,
            peak_hours=result.get("peak_hours", [19, 20, 21, 22]),
            off_peak_hours=result.get("off_peak_hours", [0, 1, 2, 3, 4, 5]),
            off_peak_activity_multiplier=0.05,  # 凌晨几乎无人
            morning_hours=result.get("morning_hours", [6, 7, 8]),
            morning_activity_multiplier=0.4,
            work_hours=result.get("work_hours", list(range(9, 19))),
            work_activity_multiplier=0.7,
            peak_activity_multiplier=1.5
        )
    
    def _generate_event_config(
        self, 
        context: str, 
        simulation_requirement: str,
        entities: List[EntityNode]
    ) -> Dict[str, Any]:
        """生成事件配置"""
        
        # 为每种类型列出代表性实体名称
        type_examples = {}
        for e in entities:
            etype = e.get_entity_type() or "Unknown"
            if etype not in type_examples:
                type_examples[etype] = []
            if len(type_examples[etype]) < 3:
                type_examples[etype].append(e.name)
        
        type_info = "\n".join([
            f"- {t}: {', '.join(examples)}"
            for t, examples in type_examples.items()
        ])
        # poster_type 只能取这些值（按出现顺序，去重）
        allowed_types = list(type_examples)
        allowed_types_text = " / ".join(allowed_types)
        
        # 使用配置的上下文截断长度
        context_truncated = context[:self.EVENT_CONFIG_CONTEXT_LENGTH]
        
        prompt = f"""基于以下模拟需求，生成事件配置。

模拟需求: {simulation_requirement}

{context_truncated}

## 可用实体类型及示例（poster_type 只能取下面的类型名）
{type_info}

## 任务
请生成事件配置JSON：
- 提取热点话题关键词
- 提炼议题短语 topic：不超过15个词，中立地描述讨论的对象（例如"HEGAM 分拆上市后的股价反应"），**不要包含结论或预测**；它会被写进每个 Agent 的人设里
- 描述舆论发展方向（这只是一个待检验的假设，不会提供给任何 Agent）
- 设计初始帖子内容，**每个帖子必须指定 poster_type（发布者类型）**
- 可选：给出最多3个"值得检验的假设性后续事件" suggested_events（at_sim_hour 是模拟开始后的小时数）。它们只是供用户参考的候选，默认不会执行；请只写合理的、符合背景的假设，**不要把虚构的内容写成既成事实**

**重要**: poster_type 只能是下列类型名之一，并且必须逐字照抄：{allowed_types_text}
不要写受众、职业或角色（例如 "retail traders"、"analysts"），也不要写某个实体的名字；想让某一类声音发帖时，选最接近的上述类型，这样初始帖子才能分配给合适的 Agent 发布。

返回JSON格式（不要markdown）：
{{
    "hot_topics": ["关键词1", "关键词2", ...],
    "topic": "<议题短语，不超过15个词>",
    "narrative_direction": "<舆论发展方向描述>",
    "initial_posts": [
        {{"content": "帖子内容", "poster_type": "<{allowed_types_text}>"}},
        ...
    ],
    "suggested_events": [
        {{"at_sim_hour": <整数>, "poster_type": "<{allowed_types_text}>", "content": "假设性后续事件的帖子内容"}}
    ],
    "reasoning": "<简要说明>"
}}"""

        system_prompt = "你是舆论分析专家。返回纯JSON格式。注意 poster_type 必须精确匹配可用实体类型。"
        system_prompt = f"{system_prompt}\n\n{get_language_instruction()}\nIMPORTANT: The 'poster_type' field value MUST be in English PascalCase exactly matching the available entity types. Only 'content', 'topic', 'narrative_direction', 'hot_topics' and 'reasoning' fields should use the specified language."

        try:
            return self._call_llm_with_retry(prompt, system_prompt)
        except Exception as e:
            logger.warning(f"事件配置LLM生成失败: {e}, 使用默认配置")
            return {
                "hot_topics": [],
                "narrative_direction": "",
                "initial_posts": [],
                "reasoning": "使用默认配置"
            }
    
    def _parse_event_config(
        self,
        result: Dict[str, Any],
        simulation_requirement: str = "",
        total_hours: float = 72,
    ) -> EventConfig:
        """解析事件配置结果

        scheduled_events 永远为空：它只能由用户编写，LLM 不会凭空编造未来事件。
        """
        return EventConfig(
            initial_posts=result.get("initial_posts", []),
            scheduled_events=[],
            suggested_events=sanitize_suggested_events(
                result.get("suggested_events"), total_hours
            ),
            hot_topics=result.get("hot_topics", []),
            topic=clean_topic(result.get("topic"), simulation_requirement),
            narrative_direction=result.get("narrative_direction", "")
        )
    
    def _assign_initial_post_agents(
        self,
        event_config: EventConfig,
        agent_configs: List[AgentActivityConfig]
    ) -> EventConfig:
        """
        为初始帖子分配合适的发布者 Agent

        根据每个帖子的 poster_type 匹配最合适的 agent_id（逻辑见 assign_poster_agents，
        用户新增的定时事件也共用同一套逻辑）
        """
        if not event_config.initial_posts:
            return event_config

        event_config.initial_posts = assign_poster_agents(
            event_config.initial_posts, agent_configs
        )
        return event_config

    def _generate_agent_configs_batch(
        self,
        context: str,
        entities: List[EntityNode],
        start_idx: int,
        simulation_requirement: str
    ) -> List[AgentActivityConfig]:
        """分批生成Agent配置"""
        
        # 构建实体信息（使用配置的摘要长度）
        entity_list = []
        summary_len = self.AGENT_SUMMARY_LENGTH
        for i, e in enumerate(entities):
            entity_list.append({
                "agent_id": start_idx + i,
                "entity_name": e.name,
                "entity_type": e.get_entity_type() or "Unknown",
                "summary": e.summary[:summary_len] if e.summary else ""
            })
        
        prompt = f"""基于以下信息，为每个实体生成社交媒体活动配置。

模拟需求: {simulation_requirement}

## 实体列表
```json
{json.dumps(entity_list, ensure_ascii=False, indent=2)}
```

## 任务
为每个实体生成活动配置，注意：
- **时间符合目标用户群体作息**：以下为参考（东八区），请根据模拟场景调整
- **官方机构**（University/GovernmentAgency）：活跃度低(0.1-0.3)，工作时间(9-17)活动，响应慢(60-240分钟)，影响力高(2.5-3.0)
- **媒体**（MediaOutlet）：活跃度中(0.4-0.6)，全天活动(8-23)，响应快(5-30分钟)，影响力高(2.0-2.5)
- **个人**（Student/Person/Alumni）：活跃度高(0.6-0.9)，主要晚间活动(18-23)，响应快(1-15分钟)，影响力低(0.8-1.2)
- **公众人物/专家**：活跃度中(0.4-0.6)，影响力中高(1.5-2.0)

返回JSON格式（不要markdown）：
{{
    "agent_configs": [
        {{
            "agent_id": <必须与输入一致>,
            "activity_level": <0.0-1.0>,
            "posts_per_hour": <发帖频率>,
            "comments_per_hour": <评论频率>,
            "active_hours": [<活跃小时列表，考虑中国人作息>],
            "response_delay_min": <最小响应延迟分钟>,
            "response_delay_max": <最大响应延迟分钟>,
            "sentiment_bias": <-1.0到1.0>,
            "stance": "<supportive/opposing/neutral/observer>",
            "influence_weight": <影响力权重>
        }},
        ...
    ]
}}"""

        system_prompt = "你是社交媒体行为分析专家。返回纯JSON，配置需符合模拟场景中目标用户群体的作息习惯。"
        system_prompt = f"{system_prompt}\n\n{get_language_instruction()}\nIMPORTANT: The 'stance' field value MUST be one of the English strings: 'supportive', 'opposing', 'neutral', 'observer'. All JSON field names and numeric values must remain unchanged. Only natural language text fields should use the specified language."

        expected_ids = [start_idx + i for i in range(len(entities))]
        try:
            result = self._call_llm_with_retry(prompt, system_prompt)
            llm_configs = index_agent_configs(result, expected_ids)
        except Exception as e:
            logger.warning(f"Agent配置批次LLM生成失败: {e}, 使用规则生成")
            llm_configs = {}
        else:
            missing_ids = [i for i in expected_ids if i not in llm_configs]
            if missing_ids:
                logger.warning(f"模型返回的配置缺少 Agent {missing_ids}，这些 Agent 使用规则生成")
        
        # 构建AgentActivityConfig对象
        configs = []
        for i, entity in enumerate(entities):
            agent_id = start_idx + i
            cfg = llm_configs.get(agent_id, {})
            
            # 如果LLM没有生成，使用规则生成
            if not cfg:
                cfg = self._generate_agent_config_by_rule(entity)
            
            # 运行器会真正使用这些字段，所以先校验并钳制 LLM 的输出
            cfg = _sanitize_agent_config(cfg)

            config = AgentActivityConfig(
                agent_id=agent_id,
                entity_uuid=entity.uuid,
                entity_name=entity.name,
                entity_type=entity.get_entity_type() or "Unknown",
                activity_level=cfg["activity_level"],
                posts_per_hour=cfg["posts_per_hour"],
                comments_per_hour=cfg["comments_per_hour"],
                active_hours=cfg["active_hours"],
                response_delay_min=cfg["response_delay_min"],
                response_delay_max=cfg["response_delay_max"],
                sentiment_bias=cfg["sentiment_bias"],
                stance=cfg["stance"],
                influence_weight=cfg["influence_weight"]
            )
            configs.append(config)
        
        return configs
    
    def _generate_agent_config_by_rule(self, entity: EntityNode) -> Dict[str, Any]:
        """基于规则生成单个Agent配置（中国人作息）"""
        entity_type = (entity.get_entity_type() or "Unknown").lower()
        
        if entity_type in ["university", "governmentagency", "ngo"]:
            # 官方机构：工作时间活动，低频率，高影响力
            return {
                "activity_level": 0.2,
                "posts_per_hour": 0.1,
                "comments_per_hour": 0.05,
                "active_hours": list(range(9, 18)),  # 9:00-17:59
                "response_delay_min": 60,
                "response_delay_max": 240,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 3.0
            }
        elif entity_type in ["mediaoutlet"]:
            # 媒体：全天活动，中等频率，高影响力
            return {
                "activity_level": 0.5,
                "posts_per_hour": 0.8,
                "comments_per_hour": 0.3,
                "active_hours": list(range(7, 24)),  # 7:00-23:59
                "response_delay_min": 5,
                "response_delay_max": 30,
                "sentiment_bias": 0.0,
                "stance": "observer",
                "influence_weight": 2.5
            }
        elif entity_type in ["professor", "expert", "official"]:
            # 专家/教授：工作+晚间活动，中等频率
            return {
                "activity_level": 0.4,
                "posts_per_hour": 0.3,
                "comments_per_hour": 0.5,
                "active_hours": list(range(8, 22)),  # 8:00-21:59
                "response_delay_min": 15,
                "response_delay_max": 90,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 2.0
            }
        elif entity_type in ["student"]:
            # 学生：晚间为主，高频率
            return {
                "activity_level": 0.8,
                "posts_per_hour": 0.6,
                "comments_per_hour": 1.5,
                "active_hours": [8, 9, 10, 11, 12, 13, 18, 19, 20, 21, 22, 23],  # 上午+晚间
                "response_delay_min": 1,
                "response_delay_max": 15,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 0.8
            }
        elif entity_type in ["alumni"]:
            # 校友：晚间为主
            return {
                "activity_level": 0.6,
                "posts_per_hour": 0.4,
                "comments_per_hour": 0.8,
                "active_hours": [12, 13, 19, 20, 21, 22, 23],  # 午休+晚间
                "response_delay_min": 5,
                "response_delay_max": 30,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 1.0
            }
        else:
            # 普通人：晚间高峰
            return {
                "activity_level": 0.7,
                "posts_per_hour": 0.5,
                "comments_per_hour": 1.2,
                "active_hours": [9, 10, 11, 12, 13, 18, 19, 20, 21, 22, 23],  # 白天+晚间
                "response_delay_min": 2,
                "response_delay_max": 20,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 1.0
            }
    

