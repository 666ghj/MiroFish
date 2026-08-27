import importlib.util
import sys
import types
from pathlib import Path


def _load_graphiti_client(monkeypatch):
    backend_dir = Path(__file__).resolve().parents[2]

    app_package = types.ModuleType("app")
    app_package.__path__ = [str(backend_dir / "app")]
    services_package = types.ModuleType("app.services")
    services_package.__path__ = [str(backend_dir / "app" / "services")]
    config_module = types.ModuleType("app.config")
    config_module.Config = type("Config", (), {})

    monkeypatch.setitem(sys.modules, "app", app_package)
    monkeypatch.setitem(sys.modules, "app.services", services_package)
    monkeypatch.setitem(sys.modules, "app.config", config_module)

    adapter_name = "app.services.zep_adapter"
    adapter_spec = importlib.util.spec_from_file_location(
        adapter_name, backend_dir / "app" / "services" / "zep_adapter.py"
    )
    adapter_module = importlib.util.module_from_spec(adapter_spec)
    monkeypatch.setitem(sys.modules, adapter_name, adapter_module)
    adapter_spec.loader.exec_module(adapter_module)

    captured = {"embedder": {}, "llm": {}}

    class FakeOpenAIEmbedderConfig:
        def __init__(self, **kwargs):
            captured["embedder"].update(kwargs)

    class FakeOpenAIEmbedder:
        def __init__(self, config):
            self.config = config

    graphiti_package = types.ModuleType("graphiti_core")
    embedder_package = types.ModuleType("graphiti_core.embedder")
    openai_module = types.ModuleType("graphiti_core.embedder.openai")
    openai_module.OpenAIEmbedder = FakeOpenAIEmbedder
    openai_module.OpenAIEmbedderConfig = FakeOpenAIEmbedderConfig
    monkeypatch.setitem(sys.modules, "graphiti_core", graphiti_package)
    monkeypatch.setitem(sys.modules, "graphiti_core.embedder", embedder_package)
    monkeypatch.setitem(sys.modules, "graphiti_core.embedder.openai", openai_module)

    class FakeLLMConfig:
        def __init__(self, **kwargs):
            captured["llm"].update(kwargs)

    class FakeOpenAIGenericClient:
        def __init__(self, config):
            self.config = config

    llm_package = types.ModuleType("graphiti_core.llm_client")
    llm_config_module = types.ModuleType("graphiti_core.llm_client.config")
    llm_openai_module = types.ModuleType("graphiti_core.llm_client.openai_generic_client")
    llm_config_module.LLMConfig = FakeLLMConfig
    llm_openai_module.OpenAIGenericClient = FakeOpenAIGenericClient
    monkeypatch.setitem(sys.modules, "graphiti_core.llm_client", llm_package)
    monkeypatch.setitem(sys.modules, "graphiti_core.llm_client.config", llm_config_module)
    monkeypatch.setitem(
        sys.modules, "graphiti_core.llm_client.openai_generic_client", llm_openai_module
    )

    deepseek_module = types.ModuleType("app.services.deepseek_graphiti_client")
    deepseek_module.DeepSeekGraphitiClient = type(
        "DeepSeekGraphitiClient", (FakeOpenAIGenericClient,), {}
    )
    monkeypatch.setitem(
        sys.modules, "app.services.deepseek_graphiti_client", deepseek_module
    )

    module_name = "app.services.zep_graphiti_impl"
    module_spec = importlib.util.spec_from_file_location(
        module_name, backend_dir / "app" / "services" / "zep_graphiti_impl.py"
    )
    module = importlib.util.module_from_spec(module_spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    module_spec.loader.exec_module(module)
    return module.GraphitiClient, captured


def test_embedder_prefers_dedicated_environment(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "deepseek-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("GRAPHITI_EMBEDDING_API_KEY", "local-key")
    monkeypatch.setenv("GRAPHITI_EMBEDDING_BASE_URL", "http://embedding:80/v1")
    monkeypatch.setenv("GRAPHITI_EMBEDDING_MODEL", "multilingual-minilm")

    graphiti_client, captured = _load_graphiti_client(monkeypatch)
    client = graphiti_client.__new__(graphiti_client)
    monkeypatch.setattr(client, "_is_openai_compatible_only", lambda: False)

    client._build_default_embedder()

    assert captured["embedder"]["api_key"] == "local-key"
    assert captured["embedder"]["base_url"] == "http://embedding:80/v1"
    assert captured["embedder"]["embedding_model"] == "multilingual-minilm"


def test_embedder_falls_back_to_openai_environment(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "shared-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://shared.example/v1")
    monkeypatch.delenv("GRAPHITI_EMBEDDING_API_KEY", raising=False)
    monkeypatch.delenv("GRAPHITI_EMBEDDING_BASE_URL", raising=False)
    monkeypatch.setenv("GRAPHITI_EMBEDDING_MODEL", "embedding-model")

    graphiti_client, captured = _load_graphiti_client(monkeypatch)
    client = graphiti_client.__new__(graphiti_client)
    monkeypatch.setattr(client, "_is_openai_compatible_only", lambda: False)

    client._build_default_embedder()

    assert captured["embedder"]["api_key"] == "shared-key"
    assert captured["embedder"]["base_url"] == "https://shared.example/v1"
    assert captured["embedder"]["embedding_model"] == "embedding-model"


def test_llm_ignores_dedicated_embedding_environment(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "deepseek-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("GRAPHITI_EMBEDDING_API_KEY", "local-key")
    monkeypatch.setenv("GRAPHITI_EMBEDDING_BASE_URL", "http://embedding:80/v1")
    monkeypatch.setenv("GRAPHITI_LLM_MODEL", "deepseek-v4-flash")

    graphiti_client, captured = _load_graphiti_client(monkeypatch)
    client = graphiti_client.__new__(graphiti_client)

    client._build_default_llm_client()

    assert captured["llm"]["api_key"] == "deepseek-key"
    assert captured["llm"]["base_url"] == "https://api.deepseek.com"
    assert captured["llm"]["model"] == "deepseek-v4-flash"


def test_deepseek_base_url_selects_compatible_client(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "deepseek-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("GRAPHITI_LLM_MODEL", "deepseek-v4-flash")

    graphiti_client, _ = _load_graphiti_client(monkeypatch)
    client = graphiti_client.__new__(graphiti_client)

    llm_client = client._build_default_llm_client()

    assert type(llm_client).__name__ == "DeepSeekGraphitiClient"
