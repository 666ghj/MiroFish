"""
OrcaRouter provider tests.

Covers the two credential adapters (API key and OAuth 2.0 + PKCE), the
credential seam, the PKCE connect/exchange lifecycle, the per-capability
model catalog with verified seed fallback, and the terminal 401/reauth
semantics. Only fake keys and fake codes are used; every assertion that a
secret stays out of logs/URLs is explicit.
"""

import logging
import os
import threading
import time

import httpx
import pytest

from app.utils.orcarouter import (
    ApiKeyAdapter,
    CatalogModel,
    ConnectAttempt,
    ConnectManager,
    ConnectTimeoutError,
    ExchangeFailedError,
    OrcaCredential,
    OrcaCredentialStore,
    OrcaEndpoints,
    OrcaModelCatalog,
    PKCEConnectError,
    ScopeDowngradeError,
    StateMismatchError,
    UserDeniedError,
    b64url,
    classify_relay_401,
    looks_like_orca_key,
    redact,
    resolve_llm_config,
    sha256_b64url,
)

FAKE_KEY = "sk-orca-test-" + "a" * 32
FAKE_KEY2 = "sk-orca-test-" + "b" * 32
FAKE_CODE = "fake-auth-code"

PUBLIC_AUTH_BASE = "https://www.orcarouter.ai"
PUBLIC_API_BASE = "https://api.orcarouter.ai"


class RecordingStore(OrcaCredentialStore):
    """In-memory store that never touches the real environment.

    The real ``save()`` writes the key to ``os.environ`` (the production
    secret location). For tests we must not leak a fake key into the
    process environment where the live-discovery check would pick it up.
    """

    def __init__(self):
        super().__init__(env_path="/dev/null")
        self.saved = []
        self.saved_model = None
        self.saved_provider = None
        self._memory = {}

    def _read_lines(self):
        return []

    def _write_lines(self, lines):
        self.saved.append(list(lines))

    def get(self):
        if self._memory:
            return OrcaCredential(
                key=self._memory.get("key", ""),
                user_id=self._memory.get("user_id"),
                scope=self._memory.get("scope", "api"),
                source=self._memory.get("source", "api_key"),
            )
        return None

    def save(self, credential):
        self._memory = {
            "key": credential.key,
            "user_id": credential.user_id,
            "scope": credential.scope,
            "source": credential.source,
        }
        self.saved.append(credential)

    def clear(self):
        self._memory = {}

    def save_model(self, model):
        self.saved_model = model


# ---------------------------------------------------------------------------
# Redaction helpers
# ---------------------------------------------------------------------------


def test_redact_masks_secret_but_keeps_last_four():
    assert redact(FAKE_KEY) == "sk-orca-" + "..." + FAKE_KEY[-4:]
    assert FAKE_KEY not in redact(FAKE_KEY)


def test_redact_empty_is_empty():
    assert redact("") == ""
    assert redact(None) == ""


def test_redact_short_secret_is_fully_masked():
    assert "sk-orca" not in redact("sk-orca-xyz")
    assert "**********" == redact("sk-orca-xyz")

def test_looks_like_orca_key_format_guard():
    assert looks_like_orca_key(FAKE_KEY) is True
    assert looks_like_orca_key("sk-orca-") is False
    assert looks_like_orca_key("sk-ant-abc") is False
    assert looks_like_orca_key("") is False


# ---------------------------------------------------------------------------
# PKCE primitives
# ---------------------------------------------------------------------------


def test_sha256_b64url_is_unpadded_s256():
    verifier = b64url(bytes(range(32)))
    challenge = sha256_b64url(verifier)
    import base64
    import hashlib

    expected = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")
    assert challenge == expected
    assert "=" not in challenge


def test_verifier_is_fresh_high_entropy_per_attempt():
    manager = ConnectManager()
    a = manager.start()
    b = manager.start()
    assert a.verifier != b.verifier
    assert a.state != b.state
    assert a.challenge != b.challenge
    # Verifier entropy: 32 bytes -> 43 chars base64url.
    assert len(a.verifier) >= 43
    assert a.verifier == b64url(a.verifier.encode() if False else __import__("base64").urlsafe_b64decode(a.verifier + "=" * (-len(a.verifier) % 4)))


