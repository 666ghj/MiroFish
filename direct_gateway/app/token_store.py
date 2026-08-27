from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .oauth import OAuthTokens


class TokenStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def save(self, tokens: OAuthTokens, *, account_id: str | None, email: str | None, plan: str | None, residency: str | None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.path.parent, 0o700)
        payload = {**tokens.__dict__, "account_id": account_id, "email": email, "plan": plan, "residency": residency}
        descriptor, temporary = tempfile.mkstemp(prefix="credentials-", suffix=".tmp", dir=self.path.parent)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w") as handle:
                json.dump(payload, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def load(self) -> tuple[OAuthTokens, dict]:
        data = json.loads(self.path.read_text())
        tokens = OAuthTokens(data["access_token"], data["refresh_token"], data.get("id_token", ""), data["expires_at"])
        return tokens, {key: data.get(key) for key in ("account_id", "email", "plan", "residency")}

    def status(self) -> dict:
        if not self.path.exists():
            return {"authenticated": False}
        tokens, metadata = self.load()
        email = metadata.get("email")
        if email and "@" in email:
            local, domain = email.split("@", 1)
            email = (local[0] + "***" + local[-1] if len(local) > 1 else "***") + "@" + domain
        return {"authenticated": True, "email": email, "plan": metadata.get("plan"), "expires_at": tokens.expires_at}

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
