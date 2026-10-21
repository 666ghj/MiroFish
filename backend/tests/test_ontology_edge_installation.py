from types import SimpleNamespace

import pytest
from zep_cloud.external_clients.ontology import edge_model_to_api_schema

from app.services.graph_builder import GraphBuilderService
from app.services.ontology_generator import OntologyGenerator


def _edge(name, target):
    return {"name": name, "source_targets": [{"source": "Person", "target": target}]}


@pytest.mark.parametrize("raw_edges,expected_names", [
    ([_edge("WORKS_FOR", "UnknownType")], []),
    ([_edge(f"INVALID_{i}", "UnknownType") for i in range(10)] + [
        _edge("WORKS_FOR", "Organization"),
    ], ["WORKS_FOR"]),
    ([_edge("WORKS_FOR", "UnknownType"), _edge("WORKS_FOR", "Organization")], ["WORKS_FOR"]),
    ([], []),
])
def test_normalized_edge_definitions_match_what_the_builder_can_install(raw_edges, expected_names):
    normalized = OntologyGenerator(llm_client=object())._validate_and_process({
        "entity_types": [{"name": "Person"}, {"name": "Organization"}],
        "edge_types": raw_edges,
    })
    installed = {}
    builder = object.__new__(GraphBuilderService)
    builder.client = SimpleNamespace(graph=SimpleNamespace(
        set_ontology=lambda **kwargs: installed.update(kwargs),
    ))
    builder.set_ontology("graph-1", normalized)
    definitions = installed.get("edges") or {}

    assert [edge["name"] for edge in normalized["edge_types"]] == expected_names
    assert list(definitions) == expected_names
    for name, (edge_model, source_targets) in definitions.items():
        # The pinned SDK can serialize every retained definition and endpoint.
        schema = edge_model_to_api_schema(edge_model, name)
        assert schema["name"] == name
        assert [(pair.source, pair.target) for pair in source_targets] == [
            ("Person", "Organization"),
        ]
