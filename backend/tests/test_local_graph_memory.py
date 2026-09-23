"""Neo4j 本地图记忆后端测试（novel-mac fork）。

GRAPH_MEMORY_BACKEND=neo4j_local 时，共享 zep 客户端接缝返回本地 Neo4j 实现，
且不再要求 ZEP Cloud 凭据；云后端的校验强度保持不变。需要真实 Neo4j 的
roundtrip 用例在 Neo4j 不可达时跳过，配置切换断言始终运行。
"""

from __future__ import annotations

import os
import uuid as uuidlib

import pytest

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


# ---------- Config.validate 按后端分支 ----------


def test_validate_allows_local_backend_without_zep_key(monkeypatch):
    from app.config import Config

    monkeypatch.setenv("GRAPH_MEMORY_BACKEND", "neo4j_local")
    monkeypatch.setattr(Config, "LLM_API_KEY", "test-llm-key")
    monkeypatch.setattr(Config, "ZEP_API_KEY", None)
    monkeypatch.delenv("ZEP_API_URL", raising=False)

    errors = Config.validate()
    assert errors == [], f"neo4j_local 后端不应要求 Zep 配置: {errors}"


def test_validate_still_requires_zep_key_on_cloud_backend(monkeypatch):
    from app.config import Config

    monkeypatch.delenv("GRAPH_MEMORY_BACKEND", raising=False)
    monkeypatch.setattr(Config, "GRAPH_MEMORY_BACKEND", "zep")
    monkeypatch.setattr(Config, "LLM_API_KEY", "test-llm-key")
    monkeypatch.setattr(Config, "ZEP_API_KEY", None)
    monkeypatch.delenv("ZEP_API_URL", raising=False)

    errors = Config.validate()
    assert any("ZEP_API_KEY" in e for e in errors), "云后端不得放松 ZEP_API_KEY 校验"


def test_validate_rejects_unknown_backend(monkeypatch):
    from app.config import Config

    monkeypatch.setenv("GRAPH_MEMORY_BACKEND", "sqlite_magic")
    monkeypatch.setattr(Config, "LLM_API_KEY", "test-llm-key")
    monkeypatch.setattr(Config, "ZEP_API_KEY", "some-key")
    monkeypatch.delenv("ZEP_API_URL", raising=False)

    errors = Config.validate()
    assert any("GRAPH_MEMORY_BACKEND" in e for e in errors), "未知后端必须显式报错"


# ---------- 客户端接缝切换 ----------


def test_get_zep_client_switches_to_local_backend(monkeypatch):
    from app.utils import zep as zep_utils

    monkeypatch.setenv("GRAPH_MEMORY_BACKEND", "neo4j_local")
    monkeypatch.setattr(
        zep_utils.Config,
        "NEO4J_URI",
        NEO4J_TEST_URI,
    )
    monkeypatch.setattr(zep_utils.Config, "NEO4J_USER", NEO4J_TEST_USER)
    monkeypatch.setattr(zep_utils.Config, "NEO4J_PASSWORD", NEO4J_TEST_PASSWORD)
    monkeypatch.setattr(zep_utils.Config, "ZEP_API_KEY", None)
    zep_utils.clear_zep_client_cache()
    try:
        client = zep_utils.get_zep_client()
        assert type(client).__name__ == "LocalGraphMemoryClient"
    finally:
        zep_utils.clear_zep_client_cache()


def test_get_zep_client_still_requires_zep_key_on_cloud(monkeypatch):
    from app.utils import zep as zep_utils

    monkeypatch.delenv("GRAPH_MEMORY_BACKEND", raising=False)
    monkeypatch.setattr(zep_utils.Config, "GRAPH_MEMORY_BACKEND", "zep")
    monkeypatch.setattr(zep_utils.Config, "ZEP_API_KEY", None)
    zep_utils.clear_zep_client_cache()
    try:
        with pytest.raises(ValueError, match="ZEP_API_KEY"):
            zep_utils.get_zep_client()
    finally:
        zep_utils.clear_zep_client_cache()


# ---------- 本地客户端与真实 Neo4j 的 roundtrip ----------


@requires_neo4j
def test_graph_lifecycle_create_get_delete(monkeypatch):
    from app.utils.local_graph_memory import LocalGraphMemoryClient

    client = LocalGraphMemoryClient(
        NEO4J_TEST_URI, NEO4J_TEST_USER, NEO4J_TEST_PASSWORD
    )
    graph_id = f"mfn_{uuidlib.uuid4().hex[:12]}"
    try:
        client.graph.create(
            graph_id=graph_id, name="novel-seed-test", description="本地后端测试图"
        )
        found = client.graph.get(graph_id=graph_id)
        assert getattr(found, "uuid_", None) == graph_id
        assert getattr(found, "name", None) == "novel-seed-test"
    finally:
        client.graph.delete(graph_id=graph_id)

    from zep_cloud import NotFoundError

    with pytest.raises(NotFoundError):
        client.graph.get(graph_id=graph_id)


