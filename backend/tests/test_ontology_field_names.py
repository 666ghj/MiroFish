from types import SimpleNamespace

import pytest
from zep_cloud.external_clients.ontology import entity_model_to_api_schema, edge_model_to_api_schema

from app.services.graph_builder import GraphBuilderService
from app.services.ontology_generator import OntologyGenerator


def _installed_schema(owner, attributes):
    ontology = OntologyGenerator(llm_client=object())._validate_and_process({
        "entity_types": [{"name": "Speaker", "attributes": attributes if owner == "entity" else ["role"]}],
        "edge_types": [{"name": "WORKS_FOR", "attributes": attributes if owner == "edge" else ["role"],
                        "source_targets": [{"source": "Speaker", "target": "Speaker"}]}],
    })
    captured = {}
    builder = object.__new__(GraphBuilderService)
    builder.client = SimpleNamespace(graph=SimpleNamespace(
        set_ontology=lambda **kwargs: captured.update(kwargs),
    ))
    builder.set_ontology("graph-1", ontology)
    if owner == "entity":
        return entity_model_to_api_schema(captured["entities"]["Speaker"], "Speaker")
    edge_model, _ = captured["edges"]["WORKS_FOR"]
    return edge_model_to_api_schema(edge_model, "WORKS_FOR")


@pytest.mark.parametrize("owner", ["entity", "edge"])
@pytest.mark.parametrize("name", ["_role", "model_config", "model_dump"])
def test_model_reserved_attribute_names_can_be_installed(owner, name):
    schema = _installed_schema(owner, [{"name": name, "description": "Original description"}])

    assert schema["properties"] == [{
        "name": f"entity_{name.lstrip('_')}", "type": "Text", "description": "Original description",
    }]


@pytest.mark.parametrize("owner", ["entity", "edge"])
def test_aliases_do_not_overwrite_existing_valid_attributes(owner):
    schema = _installed_schema(owner, [
        {"name": "summary", "description": "Reserved source attribute"},
        {"name": "entity_summary", "description": "Existing valid attribute"},
    ])
    properties = {field["name"]: field["description"] for field in schema["properties"]}

    assert len(properties) == 2
    assert properties["entity_summary"] == "Existing valid attribute"
    assert set(properties.values()) == {"Reserved source attribute", "Existing valid attribute"}


@pytest.mark.parametrize("owner", ["entity", "edge"])
def test_valid_attributes_including_model_prefixes_keep_their_names(owner):
    schema = _installed_schema(owner, ["role", "model_version", "entity_role"])

    assert [field["name"] for field in schema["properties"]] == [
        "role", "model_version", "entity_role",
    ]
