"""NovelMirofishSeed 确定性摄入服务（novel-mac fork，改造 ①）。

把 novel-agent 侧编译的种子 JSON 一次写入：project（含正文缓存与确定性的
simulation_requirement）+ 图谱实体/边。全程不经 LLM 与本体抽取；同一 seed
产生相同 inputHash 与同构实体集。设计契约见 novel-agent 仓库
docs/mirofish-novel-sandbox-design.md（seed schema 与 proposal-only 断言）。
"""

from __future__ import annotations

import hashlib
import json
import uuid as uuidlib
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..models.project import ProjectManager, ProjectStatus
from ..utils.logger import get_logger
from ..utils.zep import get_zep_client

logger = get_logger("mirofish.novel_seed")


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SeedManuscriptUnit(_StrictModel):
    unitId: str
    title: str
    acceptedText: str
    sourceAnchors: List[str] = Field(default_factory=list)


class SeedCharacter(_StrictModel):
    id: str
    name: str
    goals: List[str] = Field(default_factory=list)
    beliefs: List[str] = Field(default_factory=list)
    constraints: List[str] = Field(default_factory=list)
    relationships: List[str] = Field(default_factory=list)
    knowledgeBoundary: List[str] = Field(default_factory=list)


class SeedFaction(_StrictModel):
    id: str
    name: str
    goals: List[str] = Field(default_factory=list)


class SeedWorldRule(_StrictModel):
    id: str
    statement: str
    exceptions: List[str] = Field(default_factory=list)


class SeedPromise(_StrictModel):
    id: str
    state: str
    expectedWindow: Optional[str] = None


class SeedReaderPersona(_StrictModel):
    id: str
    name: str
    description: str
    readingHistory: List[str] = Field(default_factory=list)


class SeedRelation(_StrictModel):
    sourceId: str
    targetId: str
    name: str
    fact: str = ""


class SeedScenario(_StrictModel):
    question: str
    intervention: str = ""
    horizon: str = ""


class NovelMirofishSeed(_StrictModel):
    projectId: str
    sourceRevision: int
    manuscriptUnits: List[SeedManuscriptUnit] = Field(default_factory=list)
    characters: List[SeedCharacter] = Field(default_factory=list)
    factions: List[SeedFaction] = Field(default_factory=list)
    worldRules: List[SeedWorldRule] = Field(default_factory=list)
    promises: List[SeedPromise] = Field(default_factory=list)
    readerPersonas: List[SeedReaderPersona] = Field(default_factory=list)
    relations: List[SeedRelation] = Field(default_factory=list)
    scenario: SeedScenario


class NovelSeedValidationError(ValueError):
    """种子不合法（schema 之外的业务引用错误）。"""


