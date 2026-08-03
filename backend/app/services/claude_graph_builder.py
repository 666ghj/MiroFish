"""
图谱构建服务 - Claude 引擎
使用 Claude（Anthropic API）作为图谱构建的智能体，对文本分片进行实体/关系抽取，
按照 Graphify 的思路做"增量式、透明化"的图谱构建：每个文本块都会被 Claude
以结构化 tool-use 的方式抽取实体与关系，逐步合并进本地图谱存储。

与 GraphBuilderService（Zep 引擎）保持一致的公开接口，可在 API 层互换使用：
    create_graph / set_ontology / add_text_batches / _wait_for_episodes /
    get_graph_data / delete_graph
"""

import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional, Callable

import anthropic

from ..config import Config
from ..models.graph_store import GraphStore
from ..utils.locale import t, get_language_instruction


def _extraction_tool(ontology: Dict[str, Any]) -> Dict[str, Any]:
    """根据本体定义动态构建 Claude tool-use 的抽取工具schema"""
    entity_names = [e["name"] for e in ontology.get("entity_types", [])] or ["Entity"]
    edge_names = [e["name"] for e in ontology.get("edge_types", [])] or ["RELATED_TO"]

    return {
        "name": "record_graph_fragment",
        "description": (
            "Record the entities and relationships that are explicitly grounded in the "
            "given text fragment, strictly following the provided ontology types."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "entities": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Canonical name of the entity, consistent across mentions in the whole document."
                            },
                            "type": {"type": "string", "enum": entity_names},
                            "summary": {
                                "type": "string",
                                "description": "One-sentence summary of this entity grounded in the text."
                            },
                            "attributes": {
                                "type": "object",
                                "description": "Key/value attributes for this entity matching its ontology type, string values only.",
                                "additionalProperties": {"type": "string"}
                            }
                        },
                        "required": ["name", "type"]
                    }
                },
                "relationships": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "source": {"type": "string", "description": "Name of the source entity, must match one of the entities above."},
                            "target": {"type": "string", "description": "Name of the target entity, must match one of the entities above."},
                            "relation": {"type": "string", "enum": edge_names},
                            "fact": {"type": "string", "description": "The specific fact/sentence from the text that supports this relationship."}
                        },
                        "required": ["source", "target", "relation", "fact"]
                    }
                }
            },
            "required": ["entities", "relationships"]
        }
    }


def _system_prompt(ontology: Dict[str, Any]) -> str:
    entity_lines = []
    for e in ontology.get("entity_types", []):
        entity_lines.append(f"- {e['name']}: {e.get('description', '')}")
    edge_lines = []
    for edge in ontology.get("edge_types", []):
        targets = ", ".join(
            f"{st.get('source')}->{st.get('target')}" for st in edge.get("source_targets", [])
        )
        edge_lines.append(f"- {edge['name']}: {edge.get('description', '')} (allowed: {targets})")

    return f"""You are a precise knowledge-graph extraction agent, acting as the graph-construction engine of MiroFish.

Your job: read one text fragment at a time and call the `record_graph_fragment` tool with the
entities and relationships that are EXPLICITLY grounded in that fragment. Do not invent facts.
Reuse entity names exactly as they appear elsewhere so the graph can be merged correctly.

## Entity types
{chr(10).join(entity_lines) or '- Entity: generic entity'}

## Relationship types
{chr(10).join(edge_lines) or '- RELATED_TO: generic relationship'}

## Rules
1. Only extract entities/relationships that are supported by the text fragment given to you.
2. Entity `name` must be the canonical, real-world name (e.g. a person's full name), not a pronoun.
3. Every relationship's `source` and `target` must refer to an entity you also listed in `entities`.
4. If nothing relevant is in the fragment, call the tool with empty `entities` and `relationships` arrays.
5. {get_language_instruction()} (this applies to `summary` and `fact` fields only; `name`/`type`/`relation` stay as defined by the ontology).
"""


