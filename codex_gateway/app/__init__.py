"""MiroFish Codex Gateway application factory."""

from __future__ import annotations

import atexit
import os
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from .config import GatewayConfig


def _default_codex_factory(config: "GatewayConfig"):
    from openai_codex import Codex, CodexConfig

    return Codex(
        config=CodexConfig(
            cwd="/workspace",
            env={
                "CODEX_HOME": config.codex_home,
                "CODEX_DISABLE_PROJECT_DOC": "1",
                "RUST_LOG": os.environ.get("RUST_LOG", "warn"),
            },
            config_overrides=(
                'approval_policy="never"',
                'sandbox_mode="read-only"',
                "mcp_servers={}",
            ),
        )
    )


def _default_openai_factory(**kwargs):
    from openai import OpenAI

    return OpenAI(**kwargs)


def create_app(
    *,
    config: "GatewayConfig | None" = None,
    codex_factory: Callable[["GatewayConfig"], Any] | None = None,
    openai_factory: Callable[..., Any] | None = None,
):
    from .api import create_app as create_http_app
    from .codex_provider import CodexProvider
    from .config import GatewayConfig
    from .deepseek_provider import DeepSeekProvider
    from .login import read_account_status
    from .router import CompletionRouter

    config = config or GatewayConfig.from_env()
    codex_factory = codex_factory or _default_codex_factory
    openai_factory = openai_factory or _default_openai_factory

    codex = codex_factory(config)
    fallback_client = openai_factory(
        api_key=config.fallback_api_key,
        base_url=config.fallback_base_url,
    )
    codex_provider = CodexProvider(
        codex=codex,
        model=config.codex_model,
        max_concurrency=config.max_concurrency,
        queue_size=config.queue_size,
        request_timeout_seconds=config.request_timeout_seconds,
    )
    fallback_provider = DeepSeekProvider(
        client=fallback_client,
        model=config.fallback_model,
    )
    router = CompletionRouter(codex=codex_provider, fallback=fallback_provider)
    app = create_http_app(
        router=router,
        config=config,
        account_reader=lambda: read_account_status(codex),
    )
    app.extensions["codex_runtime"] = codex

    close = getattr(codex, "close", None)
    if callable(close):
        atexit.register(close)
    return app
