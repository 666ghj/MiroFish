import pytest


@pytest.fixture(autouse=True)
def reset_graph_factory_singleton():
    """Reset the graph backend singleton before each test to avoid cross-test contamination."""
    yield
    try:
        import backend.app.graph.factory as fmod
        fmod._backend_instance = None
    except ImportError:
        pass
