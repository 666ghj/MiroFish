import base64
import json
import threading
import time

import httpx

from app.oauth import DeviceAuthorization, DeviceCodeClient, OAuthTokens, extract_account_metadata


def _jwt(payload):
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"x.{encoded}.x"


def test_device_flow_pending_then_exchanges_code():
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("usercode"):
            return httpx.Response(200, json={"device_auth_id": "device-secret", "user_code": "ABCD-EFGH", "interval": 0})
        if request.url.path.endswith("/deviceauth/token"):
            polls = sum(r.url.path.endswith("/deviceauth/token") for r in requests)
            if polls == 1:
                return httpx.Response(403)
            return httpx.Response(200, json={"authorization_code": "auth-secret", "code_verifier": "verifier-secret"})
        return httpx.Response(200, json={"access_token": "access-secret", "refresh_token": "refresh-secret", "id_token": _jwt({"email": "u@example.com"}), "expires_in": 3600})

    client = DeviceCodeClient(http=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _: None)
    auth = client.start()
    tokens = client.poll(auth)
    exchange = requests[-1]
    assert tokens.refresh_token == "refresh-secret"
    assert exchange.url.path == "/oauth/token"
    assert exchange.read().decode().find("grant_type=authorization_code&code=auth-secret") >= 0
    assert exchange.read().decode().find("code_verifier=verifier-secret") >= 0


def test_refresh_is_single_flight_and_preserves_refresh_token():
    calls = 0
    lock = threading.Lock()

    def handler(request):
        nonlocal calls
        with lock:
            calls += 1
        time.sleep(0.02)
        return httpx.Response(200, json={"access_token": "new-access", "expires_in": 3600})

    client = DeviceCodeClient(http=httpx.Client(transport=httpx.MockTransport(handler)))
    old = OAuthTokens("old", "old-refresh", "id", time.time() - 1)
    results = []
    threads = [threading.Thread(target=lambda: results.append(client.ensure_fresh(old))) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert calls == 1
    assert all(item.refresh_token == "old-refresh" for item in results)


def test_extracts_metadata_without_treating_claims_as_authorization():
    metadata = extract_account_metadata(
        _jwt({"email": "user@example.com", "https://api.openai.com/auth": {"chatgpt_account_id": "acct", "chatgpt_plan_type": "pro", "chatgpt_residency": "us"}}),
        _jwt({}),
    )
    assert metadata.account_id == "acct"
    assert metadata.email == "user@example.com"
    assert metadata.plan == "pro"
    assert metadata.trusted_for_authorization is False
