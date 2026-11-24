import inspect

from zep_cloud.client import Zep
from zep_cloud.ontology import EdgeModel, EntityModel, EntityText, build_ontology
from zep_cloud.types import (
    BatchItemInput,
    EdgeListFilters,
    EdgeSearchFilters,
    NodeSearchFilters,
)


GRAPH_UUID = "00000000-0000-4000-8000-000000000001"
NODE_UUID = "00000000-0000-4000-8000-000000000002"
EPISODE_UUID = "00000000-0000-4000-8000-000000000003"


def _resolve(client, method_path):
    method = client
    for name in method_path.split("."):
        method = getattr(method, name)
    return method


def test_mirofish_zep_calls_bind_to_the_installed_v4_sdk():
    client = Zep(api_key="contract-test")
    batch_item = BatchItemInput(
        type="graph_episode",
        graph_uuid=GRAPH_UUID,
        data="contract test",
        data_type="text",
        reference_time="2026-01-01T00:00:00Z",
        source_description="MiroFish contract test",
        metadata={"source": "contract-test"},
    )
    calls = [
        (
            "graph.create",
            (),
            {
                "name": "MiroFish",
                "description": "MiroFish Social Simulation Graph",
                "idempotency_key": "00000000-0000-4000-8000-000000000004",
            },
        ),
        (
            "graph.set_ontology",
            (GRAPH_UUID,),
            {"entity_types": [], "edge_types": []},
        ),
        (
            "graph.delete",
            (GRAPH_UUID,),
            {},
        ),
        (
            "graph.lookup",
            (),
            {"graph_id": "legacy-zep-v3-id"},
        ),
        (
            "graph.node.get",
            (GRAPH_UUID, NODE_UUID),
            {},
        ),
        (
            "graph.node.list",
            (GRAPH_UUID,),
            {"page_size": 100, "cursor": "opaque-node-cursor"},
        ),
        (
            "graph.edge.list",
            (GRAPH_UUID,),
            {
                "page_size": 100,
                "cursor": "opaque-edge-cursor",
                "filters": EdgeListFilters(
                    connected_node_uuids=[NODE_UUID],
                ),
            },
        ),
        (
            "graph.episode.add",
            (GRAPH_UUID,),
            {
                "type": "text",
                "data": "episode content",
                "reference_time": "2026-01-01T00:00:00Z",
                "source_description": "MiroFish simulation activity batch",
                "metadata": {"simulation_id": "simulation-1"},
            },
        ),
        (
            "graph.episode.get",
            (GRAPH_UUID, EPISODE_UUID),
            {},
        ),
        (
            "graph.episode.list",
            (GRAPH_UUID,),
            {"page_size": 50, "order_by": "created_at", "order": "desc"},
        ),
        (
            "graph.search_edges",
            (GRAPH_UUID,),
            {
                "query": "edge query",
                "page_size": 10,
                "reranker": "cross_encoder",
            },
        ),
        (
            "graph.search_edges",
            (GRAPH_UUID,),
            {
                "query": "typed edge query",
                "page_size": 10,
                "reranker": "rrf",
                "filters": EdgeSearchFilters(edge_types=["WORKS_AT"]),
            },
        ),
        (
            "graph.search_nodes",
            (GRAPH_UUID,),
            {
                "query": "node query",
                "page_size": 10,
                "reranker": "rrf",
                "filters": NodeSearchFilters(node_labels=["Person"]),
            },
        ),
        (
            "graph.search_episodes",
            (GRAPH_UUID,),
            {"query": "episode query", "page_size": 10, "reranker": "rrf"},
        ),
        (
            "graph.get_context",
            (GRAPH_UUID,),
            {"query": "context query", "max_characters": 3000},
        ),
        (
            "batch.create",
            (),
            {
                "metadata": {"graph_id": GRAPH_UUID},
                "idempotency_key": "00000000-0000-4000-8000-000000000005",
            },
        ),
        (
            "batch.add_items",
            ("batch-uuid",),
            {
                "items": [batch_item],
                "idempotency_key": "00000000-0000-4000-8000-000000000006",
            },
        ),
        (
            "batch.process",
            ("batch-uuid",),
            {"idempotency_key": "00000000-0000-4000-8000-000000000007"},
        ),
        ("batch.get", ("batch-uuid",), {}),
        (
            "batch.list",
            (),
            {"page_size": 100, "cursor": "opaque-batch-cursor"},
        ),
        (
            "batch.list_items",
            ("batch-uuid",),
            {"page_size": 100, "cursor": "opaque-item-cursor"},
        ),
        ("task.get", ("task-uuid",), {}),
    ]

    for method_path, args, kwargs in calls:
        inspect.signature(_resolve(client, method_path)).bind(*args, **kwargs)


def test_mirofish_imports_exist_in_the_v4_sdk():
    assert EntityModel
    assert EntityText
    assert EdgeModel
    assert build_ontology
    assert BatchItemInput
    assert EdgeListFilters
    assert EdgeSearchFilters
    assert NodeSearchFilters
