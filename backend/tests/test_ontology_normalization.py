from app.services.graph_builder import GraphBuilderService
from app.services.ontology_schema import normalize_ontology_schema


def legacy_ontology():
    return {
        "entity_types": [
            {
                "name": "Founder",
                "description": "Startup founder",
                "attributes": [
                    {
                        "full_name": "Founder full name",
                        "role": "Founder title",
                        "description": "Founder bio",
                    }
                ],
                "examples": ["Ada Lovelace"],
            }
        ],
        "edge_types": [
            {
                "name": "FOUNDS",
                "description": "Founder starts a company",
                "source_targets": [{"source": "Founder", "target": "Organization"}],
                "attributes": [{"started_at": "When the company was started"}],
            }
        ],
    }


def test_normalize_ontology_schema_converts_legacy_attribute_maps():
    normalized = normalize_ontology_schema(legacy_ontology())

    assert normalized["entity_types"][0]["attributes"] == [
        {"name": "full_name", "type": "text", "description": "Founder full name"},
        {"name": "role", "type": "text", "description": "Founder title"},
        {"name": "description", "type": "text", "description": "Founder bio"},
    ]
    assert normalized["edge_types"][0]["attributes"] == [
        {"name": "started_at", "type": "text", "description": "When the company was started"},
    ]


def test_graph_builder_set_ontology_accepts_legacy_attribute_maps():
    captured = {}

    class DummyGraph:
        def set_ontology(self, **kwargs):
            captured.update(kwargs)

    class DummyClient:
        graph = DummyGraph()

    builder = GraphBuilderService.__new__(GraphBuilderService)
    builder.client = DummyClient()

    builder.set_ontology("graph_123", legacy_ontology())

    assert captured["graph_ids"] == ["graph_123"]
    assert set(captured["entities"]["Founder"].model_fields.keys()) == {
        "description",
        "full_name",
        "role",
    }

    edge_model, source_targets = captured["edges"]["FOUNDS"]
    assert set(edge_model.model_fields.keys()) == {"started_at"}
    assert len(source_targets) == 1
    assert source_targets[0].source == "Founder"
    assert source_targets[0].target == "Organization"
