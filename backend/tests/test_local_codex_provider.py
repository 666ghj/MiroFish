import os

from flask import Flask

from app.api import provider_bp
from app.config import Config
from app.services import local_codex_provider as provider


def test_provider_activation_switches_future_requests_and_restores_configuration(monkeypatch):
    class FakeProcess:
        def poll(self):
            return None

        def terminate(self):
            pass

    monkeypatch.setattr(provider.shutil, "which", lambda _: "codex")
    monkeypatch.setattr(provider, "verify_chatgpt_login", lambda _: None)
    monkeypatch.setattr(provider, "_free_loopback_port", lambda: 8765)
    monkeypatch.setattr(provider.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    monkeypatch.setattr(provider, "_bridge_ready", lambda: provider._bridge_process is not None)
    monkeypatch.setattr(provider, "_bridge_process", None)
    monkeypatch.setattr(provider, "_bridge_port", None)
    monkeypatch.setattr(provider, "_bridge_token", None)
    monkeypatch.setattr(provider, "_active", False)

    try:
        result = provider.activate()
        assert result["codex_connected"] is True
        assert result["codex_model"] == "gpt-6-luna"
        assert "token" not in result
        assert Config.LLM_MODEL_NAME == "codex-bridge"
        assert Config.LLM_BASE_URL == "http://127.0.0.1:8765/v1"
        assert os.environ["LLM_BOOST_API_KEY"] == ""
        assert provider.deactivate()["active_provider"] == "configured"
        assert Config.LLM_MODEL_NAME == provider._original["LLM_MODEL_NAME"]
    finally:
        provider.deactivate()


def test_provider_switch_requires_local_request_and_local_origin(monkeypatch):
    app = Flask(__name__)
    app.register_blueprint(provider_bp, url_prefix="/api/provider")
    monkeypatch.setattr(provider, "activate", lambda: {"active_provider": "codex"})
    monkeypatch.setattr(provider, "deactivate", lambda: {"active_provider": "configured"})
    client = app.test_client()

    remote = client.post(
        "/api/provider/codex/activate",
        environ_base={"REMOTE_ADDR": "192.0.2.10"},
    )
    foreign_origin = client.post(
        "/api/provider/codex/activate",
        headers={"Origin": "https://example.com"},
    )
    local = client.post(
        "/api/provider/codex/activate",
        headers={"Origin": "http://localhost:3000"},
    )

    assert remote.status_code == 403
    assert foreign_origin.status_code == 403
    assert local.status_code == 200
    assert client.post(
        "/api/provider/codex/deactivate",
        headers={"Origin": "https://example.com"},
    ).status_code == 403
