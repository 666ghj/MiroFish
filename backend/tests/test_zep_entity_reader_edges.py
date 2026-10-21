from types import SimpleNamespace

from app.services.zep_entity_reader import ZepEntityReader
from zep_cloud.graph.node.client import NodeClient


def test_pinned_zep_sdk_exposes_get_edges_not_get_entity_edges():
    assert hasattr(NodeClient, "get_edges")
    assert not hasattr(NodeClient, "get_entity_edges")


def test_get_node_edges_uses_the_supported_sdk_method():
    calls = []

    class NodeApi:
        def get_edges(self, *, node_uuid):
            calls.append(node_uuid)
            return [SimpleNamespace(
                uuid_="edge-1",
                name="KNOWS",
                fact="Alice knows Bob",
                source_node_uuid="node-1",
                target_node_uuid="node-2",
                attributes={"since": "2024"},
            )]

    class GraphApi:
        node = NodeApi()

    class Client:
        graph = GraphApi()

    reader = object.__new__(ZepEntityReader)
    reader.client = Client()

    assert reader.get_node_edges("node-1") == [{
        "uuid": "edge-1",
        "name": "KNOWS",
        "fact": "Alice knows Bob",
        "source_node_uuid": "node-1",
        "target_node_uuid": "node-2",
        "attributes": {"since": "2024"},
    }]
    assert calls == ["node-1"]


def test_entity_enrichment_preserves_order_direction_and_parallel_self_edges():
    reader = object.__new__(ZepEntityReader)
    reader.get_all_nodes = lambda graph_id: [
        {"uuid": uuid, "name": uuid, "labels": labels, "summary": uuid, "attributes": {}}
        for uuid, labels in [("a", ["Person"]), ("b", ["Person"]), ("c", ["Entity"])]
    ]
    reader.get_all_edges = lambda graph_id: [
        {"uuid": f"e{i}", "name": f"REL{i}", "fact": f"fact{i}",
         "source_node_uuid": source, "target_node_uuid": target, "attributes": {}}
        for i, (source, target) in enumerate([
            ("a", "b"), ("b", "a"), ("a", "a"), ("a", "b"), ("c", "a"),
        ])
    ]

    entities = reader.filter_defined_entities("graph-1").entities

    assert len(entities) == 2
    assert [edge["fact"] for edge in entities[0].related_edges] == [
        "fact0", "fact1", "fact2", "fact3", "fact4",
    ]
    assert [edge["direction"] for edge in entities[0].related_edges] == [
        "outgoing", "incoming", "outgoing", "outgoing", "incoming",
    ]
    assert {node["uuid"] for node in entities[0].related_nodes} == {"a", "b", "c"}
    assert [edge["fact"] for edge in entities[1].related_edges] == [
        "fact0", "fact1", "fact3",
    ]


def test_entity_enrichment_has_a_linear_full_edge_scan_budget():
    class CountingEdges(list):
        visits = 0

        def __iter__(self):
            for edge in super().__iter__():
                self.visits += 1
                yield edge

    edges = CountingEdges({
        "uuid": f"e{i}", "name": "REL", "fact": f"fact{i}",
        "source_node_uuid": f"n{i % 100}",
        "target_node_uuid": f"n{(i + 1) % 100}", "attributes": {},
    } for i in range(400))
    reader = object.__new__(ZepEntityReader)
    reader.get_all_nodes = lambda graph_id: [
        {"uuid": f"n{i}", "name": f"n{i}", "labels": ["Person"],
         "summary": "", "attributes": {}} for i in range(100)
    ]
    reader.get_all_edges = lambda graph_id: edges

    result = reader.filter_defined_entities("graph-1")

    assert result.filtered_count == 100
    assert all(len(entity.related_edges) == 8 for entity in result.entities)
    assert edges.visits <= 2 * len(edges)
