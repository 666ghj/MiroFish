from app.services.ontology_generator import OntologyGenerator
from app.services import graph_builder as graph_builder_module
from app.services.graph_builder import GraphBuilderService
from app.utils.ontology import (
    MAX_ONTOLOGY_ATTRIBUTES,
    MAX_ONTOLOGY_SOURCE_TARGETS,
    normalize_ontology_attribute,
    normalize_ontology_attributes,
)
from zep_cloud.ontology import EdgeModel, EntityModel, EntityText

GRAPH_UUID = "00000000-0000-4000-8000-000000000001"


def _capture_ontology_build(monkeypatch):
    captured = {}

    def build_ontology(*, entities, edges):
        captured["entities"] = entities
        captured["edges"] = edges
        return ["entity-type"], ["edge-type"]

    monkeypatch.setattr(
        graph_builder_module,
        "build_ontology",
        build_ontology,
    )
    return captured


def test_normalize_string_attribute():
    assert normalize_ontology_attribute("role") == {
        "name": "role",
        "type": "text",
        "description": "role",
    }


def test_preserve_valid_dictionary_attribute():
    original = {"name": "role", "type": "text", "description": "Public role"}
    assert normalize_ontology_attribute(original) == original
    assert normalize_ontology_attribute(original) is not original


def test_reject_unusable_attribute_shapes():
    for value in (None, 7, [], {}, {"name": None}, {"name": ""}, "   "):
        assert normalize_ontology_attribute(value) is None


def test_attribute_list_is_non_empty_and_capped_for_zep():
    assert normalize_ontology_attributes(None) == [{
        "name": "details",
        "type": "text",
        "description": "Additional details about this ontology type.",
    }]

    attributes = [None] + [f"field_{index}" for index in range(12)]
    normalized = normalize_ontology_attributes(attributes)

    assert len(normalized) == MAX_ONTOLOGY_ATTRIBUTES
    assert [attribute["name"] for attribute in normalized] == [
        f"field_{index}" for index in range(MAX_ONTOLOGY_ATTRIBUTES)
    ]


def test_generator_normalizes_entity_and_edge_attributes():
    result = OntologyGenerator(llm_client=object())._validate_and_process({
        "entity_types": [{"name": "speaker", "attributes": ["role", None]}],
        "edge_types": [{"name": "quotes", "attributes": ["source_url", {}]}],
    })

    assert result["entity_types"][0]["attributes"] == [{
        "name": "role",
        "type": "text",
        "description": "role",
    }]
    assert result["edge_types"][0]["attributes"] == [{
        "name": "source_url",
        "type": "text",
        "description": "source_url",
    }]


def test_generator_adds_a_property_to_empty_custom_types():
    result = OntologyGenerator(llm_client=object())._validate_and_process({
        "entity_types": [{"name": "speaker", "attributes": []}],
        "edge_types": [{"name": "quotes", "attributes": []}],
    })

    assert result["entity_types"][0]["attributes"][0]["name"] == "details"
    assert result["edge_types"][0]["attributes"][0]["name"] == "details"


def test_graph_builder_safety_net_accepts_strings_and_skips_invalid_values(
    monkeypatch,
):
    captured = _capture_ontology_build(monkeypatch)
    api_call = {}

    class GraphApi:
        def set_ontology(self, graph_uuid, **kwargs):
            api_call.update(graph_uuid=graph_uuid, **kwargs)

    class Client:
        graph = GraphApi()

    builder = object.__new__(GraphBuilderService)
    builder.client = Client()
    builder.set_ontology(GRAPH_UUID, {
        "entity_types": [{
            "name": "Speaker",
            "attributes": ["role", None, {"name": "summary"}],
        }],
        "edge_types": [],
    })

    speaker = captured["entities"]["Speaker"]
    assert set(speaker.__annotations__) == {"role", "entity_summary"}
    assert issubclass(speaker, EntityModel)
    assert speaker.__annotations__["role"] is EntityText
    assert api_call == {
        "graph_uuid": GRAPH_UUID,
        "entity_types": ["entity-type"],
        "edge_types": ["edge-type"],
    }