@requires_neo4j
def test_add_fact_triple_then_read_nodes_and_edges(monkeypatch):
    from app.utils.local_graph_memory import LocalGraphMemoryClient

    client = LocalGraphMemoryClient(
        NEO4J_TEST_URI, NEO4J_TEST_USER, NEO4J_TEST_PASSWORD
    )
    graph_id = f"mfn_{uuidlib.uuid4().hex[:12]}"
    try:
        client.graph.create(graph_id=graph_id, name="seed-roundtrip", description="")
        client.graph.add_fact_triple(
            fact="林砚维护雾港的夜间航标",
            fact_name="maintains",
            graph_id=graph_id,
            source_node_name="林砚",
            source_node_labels=["Entity", "Character"],
            source_node_summary="雾港夜班航标维护员",
            target_node_name="雾港航标",
            target_node_labels=["Entity", "Location"],
            target_node_summary="雾港的航标系统",
        )

        nodes_page = client.graph.node.with_raw_response.get_by_graph_id(
            graph_id, limit=100
        )
        nodes = list(getattr(nodes_page, "data", None) or [])
        assert len(nodes) == 2
        by_name = {n.name: n for n in nodes}
        assert set(by_name) == {"林砚", "雾港航标"}
        assert "Character" in by_name["林砚"].labels
        assert by_name["林砚"].summary == "雾港夜班航标维护员"

        edges_page = client.graph.edge.with_raw_response.get_by_graph_id(
            graph_id, limit=100
        )
        edges = list(getattr(edges_page, "data", None) or [])
        assert len(edges) == 1
        assert edges[0].fact == "林砚维护雾港的夜间航标"
        assert edges[0].name == "maintains"
        assert edges[0].source_node_uuid == by_name["林砚"].uuid_
        assert edges[0].target_node_uuid == by_name["雾港航标"].uuid_

        fetched = client.graph.node.get(uuid_=by_name["林砚"].uuid_)
        assert fetched.name == "林砚"

        out_edges = client.graph.node.get_edges(node_uuid=by_name["林砚"].uuid_)
        assert [e.name for e in out_edges] == ["maintains"]
    finally:
        client.graph.delete(graph_id=graph_id)


@requires_neo4j
def test_paging_returns_cursor_headers_and_stable_order(monkeypatch):
    from app.utils.local_graph_memory import LocalGraphMemoryClient

    client = LocalGraphMemoryClient(
        NEO4J_TEST_URI, NEO4J_TEST_USER, NEO4J_TEST_PASSWORD
    )
    graph_id = f"mfn_{uuidlib.uuid4().hex[:12]}"
    try:
        client.graph.create(graph_id=graph_id, name="paging", description="")
        for index in range(3):
            client.graph.add_fact_triple(
                fact=f"读者{index}追读第七码头",
                fact_name="reads",
                graph_id=graph_id,
                source_node_name=f"读者{index}",
                source_node_labels=["Entity", "ReaderPersona"],
                target_node_name="第七码头",
                target_node_labels=["Entity", "Location"],
            )

        seen: list[str] = []
        cursor = None
        pages = 0
        while True:
            response = client.graph.node.with_raw_response.get_by_graph_id(
                graph_id, limit=2, cursor=cursor
            )
            seen.extend(n.name for n in (getattr(response, "data", None) or []))
            pages += 1
            next_cursor = response.headers.get("zep-next-cursor")
            if next_cursor is None:
                break
            cursor = next_cursor

        assert pages == 2, "4 个节点按 limit=2 应恰好两页"
        assert sorted(seen) == sorted(["读者0", "读者1", "读者2", "第七码头"])
    finally:
        client.graph.delete(graph_id=graph_id)


@requires_neo4j
def test_reader_filter_semantics_hold_on_local_backend(monkeypatch):
    """ZepEntityReader 的类型筛选逻辑在本地后端上必须同样成立。

    筛选规则：labels 只有 "Entity"/"Node" 的节点视为未定义类型并被跳过；
    带有额外标签（如 Character/ReaderPersona）的节点保留。
    """

    from app.services.zep_entity_reader import ZepEntityReader
    from app.utils import zep as zep_utils
    from app.utils.local_graph_memory import LocalGraphMemoryClient

    client = LocalGraphMemoryClient(
        NEO4J_TEST_URI, NEO4J_TEST_USER, NEO4J_TEST_PASSWORD
    )
    graph_id = f"mfn_{uuidlib.uuid4().hex[:12]}"
    monkeypatch.setenv("GRAPH_MEMORY_BACKEND", "neo4j_local")
    monkeypatch.setattr(zep_utils.Config, "NEO4J_URI", NEO4J_TEST_URI)
    monkeypatch.setattr(zep_utils.Config, "NEO4J_USER", NEO4J_TEST_USER)
    monkeypatch.setattr(zep_utils.Config, "NEO4J_PASSWORD", NEO4J_TEST_PASSWORD)
    zep_utils.clear_zep_client_cache()
    try:
        client.graph.create(graph_id=graph_id, name="filter", description="")
        client.graph.add_fact_triple(
            fact="林砚与苏晚搭档",
            fact_name="partners_with",
            graph_id=graph_id,
            source_node_name="林砚",
            source_node_labels=["Entity", "Character"],
            target_node_name="苏晚",
            target_node_labels=["Entity", "Character"],
        )

        reader = ZepEntityReader(api_key=None)
        assert isinstance(reader.client, LocalGraphMemoryClient)

        result = reader.filter_defined_entities(
            graph_id=graph_id,
            defined_entity_types=["Character"],
            enrich_with_edges=True,
        )
        assert result.filtered_count == 2
        assert "Character" in set(result.entity_types)
    finally:
        zep_utils.clear_zep_client_cache()
        client.graph.delete(graph_id=graph_id)
