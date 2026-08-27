from __future__ import annotations

import base64
import json
import threading
import time
from dataclasses import dataclass
from typing import Callable

import httpx

from .config import DirectConfig


@dataclass(frozen=True)
class DeviceAuthorization:
    device_auth_id: str
    user_code: str
    interval: float
    verification_uri: str = "https://auth.openai.com/codex/device"


@dataclass(frozen=True)
class OAuthTokens:
    access_token: str
    refresh_token: str
    id_token: str
    expires_at: float


@dataclass(frozen=True)
class AccountMetadata:
    account_id: str | None
    email: str | None
    plan: str | None
    residency: str | None
    trusted_for_authorization: bool = False


def _claims(token: str) -> dict:
    try:
        segment = token.split(".")[1]
        segment += "=" * (-len(segment) % 4)
        value = json.loads(base64.urlsafe_b64decode(segment))
        return value if isinstance(value, dict) else {}
    except (ValueError, IndexError, json.JSONDecodeError):
        return {}


def extract_account_metadata(id_token: str, access_token: str) -> AccountMetadata:
    claims = {**_claims(access_token), **_claims(id_token)}
    nested = claims.get("https://api.openai.com/auth")
    auth = nested if isinstance(nested, dict) else {}
    return AccountMetadata(
        account_id=auth.get("chatgpt_account_id") or claims.get("chatgpt_account_id"),
        email=claims.get("email"),
        plan=auth.get("chatgpt_plan_type") or claims.get("chatgpt_plan_type"),
        residency=auth.get("chatgpt_residency") or claims.get("chatgpt_residency"),
    )


class DeviceCodeClient:
    def __init__(self, *, config: DirectConfig | None = None, http: httpx.Client | None = None, sleep: Callable[[float], None] = time.sleep) -> None:
        self.config = config or DirectConfig()
        self.http = http or httpx.Client(timeout=30)
        self.sleep = sleep
        self._refresh_lock = threading.Lock()
        self._latest: OAuthTokens | None = None

    def start(self) -> DeviceAuthorization:
        response = self.http.post(self.config.issuer + self.config.device_start_path, json={"client_id": self.config.client_id})
        response.raise_for_status()
        data = response.json()
        return DeviceAuthorization(data["device_auth_id"], data["user_code"], float(data.get("interval", 5)))

    def poll(self, auth: DeviceAuthorization, timeout: float = 900) -> OAuthTokens:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            response = self.http.post(self.config.issuer + self.config.device_poll_path, json={"device_auth_id": auth.device_auth_id, "user_code": auth.user_code})
            if response.status_code in {403, 404}:
                self.sleep(auth.interval + 3)
                continue
            response.raise_for_status()
            data = response.json()
            return self._exchange(data["authorization_code"], data["code_verifier"])
        raise TimeoutError("device authorization timed out")

    def _exchange(self, authorization_code: str, code_verifier: str) -> OAuthTokens:
        response = self.http.post(self.config.issuer + self.config.token_path, data={"grant_type": "authorization_code", "code": authorization_code, "redirect_uri": self.config.redirect_uri, "client_id": self.config.client_id, "code_verifier": code_verifier})
        response.raise_for_status()
        return self._parse_tokens(response.json(), "")

    def refresh(self, refresh_token: str) -> OAuthTokens:
        response = self.http.post(self.config.issuer + self.config.token_path, data={"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": self.config.client_id})
        response.raise_for_status()
        return self._parse_tokens(response.json(), refresh_token)

    def ensure_fresh(self, tokens: OAuthTokens) -> OAuthTokens:
        if tokens.expires_at > time.time() + 60:
            return tokens
        with self._refresh_lock:
            if self._latest is not None and self._latest.expires_at > time.time() + 60:
                return self._latest
            self._latest = self.refresh(tokens.refresh_token)
            return self._latest

    @staticmethod
    def _parse_tokens(data: dict, old_refresh: str) -> OAuthTokens:
        return OAuthTokens(data["access_token"], data.get("refresh_token") or old_refresh, data.get("id_token", ""), time.time() + float(data.get("expires_in", 3600)))