class ClaudeGraphBuilderService:
    """
    图谱构建服务 - Claude 引擎
    使用 Anthropic Claude API 作为图谱构建的智能体
    """

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or Config.ANTHROPIC_API_KEY
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY 未配置")

        self.model = model or Config.CLAUDE_MODEL_NAME
        client_kwargs = {"api_key": self.api_key}
        if Config.ANTHROPIC_BASE_URL:
            client_kwargs["base_url"] = Config.ANTHROPIC_BASE_URL

        self.client = anthropic.Anthropic(**client_kwargs)

    # ============== 与 GraphBuilderService 对齐的公开接口 ==============

    def create_graph(self, name: str) -> str:
        """创建本地图谱（公开方法，与 Zep 引擎接口对齐）"""
        graph_id = f"mirofish_claude_{uuid.uuid4().hex[:16]}"
        GraphStore.create(graph_id, name=name, description="MiroFish Claude-powered Graph")
        return graph_id

    def set_ontology(self, graph_id: str, ontology: Dict[str, Any]) -> None:
        """设置图谱本体（公开方法）"""
        data = GraphStore.load(graph_id)
        if data is None:
            raise ValueError(f"图谱不存在: {graph_id}")
        data["ontology"] = ontology
        GraphStore.save(graph_id, data)

    def add_text_batches(
        self,
        graph_id: str,
        chunks: List[str],
        batch_size: int = 3,
        progress_callback: Optional[Callable] = None
    ) -> List[str]:
        """
        对每个文本块调用 Claude 进行实体/关系抽取，逐步合并进图谱
        返回处理过的 episode id 列表（用于与 Zep 引擎接口对齐）
        """
        data = GraphStore.load(graph_id)
        if data is None:
            raise ValueError(f"图谱不存在: {graph_id}")

        ontology = data.get("ontology") or {}
        tool = _extraction_tool(ontology)
        system_prompt = _system_prompt(ontology)

        episode_uuids = []
        total_chunks = len(chunks)
        failures = 0

        for i, chunk in enumerate(chunks):
            episode_id = f"ep_{uuid.uuid4().hex[:12]}"

            if progress_callback:
                progress_callback(
                    t('progress.claudeExtractingChunk', current=i + 1, total=total_chunks),
                    (i + 1) / total_chunks
                )

            try:
                fragment = self._extract_fragment(chunk, tool, system_prompt)
                self._merge_fragment(data, fragment, episode_id)
                GraphStore.save(graph_id, data)
                episode_uuids.append(episode_id)
            except Exception as e:
                failures += 1
                if progress_callback:
                    progress_callback(
                        t('progress.claudeChunkFailed', current=i + 1, error=str(e)),
                        (i + 1) / total_chunks
                    )

        if failures == total_chunks and total_chunks > 0:
            raise RuntimeError(t('progress.claudeAllChunksFailed'))

        return episode_uuids

    def _wait_for_episodes(
        self,
        episode_uuids: List[str],
        progress_callback: Optional[Callable] = None,
        timeout: int = 600
    ) -> None:
        """Claude 引擎是同步抽取的，无需等待，直接汇报完成"""
        if progress_callback:
            progress_callback(
                t('progress.processingComplete', completed=len(episode_uuids), total=len(episode_uuids)),
                1.0
            )

    def get_graph_data(self, graph_id: str) -> Dict[str, Any]:
        """获取完整图谱数据（nodes/edges），与 Zep 引擎返回格式保持一致"""
        data = GraphStore.load(graph_id)
        if data is None:
            raise ValueError(f"图谱不存在: {graph_id}")

        nodes_data = list(data.get("nodes", {}).values())
        edges_data = data.get("edges", [])

        return {
            "graph_id": graph_id,
            "nodes": nodes_data,
            "edges": edges_data,
            "node_count": len(nodes_data),
            "edge_count": len(edges_data),
        }

    def delete_graph(self, graph_id: str) -> None:
        """删除本地图谱"""
        GraphStore.delete(graph_id)

    # ============== 内部实现 ==============

    def _extract_fragment(
        self,
        chunk: str,
        tool: Dict[str, Any],
        system_prompt: str
    ) -> Dict[str, Any]:
        """调用 Claude，对单个文本块做结构化实体/关系抽取"""
        message = self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=system_prompt,
            tools=[tool],
            tool_choice={"type": "tool", "name": "record_graph_fragment"},
            messages=[{"role": "user", "content": chunk}],
        )

        for block in message.content:
            if getattr(block, "type", None) == "tool_use" and block.name == "record_graph_fragment":
                return block.input

        raise RuntimeError("Claude 未返回有效的图谱抽取结果")

    def _merge_fragment(self, data: Dict[str, Any], fragment: Dict[str, Any], episode_id: str) -> None:
        """将单个文本块的抽取结果合并进图谱存储"""
        nodes = data["nodes"]
        edges = data["edges"]
        now = datetime.now().isoformat()

        # 本次抽取内 name -> uuid 的映射，便于关系解析
        local_name_index: Dict[str, str] = {}

        for entity in fragment.get("entities", []):
            name = (entity.get("name") or "").strip()
            if not name:
                continue
            entity_type = entity.get("type") or "Entity"

            existing_uuid = self._find_node(nodes, name, entity_type)
            if existing_uuid:
                node = nodes[existing_uuid]
                # 合并属性（新值补充空缺字段）
                attrs = node.get("attributes") or {}
                for k, v in (entity.get("attributes") or {}).items():
                    if v and not attrs.get(k):
                        attrs[k] = v
                node["attributes"] = attrs
                summary = entity.get("summary")
                if summary and summary not in (node.get("summary") or ""):
                    node["summary"] = (node.get("summary") or "").strip()
                    node["summary"] = f"{node['summary']} {summary}".strip()
                local_name_index[name.lower()] = existing_uuid
                continue

            node_uuid = uuid.uuid4().hex
            nodes[node_uuid] = {
                "uuid": node_uuid,
                "name": name,
                "labels": ["Entity", entity_type],
                "summary": entity.get("summary") or "",
                "attributes": entity.get("attributes") or {},
                "created_at": now,
            }
            local_name_index[name.lower()] = node_uuid

        for rel in fragment.get("relationships", []):
            source_name = (rel.get("source") or "").strip()
            target_name = (rel.get("target") or "").strip()
            relation = rel.get("relation") or "RELATED_TO"
            fact = rel.get("fact") or ""

            source_uuid = local_name_index.get(source_name.lower()) or self._find_node_by_name(nodes, source_name)
            target_uuid = local_name_index.get(target_name.lower()) or self._find_node_by_name(nodes, target_name)

            if not source_uuid or not target_uuid:
                # 关系引用了未抽取到的实体，跳过而不是伪造节点
                continue

            if self._edge_exists(edges, source_uuid, target_uuid, relation, fact):
                continue

            edges.append({
                "uuid": uuid.uuid4().hex,
                "name": relation,
                "fact": fact,
                "fact_type": relation,
                "source_node_uuid": source_uuid,
                "target_node_uuid": target_uuid,
                "attributes": {},
                "created_at": now,
                "valid_at": now,
                "invalid_at": None,
                "expired_at": None,
                "episodes": [episode_id],
            })

    @staticmethod
    def _find_node(nodes: Dict[str, Any], name: str, entity_type: str) -> Optional[str]:
        name_l = name.lower()
        for node_uuid, node in nodes.items():
            if node["name"].lower() == name_l and entity_type in (node.get("labels") or []):
                return node_uuid
        return None

    @staticmethod
    def _find_node_by_name(nodes: Dict[str, Any], name: str) -> Optional[str]:
        name_l = name.lower()
        for node_uuid, node in nodes.items():
            if node["name"].lower() == name_l:
                return node_uuid
        return None

    @staticmethod
    def _edge_exists(edges: List[Dict[str, Any]], source_uuid: str, target_uuid: str, relation: str, fact: str) -> bool:
        for edge in edges:
            if (
                edge["source_node_uuid"] == source_uuid
                and edge["target_node_uuid"] == target_uuid
                and edge["name"] == relation
                and edge["fact"] == fact
            ):
                return True
        return False