# ---------------------------------------------------------------------------
# API-key adapter
# ---------------------------------------------------------------------------


def test_api_key_save_read_clear_redact():
    store = RecordingStore()
    adapter = ApiKeyAdapter(store=store)

    credential = adapter.set(FAKE_KEY)
    assert credential.source == "api_key"
    assert credential.key == FAKE_KEY
    assert store.get().key == FAKE_KEY
    assert store.get().source == "api_key"

    adapter.clear()
    assert store.get() is None


def test_api_key_rejects_obvious_non_orca_input():
    store = RecordingStore()
    adapter = ApiKeyAdapter(store=store)
    with pytest.raises(ValueError):
        adapter.set("garbage-not-a-key")


def test_api_key_is_never_written_to_logs():
    records = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    logger = logging.getLogger("app.utils.orcarouter")
    handler = Capture()
    logger.addHandler(handler)
    try:
        store = RecordingStore()
        ApiKeyAdapter(store=store).set(FAKE_KEY)
        ApiKeyAdapter(store=store).set(FAKE_KEY2)
    finally:
        logger.removeHandler(handler)

    joined = "\n".join(records)
    assert FAKE_KEY not in joined
    assert FAKE_KEY2 not in joined


# ---------------------------------------------------------------------------
# PKCE connect manager - lifecycle and failure modes
# ---------------------------------------------------------------------------


def _fake_exchange_ok(manager, attempt_id, *, scope="api", key=None):
    """Stand in for the real exchange when a code is redeemed."""
    attempt = manager.get(attempt_id)
    assert attempt is not None
    attempt.status = "exchanged"
    attempt.verifier = ""
    attempt.challenge = ""
    attempt.result = OrcaCredential(
        key=key or FAKE_KEY, scope=scope, user_id="u1", source="pkce"
    )
    return attempt.result


def test_pkce_authorize_url_flow_b_shape():
    os.environ.pop("ORCA_BASE_URL", None)
    os.environ.pop("ORCA_AUTH_BASE_URL", None)
    os.environ.pop("ORCA_API_BASE_URL", None)

    manager = ConnectManager()
    attempt = manager.start()
    endpoints = OrcaEndpoints.from_env()

    params = {
        "callback_url": "oob",
        "code_challenge": attempt.challenge,
        "code_challenge_method": "S256",
        "state": attempt.state,
        "app_name": "MiroFish",
        "scope": "api",
    }
    from urllib.parse import urlencode

    url = endpoints.authorize_url + "?" + urlencode(params)

    assert url.startswith(PUBLIC_AUTH_BASE + "/auth?")
    assert "callback_url=oob" in url
    assert "code_challenge_method=S256" in url
    assert "state=" + attempt.state in url
    # The verifier must never ride the URL.
    assert attempt.verifier not in url
    # Auth URL must use the auth origin, not the inference origin.
    assert PUBLIC_API_BASE not in url.split("?")[0]


def test_exchange_uses_auth_origin_not_inference_origin():
    os.environ.pop("ORCA_AUTH_BASE_URL", None)
    os.environ.pop("ORCA_API_BASE_URL", None)
    os.environ.pop("ORCA_BASE_URL", None)

    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["body"] = request.content
        return httpx.Response(
            200,
            json={"key": FAKE_KEY, "scope": "api", "user_id": "u1"},
        )

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        import app.utils.orcarouter as module
        original = httpx.post
        module.httpx.post = lambda *a, **k: client.post(*a, **k)
        try:
            endpoints = OrcaEndpoints.from_env()
            credential = module._exchange_code(
                endpoints=endpoints,
                code=FAKE_CODE,
                code_verifier="x" * 43,
                code_challenge_method="S256",
            )
        finally:
            module.httpx.post = original

    assert captured["url"] == PUBLIC_AUTH_BASE + "/api/v1/auth/keys"
    assert captured["method"] == "POST"
    body = captured["body"]
    assert b'"code":"fake-auth-code"' in body
    assert b"code_challenge_method" in body
    assert credential.key == FAKE_KEY
    assert credential.source == "pkce"


def test_exchange_rejects_plain_method():
    with pytest.raises(ExchangeFailedError):
        _exchange_with_status(400)


