# backend/tests/test_graph_clone.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio

def test_clone_graph_executes_two_queries():
    """clone_graph should run exactly 2 Cypher queries: one for nodes, one for relationships."""
    from backend.app.graph.graphiti_backend import GraphitiBackend

    backend = GraphitiBackend.__new__(GraphitiBackend)

    executed_queries = []
    async def fake_execute_query(query, parameters=None, **kwargs):
        executed_queries.append(query)
        return []

    backend._execute_neo4j_query = fake_execute_query
    asyncio.run(backend.clone_graph("src_group", "dst_group"))

    assert len(executed_queries) == 2
    combined = " ".join(executed_queries).lower()
    assert "group_id" in combined

def test_delete_graph_executes_detach_delete():
    """delete_graph should run a DETACH DELETE query."""
    from backend.app.graph.graphiti_backend import GraphitiBackend

    backend = GraphitiBackend.__new__(GraphitiBackend)

    executed_queries = []
    async def fake_execute_query(query, parameters=None, **kwargs):
        executed_queries.append(query)
        return []

    backend._execute_neo4j_query = fake_execute_query
    asyncio.run(backend.delete_graph_async("group_to_delete"))

    assert any("DETACH DELETE" in q for q in executed_queries)
