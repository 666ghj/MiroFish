from app.config import GatewayConfig


def test_config_requires_all_runtime_credentials():
    try:
        GatewayConfig.from_mapping({})
    except ValueError as error:
        message = str(error)
        assert "CODEX_GATEWAY_TOKEN" in message
        assert "FALLBACK_LLM_API_KEY" in message
    else:
        raise AssertionError("missing credentials should fail startup")


def test_config_parses_bounded_concurrency_values():
    config = GatewayConfig.from_mapping(
        {
            "CODEX_GATEWAY_TOKEN": "internal",
            "CODEX_MODEL": "gpt-5.6-terra",
            "FALLBACK_LLM_API_KEY": "fallback",
            "FALLBACK_LLM_BASE_URL": "https://api.deepseek.com",
            "FALLBACK_LLM_MODEL": "deepseek-v4-flash",
            "CODEX_MAX_CONCURRENCY": "1",
            "CODEX_QUEUE_SIZE": "20",
            "CODEX_REQUEST_TIMEOUT_SECONDS": "300",
            "CODEX_HOME": "/var/lib/codex",
        }
    )
    assert config.max_concurrency == 1
    assert config.queue_size == 20