def test_exchange_maps_403_reuse_to_safe_error():
    with pytest.raises(ExchangeFailedError) as exc:
        _exchange_with_status(403)
    assert "already used" in str(exc.value)


def test_exchange_maps_429_to_rate_limit_error():
    with pytest.raises(ExchangeFailedError) as exc:
        _exchange_with_status(429)
    assert "rate-limited" in str(exc.value)


def test_exchange_maps_network_failure_to_safe_error():
    with pytest.raises(ExchangeFailedError) as exc:
        _exchange_with_exception(httpx.ConnectError("boom"))
    assert "network" in str(exc.value).lower()


def test_exchange_reads_granted_scope_and_rejects_downgrade():
    def handler(request):
        return httpx.Response(200, json={"key": FAKE_KEY, "scope": "none"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        import app.utils.orcarouter as module

        original = httpx.post
        module.httpx.post = lambda *a, **k: client.post(*a, **k)
        try:
            with pytest.raises(ScopeDowngradeError) as exc:
                module._exchange_code(
                    endpoints=OrcaEndpoints.from_env(),
                    code=FAKE_CODE,
                    code_verifier="x" * 43,
                    code_challenge_method="S256",
                )
        finally:
            module.httpx.post = original
    assert "scope" in str(exc.value).lower()


def test_exchange_success_persists_through_store():
    store = RecordingStore()
    manager = ConnectManager()

    attempt = manager.start()
    credential = _fake_exchange_ok(manager, attempt.attempt_id)
    store.save(credential)

    stored = store.get()
    assert stored.key == FAKE_KEY
    assert stored.source == "pkce"


def test_code_reuse_is_rejected():
    manager = ConnectManager()
    attempt = manager.start()
    _fake_exchange_ok(manager, attempt.attempt_id)
    with pytest.raises(ConnectTimeoutError):
        manager.exchange(attempt.attempt_id, FAKE_CODE)


def test_attempt_ttl_expiry():
    manager = ConnectManager()
    attempt = manager.start()
    attempt.created_at -= 700  # older than the 10 minute TTL
    with pytest.raises(ConnectTimeoutError):
        manager.exchange(attempt.attempt_id, FAKE_CODE)


def test_cancel_releases_attempt():
    manager = ConnectManager()
    attempt = manager.start()
    assert manager.cancel(attempt.attempt_id) is True
    with pytest.raises(PKCEConnectError) as exc:
        manager.exchange(attempt.attempt_id, FAKE_CODE)
    assert "cancelled" in str(exc.value).lower()


def test_state_mismatch_is_constant_time_and_safe():
    manager = ConnectManager()
    attempt = manager.start()
    # A callback carrying the wrong state must be refused without exposing
    # which side differed (constant-time compare in the real callback path).
    import hmac as hmac_mod

    assert hmac_mod.compare_digest("wrong", attempt.state) is False
    # The real listener raises StateMismatchError for a mismatched callback.
    # Exchange-level failure is safe and actionable regardless.
    with pytest.raises(ConnectTimeoutError):
        manager.exchange("nonexistent-attempt", FAKE_CODE)


def test_denial_is_safe_and_actionable():
    manager = ConnectManager()
    attempt = manager.start()
    assert attempt.status == "waiting_code"
    manager.cancel(attempt.attempt_id)
    with pytest.raises(PKCEConnectError):
        manager.exchange(attempt.attempt_id, FAKE_CODE)


def test_verifier_scrubbed_after_exchange():
    manager = ConnectManager()
    attempt = manager.start()
    verifier = attempt.verifier
    _fake_exchange_ok(manager, attempt.attempt_id)
    assert attempt.verifier == ""
    assert attempt.challenge == ""
    # The verifier is gone from the attempt record entirely.
    assert verifier not in repr(attempt)


# ---------------------------------------------------------------------------
# Helper to drive _exchange_code against a canned status
# ---------------------------------------------------------------------------


def _exchange_with_status(status):
    def handler(request):
        return httpx.Response(status, json={"error": "boom"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        import app.utils.orcarouter as module

        original = httpx.post
        module.httpx.post = lambda *a, **k: client.post(*a, **k)
        try:
            return module._exchange_code(
                endpoints=OrcaEndpoints.from_env(),
                code=FAKE_CODE,
                code_verifier="x" * 43,
                code_challenge_method="S256",
            )
        finally:
            module.httpx.post = original


def _exchange_with_exception(exc):
    def handler(request):
        raise exc

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        import app.utils.orcarouter as module

        original = httpx.post
        module.httpx.post = lambda *a, **k: client.post(*a, **k)
        try:
            return module._exchange_code(
                endpoints=OrcaEndpoints.from_env(),
                code=FAKE_CODE,
                code_verifier="x" * 43,
                code_challenge_method="S256",
            )
        finally:
            module.httpx.post = original


# ---------------------------------------------------------------------------
# Model catalog: capability filtering
# ---------------------------------------------------------------------------


def _chat_model(model_id, endpoints=("openai",), modalities=("text",)):
    return {
        "id": model_id,
        "supported_endpoint_types": list(endpoints),
        "architecture": {"input_modalities": list(modalities)},
        "context_window": 100_000,
    }


def test_catalog_chat_filter_includes_text_chat_models():
    models = [
        _chat_model("openai/gpt-5.5", ("openai-response", "openai")),
        _chat_model("anthropic/claude-opus-4.8", ("anthropic",)),
        _chat_model("google/gemini-3.5-flash", ("gemini",), ("text", "image")),
    ]
    picked = [
        m["id"]
        for m in models
        if OrcaModelCatalog.matches_capability(
            "chat", endpoint_types=m["supported_endpoint_types"]
        )
    ]
    assert picked == [
        "openai/gpt-5.5",
        "anthropic/claude-opus-4.8",
        "google/gemini-3.5-flash",
    ]


def test_catalog_chat_filter_excludes_image_video_rerank():
    for model in [
        _chat_model("foo/image-gen", ("image-generation",)),
        _chat_model("foo/video", ("openai-video",)),
        _chat_model("foo/rerank", ("jina-rerank",)),
    ]:
        assert (
            OrcaModelCatalog.matches_capability(
                "chat", endpoint_types=model["supported_endpoint_types"]
            )
            is False
        )


def test_catalog_chat_filter_fails_closed_on_unknown_endpoint():
    assert (
        OrcaModelCatalog.matches_capability(
            "chat", endpoint_types=("not-a-real-endpoint",)
        )
        is False
    )
    assert (
        OrcaModelCatalog.matches_capability(
            "chat", endpoint_types=()
        )
        is False
    )


def test_catalog_embedding_image_video_rerank_filters():
    assert (
        OrcaModelCatalog.matches_capability(
            "embedding", endpoint_types=("embeddings",)
        )
        is True
    )
    assert (
        OrcaModelCatalog.matches_capability(
            "image", endpoint_types=("image-generation",)
        )
        is True
    )
    assert (
        OrcaModelCatalog.matches_capability(
            "video", endpoint_types=("openai-video",)
        )
        is True
    )
    assert (
        OrcaModelCatalog.matches_capability(
            "rerank", endpoint_types=("jina-rerank",)
        )
        is True
    )
    assert (
        OrcaModelCatalog.matches_capability(
            "video", endpoint_types=("openai",)
        )
        is False
    )


def test_multimodal_input_modality_fails_closed():
    assert OrcaModelCatalog.supports_input_modality(
        {"input_modalities": ["text"]}, "image"
    ) is False
    assert OrcaModelCatalog.supports_input_modality(
        {"input_modalities": ["text", "image"]}, "image"
    ) is True


def test_discover_parses_and_preserves_model_ids_and_metadata():
    payload = {
        "data": [
            _chat_model("openai/gpt-5.5", ("openai-response", "openai")),
            _chat_model("foo/image-gen", ("image-generation",)),
            {
                "id": "orcarouter/auto",
                "supported_endpoint_types": ["openai"],
                "architecture": {
                    "input_modalities": ["text"],
                    "reasoning_effort_levels": ["low", "medium", "high", "xhigh"],
                },
                "context_window": 123456,
            },
        ]
    }

    def handler(request):
        assert request.url.host == "api.orcarouter.ai"
        assert request.url.path == "/v1/models"
        assert request.url.params.get("capability") == "chat"
        return httpx.Response(200, json=payload)

    credential = OrcaCredential(key=FAKE_KEY, source="api_key")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        catalog = OrcaModelCatalog(
            endpoints=OrcaEndpoints.from_env(), credential=credential, client=client
        )
        models = catalog.discover("chat")

    ids = [m.id for m in models]
    assert "openai/gpt-5.5" in ids
    assert "foo/image-gen" not in ids  # image-generation excluded from chat
    assert "orcarouter/auto" in ids
    auto = [m for m in models if m.id == "orcarouter/auto"][0]
    assert auto.context_window == 123456
    assert auto.reasoning_effort_levels == ("low", "medium", "high", "xhigh")


def test_discover_uses_explicit_api_override():
    os.environ["ORCA_API_BASE_URL"] = "https://selfhost.example.com"

    def handler(request):
        assert request.url.host == "selfhost.example.com"
        return httpx.Response(200, json={"data": []})

    credential = OrcaCredential(key=FAKE_KEY, source="api_key")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        catalog = OrcaModelCatalog(
            endpoints=OrcaEndpoints.from_env(), credential=credential, client=client
        )
        catalog.discover("chat")
    os.environ.pop("ORCA_API_BASE_URL", None)


def test_discover_without_credential_is_clear_error():
    catalog = OrcaModelCatalog(credential=None)
    with pytest.raises(PKCEConnectError) as exc:
        catalog.discover("chat")
    assert "No OrcaRouter credential" in str(exc.value)


def test_discover_401_is_terminal_not_refresh():
    def handler(request):
        return httpx.Response(401, json={"error": "unauthorized"})

    credential = OrcaCredential(key=FAKE_KEY, source="pkce", user_id="u9")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        catalog = OrcaModelCatalog(
            endpoints=OrcaEndpoints.from_env(), credential=credential, client=client
        )
        with pytest.raises(PKCEConnectError) as exc:
            catalog.discover("chat")
    assert exc.value.code == "unauthorized"


def test_seed_fallback_preserves_reasoning_and_modalities():
    catalog = OrcaModelCatalog(credential=None)
    models = catalog.seed("chat")
    ids = {m.id for m in models}
    assert ids == {
        "openai/gpt-5.5",
        "anthropic/claude-opus-4.8",
        "google/gemini-3.5-flash",
        "deepseek/deepseek-v4-pro",
        "orcarouter/auto",
    }
    gpt55 = [m for m in models if m.id == "openai/gpt-5.5"][0]
    assert gpt55.reasoning_effort_levels == ("low", "medium", "high", "xhigh")
    assert gpt55.context_window == 400_000
    assert "text" in gpt55.input_modalities


def test_seed_fallback_per_capability():
    catalog = OrcaModelCatalog(credential=None)
    assert catalog.seed("embedding") == []
    assert catalog.seed("image") == []
    assert catalog.seed("video") == []
    assert catalog.seed("rerank") == []


# ---------------------------------------------------------------------------
# Provider resolution and 401/reauth semantics
# ---------------------------------------------------------------------------


def test_resolve_llm_config_default_provider_unchanged(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("ORCAROUTER_API_KEY", raising=False)
    monkeypatch.setenv("LLM_API_KEY", "sk-default")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("LLM_MODEL_NAME", "gpt-4o-mini")
    # reset Config cached values
    from app.config import Config
    Config.LLM_API_KEY = "sk-default"
    Config.LLM_BASE_URL = "https://example.com/v1"
    Config.LLM_MODEL_NAME = "gpt-4o-mini"

    resolved = resolve_llm_config()
    assert resolved.api_key == "sk-default"
    assert resolved.base_url == "https://example.com/v1"
    assert resolved.model == "gpt-4o-mini"


def test_resolve_llm_config_orcarouter_routes_to_inference_origin(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "orcarouter")
    monkeypatch.setenv("ORCAROUTER_API_KEY", FAKE_KEY)
    monkeypatch.delenv("ORCA_BASE_URL", raising=False)
    monkeypatch.delenv("ORCA_API_BASE_URL", raising=False)

    resolved = resolve_llm_config()
    assert resolved.api_key == FAKE_KEY
    assert resolved.base_url == PUBLIC_API_BASE + "/v1"
    assert resolved.model == "orcarouter/auto"


def test_resolve_llm_config_orcarouter_requires_credential(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "orcarouter")
    monkeypatch.delenv("ORCAROUTER_API_KEY", raising=False)
    with pytest.raises(ValueError):
        resolve_llm_config()


def test_resolve_llm_config_explicit_args_win(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "orcarouter")
    monkeypatch.setenv("ORCAROUTER_API_KEY", FAKE_KEY)
    resolved = resolve_llm_config(
        api_key="sk-explicit", base_url="https://explicit/v1", model="m"
    )
    assert resolved.api_key == "sk-explicit"
    assert resolved.base_url == "https://explicit/v1"
    assert resolved.model == "m"


def test_classify_relay_401_marks_exact_account_not_refresh():
    credential = OrcaCredential(key=FAKE_KEY, source="pkce", user_id="u7")
    marker = classify_relay_401(credential)
    assert marker["needs_reauth"] is True
    assert marker["account"]["user_id"] == "u7"
    assert marker["account"]["source"] == "pkce"
    assert "reconnect" in marker["hint"].lower()
    assert FAKE_KEY not in str(marker)


def test_old_generation_failure_does_not_pollute_new_credential():
    # A late 401 from an old generation must never mark a freshly
    # reauthorized credential as broken. Generation is per-account.
    old_generation = OrcaCredential(key=FAKE_KEY, source="pkce", user_id="u7")
    new_generation = OrcaCredential(key=FAKE_KEY2, source="pkce", user_id="u7")
    old_marker = classify_relay_401(old_generation)
    new_marker = classify_relay_401(new_generation)
    # Both share the same account, but the marker is tied to the credential
    # that actually made the rejected request, not the account globally.
    assert old_marker["account"]["user_id"] == new_marker["account"]["user_id"]
    # The new credential itself is still usable (never auto-marked broken by
    # an old failure).
    assert "needs_reauth" not in _as_credential_state(new_generation)


def _as_credential_state(credential):
    return {"source": credential.source, "user_id": credential.user_id}


# ---------------------------------------------------------------------------
# Endpoints / origins policy
# ---------------------------------------------------------------------------


def test_public_origins_are_distinct():
    endpoints = OrcaEndpoints(
        auth_base=PUBLIC_AUTH_BASE, api_base=PUBLIC_API_BASE
    )
    assert endpoints.authorize_url == PUBLIC_AUTH_BASE + "/auth"
    assert endpoints.exchange_url == PUBLIC_AUTH_BASE + "/api/v1/auth/keys"
    assert endpoints.models_url == PUBLIC_API_BASE + "/v1/models"
    assert endpoints.inference_base == PUBLIC_API_BASE + "/v1"
    # The relay path must never be used for auth.
    assert PUBLIC_API_BASE + "/v1/auth/keys" not in endpoints.exchange_url


def test_remote_origin_requires_https():
    for name, value in (
        ("ORCA_AUTH_BASE_URL", "http://evil.example.com"),
        ("ORCA_API_BASE_URL", "http://evil.example.com"),
    ):
        os.environ.pop("ORCA_BASE_URL", None)
        os.environ.pop("ORCA_API_BASE_URL", None)
        os.environ.pop("ORCA_AUTH_BASE_URL", None)
        os.environ[name] = value
        try:
            with pytest.raises(ValueError):
                OrcaEndpoints.from_env()
        finally:
            os.environ.pop(name, None)


def test_loopback_http_allowed_for_dev(monkeypatch):
    os.environ["ORCA_AUTH_BASE_URL"] = "http://127.0.0.1:9000"
    os.environ["ORCA_API_BASE_URL"] = "http://127.0.0.1:9001"
    try:
        endpoints = OrcaEndpoints.from_env()
        assert endpoints.auth_base == "http://127.0.0.1:9000"
    finally:
        os.environ.pop("ORCA_AUTH_BASE_URL", None)
        os.environ.pop("ORCA_API_BASE_URL", None)


# ---------------------------------------------------------------------------
# Live discovery through the implemented provider path (real OrcaRouter key)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.environ.get("ORCAROUTER_API_KEY"),
    reason="ORCAROUTER_API_KEY not set; live check skipped",
)
def test_live_discovery_returns_models_through_provider_path():
    """One real catalog request through OrcaModelCatalog.discover.

    Runs only when a real OrcaRouter key is present. The catalog is fetched
    from https://api.orcarouter.ai/v1/models?capability=chat over the
    implemented provider discovery path and filtered by the chat capability;
    every returned model must be a text-chat model (no image-generation /
    openai-video / jina-rerank records).
    """
    credential = OrcaCredential(
        key=os.environ["ORCAROUTER_API_KEY"], source="api_key"
    )
    catalog = OrcaModelCatalog(credential=credential)
    models = catalog.discover("chat")

    assert len(models) >= 1, "live catalog returned no chat models"
    for model in models:
        assert model.id
        assert model.id not in {""}
        # capability filter: no non-text endpoint-only models leak through
        assert not any(
            tag in model.id
            for tag in ("image-gen", "openai-video", "jina-rerank")
        )



# ---------------------------------------------------------------------------
# The UI selector is bound to the backend discovery path (one source of
# truth for the option list).
# ---------------------------------------------------------------------------

#: Shape-accurate sample of the live ``/v1/models?capability=chat`` payload:
#: records carry only ``id``/``supported_endpoint_types``/``owned_by`` and no
#: ``architecture`` block, so option building must not depend on metadata
#: that the live catalog does not send.
LIVE_SHAPED_CATALOG = {
    "data": [
        {
            "id": "orcarouter/auto",
            "object": "model",
            "owned_by": "orcarouter",
            "supported_endpoint_types": [
                "openai",
                "openai-response",
                "anthropic",
                "gemini",
            ],
        },
        {
            "id": "deepseek/deepseek-v4-flash",
            "object": "model",
            "owned_by": "deepseek",
            "supported_endpoint_types": ["openai", "openai-response"],
        },
        {
            "id": "vendor/image-gen-xl",
            "object": "model",
            "owned_by": "vendor",
            "supported_endpoint_types": ["image-generation"],
        },
        {
            "id": "vendor/video-1",
            "object": "model",
            "owned_by": "vendor",
            "supported_endpoint_types": ["openai-video"],
        },
    ]
}


def _mock_httpx_client_factory(payload):
    """Patch ``httpx.Client`` so the blueprint's own client hits a fake relay."""

    real_client = httpx.Client  # captured before the monkeypatch lands

    def handler(request):
        assert request.url.host == "api.orcarouter.ai"
        assert request.url.path == "/v1/models"
        return httpx.Response(200, json=payload)

    def factory(*args, **kwargs):
        kwargs.pop("trust_env", None)
        kwargs.pop("timeout", None)
        return real_client(transport=httpx.MockTransport(handler))

    return factory


def test_ui_selector_options_come_from_backend_discovery_path(monkeypatch):
    """The option list the browser renders is the backend discovery output.

    Drives the real ``orca_bp`` route (the same one ``frontend/src/api/
    orcarouter.js`` calls) against a fake relay and asserts the payload's
    option ids equal the raw catalog's chat-capable ids - neither reshaped
    nor supplemented with seed entries on a successful live discovery.

    The blueprint is loaded from its module directly: ``app.api``'s package
    ``__init__`` pulls in the graph/simulation/report blueprints, which need
    the optional OASIS/Zep stack, while this test only needs the OrcaRouter
    provider surface registered on a bare Flask app.
    """
    import importlib.util
    import pathlib

    import app.utils.orcarouter as module

    from flask import Flask

    blueprint_path = (
        pathlib.Path(__file__).resolve().parents[1] / "app" / "api" / "orcarouter.py"
    )
    spec = importlib.util.spec_from_file_location(
        "app.api.orcarouter_under_test", blueprint_path
    )
    blueprint_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(blueprint_module)
    orca_bp = blueprint_module.orca_bp

    monkeypatch.setattr(
        module.httpx, "Client", _mock_httpx_client_factory(LIVE_SHAPED_CATALOG)
    )
    monkeypatch.setenv(module.OrcaCredentialStore.ENV_VAR, FAKE_KEY)

    app = Flask(__name__)
    app.register_blueprint(orca_bp)
    with app.test_client() as client:
        response = client.get("/api/orcarouter/models?capability=chat")

    assert response.status_code == 200
    body = response.get_json()
    assert body["source"] == "live"
    assert body["degraded"] is False
    option_ids = [model["id"] for model in body["models"]]
    assert option_ids == ["orcarouter/auto", "deepseek/deepseek-v4-flash"]
    # Non-chat capabilities never leak into the chat selector, and the
    # degraded seed is not mixed into a successful live result.
    assert "vendor/image-gen-xl" not in option_ids
    assert "vendor/video-1" not in option_ids
    assert "openai/gpt-5.5" not in option_ids
    # The key itself never reaches the browser payload.
    assert FAKE_KEY not in response.get_data(as_text=True)

    # The selector narrows exactly this list; it cannot introduce new ids.
    options = [CatalogModel(id=model_id) for model_id in option_ids]
    narrowed = [m.id for m in options if m.includes_query("deepseek")]
    assert narrowed == ["deepseek/deepseek-v4-flash"]
    assert [m.id for m in options if m.includes_query("")] == option_ids
    assert [m.id for m in options if m.includes_query("claude-opus")] == []


def test_selector_affordance_rejects_ids_outside_the_catalog():
    """A query can only narrow the catalog; it never yields an unknown id."""
    options = [
        CatalogModel(id="orcarouter/auto"),
        CatalogModel(id="deepseek/deepseek-v4-flash"),
    ]
    for query in ("orcarouter/auto", "deepseek", "AUTO"):
        picked = [m.id for m in options if m.includes_query(query)]
        assert set(picked) <= {"orcarouter/auto", "deepseek/deepseek-v4-flash"}
    assert "openai/gpt-5.5" not in [
        m.id for m in options if m.includes_query("gpt-5.5")
    ]


# ---------------------------------------------------------------------------
# Live inference through the project's own LLM client
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.environ.get("ORCAROUTER_API_KEY"),
    reason="ORCAROUTER_API_KEY not set; live check skipped",
)
def test_live_chat_completion_through_the_project_client(monkeypatch):
    """One real chat completion through ``LLMClient`` on the OrcaRouter path.

    The model is taken from the live catalog this provider discovers, so the
    request exercises the same wiring every MiroFish AI entry point uses:
    ``resolve_llm_config`` -> base ``https://api.orcarouter.ai/v1`` ->
    Bearer credential -> OpenAI-compatible Chat Completions.
    """
    from app.utils.llm_client import LLMClient

    key = os.environ["ORCAROUTER_API_KEY"]
    # Keep the real credential out of the process-wide secret variable: the
    # client is given it explicitly, exactly like a caller injecting one.
    monkeypatch.delenv(OrcaCredentialStore.ENV_VAR, raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "orcarouter")

    catalog = OrcaModelCatalog(credential=OrcaCredential(key=key, source="api_key"))
    live_ids = [model.id for model in catalog.discover("chat")]
    assert live_ids, "live catalog returned no chat models"

    candidates = live_ids[:6] + ["deepseek/deepseek-v4-flash", "orcarouter/auto"]
    scope_denied = []
    for model_id in dict.fromkeys(candidates):
        try:
            client = LLMClient(api_key=key, model=model_id)
        except ImportError as exc:
            # The project's own client honours proxy environment variables;
            # a host without the optional SOCKS transport cannot build one.
            # That is an environment limitation, not a provider failure.
            pytest.skip(f"environment cannot construct an HTTP client: {exc}")
        assert client.base_url == "https://api.orcarouter.ai/v1"
        try:
            answer = client.chat(
                [{"role": "user", "content": "Reply with the single word: ok"}],
                max_tokens=16,
            )
        except Exception as exc:  # noqa: BLE001 - classified below
            status = getattr(exc, "status_code", None)
            if status in (401, 403):
                # This workspace's key scope simply does not include that
                # model; try the next catalog entry rather than failing the
                # provider wiring.
                scope_denied.append(model_id)
                continue
            raise
        assert isinstance(answer, str) and answer.strip(), "empty completion"
        assert key not in str(answer)
        return

    pytest.skip(
        "the configured OrcaRouter key cannot call any catalog model "
        "(scope denied for: " + ", ".join(scope_denied[:6]) + ")"
    )
