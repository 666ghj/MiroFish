"""报告小说化模式（novel-mac fork，改造 ③）。

novel seed 建立的项目在报告生成时进入小说模式：大纲规划 prompt 携带
小说 craft 约束（Persona 反应与引用、分歧/误读、期待与退出点、未收束
钩子），fallback 大纲即含这些章节；最终 markdown 经确定性后处理——
越界市场断言被降级标注，并追加「限制与不确定」一节（非市场代表、
不作预测、结果 proposal-only、标注 sourceRevision）。
"""

from __future__ import annotations

import os

import pytest

from app import create_app
from app.models.project import ProjectManager
from app.utils import zep as zep_utils

NEO4J_TEST_URI = os.environ.get("NEO4J_TEST_URI", "bolt://localhost:17687")
NEO4J_TEST_USER = os.environ.get("NEO4J_TEST_USER", "neo4j")
NEO4J_TEST_PASSWORD = os.environ.get("NEO4J_TEST_PASSWORD", "mirofishnovellocal")


def _neo4j_reachable() -> bool:
    try:
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(
            NEO4J_TEST_URI, auth=(NEO4J_TEST_USER, NEO4J_TEST_PASSWORD)
        )
        try:
            driver.verify_connectivity()
        finally:
            driver.close()
        return True
    except Exception:
        return False


requires_neo4j = pytest.mark.skipif(
    not _neo4j_reachable(), reason=f"本地 Neo4j 不可达: {NEO4J_TEST_URI}"
)


def _agent(novel_seed=None):
    from app.services.report_agent import ReportAgent

    return ReportAgent(
        graph_id="g",
        simulation_id="s",
        simulation_requirement="实验问题：x",
        novel_seed=novel_seed,
    )


# ---------- 元数据贯通 ----------


@requires_neo4j
def test_novel_seed_metadata_reaches_project(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPH_MEMORY_BACKEND", "neo4j_local")
    monkeypatch.setattr(zep_utils.Config, "NEO4J_URI", NEO4J_TEST_URI)
    monkeypatch.setattr(zep_utils.Config, "NEO4J_USER", NEO4J_TEST_USER)
    monkeypatch.setattr(zep_utils.Config, "NEO4J_PASSWORD", NEO4J_TEST_PASSWORD)
    monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(tmp_path))
    zep_utils.clear_zep_client_cache()

    from tests.test_novel_seed_endpoint import _cleanup_graphs, _seed_payload

    app = create_app()
    app.config.update(TESTING=True)
    data = app.test_client().post("/api/novel/seed", json=_seed_payload()).json["data"]
    try:
        project = ProjectManager.get_project(data["project_id"])
        assert project.novel_seed == {
            "projectId": "wugang-R5",
            "sourceRevision": 5,
            "inputHash": data["input_hash"],
        }
    finally:
        zep_utils.clear_zep_client_cache()
        _cleanup_graphs([data["graph_id"]])


# ---------- 大纲：prompt 约束与确定性 fallback ----------


def test_novel_outline_prompt_carries_craft_constraints(monkeypatch):
    agent = _agent(novel_seed={"projectId": "p", "sourceRevision": 5, "inputHash": "h"})
    captured = {}

    class FakeLLM:
        def chat_json(self, *, messages, **_kwargs):
            captured["system"] = messages[0]["content"]
            captured["user"] = messages[1]["content"]
            return {"title": "t", "summary": "s", "sections": []}

    class FakeZepTools:
        def get_simulation_context(self, **_kwargs):
            return {"graph_statistics": {}, "related_facts": [], "total_entities": 0}

    monkeypatch.setattr(agent, "llm", FakeLLM())
    monkeypatch.setattr(agent, "zep_tools", FakeZepTools())

    outline = agent.plan_outline()

    combined = captured["system"] + captured["user"]
    for keyword in ("误读", "期待", "退出", "未收束钩子", "引用"):
        assert keyword in combined, f"大纲 prompt 缺少小说约束: {keyword}"
    assert outline is not None


def test_novel_outline_fallback_contains_craft_sections(monkeypatch):
    agent = _agent(novel_seed={"projectId": "p", "sourceRevision": 5, "inputHash": "h"})

    class FailingLLM:
        def chat_json(self, **_kwargs):
            raise RuntimeError("llm down")

    class FakeZepTools:
        def get_simulation_context(self, **_kwargs):
            return {"graph_statistics": {}, "related_facts": [], "total_entities": 0}

    monkeypatch.setattr(agent, "llm", FailingLLM())
    monkeypatch.setattr(agent, "zep_tools", FakeZepTools())

    outline = agent.plan_outline()
    titles = " ".join(section.title for section in outline.sections)
    for keyword in ("Persona", "误读", "退出", "未收束钩子", "限制与不确定"):
        assert keyword in titles, f"fallback 大纲缺少章节: {keyword}"


def test_non_novel_outline_fallback_unchanged(monkeypatch):
    agent = _agent(novel_seed=None)

    class FailingLLM:
        def chat_json(self, **_kwargs):
            raise RuntimeError("llm down")

    class FakeZepTools:
        def get_simulation_context(self, **_kwargs):
            return {"graph_statistics": {}, "related_facts": [], "total_entities": 0}

    monkeypatch.setattr(agent, "llm", FailingLLM())
    monkeypatch.setattr(agent, "zep_tools", FakeZepTools())

    outline = agent.plan_outline()
    titles = " ".join(section.title for section in outline.sections)
    assert "未收束钩子" not in titles
    assert "预测" in titles or "分析" in titles


# ---------- 确定性后处理：越界断言降级 + 限制节 ----------


def test_postprocess_neutralizes_market_claims_and_appends_constraints():
    from app.services.novel_report import novel_report_postprocess

    markdown = "# 模拟分析报告\n\n## 反应\n\n这个开篇必然爆款。\n\n读者会大量流失。\n"
    result = novel_report_postprocess(
        markdown,
        {"projectId": "wugang-R5", "sourceRevision": 5, "inputHash": "h"},
    )

    assert "必然爆款" in result  # 原文保留
    assert "未经证实的市场断言" in result  # 但被降级标注
    assert "限制与不确定" in result
    assert "R5" in result
    assert "proposal" in result or "提案" in result


def test_postprocess_is_identity_without_novel_seed():
    from app.services.novel_report import novel_report_postprocess

    markdown = "# 普通报告\n\n这个开篇必然爆款。\n"
    assert novel_report_postprocess(markdown, None) == markdown