def test_graph_builder_emits_v4_entity_and_edge_models(monkeypatch):
    captured = _capture_ontology_build(monkeypatch)

    class GraphApi:
        def set_ontology(self, _graph_uuid, **_kwargs):
            pass

    class Client:
        graph = GraphApi()

    builder = object.__new__(GraphBuilderService)
    builder.client = Client()
    builder.set_ontology(GRAPH_UUID, {
        "entity_types": [{
            "name": "Speaker",
            "attributes": ["graph_id"] + [
                f"field_{index}" for index in range(10)
            ],
        }],
        "edge_types": [{
            "name": "MENTIONS",
            "attributes": [],
            "source_targets": [{"source": "Speaker", "target": "Speaker"}],
        }],
    })

    speaker = captured["entities"]["Speaker"]
    assert issubclass(speaker, EntityModel)
    assert len(speaker.__annotations__) == MAX_ONTOLOGY_ATTRIBUTES
    assert speaker.model_fields["entity_graph_id"].description == "graph_id"

    mentions, source_targets = captured["edges"]["MENTIONS"]
    assert issubclass(mentions, EdgeModel)
    assert mentions.model_fields["details"].description == (
        "Additional details about this ontology type."
    )
    assert source_targets == [{"source": "Speaker", "target": "Speaker"}]


def test_graph_builder_passes_an_empty_entity_mapping_for_edge_only_ontology(
    monkeypatch,
):
    captured = _capture_ontology_build(monkeypatch)

    class GraphApi:
        def set_ontology(self, _graph_uuid, **_kwargs):
            pass

    class Client:
        graph = GraphApi()

    builder = object.__new__(GraphBuilderService)
    builder.client = Client()
    builder.set_ontology(GRAPH_UUID, {
        "entity_types": [],
        "edge_types": [{
            "name": "RELATED_TO",
            "attributes": ["reason"],
            "source_targets": [{"source": "Entity", "target": "Entity"}],
        }],
    })

    assert captured["entities"] == {}
    assert "RELATED_TO" in captured["edges"]


def test_graph_builder_deduplicates_and_caps_edge_source_targets_for_zep(
    monkeypatch,
):
    captured = _capture_ontology_build(monkeypatch)

    class GraphApi:
        def set_ontology(self, _graph_uuid, **_kwargs):
            pass

    class Client:
        graph = GraphApi()

    source_targets = [
        {"source": f"Source{index}", "target": f"Target{index}"}
        for index in range(MAX_ONTOLOGY_SOURCE_TARGETS + 2)
    ]
    source_targets.insert(1, dict(source_targets[0]))

    builder = object.__new__(GraphBuilderService)
    builder.client = Client()
    builder.set_ontology(GRAPH_UUID, {
        "entity_types": [],
        "edge_types": [{
            "name": "RELATED_TO",
            "attributes": ["reason"],
            "source_targets": source_targets,
        }],
    })

    _, normalized_targets = captured["edges"]["RELATED_TO"]
    assert len(normalized_targets) == MAX_ONTOLOGY_SOURCE_TARGETS
    assert [(item["source"], item["target"]) for item in normalized_targets] == [
        (f"Source{index}", f"Target{index}")
        for index in range(MAX_ONTOLOGY_SOURCE_TARGETS)
    ]


def test_generator_ignores_invalid_entries_and_normalizes_edge_names():
    source_targets = [
        {"source": "speaker", "target": "news outlet"},
        {"source": "speaker", "target": "news outlet"},
        None,
    ] + [
        {"source": "speaker", "target": "news outlet" if index == 0 else "Person"}
        for index in range(12)
    ]

    result = OntologyGenerator(llm_client=object())._validate_and_process({
        "entity_types": ["speaker", None, 7, {"name": "news outlet"}],
        "edge_types": [
            "unusable edge",
            None,
            {"name": "worksFor", "source_targets": source_targets},
            {"name": "works-for", "source_targets": []},
        ],
    })

    assert [entity["name"] for entity in result["entity_types"][:2]] == [
        "Speaker",
        "NewsOutlet",
    ]
    assert [edge["name"] for edge in result["edge_types"]] == ["WORKS_FOR"]
    assert result["edge_types"][0]["source_targets"] == [
        {"source": "Speaker", "target": "NewsOutlet"},
        {"source": "Speaker", "target": "Person"},
    ]


def test_generator_caps_after_discarding_invalid_edge_endpoints():
    invalid_first = [
        {"source": f"Removed{index}", "target": "AlsoRemoved"}
        for index in range(MAX_ONTOLOGY_SOURCE_TARGETS)
    ]
    result = OntologyGenerator(llm_client=object())._validate_and_process({
        "entity_types": [{"name": "person"}, {"name": "organization"}],
        "edge_types": [{
            "name": "works_for",
            "source_targets": invalid_first + [
                {"source": "person", "target": "organization"}
            ],
        }],
    })

    assert result["edge_types"][0]["source_targets"] == [
        {"source": "Person", "target": "Organization"}
    ]
