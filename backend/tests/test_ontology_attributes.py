def test_graph_builder_normalizes_string_attributes():
    """_normalize_entity_attributes converts strings to dicts without crashing."""
    from app.services.graph_builder import GraphBuilderService

    mixed = ["name", "age", {"name": "email", "type": "text", "description": "Email"}]
    result = GraphBuilderService._normalize_entity_attributes(mixed)

    assert all(isinstance(a, dict) for a in result)
    assert result[0] == {"name": "name", "type": "text", "description": "name"}
    assert result[1] == {"name": "age", "type": "text", "description": "age"}
    assert result[2]["name"] == "email"


def test_graph_builder_normalize_empty():
    """Empty attribute list returns empty list."""
    from app.services.graph_builder import GraphBuilderService
    assert GraphBuilderService._normalize_entity_attributes([]) == []


def test_ontology_generator_normalizes_string_attributes():
    """_normalize_ontology_attributes converts string attrs in entities and edges."""
    from app.services.ontology_generator import OntologyGenerator

    raw = {
        "entities": [{"name": "Person", "description": "A person", "attributes": ["name", "age"]}],
        "edges": [{"name": "KNOWS", "description": "Knows", "attributes": ["since"]}],
    }
    result = OntologyGenerator._normalize_ontology_attributes(raw)

    entity_attrs = result["entities"][0]["attributes"]
    assert all(isinstance(a, dict) for a in entity_attrs)
    assert entity_attrs[0] == {"name": "name", "type": "text", "description": "name"}

    edge_attrs = result["edges"][0]["attributes"]
    assert all(isinstance(a, dict) for a in edge_attrs)
    assert edge_attrs[0] == {"name": "since", "type": "text", "description": "since"}
