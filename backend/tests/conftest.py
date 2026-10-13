"""Legacy service tests exercise cloud contracts independently of the local .env."""
import pytest


@pytest.fixture(autouse=True)
def default_graph_provider(monkeypatch):
    from app.config import Config
    monkeypatch.setattr(Config, 'GRAPH_PROVIDER', 'zep')
