"""
认证中间件测试

覆盖 Config.API_KEYS 驱动的 API Key 认证：匿名访问（未启用认证）、
合法凭证、缺失凭证、错误凭证、豁免路径、CORS 预检请求。
"""

import pytest

from app import create_app
from app.config import Config
from app.utils.auth import AuthenticationError, authenticate_request


@pytest.fixture
def client_no_auth(monkeypatch):
    monkeypatch.setattr(Config, "API_KEYS", {})
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


@pytest.fixture
def client_with_auth(monkeypatch):
    monkeypatch.setattr(Config, "API_KEYS", {"secret-key-1": "alice", "secret-key-2": "bob"})
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_anonymous_access_allowed_when_auth_disabled(client_no_auth):
    response = client_no_auth.get("/api/simulation/list")
    assert response.status_code != 401


def test_health_check_never_requires_auth(client_with_auth):
    response = client_with_auth.get("/health")
    assert response.status_code == 200


def test_anonymous_access_rejected_when_auth_enabled(client_with_auth):
    response = client_with_auth.get("/api/simulation/list")
    assert response.status_code == 401
    assert response.json["error"] == "unauthorized"


def test_invalid_token_rejected(client_with_auth):
    response = client_with_auth.get(
        "/api/simulation/list", headers={"Authorization": "Bearer not-a-real-key"}
    )
    assert response.status_code == 401


def test_valid_bearer_token_accepted(client_with_auth):
    response = client_with_auth.get(
        "/api/simulation/list", headers={"Authorization": "Bearer secret-key-1"}
    )
    assert response.status_code != 401


def test_valid_x_api_key_header_accepted(client_with_auth):
    response = client_with_auth.get(
        "/api/simulation/list", headers={"X-API-Key": "secret-key-2"}
    )
    assert response.status_code != 401


def test_malformed_authorization_header_rejected(client_with_auth):
    # Missing the "Bearer " scheme prefix.
    response = client_with_auth.get(
        "/api/simulation/list", headers={"Authorization": "secret-key-1"}
    )
    assert response.status_code == 401


def test_empty_bearer_token_rejected(client_with_auth):
    response = client_with_auth.get(
        "/api/simulation/list", headers={"Authorization": "Bearer "}
    )
    assert response.status_code == 401


def test_options_preflight_bypasses_auth(client_with_auth):
    response = client_with_auth.options("/api/simulation/list")
    assert response.status_code != 401


class TestAuthenticateRequestUnit:
    def test_returns_none_when_disabled(self, monkeypatch):
        monkeypatch.setattr(Config, "API_KEYS", {})
        app = create_app()
        with app.test_request_context("/api/simulation/list"):
            assert authenticate_request() is None

    def test_returns_user_id_for_valid_key(self, monkeypatch):
        monkeypatch.setattr(Config, "API_KEYS", {"k1": "alice"})
        app = create_app()
        with app.test_request_context(
            "/api/simulation/list", headers={"X-API-Key": "k1"}
        ):
            assert authenticate_request() == "alice"

    def test_raises_for_missing_key(self, monkeypatch):
        monkeypatch.setattr(Config, "API_KEYS", {"k1": "alice"})
        app = create_app()
        with app.test_request_context("/api/simulation/list"):
            with pytest.raises(AuthenticationError):
                authenticate_request()

    def test_raises_for_wrong_key(self, monkeypatch):
        monkeypatch.setattr(Config, "API_KEYS", {"k1": "alice"})
        app = create_app()
        with app.test_request_context(
            "/api/simulation/list", headers={"X-API-Key": "wrong"}
        ):
            with pytest.raises(AuthenticationError):
                authenticate_request()
