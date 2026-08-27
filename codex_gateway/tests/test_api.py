from types import SimpleNamespace

from app.api import create_app
from app.codex_provider import QueueFullError
from app.config import GatewayConfig


def make_config():
    return GatewayConfig(
        internal_token="internal-secret",
        codex_model="gpt-5.6-terra",
        fallback_api_key="fallback-secret",
        fallback_base_url="https://api.deepseek.com",
        fallback_model="deepseek-v4-flash",
        max_concurrency=1,
        queue_size=20,
        request_timeout_seconds=300,
        codex_home="/tmp/codex",
    )


def test_chat_completion_requires_internal_bearer_token():
    app = create_app(router=SimpleNamespace(), config=make_config())
    response = app.test_client().post("/v1/chat/completions", json={"messages": []})
    assert response.status_code == 401


def test_chat_completion_returns_openai_compatible_response():
    router = SimpleNamespace(
        complete=lambda request: SimpleNamespace(
            content="answer",
            model="gpt-5.6-terra",
            provider="codex",
            fallback_reason=None,
            usage=None,
        )
    )
    app = create_app(router=router, config=make_config())
    response = app.test_client().post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer internal-secret"},
        json={"model": "ignored", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert response.headers["X-MiroFish-Provider"] == "codex"
    body = response.get_json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"] == {"role": "assistant", "content": "answer"}


def test_streaming_is_rejected_explicitly():
    app = create_app(router=SimpleNamespace(), config=make_config())
    response = app.test_client().post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer internal-secret"},
        json={"messages": [], "stream": True},
    )
    assert response.status_code == 400
    assert "stream" in response.get_json()["error"]["message"]


def test_queue_full_returns_503_without_fallback():
    def fail(_request):
        raise QueueFullError("full")

    app = create_app(router=SimpleNamespace(complete=fail), config=make_config())
    response = app.test_client().post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer internal-secret"},
        json={"messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 503


def test_account_returns_only_safe_metadata():
    account_reader = lambda: {
        "authenticated": True,
        "email": "o***r@example.com",
        "plan_type": "pro",
    }
    app = create_app(
        router=SimpleNamespace(),
        config=make_config(),
        account_reader=account_reader,
    )
    response = app.test_client().get(
        "/account",
        headers={"Authorization": "Bearer internal-secret"},
    )
    assert response.get_json() == account_reader()


def test_provider_failure_logs_only_error_type(caplog):
    class SensitiveFailure(RuntimeError):
        pass

    def fail(_request):
        raise SensitiveFailure("private prompt and secret-token")

    app = create_app(router=SimpleNamespace(complete=fail), config=make_config())
    with caplog.at_level("ERROR"):
        response = app.test_client().post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer internal-secret"},
            json={"messages": [{"role": "user", "content": "private prompt"}]},
        )

    assert response.status_code == 502
    logs = caplog.text
    assert "SensitiveFailure" in logs
    assert "private prompt" not in logs
    assert "secret-token" not in logs
