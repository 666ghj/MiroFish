# backend/tests/test_zep_entity_reader.py
import pytest
from unittest.mock import patch, MagicMock
from backend.app.services.zep_entity_reader import ZepEntityReader, EntityNode

def _make_entity(uuid, name, edge_count):
    e = EntityNode(uuid=uuid, name=name, labels=["Person", "Entity"], summary="", attributes={})
    e.related_edges = [{}] * edge_count  # simulate edge_count edges
    return e

def test_get_entities_by_connectivity_returns_top_n():
    reader = ZepEntityReader.__new__(ZepEntityReader)
    entities = [
        _make_entity("u1", "Alice", 10),
        _make_entity("u2", "Bob", 3),
        _make_entity("u3", "Carol", 7),
        _make_entity("u4", "Dave", 1),
        _make_entity("u5", "Eve", 5),
    ]

    with patch.object(reader, 'filter_defined_entities') as mock_filter:
        from backend.app.services.zep_entity_reader import FilteredEntities
        mock_filter.return_value = FilteredEntities(
            entities=entities, entity_types=set(), total_count=5, filtered_count=5
        )
        result = reader.get_entities_by_connectivity(graph_id="g1", max_n=3)

    assert len(result) == 3
    assert result[0].name == "Alice"   # 10 edges — top
    assert result[1].name == "Carol"   # 7 edges
    assert result[2].name == "Eve"     # 5 edges

def test_get_entities_by_connectivity_no_limit():
    reader = ZepEntityReader.__new__(ZepEntityReader)
    entities = [_make_entity(f"u{i}", f"E{i}", i) for i in range(5)]
    with patch.object(reader, 'filter_defined_entities') as mock_filter:
        from backend.app.services.zep_entity_reader import FilteredEntities
        mock_filter.return_value = FilteredEntities(
            entities=entities, entity_types=set(), total_count=5, filtered_count=5
        )
        result = reader.get_entities_by_connectivity(graph_id="g1", max_n=None)
    assert len(result) == 5
