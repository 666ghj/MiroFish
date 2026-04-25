import pytest
from unittest.mock import patch, MagicMock

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


def test_gemini_provider_sets_base_url_automatically():
    import backend.app.config as cfg
    orig_provider = cfg.Config.LLM_PROVIDER
    orig_key = cfg.Config.LLM_API_KEY
    orig_url = cfg.Config.LLM_BASE_URL
    try:
        cfg.Config.LLM_PROVIDER = "gemini"
        cfg.Config.LLM_API_KEY = "AIzatest"
        cfg.Config.LLM_BASE_URL = "https://api.openai.com/v1"

        with patch("backend.app.utils.llm_client.OpenAI") as mock_openai:
            mock_openai.return_value = MagicMock()
            import importlib
            import backend.app.utils.llm_client as lm
            importlib.reload(lm)
            client = lm.LLMClient()
            assert GEMINI_URL in client.base_url
    finally:
        cfg.Config.LLM_PROVIDER = orig_provider
        cfg.Config.LLM_API_KEY = orig_key
        cfg.Config.LLM_BASE_URL = orig_url


def test_non_gemini_provider_uses_configured_url():
    import backend.app.config as cfg
    orig_provider = cfg.Config.LLM_PROVIDER
    orig_key = cfg.Config.LLM_API_KEY
    orig_url = cfg.Config.LLM_BASE_URL
    try:
        cfg.Config.LLM_PROVIDER = ""
        cfg.Config.LLM_API_KEY = "sk-test"
        cfg.Config.LLM_BASE_URL = "https://api.openai.com/v1"

        with patch("backend.app.utils.llm_client.OpenAI") as mock_openai:
            mock_openai.return_value = MagicMock()
            import importlib
            import backend.app.utils.llm_client as lm
            importlib.reload(lm)
            client = lm.LLMClient()
            assert "openai.com" in client.base_url
    finally:
        cfg.Config.LLM_PROVIDER = orig_provider
        cfg.Config.LLM_API_KEY = orig_key
        cfg.Config.LLM_BASE_URL = orig_url


def test_explicit_base_url_overrides_gemini_auto():
    """If base_url is passed explicitly, it should NOT be replaced even if LLM_PROVIDER=gemini."""
    import backend.app.config as cfg
    orig_provider = cfg.Config.LLM_PROVIDER
    orig_key = cfg.Config.LLM_API_KEY
    try:
        cfg.Config.LLM_PROVIDER = "gemini"
        cfg.Config.LLM_API_KEY = "AIzatest"

        with patch("backend.app.utils.llm_client.OpenAI") as mock_openai:
            mock_openai.return_value = MagicMock()
            import importlib
            import backend.app.utils.llm_client as lm
            importlib.reload(lm)
            client = lm.LLMClient(base_url="https://custom.endpoint/v1")
            assert "custom.endpoint" in client.base_url
            assert GEMINI_URL not in client.base_url
    finally:
        cfg.Config.LLM_PROVIDER = orig_provider
        cfg.Config.LLM_API_KEY = orig_key
