"""Validated environment configuration for the Codex Gateway."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class GatewayConfig:
    internal_token: str
    codex_model: str
    fallback_api_key: str
    fallback_base_url: str
    fallback_model: str
    max_concurrency: int
    queue_size: int
    request_timeout_seconds: int
    codex_home: str

    @classmethod
    def from_mapping(cls, values: Mapping[str, str]) -> "GatewayConfig":
        required = {
            "CODEX_GATEWAY_TOKEN": values.get("CODEX_GATEWAY_TOKEN", ""),
            "CODEX_MODEL": values.get("CODEX_MODEL", ""),
            "FALLBACK_LLM_API_KEY": values.get("FALLBACK_LLM_API_KEY", ""),
            "FALLBACK_LLM_BASE_URL": values.get("FALLBACK_LLM_BASE_URL", ""),
            "FALLBACK_LLM_MODEL": values.get("FALLBACK_LLM_MODEL", ""),
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError("missing gateway configuration: " + ", ".join(missing))

        max_concurrency = int(values.get("CODEX_MAX_CONCURRENCY", "1"))
        queue_size = int(values.get("CODEX_QUEUE_SIZE", "20"))
        timeout = int(values.get("CODEX_REQUEST_TIMEOUT_SECONDS", "300"))
        if max_concurrency <= 0 or max_concurrency > 4:
            raise ValueError("CODEX_MAX_CONCURRENCY must be between 1 and 4")
        if queue_size < 0:
            raise ValueError("CODEX_QUEUE_SIZE must be at least 0")
        if timeout <= 0:
            raise ValueError("CODEX_REQUEST_TIMEOUT_SECONDS must be greater than 0")

        return cls(
            internal_token=required["CODEX_GATEWAY_TOKEN"],
            codex_model=required["CODEX_MODEL"],
            fallback_api_key=required["FALLBACK_LLM_API_KEY"],
            fallback_base_url=required["FALLBACK_LLM_BASE_URL"],
            fallback_model=required["FALLBACK_LLM_MODEL"],
            max_concurrency=max_concurrency,
            queue_size=queue_size,
            request_timeout_seconds=timeout,
            codex_home=values.get("CODEX_HOME", "/var/lib/codex"),
        )

    @classmethod
    def from_env(cls) -> "GatewayConfig":
        return cls.from_mapping(os.environ)
