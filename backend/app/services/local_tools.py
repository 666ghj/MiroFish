"""
Local tools service for ReportAgent when GRAPH_BACKEND=local.

This provides a minimal subset of ZepToolsService capabilities using:
- Neo4j graph for nodes/edges
- Qdrant for semantic search over chunks (optional)

The return types reuse dataclasses from zep_tools.py for compatibility.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..config import Config
from ..utils.logger import get_logger
from .local_graph_store import LocalNeo4jGraphStore
from .local_vector_store import QdrantChunkStore
from .zep_tools import (
    InsightForgeResult,
    PanoramaResult,
    SearchResult,
    NodeInfo,
    EdgeInfo,
    InterviewResult,
    AgentInterview,
)

logger = get_logger("mirofish.local_tools")


class LocalToolsService:
    def __init__(self):
        self.graph_store = LocalNeo4jGraphStore()
        self.vector_store = None
        if Config.VECTOR_BACKEND == "qdrant":
            try:
                self.vector_store = QdrantChunkStore()
            except Exception as e:
                logger.warning(f"Qdrant init failed, semantic search disabled: {e}")
                self.vector_store = None

    @staticmethod
    def _load_agent_profiles(simulation_id: str) -> List[Dict[str, Any]]:
        """
        Load prepared agent profiles for a simulation.

        Mirrors ZepToolsService._load_agent_profiles() but without requiring Zep.
        """
        import os
        import csv
        import json

        sim_dir = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, simulation_id)
        profiles: List[Dict[str, Any]] = []

        reddit_profile_path = os.path.join(sim_dir, "reddit_profiles.json")
        if os.path.exists(reddit_profile_path):
            try:
                with open(reddit_profile_path, "r", encoding="utf-8") as f:
                    profiles = json.load(f)
                return profiles if isinstance(profiles, list) else []
            except Exception as e:
                logger.warning(f"Read reddit_profiles.json failed: {e}")

        twitter_profile_path = os.path.join(sim_dir, "twitter_profiles.csv")
        if os.path.exists(twitter_profile_path):
            try:
                with open(twitter_profile_path, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        profiles.append(
                            {
                                "realname": row.get("name", ""),
                                "username": row.get("username", ""),
                                "bio": row.get("description", ""),
                                "persona": row.get("user_char", ""),
                                "profession": "未知",
                            }
                        )
                return profiles
            except Exception as e:
                logger.warning(f"Read twitter_profiles.csv failed: {e}")

        return []

    def interview_agents(
        self,
        simulation_id: str,
        interview_requirement: str,
        simulation_requirement: str = "",
        max_agents: int = 5,
        custom_questions: Optional[List[str]] = None,
        **_: Any,
    ) -> InterviewResult:
        """
        Minimal implementation of ZepToolsService.interview_agents for local backend.

        It calls the real OASIS interview batch API (SimulationRunner.interview_agents_batch).
        """
        from .simulation_runner import SimulationRunner

        result = InterviewResult(
            interview_topic=interview_requirement,
            interview_questions=custom_questions or [],
        )

        profiles = self._load_agent_profiles(simulation_id)
        if not profiles:
            result.summary = "未找到可采访的 Agent 人设文件（请先完成 Step2 环境准备）"
            return result

        result.total_agents = len(profiles)

        # Select a deterministic subset (evenly spaced) to avoid biasing toward the first few.
        n = max(0, min(int(max_agents or 0), len(profiles)))
        if n == 0:
            result.summary = "max_agents=0，未执行采访"
            return result

        if n >= len(profiles):
            selected_indices = list(range(len(profiles)))
        else:
            step = max(1, len(profiles) // n)
            selected_indices = list(dict.fromkeys([i * step for i in range(n)]))[:n]

        # Build interview prompt (single prompt per agent; platform=None -> twitter+reddit)
        if custom_questions:
            combined_prompt = "\n".join([q.strip() for q in custom_questions if q and q.strip()][:5])
        else:
            combined_prompt = (
                "请以你的身份与立场，回答以下采访主题，并给出清晰、具体的观点与理由。\n\n"
                f"【模拟背景】{simulation_requirement}\n"
                f"【采访主题】{interview_requirement}\n"
                "要求：不要使用标题；可以分点；尽量引用你在模拟中的观察/经历（如有）。"
            )
            result.interview_questions = [interview_requirement]

        interviews_request = [{"agent_id": idx, "prompt": combined_prompt} for idx in selected_indices]

        # Environment must be alive (OASIS not closed)
        if not SimulationRunner.check_env_alive(simulation_id):
            result.summary = "采访失败：模拟环境未运行或已关闭（请保持模拟环境处于运行状态）"
            return result

        api_result = SimulationRunner.interview_agents_batch(
            simulation_id=simulation_id,
            interviews=interviews_request,
            platform=None,  # dual-platform interview
            timeout=180.0,
        )
        if not api_result.get("success", False):
            result.summary = f"采访API调用失败：{api_result.get('error', '未知错误')}"
            return result

        api_data = api_result.get("result", {})
        results_dict = api_data.get("results", {}) if isinstance(api_data, dict) else {}

        for agent_idx in selected_indices:
            agent = profiles[agent_idx] if agent_idx < len(profiles) else {}
            agent_name = agent.get("realname", agent.get("username", f"Agent_{agent_idx}"))
            agent_role = agent.get("profession", "未知")
            agent_bio = agent.get("bio", "")

            twitter_result = results_dict.get(f"twitter_{agent_idx}", {}) or {}
            reddit_result = results_dict.get(f"reddit_{agent_idx}", {}) or {}
            twitter_response = twitter_result.get("response", "") or ""
            reddit_response = reddit_result.get("response", "") or ""

            parts = []
            if twitter_response:
                parts.append(f"【Twitter平台回答】\n{twitter_response}")
            if reddit_response:
                parts.append(f"【Reddit平台回答】\n{reddit_response}")
            response_text = "\n\n".join(parts) if parts else "[无回复]"

            result.interviews.append(
                AgentInterview(
                    agent_name=agent_name,
                    agent_role=agent_role,
                    agent_bio=(agent_bio or "")[:1000],
                    question=combined_prompt,
                    response=response_text,
                    key_quotes=[],
                )
            )

        result.interviewed_count = len(result.interviews)
        if result.interviews:
            result.summary = f"已采访 {result.interviewed_count} 位Agent（本地模式）"
        else:
            result.summary = "未获得有效采访回复"
        return result

    def quick_search(self, graph_id: str, query: str, limit: int = 10) -> SearchResult:
        facts: List[str] = []
        if self.vector_store is not None:
            try:
                items = self.vector_store.search_chunks(
                    project_id=None,
                    graph_id=graph_id,
                    query=query,
                    limit=limit,
                )
                facts = [i.get("text", "") for i in items if i.get("text")]
            except Exception as e:
                logger.warning(f"Local quick_search vector failed: {e}")

        # Fallback: show edge facts from Neo4j
        if not facts:
            graph = self.graph_store.get_graph_data(graph_id)
            for e in (graph.get("edges") or [])[:limit]:
                fact = e.get("fact") or ""
                if fact:
                    facts.append(fact)

        return SearchResult(
            facts=facts[:limit],
            edges=[],
            nodes=[],
            query=query,
            total_count=len(facts[:limit]),
        )

    def search_graph(self, graph_id: str, query: str, limit: int = 10, scope: str = "edges") -> SearchResult:
        # Backward-compatible alias used by debug endpoints and older code.
        _ = scope
        return self.quick_search(graph_id=graph_id, query=query, limit=limit)

    def panorama_search(self, graph_id: str, query: str, include_expired: bool = True) -> PanoramaResult:
        graph = self.graph_store.get_graph_data(graph_id)
        nodes = graph.get("nodes") or []
        edges = graph.get("edges") or []

        # Facts: prefer vector search results if available, else use edge facts
        facts: List[str] = []
        if self.vector_store is not None and query:
            try:
                items = self.vector_store.search_chunks(
                    project_id=None,
                    graph_id=graph_id,
                    query=query,
                    limit=30,
                )
                facts = [i.get("text", "") for i in items if i.get("text")]
            except Exception:
                facts = []

        if not facts:
            facts = [e.get("fact") for e in edges if e.get("fact")]

        node_infos = [
            NodeInfo(
                uuid=n.get("uuid", ""),
                name=n.get("name", ""),
                labels=n.get("labels", []) or ["Entity"],
                summary=n.get("summary", ""),
                attributes=n.get("attributes", {}) or {},
            )
            for n in nodes
        ]

        edge_infos = [
            EdgeInfo(
                uuid=e.get("uuid", ""),
                name=e.get("name", ""),
                fact=e.get("fact", ""),
                source_node_uuid=e.get("source_node_uuid", ""),
                target_node_uuid=e.get("target_node_uuid", ""),
                source_node_name=e.get("source_node_name"),
                target_node_name=e.get("target_node_name"),
                created_at=e.get("created_at"),
                valid_at=e.get("valid_at"),
                invalid_at=e.get("invalid_at"),
                expired_at=e.get("expired_at"),
            )
            for e in edges
        ]

        result = PanoramaResult(query=query)
        result.all_nodes = node_infos
        result.all_edges = edge_infos
        result.total_nodes = len(node_infos)
        result.total_edges = len(edge_infos)
        result.active_facts = facts
        result.historical_facts = [] if not include_expired else []
        result.active_count = len(result.active_facts)
        result.historical_count = len(result.historical_facts)
        return result

    def insight_forge(
        self,
        graph_id: str,
        query: str,
        simulation_requirement: str = "",
        report_context: str = "",
    ) -> InsightForgeResult:
        # Minimal implementation: treat the query as a single sub-query and return semantic facts.
        search = self.quick_search(graph_id=graph_id, query=query, limit=15)

        graph = self.graph_store.get_graph_data(graph_id)
        nodes = graph.get("nodes") or []
        edges = graph.get("edges") or []

        # Pick top entities by occurrence in facts (very rough)
        entity_insights: List[Dict[str, Any]] = []
        for n in nodes[:10]:
            etype = next((l for l in (n.get("labels") or []) if l not in ["Entity", "Node"]), "实体")
            entity_insights.append(
                {
                    "name": n.get("name", ""),
                    "type": etype,
                    "summary": n.get("summary", ""),
                    "related_facts": [],
                }
            )

        relationship_chains = []
        for e in edges[:20]:
            s = e.get("source_node_name") or e.get("source_node_uuid", "")[:8]
            t = e.get("target_node_name") or e.get("target_node_uuid", "")[:8]
            rel = e.get("name") or e.get("fact_type") or "REL"
            relationship_chains.append(f"{s} --[{rel}]--> {t}")

        result = InsightForgeResult(
            query=query,
            simulation_requirement=simulation_requirement or "",
            sub_queries=[query],
        )
        result.semantic_facts = search.facts
        result.entity_insights = entity_insights
        result.relationship_chains = relationship_chains
        result.total_facts = len(result.semantic_facts)
        result.total_entities = len(result.entity_insights)
        result.total_relationships = len(result.relationship_chains)
        return result

    # Backward-compatible helpers used by ReportAgent
    def get_graph_statistics(self, graph_id: str) -> Dict[str, Any]:
        g = self.graph_store.get_graph_data(graph_id)
        return {"graph_id": graph_id, "node_count": g.get("node_count", 0), "edge_count": g.get("edge_count", 0)}

    def get_entities_by_type(self, graph_id: str, entity_type: str) -> List[NodeInfo]:
        g = self.graph_store.get_graph_data(graph_id)
        nodes = g.get("nodes") or []
        out: List[NodeInfo] = []
        for n in nodes:
            labels = n.get("labels") or []
            if entity_type and entity_type not in labels:
                continue
            out.append(
                NodeInfo(
                    uuid=n.get("uuid", ""),
                    name=n.get("name", ""),
                    labels=labels or ["Entity"],
                    summary=n.get("summary", ""),
                    attributes=n.get("attributes", {}) or {},
                )
            )
        return out

    def get_entity_summary(self, graph_id: str, entity_name: str) -> Dict[str, Any]:
        g = self.graph_store.get_graph_data(graph_id)
        for n in g.get("nodes") or []:
            if (n.get("name") or "").strip() == (entity_name or "").strip():
                etype = next((l for l in (n.get("labels") or []) if l not in ["Entity", "Node"]), "实体")
                return {
                    "name": n.get("name", ""),
                    "type": etype,
                    "summary": n.get("summary", ""),
                    "attributes": n.get("attributes", {}) or {},
                }
        return {"name": entity_name, "summary": "", "attributes": {}}

    def get_simulation_context(
        self,
        graph_id: str,
        simulation_requirement: str = "",
        limit: int = 30,
        query: Optional[str] = None,
        **_: Any,
    ) -> Dict[str, Any]:
        """
        Compatibility shim for ZepToolsService.get_simulation_context().

        ReportAgent expects this method to accept `simulation_requirement` and to return:
          - simulation_requirement
          - related_facts
          - graph_statistics
          - entities
          - total_entities
        """
        q = (query or simulation_requirement or "").strip()

        search = self.quick_search(graph_id=graph_id, query=q, limit=limit)
        stats = self.get_graph_statistics(graph_id)

        g = self.graph_store.get_graph_data(graph_id)
        entities: List[Dict[str, Any]] = []
        for n in g.get("nodes") or []:
            labels = n.get("labels") or []
            custom_labels = [l for l in labels if l not in ["Entity", "Node"]]
            if not custom_labels:
                continue
            entities.append(
                {
                    "name": n.get("name", ""),
                    "type": custom_labels[0],
                    "summary": n.get("summary", ""),
                }
            )

        return {
            "simulation_requirement": simulation_requirement,
            "related_facts": search.facts,
            "graph_statistics": stats,
            "entities": entities[:limit],
            "total_entities": len(entities),
        }