def _scalar(value: Any) -> Any:
    """zep add_nodes 的 attributes 只收标量；列表退化为「；」连接串。"""

    if isinstance(value, list):
        return "；".join(str(item) for item in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return json.dumps(value, ensure_ascii=False)


def _node_attributes(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {key: _scalar(value) for key, value in payload.items()}


def _join_summary(parts: List[str]) -> str:
    return "；".join(part for part in parts if part)


def compile_simulation_requirement(seed: NovelMirofishSeed) -> str:
    """确定性编译项目级模拟需求文本，供 prepare 阶段引用。"""

    lines = [
        f"实验问题：{seed.scenario.question}",
    ]
    if seed.scenario.intervention:
        lines.append(f"干预：{seed.scenario.intervention}")
    if seed.scenario.horizon:
        lines.append(f"观察窗口：{seed.scenario.horizon}")
    if seed.readerPersonas:
        persona_lines = [
            f"- {persona.name}（{persona.id}）：{persona.description}"
            for persona in seed.readerPersonas
        ]
        lines.append("显式读者 Persona：" + "；".join(persona_lines))
    lines.append(f"来源：novel-agent 已接受修订 R{seed.sourceRevision}")
    return "\n".join(lines)


class NovelSeeder:
    def __init__(self):
        self.client = get_zep_client()

    def seed(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            seed = NovelMirofishSeed.model_validate(payload)
        except ValidationError as error:
            raise NovelSeedValidationError(str(error)) from error

        self._validate_references(seed)

        input_hash = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()

        project = ProjectManager.create_project(
            name=f"novel-{seed.projectId}"
        )
        ProjectManager.save_extracted_text(
            project.project_id,
            "\n\n".join(
                f"## {unit.title}\n\n{unit.acceptedText}"
                for unit in seed.manuscriptUnits
            ),
        )

        graph_id = f"mirofish_novel_{seed.projectId}_{input_hash[:12]}"
        self.client.graph.create(
            graph_id=graph_id,
            name=f"novel-{seed.projectId}-R{seed.sourceRevision}",
            description=f"deterministic seed from accepted revision R{seed.sourceRevision}",
        )
        try:
            entity_index = self._write_entities(seed, graph_id)
            self._write_relations(seed, graph_id, entity_index)
        except Exception:
            # 建图失败不留半成品图；project 由调用方标记失败。
            try:
                self.client.graph.delete(graph_id=graph_id)
            except Exception:
                logger.warning("清理失败图谱 %s 未成功", graph_id)
            raise

        project.simulation_requirement = compile_simulation_requirement(seed)
        project.novel_seed = {
            "projectId": seed.projectId,
            "sourceRevision": seed.sourceRevision,
            "inputHash": input_hash,
        }
        project.graph_id = graph_id
        project.status = ProjectStatus.GRAPH_COMPLETED
        project.updated_at = _now_iso()
        ProjectManager.save_project(project)

        return {
            "project_id": project.project_id,
            "graph_id": graph_id,
            "input_hash": input_hash,
            "source_revision": seed.sourceRevision,
            "entity_count": len(entity_index),
        }

    def _validate_references(self, seed: NovelMirofishSeed) -> None:
        known_ids = {
            entity.id
            for entity in [*seed.characters, *seed.factions, *seed.readerPersonas]
        }
        for relation in seed.relations:
            if relation.sourceId not in known_ids:
                raise NovelSeedValidationError(
                    f"relations.sourceId 指向未知实体: {relation.sourceId}"
                )
            if relation.targetId not in known_ids:
                raise NovelSeedValidationError(
                    f"relations.targetId 指向未知实体: {relation.targetId}"
                )

    def _write_entities(self, seed: NovelMirofishSeed, graph_id: str) -> Dict[str, str]:
        """写全部实体节点，返回 实体id → 节点uuid 的确定性映射。"""

        index: Dict[str, str] = {}

        def deterministic_uuid(entity_id: str) -> str:
            return f"novel_{seed.projectId}_{entity_id}"

        nodes = []
        for character in seed.characters:
            nodes.append(
                {
                    "uuid": deterministic_uuid(character.id),
                    "name": character.name,
                    "label": "Character",
                    "summary": _join_summary(
                        [f"目标：{'；'.join(character.goals)}" if character.goals else "",
                         f"信念：{'；'.join(character.beliefs)}" if character.beliefs else ""]
                    ),
                    "attributes": _node_attributes(character.model_dump()),
                }
            )
            index[character.id] = deterministic_uuid(character.id)
        for faction in seed.factions:
            nodes.append(
                {
                    "uuid": deterministic_uuid(faction.id),
                    "name": faction.name,
                    "label": "Faction",
                    "summary": _join_summary(
                        [f"目标：{'；'.join(faction.goals)}" if faction.goals else ""]
                    ),
                    "attributes": _node_attributes(faction.model_dump()),
                }
            )
            index[faction.id] = deterministic_uuid(faction.id)
        for persona in seed.readerPersonas:
            nodes.append(
                {
                    "uuid": deterministic_uuid(persona.id),
                    "name": persona.name,
                    "label": "ReaderPersona",
                    "summary": persona.description,
                    "attributes": _node_attributes(persona.model_dump()),
                }
            )
            index[persona.id] = deterministic_uuid(persona.id)
        for rule in seed.worldRules:
            nodes.append(
                {
                    "uuid": deterministic_uuid(rule.id),
                    "name": rule.statement,
                    "label": "WorldRule",
                    "summary": rule.statement
                    + (f"（例外：{'；'.join(rule.exceptions)}）" if rule.exceptions else ""),
                    "attributes": _node_attributes(rule.model_dump()),
                }
            )
            index[rule.id] = deterministic_uuid(rule.id)
        for promise in seed.promises:
            nodes.append(
                {
                    "uuid": deterministic_uuid(promise.id),
                    "name": promise.id,
                    "label": "Promise",
                    "summary": f"状态 {promise.state}"
                    + (f"，预期回收窗口 {promise.expectedWindow}" if promise.expectedWindow else ""),
                    "attributes": _node_attributes(promise.model_dump()),
                }
            )
            index[promise.id] = deterministic_uuid(promise.id)

        if nodes:
            from zep_cloud import AddNodeItem

            # uuid 用字段名 uuid_ 传入：alias 'uuid' 在构造时会被静默忽略。
            items = [
                AddNodeItem(
                    uuid_=node["uuid"],
                    name=node["name"],
                    label=node["label"],
                    summary=node["summary"],
                    attributes=node["attributes"],
                )
                for node in nodes
            ]
            self.client.graph.add_nodes(nodes=items, graph_id=graph_id)
        return index

    def _write_relations(
        self, seed: NovelMirofishSeed, graph_id: str, entity_index: Dict[str, str]
    ) -> None:
        name_by_id: Dict[str, str] = {}
        for entity in [*seed.characters, *seed.factions, *seed.readerPersonas]:
            name_by_id[entity.id] = entity.name
        for rule in seed.worldRules:
            name_by_id[rule.id] = rule.statement
        for promise in seed.promises:
            name_by_id[promise.id] = promise.id

        for relation in seed.relations:
            self.client.graph.add_fact_triple(
                fact=relation.fact or f"{name_by_id[relation.sourceId]} 与 {name_by_id[relation.targetId]} 存在 {relation.name} 关系",
                fact_name=relation.name,
                graph_id=graph_id,
                source_node_uuid=entity_index[relation.sourceId],
                target_node_uuid=entity_index[relation.targetId],
            )


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
