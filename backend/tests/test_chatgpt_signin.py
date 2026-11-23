import time
from urllib.parse import parse_qs, urlparse

import pytest

from app.services import chatgpt_signin as signin
from app.services import chatgpt_compat


def test_oauth_registration_checks_state_nonce_and_scopes(monkeypatch, tmp_path):
    path = tmp_path / "session.dat"
    monkeypatch.setattr(signin, "_store_path", lambda: path)
    monkeypatch.setattr(signin, "_dpapi", lambda data, protect: data)
    monkeypatch.setattr(signin, "_pending", None)
    monkeypatch.setattr(signin, "_active", False)
    url = signin.start()
    query = parse_qs(urlparse(url).query)
    assert query["client_id"] == ["dynamic_agent_client"]
    assert query["ext_agent_host_id"][0].startswith("urn:uuid:")
    assert query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == ["http://127.0.0.1:5001/api/provider/auth/callback"]
    state = query["state"][0]

    monkeypatch.setattr(signin, "_token_request", lambda _: {
        "id_token": "signed-id", "access_token": "access", "refresh_token": "refresh",
        "scope": signin.SCOPES, "expires_in": 3600,
    })
    monkeypatch.setattr(signin, "_validate_id_token", lambda token, client_id, nonce: {"sub": "subject", "email": "test@example.com"})
    with pytest.raises(ValueError, match="no coincide"):
        signin.finish({"state": "wrong", "code": "code", "client_id": "oaiapp_test"})
    assert not signin.status()["saved_account"]

    signin.start()
    state = signin._pending["state"]
    result = signin.finish({"state": state, "code": "code", "client_id": "oaiapp_test"})
    assert result["saved_account"] is True
    assert result["connected"] is False
    assert result["account_key"]
    assert "access_token" not in result


def test_oauth_reauthorization_rejects_account_switch(monkeypatch, tmp_path):
    monkeypatch.setattr(signin, "_store_path", lambda: tmp_path / "session.dat")
    monkeypatch.setattr(signin, "_dpapi", lambda data, protect: data)
    state = {"host_id": "urn:uuid:host", "selected": "first", "accounts": [{
        "key": "first", "client_id": "oaiapp_first", "subject": "subject-one",
        "email": "one@example.com", "id_token": "prior", "refresh_token": "refresh",
        "access_token": "access", "scopes": signin.SCOPES.split(), "expires_at": time.time() + 3600,
    }]}
    signin._save(state)
    url = signin.start(account_key="first")
    assert parse_qs(urlparse(url).query)["client_id"] == ["oaiapp_first"]
    monkeypatch.setattr(signin, "_token_request", lambda _: {
        "id_token": "signed-id", "access_token": "new", "refresh_token": "new-refresh",
        "scope": signin.SCOPES, "expires_in": 3600,
    })
    monkeypatch.setattr(signin, "_validate_id_token", lambda token, client_id, nonce: {"sub": "subject-two"})
    with pytest.raises(ValueError, match="no coincide"):
        signin.finish({"state": signin._pending["state"], "code": "code"})
    assert signin._load()["accounts"][0]["refresh_token"] == "refresh"


def test_responses_adapter_preserves_native_function_call_and_required_contract(monkeypatch):
    body = {
        "model": "gpt-6-luna", "messages": [{"role": "system", "content": "Choose an action"}, {"role": "user", "content": "Post"}],
        "tools": [{"type": "function", "function": {"name": "create_post", "parameters": {"type": "object", "properties": {"text": {"type": "string"}}}}}],
        "tool_choice": "required", "temperature": 0.8,
    }
    payload = chatgpt_compat._payload(body)
    assert payload["store"] is False and payload["stream"] is True
    assert payload["input"][0]["role"] == "developer"
    assert "temperature" not in payload
    assert payload["tools"][0]["type"] == "namespace"
    response = {"output": [{"type": "function_call", "call_id": "call_1", "name": "mirofish.create_post", "arguments": '{"text":"hello"}'}]}
    result = chatgpt_compat._chat_completion(response, "gpt-6-luna")
    assert result["choices"][0]["finish_reason"] == "tool_calls"
    assert result["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "create_post"


def test_activation_requires_completed_inference_before_switch(monkeypatch, tmp_path):
    monkeypatch.setattr(signin, "_store_path", lambda: tmp_path / "session.dat")
    monkeypatch.setattr(signin, "_dpapi", lambda data, protect: data)
    monkeypatch.setattr(signin, "_active", False)
    signin._save({"host_id": "urn:uuid:host", "selected": "first", "accounts": [{
        "key": "first", "client_id": "oaiapp_first", "subject": "subject",
        "refresh_token": "refresh", "access_token": "access",
        "scopes": signin.SCOPES.split(), "expires_at": time.time() + 3600,
    }]})
    monkeypatch.setattr(signin, "list_models", lambda: [{"slug": "gpt-6-luna"}])
    calls = []
    monkeypatch.setattr(signin.local_codex_provider, "_set_llm", lambda *args: calls.append("switch"))
    monkeypatch.setattr(signin.local_codex_provider, "deactivate", lambda: None)
    monkeypatch.setattr(chatgpt_compat, "complete", lambda body: (_ for _ in ()).throw(RuntimeError("incomplete")))
    with pytest.raises(RuntimeError, match="incomplete"):
        signin.activate("gpt-6-luna")
    assert calls == []
    assert signin.status()["connected"] is False
    monkeypatch.setattr(chatgpt_compat, "complete", lambda body: calls.append("verified"))
    signin.activate("gpt-6-luna")
    assert calls == ["verified", "switch"]
