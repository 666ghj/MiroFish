from types import SimpleNamespace

from app import create_app
from app.config import GatewayConfig


def test_app_factory_creates_one_codex_runtime_and_one_fallback_client():
    config = GatewayConfig(
        internal_token="internal",
        codex_model="gpt-5.6-terra",
        fallback_api_key="fallback",
        fallback_base_url="https://api.deepseek.com",
        fallback_model="deepseek-v4-flash",
        max_concurrency=1,
        queue_size=20,
        request_timeout_seconds=300,
        codex_home="/var/lib/codex",
    )
    codex_instances = []
    fallback_calls = []

    class FakeCodex:
        def account(self, refresh_token=False):
            return SimpleNamespace(account=None)

    def codex_factory(_config):
        instance = FakeCodex()
        codex_instances.append(instance)
        return instance

    def openai_factory(**kwargs):
        fallback_calls.append(kwargs)
        return SimpleNamespace()

    app = create_app(
        config=config,
        codex_factory=codex_factory,
        openai_factory=openai_factory,
    )

    assert len(codex_instances) == 1
    assert fallback_calls == [
        {"api_key": "fallback", "base_url": "https://api.deepseek.com"}
    ]
    assert app.extensions["codex_runtime"] is codex_instances[0]
    assert app.test_client().get("/health").status_code == 200
