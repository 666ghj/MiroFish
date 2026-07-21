"""
本体生成服务
接口1：分析文本内容，生成适合社会模拟的实体和关系类型定义
"""

import json
import math
import re
import traceback
from typing import Dict, Any, List, Optional
from ..utils.llm_client import LLMClient
from ..utils.locale import get_language_instruction
from ..utils.logger import get_logger
from ..config import Config

logger = get_logger('mirofish.ontology')


def _estimate_tokens(text: str) -> int:
    """Conservative token estimate for local vLLM context budgeting."""
    text = text or ""
    cjk_chars = len(re.findall(r'[\u3400-\u9fff\uf900-\ufaff]', text))
    non_cjk_chars = len(text) - cjk_chars
    return cjk_chars + math.ceil(non_cjk_chars / 4)


def _to_pascal_case(name: str) -> str:
    """将任意格式的名称转换为 PascalCase（如 'works_for' -> 'WorksFor', 'person' -> 'Person'）"""
    # 按非字母数字字符分割
    parts = re.split(r'[^a-zA-Z0-9]+', name)
    # 再按 camelCase 边界分割（如 'camelCase' -> ['camel', 'Case']）
    words = []
    for part in parts:
        words.extend(re.sub(r'([a-z])([A-Z])', r'\1_\2', part).split('_'))
    # 每个词首字母大写，过滤空串
    result = ''.join(word.capitalize() for word in words if word)
    return result if result else 'Unknown'


# 本体生成的系统提示词
ONTOLOGY_SYSTEM_PROMPT = """你是一个专业的知识图谱本体设计专家。你的任务是分析给定的文本内容和模拟需求，设计适合**社交媒体舆论模拟**的实体类型和关系类型。

**重要：你必须输出有效的JSON格式数据，不要输出任何其他内容。**

## 核心任务背景

我们正在构建一个**社交媒体舆论模拟系统**。在这个系统中：
- 每个实体都是一个可以在社交媒体上发声、互动、传播信息的"账号"或"主体"
- 实体之间会相互影响、转发、评论、回应
- 我们需要模拟舆论事件中各方的反应和信息传播路径

因此，**实体必须是现实中真实存在的、可以在社媒上发声和互动的主体**：

**可以是**：
- 具体的个人（公众人物、当事人、意见领袖、专家学者、普通人）
- 公司、企业（包括其官方账号）
- 组织机构（大学、协会、NGO、工会等）
- 政府部门、监管机构
- 媒体机构（报纸、电视台、自媒体、网站）
- 社交媒体平台本身
- 特定群体代表（如校友会、粉丝团、维权群体等）

**不可以是**：
- 抽象概念（如"舆论"、"情绪"、"趋势"）
- 主题/话题（如"学术诚信"、"教育改革"）
- 观点/态度（如"支持方"、"反对方"）

## 输出格式

请输出JSON格式，包含以下结构：

```json
{
    "entity_types": [
        {
            "name": "实体类型名称（英文，PascalCase）",
            "description": "简短描述（英文，不超过100字符）",
            "attributes": [
                {
                    "name": "属性名（英文，snake_case）",
                    "type": "text",
                    "description": "属性描述"
                }
            ],
            "examples": ["示例实体1", "示例实体2"]
        }
    ],
    "edge_types": [
        {
            "name": "关系类型名称（英文，UPPER_SNAKE_CASE）",
            "description": "简短描述（英文，不超过100字符）",
            "source_targets": [
                {"source": "源实体类型", "target": "目标实体类型"}
            ],
            "attributes": []
        }
    ],
    "analysis_summary": "对文本内容的简要分析说明"
}
```

## 设计指南（极其重要！）

### 1. 实体类型设计 - 必须严格遵守

**数量要求：必须正好10个实体类型**

**层次结构要求（必须同时包含具体类型和兜底类型）**：

你的10个实体类型必须包含以下层次：

A. **兜底类型（必须包含，放在列表最后2个）**：
   - `Person`: 任何自然人个体的兜底类型。当一个人不属于其他更具体的人物类型时，归入此类。
   - `Organization`: 任何组织机构的兜底类型。当一个组织不属于其他更具体的组织类型时，归入此类。

B. **具体类型（8个，根据文本内容设计）**：
   - 针对文本中出现的主要角色，设计更具体的类型
   - 例如：如果文本涉及学术事件，可以有 `Student`, `Professor`, `University`
   - 例如：如果文本涉及商业事件，可以有 `Company`, `CEO`, `Employee`

**为什么需要兜底类型**：
- 文本中会出现各种人物，如"中小学教师"、"路人甲"、"某位网友"
- 如果没有专门的类型匹配，他们应该被归入 `Person`
- 同理，小型组织、临时团体等应该归入 `Organization`

**具体类型的设计原则**：
- 从文本中识别出高频出现或关键的角色类型
- 每个具体类型应该有明确的边界，避免重叠
- description 必须清晰说明这个类型和兜底类型的区别

### 2. 关系类型设计

- 数量：6-10个
- 关系应该反映社媒互动中的真实联系
- 确保关系的 source_targets 涵盖你定义的实体类型

### 3. 属性设计

- 每个实体类型1-3个关键属性
- **注意**：属性名不能使用 `name`、`uuid`、`group_id`、`created_at`、`summary`（这些是系统保留字）
- 推荐使用：`full_name`, `title`, `role`, `position`, `location`, `description` 等

## 实体类型参考

**个人类（具体）**：
- Student: 学生
- Professor: 教授/学者
- Journalist: 记者
- Celebrity: 明星/网红
- Executive: 高管
- Official: 政府官员
- Lawyer: 律师
- Doctor: 医生

**个人类（兜底）**：
- Person: 任何自然人（不属于上述具体类型时使用）

**组织类（具体）**：
- University: 高校
- Company: 公司企业
- GovernmentAgency: 政府机构
- MediaOutlet: 媒体机构
- Hospital: 医院
- School: 中小学
- NGO: 非政府组织

**组织类（兜底）**：
- Organization: 任何组织机构（不属于上述具体类型时使用）

## 关系类型参考

- WORKS_FOR: 工作于
- STUDIES_AT: 就读于
- AFFILIATED_WITH: 隶属于
- REPRESENTS: 代表
- REGULATES: 监管
- REPORTS_ON: 报道
- COMMENTS_ON: 评论
- RESPONDS_TO: 回应
- SUPPORTS: 支持
- OPPOSES: 反对
- COLLABORATES_WITH: 合作
- COMPETES_WITH: 竞争
"""


