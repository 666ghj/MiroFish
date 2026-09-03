from pathlib import Path
from types import SimpleNamespace

import pytest
from zep_cloud.core.api_error import ApiError as ZepApiError

from app.utils import zep


def test_permanent_zep_errors_fail_without_retry():
    calls = []

    def operation():
        calls.append(True)
        raise ZepApiError(status_code=400, body={"message": "bad query"})

    with pytest.raises(ZepApiError):
        zep.call_zep_read_with_retry(
            operation,
            operation_name="permanent failure",
            sleep=lambda _seconds: None,
        )

    assert len(calls) == 1


def test_rate_limit_retry_respects_retry_after():
    calls = []
    sleeps = []

    def operation():
        calls.append(True)
        if len(calls) == 1:
            raise ZepApiError(
                status_code=429,
                headers={"Retry-After": "7"},
                body={"message": "slow down"},
            )
        return "ok"

    result = zep.call_zep_read_with_retry(
        operation,
        operation_name="rate limited read",
        sleep=sleeps.append,
    )

    assert result == "ok"
    assert len(calls) == 2
    assert sleeps == [7.0]


def test_zep_client_is_shared_and_uses_an_explicit_timeout(monkeypatch):
    created = []

    def fake_zep(**kwargs):
        created.append(kwargs)
        return SimpleNamespace(kwargs=kwargs)

    monkeypatch.delenv("ZEP_API_URL", raising=False)
    # Assert the documented default, independent of the operator's .env — which
    # config.py loads with override=True at import time. A local deployment sets
    # ZEP_BASE_URL, and without this the test would fail on that machine only.
    monkeypatch.delenv("ZEP_BASE_URL", raising=False)
    monkeypatch.setattr(zep, "Zep", fake_zep)
    zep.clear_zep_client_cache()

    first = zep.get_zep_client(" test-key ", timeout=12)
    second = zep.get_zep_client("test-key", timeout=12)

    assert first is second
    assert created == [{
        "api_key": "test-key",
        "base_url": zep.ZEP_CLOUD_BASE_URL,
        "timeout": 12.0,
    }]
    zep.clear_zep_client_cache()


def test_zep_client_rejects_the_sdk_api_url_override(monkeypatch):
    """ZEP_API_URL takes precedence over an explicit base_url inside the SDK, so
    it stays rejected. ZEP_BASE_URL is the supported way to retarget."""
    monkeypatch.setenv("ZEP_API_URL", "https://example.invalid")

    with pytest.raises(ValueError, match="ZEP_API_URL"):
        zep.get_zep_client("test-key")


def test_base_url_defaults_to_cloud(monkeypatch):
    monkeypatch.delenv("ZEP_BASE_URL", raising=False)
    assert zep.resolve_zep_base_url() == zep.ZEP_CLOUD_BASE_URL


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_base_url_falls_back_to_cloud(monkeypatch, blank):
    monkeypatch.setenv("ZEP_BASE_URL", blank)
    assert zep.resolve_zep_base_url() == zep.ZEP_CLOUD_BASE_URL


def test_zep_base_url_retargets_the_client(monkeypatch):
    """UXE fork: ZEP_BASE_URL points the SDK at the local Graphiti-backed shim."""
    created = []

    def fake_zep(**kwargs):
        created.append(kwargs)
        return SimpleNamespace(kwargs=kwargs)

    monkeypatch.delenv("ZEP_API_URL", raising=False)
    monkeypatch.setenv("ZEP_BASE_URL", " http://127.0.0.1:8088/api/v2 ")
    monkeypatch.setattr(zep, "Zep", fake_zep)
    zep.clear_zep_client_cache()

    zep.get_zep_client("test-key", timeout=5)

    assert created == [{
        "api_key": "test-key",
        "base_url": "http://127.0.0.1:8088/api/v2",
        "timeout": 5.0,
    }]
    zep.clear_zep_client_cache()


