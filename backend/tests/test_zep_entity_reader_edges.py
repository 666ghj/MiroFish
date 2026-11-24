from types import SimpleNamespace

from app.services.zep_entity_reader import ZepEntityReader

GRAPH_UUID = "00000000-0000-4000-8000-000000000001"
NODE_UUID = "00000000-0000-4000-8000-000000000002"


def test_get_node_edges_uses_v4_edge_list_filters_and_all_pages():
    calls = []
    retry_calls = []

    def make_edge(uuid_, source, target):
        return SimpleNamespace(
            uuid_=uuid_,
            name="KNOWS",
            fact="Alice knows Bob",
            source_node_uuid=source,
            target_node_uuid=target,
            attributes={"since": "2024"},
        )

    def list_edges(graph_uuid, **kwargs):
        calls.append((graph_uuid, kwargs))
        if kwargs["cursor"] is None:
            return SimpleNamespace(
                items=[make_edge("edge-1", NODE_UUID, "node-2")],
                response=SimpleNamespace(next_cursor="opaque-page-2"),
            )
        return SimpleNamespace(
            items=[make_edge("edge-2", "node-3", NODE_UUID)],
            response=SimpleNamespace(next_cursor=None),
        )

    reader = object.__new__(ZepEntityReader)
    reader.client = SimpleNamespace(
        graph=SimpleNamespace(edge=SimpleNamespace(list=list_edges))
    )
    reader._call_with_retry = lambda *args, **kwargs: retry_calls.append(kwargs)

    edges = reader.get_node_edges(NODE_UUID, GRAPH_UUID)

    assert edges == [
        {
            "uuid": "edge-1",
            "name": "KNOWS",
            "fact": "Alice knows Bob",
            "source_node_uuid": NODE_UUID,
            "target_node_uuid": "node-2",
            "attributes": {"since": "2024"},
        },
        {
            "uuid": "edge-2",
            "name": "KNOWS",
            "fact": "Alice knows Bob",
            "source_node_uuid": "node-3",
            "target_node_uuid": NODE_UUID,
            "attributes": {"since": "2024"},
        },
    ]
    assert {
        "incoming" if edge["target_node_uuid"] == NODE_UUID else "outgoing"
        for edge in edges
    } == {"incoming", "outgoing"}
    assert retry_calls == []
    assert [graph_uuid for graph_uuid, _kwargs in calls] == [
        GRAPH_UUID,
        GRAPH_UUID,
    ]
    assert calls[0][1]["filters"].connected_node_uuids == [NODE_UUID]
    assert calls[0][1]["cursor"] is None
    assert calls[1][1]["cursor"] == "opaque-page-2"
