from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlparse


@dataclass(frozen=True)
class DirectConfig:
    internal_token: str = ""
    client_id: str = "app_EMoamEEZ73f0CkXaXp7hrann"
    issuer: str = "https://auth.openai.com"
    device_start_path: str = "/api/accounts/deviceauth/usercode"
    device_poll_path: str = "/api/accounts/deviceauth/token"
    token_path: str = "/oauth/token"
    redirect_uri: str = "https://auth.openai.com/deviceauth/callback"
    codex_endpoint: str = "https://chatgpt.com/backend-api/codex/responses"
    model: str = "gpt-5.6-luna"
    credentials_path: str = "/var/lib/direct-oauth/credentials.json"
    request_timeout_seconds: int = 600

    @classmethod
    def from_mapping(cls, values: Mapping[str, str]) -> "DirectConfig":
        config = cls(
            internal_token=values.get("DIRECT_GATEWAY_TOKEN", ""),
            client_id=values.get("DIRECT_OAUTH_CLIENT_ID", cls.client_id),
            issuer=values.get("DIRECT_OAUTH_ISSUER", cls.issuer),
            device_start_path=values.get("DIRECT_OAUTH_DEVICE_START_PATH", cls.device_start_path),
            device_poll_path=values.get("DIRECT_OAUTH_DEVICE_POLL_PATH", cls.device_poll_path),
            token_path=values.get("DIRECT_OAUTH_TOKEN_PATH", cls.token_path),
            redirect_uri=values.get("DIRECT_OAUTH_REDIRECT_URI", cls.redirect_uri),
            codex_endpoint=values.get("DIRECT_CODEX_ENDPOINT", cls.codex_endpoint),
            model=values.get("DIRECT_CODEX_MODEL", cls.model),
            credentials_path=values.get("DIRECT_OAUTH_CREDENTIALS_PATH", cls.credentials_path),
            request_timeout_seconds=int(values.get("DIRECT_REQUEST_TIMEOUT_SECONDS", "600")),
        )
        allow_http = values.get("DIRECT_ALLOW_HTTP_FOR_TESTS") == "1"
        for url in (config.issuer, config.redirect_uri, config.codex_endpoint):
            parsed = urlparse(url)
            if parsed.scheme != "https" and not (allow_http and parsed.hostname in {"localhost", "127.0.0.1"}):
                raise ValueError("Direct OAuth endpoints must use HTTPS")
        return config

    @classmethod
    def from_env(cls) -> "DirectConfig":
        return cls.from_mapping(os.environ)
