import time

from app.device_sessions import DeviceLoginManager
from app.oauth import AccountMetadata, DeviceAuthorization, OAuthTokens


class OAuth:
    def start(self): return DeviceAuthorization("secret-device", "ABCD-EFGH", 0, "https://auth.openai.com/codex/device")
    def poll(self, auth): return OAuthTokens("access", "refresh", "id", time.time() + 3600)


class Store:
    def save(self, tokens, **metadata): self.saved = metadata
    def clear(self): self.cleared = True
    def status(self): return {"authenticated": hasattr(self, "saved"), "email": "u***r@example.com", "plan": "pro"}


def test_device_login_exposes_only_safe_fields(monkeypatch):
    store = Store()
    monkeypatch.setattr("app.device_sessions.extract_account_metadata", lambda *_: AccountMetadata("acct", "user@example.com", "pro", None))
    manager = DeviceLoginManager(OAuth(), store)
    started = manager.start()
    for _ in range(50):
        result = manager.status(started["login_id"])
        if result["status"] == "authenticated": break
        time.sleep(.01)
    assert result["status"] == "authenticated"
    assert started["user_code"] == "ABCD-EFGH"
    assert "device_auth_id" not in str(started)
    assert "access" not in str(result)
