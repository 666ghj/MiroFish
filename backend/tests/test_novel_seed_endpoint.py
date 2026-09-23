"""JSON seed 端点测试（novel-mac fork，改造 ①）。

POST /api/novel/seed 接受 NovelMirofishSeed：确定性建 project + 图谱实体/边
（显式写入，不经 LLM/本体抽取），缓存正文文本，返回 project_id / graph_id /
inputHash。同一 seed 两次调用产生等价实体集与相同 inputHash。
"""

from __future__ import annotations

import os

import pytest

from app import create_app
from app.models.project import ProjectManager, ProjectStatus
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


def _seed_payload() -> dict:
    return {
        "projectId": "wugang-R5",
        "sourceRevision": 5,
        "manuscriptUnits": [
            {
                "unitId": "ch1",
                "title": "第一章 夜潮",
                "acceptedText": "林砚在雾港夜班巡检航标，收到第七码头被删除的记录。",
                "sourceAnchors": ["manuscript://ch1#p1"],
            }
        ],
        "characters": [
            {
                "id": "linyan",
                "name": "林砚",
                "goals": ["查清父亲下落"],
                "beliefs": ["航标记录不会无故消失"],
                "constraints": ["背负债务，不能辞职"],
                "relationships": ["与苏晚从不信任到共同承担代价"],
                "knowledgeBoundary": ["不知道旧港层显形条件"],
            },
            {
                "id": "suwan",
                "name": "苏晚",
                "goals": ["补全旧港记录"],
                "beliefs": ["制度内有人删过记录"],
                "constraints": [],
                "relationships": [],
                "knowledgeBoundary": [],
            },
        ],
        "factions": [
            {"id": "gangwu", "name": "港务", "goals": ["维持秩序", "掩盖旧账"]}
        ],
        "worldRules": [
            {"id": "rule-xianxing", "statement": "旧港层只在夜潮显形", "exceptions": ["无"]}
        ],
        "promises": [{"id": "p-dock7", "state": "open", "expectedWindow": "卷一结尾"}],
        "readerPersonas": [
            {
                "id": "mystery-reader",
                "name": "悬疑读者",
                "description": "追线索、讨厌降智，重视信息差公平性",
                "readingHistory": ["读过上架前三章"],
            },
            {
                "id": "daily-reader",
                "name": "日常向读者",
                "description": "看人物关系与职业细节，对慢热宽容",
                "readingHistory": [],
            },
        ],
        "relations": [
            {
                "sourceId": "linyan",
                "targetId": "suwan",
                "name": "partners_with",
                "fact": "林砚与苏晚搭档",
            },
            {
                "sourceId": "linyan",
                "targetId": "gangwu",
                "name": "opposes",
                "fact": "林砚追查记录，与港务秩序动机冲突",
            },
        ],
        "scenario": {
            "question": "第一章的删除记录线索是否让悬疑读者继续追读",
            "intervention": "第七码头记录被删除",
            "horizon": "前 3 章",
        },
    }


@pytest.fixture()
def local_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPH_MEMORY_BACKEND", "neo4j_local")
    monkeypatch.setattr(zep_utils.Config, "NEO4J_URI", NEO4J_TEST_URI)
    monkeypatch.setattr(zep_utils.Config, "NEO4J_USER", NEO4J_TEST_USER)
    monkeypatch.setattr(zep_utils.Config, "NEO4J_PASSWORD", NEO4J_TEST_PASSWORD)
    monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(tmp_path))
    zep_utils.clear_zep_client_cache()
    yield
    zep_utils.clear_zep_client_cache()


def _cleanup_graphs(graph_ids):
    from app.utils.local_graph_memory import LocalGraphMemoryClient

    client = LocalGraphMemoryClient(
        NEO4J_TEST_URI, NEO4J_TEST_USER, NEO4J_TEST_PASSWORD
    )
    for graph_id in graph_ids:
        try:
            client.graph.delete(graph_id=graph_id)
        except Exception:
            pass


@requires_neo4j
def test_seed_creates_project_graph_and_text_deterministically(local_env):
    app = create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    response = client.post("/api/novel/seed", json=_seed_payload())
    assert response.status_code == 200, response.json
    data = response.json["data"]
    project_id, graph_id = data["project_id"], data["graph_id"]

    try:
        project = ProjectManager.get_project(project_id)
        assert project is not None
        assert project.status == ProjectStatus.GRAPH_COMPLETED
        assert project.graph_id == graph_id
        assert "删除记录线索" in (project.simulation_requirement or "")

        extracted = ProjectManager.get_extracted_text(project_id) or ""
        assert "林砚在雾港夜班巡检航标" in extracted

        from app.services.zep_entity_reader import ZepEntityReader

        reader = ZepEntityReader(api_key=None)
        node_names = {n["name"] for n in reader.get_all_nodes(graph_id)}
        assert {"林砚", "苏晚", "港务", "悬疑读者", "日常向读者"} <= node_names

        edges = reader.get_all_edges(graph_id)
        edge_names = {e["name"] for e in edges}
        assert {"partners_with", "opposes"} <= edge_names
    finally:
        _cleanup_graphs([graph_id])


@requires_neo4j
def test_seed_is_deterministic_same_hash_equivalent_entities(local_env):
    app = create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    first = client.post("/api/novel/seed", json=_seed_payload()).json["data"]
    second = client.post("/api/novel/seed", json=_seed_payload()).json["data"]
    try:
        assert first["input_hash"] == second["input_hash"]

        from app.services.zep_entity_reader import ZepEntityReader

        reader = ZepEntityReader(api_key=None)
        first_nodes = sorted(
            n["name"] for n in reader.get_all_nodes(first["graph_id"])
        )
        second_nodes = sorted(
            n["name"] for n in reader.get_all_nodes(second["graph_id"])
        )
        assert first_nodes == second_nodes
    finally:
        _cleanup_graphs([first["graph_id"], second["graph_id"]])


@requires_neo4j
def test_seed_hash_changes_when_text_changes(local_env):
    app = create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    payload_a = _seed_payload()
    payload_b = _seed_payload()
    payload_b["manuscriptUnits"][0]["acceptedText"] += "（改写后的结尾）"

    first = client.post("/api/novel/seed", json=payload_a).json["data"]
    second = client.post("/api/novel/seed", json=payload_b).json["data"]
    try:
        assert first["input_hash"] != second["input_hash"]
    finally:
        _cleanup_graphs([first["graph_id"], second["graph_id"]])


def test_seed_rejects_missing_required_fields(local_env):
    app = create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    response = client.post("/api/novel/seed", json={"projectId": "x"})
    assert response.status_code == 400
    assert response.json["success"] is False


def test_seed_rejects_unknown_top_level_keys(local_env):
    app = create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    payload = _seed_payload()
    payload["unexpectedKey"] = True
    response = client.post("/api/novel/seed", json=payload)
    assert response.status_code == 400
    assert response.json["success"] is False


@requires_neo4j
def test_seed_rejects_relation_to_unknown_entity(local_env):
    app = create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    payload = _seed_payload()
    payload["relations"][0]["targetId"] = "nobody"
    response = client.post("/api/novel/seed", json=payload)
    assert response.status_code == 400
    assert response.json["success"] is False
