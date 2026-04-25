import pytest
from unittest.mock import MagicMock, patch


def test_graph_backend_has_required_methods():
    from backend.app.graph.base import GraphBackend
    required = [
        "create_graph", "set_ontology", "add_batch", "get_episode",
        "get_all_nodes", "get_all_edges", "get_node", "get_node_edges",
        "search", "add_text", "delete_graph",
    ]
    for method in required:
        assert hasattr(GraphBackend, method), f"GraphBackend missing: {method}"