class OntologyGenerator:
    """
    本体生成器
    分析文本内容，生成实体和关系类型定义
    """
    
    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm_client = llm_client or LLMClient()
    
    def generate(
        self,
        document_texts: List[str],
        simulation_requirement: str,
        additional_context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        生成本体定义
        
        Args:
            document_texts: 文档文本列表
            simulation_requirement: 模拟需求描述
            additional_context: 额外上下文
            
        Returns:
            本体定义（entity_types, edge_types等）
        """
        lang_instruction = get_language_instruction()
        system_prompt = f"{ONTOLOGY_SYSTEM_PROMPT}\n\n{lang_instruction}\nIMPORTANT: Entity type names MUST be in English PascalCase (e.g., 'PersonEntity', 'MediaOrganization'). Relationship type names MUST be in English UPPER_SNAKE_CASE (e.g., 'WORKS_FOR'). Attribute names MUST be in English snake_case. Only description fields and analysis_summary should use the specified language above."

        chunks = self._build_document_chunks(
            document_texts=document_texts,
            simulation_requirement=simulation_requirement,
            additional_context=additional_context,
            system_prompt=system_prompt,
        )
        fallback_ontology = self._document_aware_fallback(document_texts, simulation_requirement)
        logger.info("Ontology generation split into %s LLM chunk(s)", len(chunks))

        partial_results = []
        for index, chunk in enumerate(chunks, start=1):
            user_message = self._build_user_message(
                [chunk],
                simulation_requirement,
                additional_context,
                chunk_index=index,
                chunk_count=len(chunks),
            )
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ]

            try:
                raw_result = self.llm_client.chat_json(
                    messages=messages,
                    temperature=0.3,
                    max_tokens=Config.ONTOLOGY_MAX_OUTPUT_TOKENS,
                    max_retries=Config.LLM_JSON_MAX_RETRIES,
                )
                result = self._coerce_ontology_result(raw_result)
                if self._has_usable_ontology(result):
                    partial_results.append(result)
                else:
                    logger.warning(
                        "Ontology LLM chunk %s/%s returned JSON without usable entity_types/edge_types: %s",
                        index,
                        len(chunks),
                        str(raw_result)[:1000],
                    )
            except Exception as exc:
                logger.error("Ontology LLM chunk %s/%s failed: %s", index, len(chunks), exc)
                logger.debug(traceback.format_exc())

        if partial_results:
            result = self._merge_ontologies(partial_results, simulation_requirement)
        else:
            logger.error("All ontology LLM chunks failed, using document-aware fallback ontology")
            result = fallback_ontology
        
        # 验证和后处理
        result = self._validate_and_process(result, fill_ontology=fallback_ontology)
        
        return result

    def _coerce_ontology_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Accept common local-LLM schema variants and normalize to our shape."""
        if not isinstance(result, dict):
            return {}

        for wrapper_key in ("ontology", "data", "result"):
            wrapped = result.get(wrapper_key)
            if isinstance(wrapped, dict):
                result = wrapped
                break

        normalized = dict(result)
        if "entity_types" not in normalized:
            for key in ("entities", "entityTypes", "node_types", "nodeTypes", "nodes"):
                if isinstance(normalized.get(key), list):
                    normalized["entity_types"] = normalized[key]
                    break

        if "edge_types" not in normalized:
            for key in ("relationships", "relations", "edges", "edgeTypes", "relation_types", "relationship_types"):
                if isinstance(normalized.get(key), list):
                    normalized["edge_types"] = normalized[key]
                    break

        normalized["entity_types"] = [
            self._coerce_entity_type(item)
            for item in normalized.get("entity_types", [])
            if isinstance(item, dict)
        ]
        normalized["edge_types"] = [
            self._coerce_edge_type(item)
            for item in normalized.get("edge_types", [])
            if isinstance(item, dict)
        ]
        return normalized

    def _coerce_entity_type(self, item: Dict[str, Any]) -> Dict[str, Any]:
        name = item.get("name") or item.get("type") or item.get("label")
        attributes = item.get("attributes") if isinstance(item.get("attributes"), list) else []
        return {
            "name": name,
            "description": item.get("description") or item.get("summary") or f"{name} entity.",
            "attributes": attributes,
            "examples": item.get("examples") if isinstance(item.get("examples"), list) else [],
        }

    def _coerce_edge_type(self, item: Dict[str, Any]) -> Dict[str, Any]:
        name = item.get("name") or item.get("type") or item.get("relation")
        source_targets = item.get("source_targets")
        if not isinstance(source_targets, list):
            source = item.get("source") or item.get("source_type")
            target = item.get("target") or item.get("target_type")
            source_targets = [{"source": source or "Person", "target": target or "Organization"}]
        return {
            "name": name,
            "description": item.get("description") or item.get("summary") or f"{name} relation.",
            "source_targets": source_targets,
            "attributes": item.get("attributes") if isinstance(item.get("attributes"), list) else [],
        }

    def _has_usable_ontology(self, result: Dict[str, Any]) -> bool:
        return bool(result.get("entity_types")) and bool(result.get("edge_types"))

    def _document_aware_fallback(
        self,
        document_texts: List[str],
        simulation_requirement: str,
    ) -> Dict[str, Any]:
        corpus = "\n".join(document_texts or [])[:50000]
        lower = corpus.lower()
        fate_markers = [
            "fate/grand order",
            "lostbelt",
            "阿瓦隆",
            "勒",
            "妖精",
            "摩根",
            "迦勒底",
            "不列顛",
            "奧伯龍",
            "科爾努諾斯",
        ]
        if any(marker in lower or marker in corpus for marker in fate_markers):
            return {
                "entity_types": [
                    {
                        "name": "FictionalCharacter",
                        "description": "Named story character or role in the Lostbelt narrative.",
                        "attributes": [{"name": "role", "type": "text", "description": "Narrative role"}],
                        "examples": ["Morgan", "Artoria Caster"],
                    },
                    {
                        "name": "Faction",
                        "description": "Political, military, or social group in the setting.",
                        "attributes": [{"name": "alignment", "type": "text", "description": "Faction alignment"}],
                        "examples": ["Chaldea", "Round Table"],
                    },
                    {
                        "name": "FairyClan",
                        "description": "Fairy clan or species group in Britain.",
                        "attributes": [{"name": "clan_role", "type": "text", "description": "Clan role"}],
                        "examples": ["Wind clan", "Fang clan"],
                    },
                    {
                        "name": "Kingdom",
                        "description": "Realm, court, or governing power.",
                        "attributes": [{"name": "ruler", "type": "text", "description": "Known ruler"}],
                        "examples": ["Camelot", "Fairy Britain"],
                    },
                    {
                        "name": "Deity",
                        "description": "Godlike or mythic entity affecting events.",
                        "attributes": [{"name": "domain", "type": "text", "description": "Mythic domain"}],
                        "examples": ["Cernunnos"],
                    },
                    {
                        "name": "Location",
                        "description": "Named place or region in the chronology.",
                        "attributes": [{"name": "region_type", "type": "text", "description": "Place category"}],
                        "examples": ["Avalon", "Britain"],
                    },
                    {
                        "name": "NarrativeEvent",
                        "description": "Major battle, calamity, or turning point.",
                        "attributes": [{"name": "era", "type": "text", "description": "Era or time marker"}],
                        "examples": ["Great Calamity", "Queen Morgan battle"],
                    },
                    {
                        "name": "SourceMaterial",
                        "description": "Official or community source cited by the report.",
                        "attributes": [{"name": "source_type", "type": "text", "description": "Source category"}],
                        "examples": ["Road to 7", "official soundtrack"],
                    },
                    {
                        "name": "Person",
                        "description": "Any individual not fitting other specific person types.",
                        "attributes": [{"name": "full_name", "type": "text", "description": "Full name"}],
                        "examples": ["writer", "commentator"],
                    },
                    {
                        "name": "Organization",
                        "description": "Any organization not fitting other specific organization types.",
                        "attributes": [{"name": "org_name", "type": "text", "description": "Organization name"}],
                        "examples": ["publisher", "studio"],
                    },
                ],
                "edge_types": [
                    {
                        "name": "APPEARS_IN",
                        "description": "Entity appears in a source, era, or event.",
                        "source_targets": [{"source": "FictionalCharacter", "target": "NarrativeEvent"}],
                        "attributes": [],
                    },
                    {
                        "name": "RULES",
                        "description": "Character or power rules a realm or group.",
                        "source_targets": [{"source": "FictionalCharacter", "target": "Kingdom"}],
                        "attributes": [],
                    },
                    {
                        "name": "ALLIED_WITH",
                        "description": "Entity is allied or cooperating with another.",
                        "source_targets": [{"source": "Faction", "target": "Faction"}, {"source": "FictionalCharacter", "target": "Faction"}],
                        "attributes": [],
                    },
                    {
                        "name": "OPPOSES",
                        "description": "Entity opposes another entity or faction.",
                        "source_targets": [{"source": "FictionalCharacter", "target": "FictionalCharacter"}, {"source": "Faction", "target": "Faction"}],
                        "attributes": [],
                    },
                    {
                        "name": "LOCATED_IN",
                        "description": "Entity or event is located in a place.",
                        "source_targets": [{"source": "NarrativeEvent", "target": "Location"}, {"source": "Kingdom", "target": "Location"}],
                        "attributes": [],
                    },
                    {
                        "name": "CAUSES",
                        "description": "Entity or event causes another event.",
                        "source_targets": [{"source": "NarrativeEvent", "target": "NarrativeEvent"}, {"source": "Deity", "target": "NarrativeEvent"}],
                        "attributes": [],
                    },
                    {
                        "name": "DOCUMENTS",
                        "description": "Source material documents an entity or event.",
                        "source_targets": [{"source": "SourceMaterial", "target": "NarrativeEvent"}, {"source": "SourceMaterial", "target": "FictionalCharacter"}],
                        "attributes": [],
                    },
                    {
                        "name": "TRANSFORMS_INTO",
                        "description": "Entity changes form, role, or state.",
                        "source_targets": [{"source": "FictionalCharacter", "target": "FictionalCharacter"}, {"source": "NarrativeEvent", "target": "NarrativeEvent"}],
                        "attributes": [],
                    },
                ],
                "analysis_summary": f"Document-aware fallback ontology generated for Fate/Lostbelt content: {simulation_requirement[:200]}",
            }

        return self._fallback_ontology(simulation_requirement)

    def _fallback_ontology(self, simulation_requirement: str) -> Dict[str, Any]:
        """Deterministic ontology used when a local LLM fails JSON generation."""
        return {
            "entity_types": [
                {
                    "name": "Journalist",
                    "description": "Reporter or editor participating in public discourse.",
                    "attributes": [{"name": "role", "type": "text", "description": "Media role"}],
                    "examples": ["reporter", "editor"],
                },
                {
                    "name": "MediaOutlet",
                    "description": "Media organization publishing news or commentary.",
                    "attributes": [{"name": "org_name", "type": "text", "description": "Outlet name"}],
                    "examples": ["newspaper", "online media"],
                },
                {
                    "name": "Company",
                    "description": "Business organization involved in the issue.",
                    "attributes": [{"name": "industry", "type": "text", "description": "Industry"}],
                    "examples": ["company", "platform"],
                },
                {
                    "name": "GovernmentAgency",
                    "description": "Government or regulator relevant to the event.",
                    "attributes": [{"name": "jurisdiction", "type": "text", "description": "Jurisdiction"}],
                    "examples": ["regulator", "department"],
                },
                {
                    "name": "Official",
                    "description": "Public official or authority figure.",
                    "attributes": [{"name": "title", "type": "text", "description": "Official title"}],
                    "examples": ["mayor", "spokesperson"],
                },
                {
                    "name": "Expert",
                    "description": "Analyst, scholar, or professional commentator.",
                    "attributes": [{"name": "specialty", "type": "text", "description": "Expertise"}],
                    "examples": ["researcher", "lawyer"],
                },
                {
                    "name": "CommunityGroup",
                    "description": "Grassroots group or collective actor.",
                    "attributes": [{"name": "focus", "type": "text", "description": "Group focus"}],
                    "examples": ["local group", "advocacy group"],
                },
                {
                    "name": "Influencer",
                    "description": "Online personality with audience influence.",
                    "attributes": [{"name": "platform", "type": "text", "description": "Main platform"}],
                    "examples": ["blogger", "creator"],
                },
                {
                    "name": "Person",
                    "description": "Any individual person not fitting specific person types.",
                    "attributes": [{"name": "full_name", "type": "text", "description": "Full name"}],
                    "examples": ["ordinary citizen", "witness"],
                },
                {
                    "name": "Organization",
                    "description": "Any organization not fitting specific organization types.",
                    "attributes": [{"name": "org_name", "type": "text", "description": "Organization name"}],
                    "examples": ["association", "small organization"],
                },
            ],
            "edge_types": [
                {
                    "name": "WORKS_FOR",
                    "description": "Employment or affiliation relationship.",
                    "source_targets": [{"source": "Person", "target": "Organization"}, {"source": "Journalist", "target": "MediaOutlet"}],
                    "attributes": [],
                },
                {
                    "name": "REPORTS_ON",
                    "description": "Publishes or reports about an actor.",
                    "source_targets": [{"source": "MediaOutlet", "target": "Organization"}, {"source": "Journalist", "target": "Person"}],
                    "attributes": [],
                },
                {
                    "name": "RESPONDS_TO",
                    "description": "Publicly responds to another actor.",
                    "source_targets": [{"source": "Person", "target": "Person"}, {"source": "Organization", "target": "Organization"}],
                    "attributes": [],
                },
                {
                    "name": "SUPPORTS",
                    "description": "Expresses support for another actor.",
                    "source_targets": [{"source": "Person", "target": "Organization"}, {"source": "Organization", "target": "Person"}],
                    "attributes": [],
                },
                {
                    "name": "OPPOSES",
                    "description": "Expresses opposition to another actor.",
                    "source_targets": [{"source": "Person", "target": "Organization"}, {"source": "Organization", "target": "Person"}],
                    "attributes": [],
                },
                {
                    "name": "COLLABORATES_WITH",
                    "description": "Cooperates with another actor.",
                    "source_targets": [{"source": "Organization", "target": "Organization"}, {"source": "Person", "target": "Person"}],
                    "attributes": [],
                },
                {
                    "name": "INFLUENCES",
                    "description": "Influences opinions or decisions.",
                    "source_targets": [{"source": "Influencer", "target": "Person"}, {"source": "MediaOutlet", "target": "Person"}],
                    "attributes": [],
                },
                {
                    "name": "REGULATES",
                    "description": "Regulatory or oversight relation.",
                    "source_targets": [{"source": "GovernmentAgency", "target": "Company"}, {"source": "Official", "target": "Organization"}],
                    "attributes": [],
                },
            ],
            "analysis_summary": f"Fallback ontology generated for: {simulation_requirement[:200]}",
        }
    
    def _context_input_budget(
        self,
        system_prompt: str,
        simulation_requirement: str,
        additional_context: Optional[str],
    ) -> int:
        empty_user_message = self._build_user_message(
            [""],
            simulation_requirement,
            additional_context,
            chunk_index=1,
            chunk_count=1,
        )
        reserved = (
            _estimate_tokens(system_prompt)
            + _estimate_tokens(empty_user_message)
            + Config.ONTOLOGY_MAX_OUTPUT_TOKENS
            + Config.ONTOLOGY_PROMPT_MARGIN_TOKENS
        )
        return max(512, Config.LLM_CONTEXT_WINDOW - reserved)

    def _build_document_chunks(
        self,
        document_texts: List[str],
        simulation_requirement: str,
        additional_context: Optional[str],
        system_prompt: str,
    ) -> List[str]:
        budget = self._context_input_budget(system_prompt, simulation_requirement, additional_context)
        chunks: List[str] = []

        for text in document_texts:
            normalized = text or ""
            current_parts: List[str] = []
            current_tokens = 0
            for part in self._iter_text_parts(normalized, budget):
                part_tokens = _estimate_tokens(part)
                if current_parts and current_tokens + part_tokens > budget:
                    chunks.append("\n\n".join(current_parts))
                    current_parts = []
                    current_tokens = 0
                current_parts.append(part)
                current_tokens += part_tokens
            if current_parts:
                chunks.append("\n\n".join(current_parts))

        if not chunks:
            return [""]

        max_chunks = max(1, Config.ONTOLOGY_MAX_CHUNKS)
        if len(chunks) > max_chunks:
            logger.warning(
                "Ontology input produced %s chunks; keeping first %s to avoid endpoint overload",
                len(chunks),
                max_chunks,
            )
            chunks = chunks[:max_chunks]

        return chunks

    def _iter_text_parts(self, text: str, budget: int):
        paragraphs = [part.strip() for part in re.split(r'\n{2,}', text) if part.strip()]
        if not paragraphs:
            paragraphs = [text.strip()] if text.strip() else [""]

        for paragraph in paragraphs:
            if _estimate_tokens(paragraph) <= budget:
                yield paragraph
                continue

            sentences = [part.strip() for part in re.split(r'(?<=[。！？.!?])\s*', paragraph) if part.strip()]
            if not sentences:
                sentences = [paragraph]

            current = ""
            for sentence in sentences:
                if _estimate_tokens(sentence) > budget:
                    if current:
                        yield current
                        current = ""
                    yield from self._split_oversize_text(sentence, budget)
                    continue
                candidate = f"{current}\n{sentence}".strip() if current else sentence
                if current and _estimate_tokens(candidate) > budget:
                    yield current
                    current = sentence
                else:
                    current = candidate
            if current:
                yield current

    def _split_oversize_text(self, text: str, budget: int):
        # Conservative char window: CJK can be close to one token per char.
        window = max(800, min(len(text), budget * 2))
        start = 0
        while start < len(text):
            end = min(len(text), start + window)
            chunk = text[start:end]
            while _estimate_tokens(chunk) > budget and len(chunk) > 500:
                end = start + max(500, (end - start) // 2)
                chunk = text[start:end]
            yield chunk
            start = end
    
    def _build_user_message(
        self,
        document_texts: List[str],
        simulation_requirement: str,
        additional_context: Optional[str],
        chunk_index: int = 1,
        chunk_count: int = 1,
    ) -> str:
        """构建用户消息"""
        
        # 合并文本
        combined_text = "\n\n---\n\n".join(document_texts)
        
        message = f"""## 模拟需求

{simulation_requirement}

## 文档内容

{combined_text}
"""
        
        if additional_context:
            message += f"""
## 额外说明

{additional_context}
"""
        
        message += """
请根据以上内容，设计适合社会舆论模拟的实体类型和关系类型。

**必须遵守的规则**：
1. 必须正好输出10个实体类型
2. 最后2个必须是兜底类型：Person（个人兜底）和 Organization（组织兜底）
3. 前8个是根据文本内容设计的具体类型
4. 所有实体类型必须是现实中可以发声的主体，不能是抽象概念
5. 属性名不能使用 name、uuid、group_id 等保留字，用 full_name、org_name 等替代
"""
        if chunk_count > 1:
            message += f"\n当前是第 {chunk_index}/{chunk_count} 个文本分片。请只基于当前分片生成候选本体，后续系统会合并去重。\n"
        
        return message

    def _merge_ontologies(self, results: List[Dict[str, Any]], simulation_requirement: str) -> Dict[str, Any]:
        merged = {
            "entity_types": [],
            "edge_types": [],
            "analysis_summary": "",
        }
        seen_entities = set()
        seen_edges = set()
        summaries = []

        for result in results:
            for entity in result.get("entity_types", []):
                name = _to_pascal_case(str(entity.get("name", "")))
                if not name or name in seen_entities:
                    continue
                seen_entities.add(name)
                entity = dict(entity)
                entity["name"] = name
                merged["entity_types"].append(entity)

            for edge in result.get("edge_types", []):
                name = str(edge.get("name", "")).upper()
                if not name or name in seen_edges:
                    continue
                seen_edges.add(name)
                edge = dict(edge)
                edge["name"] = name
                merged["edge_types"].append(edge)

            summary = str(result.get("analysis_summary", "")).strip()
            if summary:
                summaries.append(summary)

        if not merged["entity_types"] or not merged["edge_types"]:
            return self._fallback_ontology(simulation_requirement)

        merged["analysis_summary"] = " ".join(summaries[:3]) or f"Ontology generated for: {simulation_requirement[:200]}"
        return merged
    
    def _validate_and_process(
        self,
        result: Dict[str, Any],
        fill_ontology: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """验证和后处理结果"""
        
        # 确保必要字段存在
        if "entity_types" not in result:
            result["entity_types"] = []
        if "edge_types" not in result:
            result["edge_types"] = []
        if "analysis_summary" not in result:
            result["analysis_summary"] = ""
        
        # 验证实体类型
        # 记录原始名称到 PascalCase 的映射，用于后续修正 edge 的 source_targets 引用
        entity_name_map = {}
        for entity in result["entity_types"]:
            # 强制将 entity name 转为 PascalCase（Zep API 要求）
            if "name" in entity:
                original_name = entity["name"]
                entity["name"] = _to_pascal_case(original_name)
                if entity["name"] != original_name:
                    logger.warning(f"Entity type name '{original_name}' auto-converted to '{entity['name']}'")
                entity_name_map[original_name] = entity["name"]
            if "attributes" not in entity:
                entity["attributes"] = []
            if "examples" not in entity:
                entity["examples"] = []
            # 确保description不超过100字符
            if len(entity.get("description", "")) > 100:
                entity["description"] = entity["description"][:97] + "..."
        
        # 验证关系类型
        for edge in result["edge_types"]:
            # 强制将 edge name 转为 SCREAMING_SNAKE_CASE（Zep API 要求）
            if "name" in edge:
                original_name = edge["name"]
                edge["name"] = original_name.upper()
                if edge["name"] != original_name:
                    logger.warning(f"Edge type name '{original_name}' auto-converted to '{edge['name']}'")
            # 修正 source_targets 中的实体名称引用，与转换后的 PascalCase 保持一致
            for st in edge.get("source_targets", []):
                if st.get("source") in entity_name_map:
                    st["source"] = entity_name_map[st["source"]]
                if st.get("target") in entity_name_map:
                    st["target"] = entity_name_map[st["target"]]
            if "source_targets" not in edge:
                edge["source_targets"] = []
            if "attributes" not in edge:
                edge["attributes"] = []
            if len(edge.get("description", "")) > 100:
                edge["description"] = edge["description"][:97] + "..."
        
        # Zep API 限制：最多 10 个自定义实体类型，最多 10 个自定义边类型
        MAX_ENTITY_TYPES = 10
        MAX_EDGE_TYPES = 10

        # 去重：按 name 去重，保留首次出现的
        seen_names = set()
        deduped = []
        for entity in result["entity_types"]:
            name = entity.get("name", "")
            if name and name not in seen_names:
                seen_names.add(name)
                deduped.append(entity)
            elif name in seen_names:
                logger.warning(f"Duplicate entity type '{name}' removed during validation")
        result["entity_types"] = deduped

        # 兜底类型定义
        person_fallback = {
            "name": "Person",
            "description": "Any individual person not fitting other specific person types.",
            "attributes": [
                {"name": "full_name", "type": "text", "description": "Full name of the person"},
                {"name": "role", "type": "text", "description": "Role or occupation"}
            ],
            "examples": ["ordinary citizen", "anonymous netizen"]
        }
        
        organization_fallback = {
            "name": "Organization",
            "description": "Any organization not fitting other specific organization types.",
            "attributes": [
                {"name": "org_name", "type": "text", "description": "Name of the organization"},
                {"name": "org_type", "type": "text", "description": "Type of organization"}
            ],
            "examples": ["small business", "community group"]
        }
        
        # 检查是否已有兜底类型
        entity_names = {e["name"] for e in result["entity_types"]}
        has_person = "Person" in entity_names
        has_organization = "Organization" in entity_names
        
        # 需要添加的兜底类型
        fallbacks_to_add = []
        if not has_person:
            fallbacks_to_add.append(person_fallback)
        if not has_organization:
            fallbacks_to_add.append(organization_fallback)
        
        if fallbacks_to_add:
            current_count = len(result["entity_types"])
            needed_slots = len(fallbacks_to_add)
            
            # 如果添加后会超过 10 个，需要移除一些现有类型
            if current_count + needed_slots > MAX_ENTITY_TYPES:
                # 计算需要移除多少个
                to_remove = current_count + needed_slots - MAX_ENTITY_TYPES
                # 从末尾移除（保留前面更重要的具体类型）
                result["entity_types"] = result["entity_types"][:-to_remove]
            
            # 添加兜底类型
            result["entity_types"].extend(fallbacks_to_add)

        # Local LLMs sometimes return too few types. Fill from deterministic
        # social-simulation defaults so downstream graph setup always has a
        # usable ontology instead of failing later.
        fill_ontology = fill_ontology or self._fallback_ontology("")

        if len(result["entity_types"]) < MAX_ENTITY_TYPES:
            entity_names = {e["name"] for e in result["entity_types"]}
            for fallback_entity in fill_ontology.get("entity_types", []):
                if len(result["entity_types"]) >= MAX_ENTITY_TYPES:
                    break
                if fallback_entity["name"] in entity_names:
                    continue
                result["entity_types"].append(fallback_entity)
                entity_names.add(fallback_entity["name"])
        
        # 最终确保不超过限制（防御性编程）
        if len(result["entity_types"]) > MAX_ENTITY_TYPES:
            result["entity_types"] = result["entity_types"][:MAX_ENTITY_TYPES]
        
        if len(result["edge_types"]) > MAX_EDGE_TYPES:
            result["edge_types"] = result["edge_types"][:MAX_EDGE_TYPES]

        if len(result["edge_types"]) < 6:
            edge_names = {edge.get("name") for edge in result["edge_types"]}
            for fallback_edge in fill_ontology.get("edge_types", []):
                if len(result["edge_types"]) >= 6:
                    break
                if fallback_edge["name"] in edge_names:
                    continue
                result["edge_types"].append(fallback_edge)
                edge_names.add(fallback_edge["name"])
        
        return result
    
    def generate_python_code(self, ontology: Dict[str, Any]) -> str:
        """
        将本体定义转换为Python代码（类似ontology.py）
        
        Args:
            ontology: 本体定义
            
        Returns:
            Python代码字符串
        """
        code_lines = [
            '"""',
            '自定义实体类型定义',
            '由MiroFish自动生成，用于社会舆论模拟',
            '"""',
            '',
            'from pydantic import Field',
            'from zep_cloud.external_clients.ontology import EntityModel, EntityText, EdgeModel',
            '',
            '',
            '# ============== 实体类型定义 ==============',
            '',
        ]
        
        # 生成实体类型
        for entity in ontology.get("entity_types", []):
            name = entity["name"]
            desc = entity.get("description", f"A {name} entity.")
            
            code_lines.append(f'class {name}(EntityModel):')
            code_lines.append(f'    """{desc}"""')
            
            attrs = entity.get("attributes", [])
            if attrs:
                for attr in attrs:
                    attr_name = attr["name"]
                    attr_desc = attr.get("description", attr_name)
                    code_lines.append(f'    {attr_name}: EntityText = Field(')
                    code_lines.append(f'        description="{attr_desc}",')
                    code_lines.append(f'        default=None')
                    code_lines.append(f'    )')
            else:
                code_lines.append('    pass')
            
            code_lines.append('')
            code_lines.append('')
        
        code_lines.append('# ============== 关系类型定义 ==============')
        code_lines.append('')
        
        # 生成关系类型
        for edge in ontology.get("edge_types", []):
            name = edge["name"]
            # 转换为PascalCase类名
            class_name = ''.join(word.capitalize() for word in name.split('_'))
            desc = edge.get("description", f"A {name} relationship.")
            
            code_lines.append(f'class {class_name}(EdgeModel):')
            code_lines.append(f'    """{desc}"""')
            
            attrs = edge.get("attributes", [])
            if attrs:
                for attr in attrs:
                    attr_name = attr["name"]
                    attr_desc = attr.get("description", attr_name)
                    code_lines.append(f'    {attr_name}: EntityText = Field(')
                    code_lines.append(f'        description="{attr_desc}",')
                    code_lines.append(f'        default=None')
                    code_lines.append(f'    )')
            else:
                code_lines.append('    pass')
            
            code_lines.append('')
            code_lines.append('')
        
        # 生成类型字典
        code_lines.append('# ============== 类型配置 ==============')
        code_lines.append('')
        code_lines.append('ENTITY_TYPES = {')
        for entity in ontology.get("entity_types", []):
            name = entity["name"]
            code_lines.append(f'    "{name}": {name},')
        code_lines.append('}')
        code_lines.append('')
        code_lines.append('EDGE_TYPES = {')
        for edge in ontology.get("edge_types", []):
            name = edge["name"]
            class_name = ''.join(word.capitalize() for word in name.split('_'))
            code_lines.append(f'    "{name}": {class_name},')
        code_lines.append('}')
        code_lines.append('')
        
        # 生成边的source_targets映射
        code_lines.append('EDGE_SOURCE_TARGETS = {')
        for edge in ontology.get("edge_types", []):
            name = edge["name"]
            source_targets = edge.get("source_targets", [])
            if source_targets:
                st_list = ', '.join([
                    f'{{"source": "{st.get("source", "Entity")}", "target": "{st.get("target", "Entity")}"}}'
                    for st in source_targets
                ])
                code_lines.append(f'    "{name}": [{st_list}],')
        code_lines.append('}')
        
        return '\n'.join(code_lines)