def test_clients_for_different_base_urls_are_not_shared(monkeypatch):
    """base_url is part of the cache key, so switching endpoints cannot hand
    back a client still pointed at the old one."""
    monkeypatch.delenv("ZEP_API_URL", raising=False)
    monkeypatch.setattr(zep, "Zep", lambda **kwargs: SimpleNamespace(kwargs=kwargs))
    zep.clear_zep_client_cache()

    monkeypatch.setenv("ZEP_BASE_URL", "http://127.0.0.1:8088/api/v2")
    local = zep.get_zep_client("test-key", timeout=5)
    monkeypatch.delenv("ZEP_BASE_URL", raising=False)
    cloud = zep.get_zep_client("test-key", timeout=5)

    assert local is not cloud
    assert local.kwargs["base_url"] == "http://127.0.0.1:8088/api/v2"
    assert cloud.kwargs["base_url"] == zep.ZEP_CLOUD_BASE_URL
    zep.clear_zep_client_cache()


def test_zep_client_ignores_legacy_timeout_env_names(monkeypatch):
    """The supported override names are ZEP_HTTP_REQUEST_TIMEOUT_SECONDS and
    ZEP_INGESTION_WAIT_TIMEOUT_SECONDS, read at import. These older names were
    never wired up and must stay inert."""
    created = []

    def fake_zep(**kwargs):
        created.append(kwargs)
        return SimpleNamespace(kwargs=kwargs)

    monkeypatch.delenv("ZEP_API_URL", raising=False)
    monkeypatch.delenv("ZEP_BASE_URL", raising=False)
    monkeypatch.setenv("ZEP_REQUEST_TIMEOUT_SECONDS", "1")
    monkeypatch.setenv("ZEP_INGESTION_TIMEOUT_SECONDS", "1")
    monkeypatch.setattr(zep, "Zep", fake_zep)
    zep.clear_zep_client_cache()

    zep.get_zep_client("test-key")

    assert created == [{
        "api_key": "test-key",
        "base_url": zep.ZEP_CLOUD_BASE_URL,
        "timeout": zep.ZEP_HTTP_REQUEST_TIMEOUT_SECONDS,
    }]
    # Assert the legacy names had no effect, rather than hard-coding the
    # defaults: a local deployment legitimately raises the ingestion timeout in
    # .env, and config.py loads that with override=True at import time.
    assert zep.ZEP_HTTP_REQUEST_TIMEOUT_SECONDS != 1
    assert zep.ZEP_INGESTION_WAIT_TIMEOUT_SECONDS != 1
    zep.clear_zep_client_cache()


def test_supported_timeout_env_names_are_honoured(monkeypatch):
    """The timeouts are module constants read at import, so verify the
    documented override names really are wired up."""
    import importlib

    monkeypatch.setenv("ZEP_HTTP_REQUEST_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("ZEP_INGESTION_WAIT_TIMEOUT_SECONDS", "4242")
    reloaded = importlib.reload(zep)
    try:
        assert reloaded.ZEP_HTTP_REQUEST_TIMEOUT_SECONDS == 12.5
        assert reloaded.ZEP_INGESTION_WAIT_TIMEOUT_SECONDS == 4242
    finally:
        # Restore the module for every other test in the session.
        monkeypatch.undo()
        importlib.reload(zep)


def test_default_timeouts_when_env_is_clean(monkeypatch):
    import importlib

    monkeypatch.delenv("ZEP_HTTP_REQUEST_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("ZEP_INGESTION_WAIT_TIMEOUT_SECONDS", raising=False)
    reloaded = importlib.reload(zep)
    try:
        assert reloaded.ZEP_HTTP_REQUEST_TIMEOUT_SECONDS == 60.0
        assert reloaded.ZEP_INGESTION_WAIT_TIMEOUT_SECONDS == 600
    finally:
        monkeypatch.undo()
        importlib.reload(zep)


def test_zep_timeout_policy_is_not_exposed_in_env_example():
    env_example = Path(__file__).resolve().parents[2] / ".env.example"
    contents = env_example.read_text(encoding="utf-8")

    assert "ZEP_REQUEST_TIMEOUT_SECONDS" not in contents
    assert "ZEP_INGESTION_TIMEOUT_SECONDS" not in contents
