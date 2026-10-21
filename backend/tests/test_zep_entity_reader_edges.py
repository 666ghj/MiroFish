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


def test_filtered_type_reaches_the_generated_profile_without_mutating_graph_labels():
    from app.services.oasis_profile_generator import OasisProfileGenerator

    original_labels = ["Entity", "Person", "Organization"]
    reader = object.__new__(ZepEntityReader)
    reader.get_all_nodes = lambda graph_id: [{
        "uuid": "node-1", "name": "Acme", "labels": original_labels,
        "summary": "An organization", "attributes": {},
    }]
    result = reader.filter_defined_entities(
        "graph-1", defined_entity_types=["Organization"], enrich_with_edges=False,
    )

    assert result.entity_types == {"Organization"}
    entity = result.entities[0]
    assert entity.get_entity_type() == "Organization"
    assert set(entity.labels) == set(original_labels)
    assert original_labels == ["Entity", "Person", "Organization"]
    generator = object.__new__(OasisProfileGenerator)
    generator.zep_client = None
    profile = generator.generate_profile_from_entity(entity, user_id=0, use_llm=False)
    assert profile.source_entity_type == "Organization"


def test_unfiltered_entities_keep_the_original_type_and_label_order():
    original_labels = ["Entity", "Person", "Organization"]
    reader = object.__new__(ZepEntityReader)
    reader.get_all_nodes = lambda graph_id: [{
        "uuid": "node-1", "name": "Acme", "labels": original_labels,
        "summary": "An entity", "attributes": {},
    }]
    result = reader.filter_defined_entities("graph-1", enrich_with_edges=False)

    assert result.entities[0].get_entity_type() == "Person"
    assert result.entities[0].labels == original_labels
