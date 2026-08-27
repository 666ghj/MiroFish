from types import SimpleNamespace

from app.models.model_config import ConnectionType, ModelRole
from app.services.model_discovery import ModelDiscovery


class Models:
    def list(self):
        return SimpleNamespace(data=[SimpleNamespace(id="qwen/qwen3.8-27b"), SimpleNamespace(id="qwen3-embedding-0.6b"), SimpleNamespace(id="text-embedding-nomic-embed-text-v1.5")])


class Client:
    models = Models()
    class Embeddings:
        def create(self, model, input):
            return SimpleNamespace(model=model, data=[SimpleNamespace(embedding=[0.1, 0.2])])
    embeddings = Embeddings()


def test_lm_studio_models_are_classified_by_role():
    discovery = ModelDiscovery(client_factory=lambda **_: Client())
    connection = SimpleNamespace(connection_type=ConnectionType.LOCAL_OPENAI, base_url="http://lm/v1", is_local=True)
    chat = discovery.list_models(connection, "key", ModelRole.HIGH_THROUGHPUT)
    embedding = discovery.list_models(connection, "key", ModelRole.EMBEDDING)

    assert [item["id"] for item in chat] == ["qwen/qwen3.8-27b"]
    assert {item["id"] for item in embedding} == {"qwen3-embedding-0.6b", "text-embedding-nomic-embed-text-v1.5"}
    assert all(item["local"] for item in chat + embedding)
