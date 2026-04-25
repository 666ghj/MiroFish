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


def test_config_graph_backend_default():
    import os
    os.environ.pop("GRAPH_BACKEND", None)
    import importlib
    import backend.app.config as cfg_mod
    importlib.reload(cfg_mod)
    assert cfg_mod.Config.GRAPH_BACKEND == "zep"


def test_config_zep_errors_when_key_missing():
    import backend.app.config as cfg_mod
    orig_backend = cfg_mod.Config.GRAPH_BACKEND
    orig_key = cfg_mod.Config.ZEP_API_KEY
    try:
        cfg_mod.Config.GRAPH_BACKEND = "zep"
        cfg_mod.Config.ZEP_API_KEY = None
        errors = cfg_mod.Config.get_graph_config_errors()
        assert any("ZEP_API_KEY" in e for e in errors)
    finally:
        cfg_mod.Config.GRAPH_BACKEND = orig_backend
        cfg_mod.Config.ZEP_API_KEY = orig_key


def test_zep_backend_implements_interface():
    from backend.app.graph.base import GraphBackend
    from backend.app.graph.zep_backend import ZepBackend
    assert issubclass(ZepBackend, GraphBackend)


def test_zep_backend_raises_without_key():
    import backend.app.config as cfg_mod
    orig = cfg_mod.Config.ZEP_API_KEY
    try:
        cfg_mod.Config.ZEP_API_KEY = None
        from backend.app.graph.zep_backend import ZepBackend
        with pytest.raises(ValueError, match="ZEP_API_KEY"):
            ZepBackend()
    finally:
        cfg_mod.Config.ZEP_API_KEY = orig


def test_config_graphiti_errors_when_missing():
    import backend.app.config as cfg_mod
    orig_backend = cfg_mod.Config.GRAPH_BACKEND
    orig_pw = cfg_mod.Config.NEO4J_PASSWORD
    try:
        cfg_mod.Config.GRAPH_BACKEND = "graphiti"
        cfg_mod.Config.NEO4J_PASSWORD = None
        errors = cfg_mod.Config.get_graph_config_errors()
        assert len(errors) >= 1
    finally:
        cfg_mod.Config.GRAPH_BACKEND = orig_backend
        cfg_mod.Config.NEO4J_PASSWORD = orig_pw
