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
