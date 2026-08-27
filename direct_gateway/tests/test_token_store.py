import os
import time

from app.oauth import OAuthTokens
from app.token_store import TokenStore


def test_store_is_atomic_private_and_status_is_redacted(tmp_path):
    path = tmp_path / "auth" / "credentials.json"
    store = TokenStore(path)
    store.save(OAuthTokens("access-secret", "refresh-secret", "id-secret", time.time() + 3600), account_id="acct", email="person@example.com", plan="pro", residency="us")
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert oct(path.parent.stat().st_mode & 0o777) == "0o700"
    raw = path.read_text()
    assert "device_auth_id" not in raw and "authorization_code" not in raw and "code_verifier" not in raw
    assert store.status()["email"] == "p***n@example.com"
    assert "access_token" not in store.status()
    assert not list(path.parent.glob("*.tmp"))
    store.clear()
    assert not path.exists()
