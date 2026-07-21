"""
Pytest configuration and shared fixtures for backend tests.

This module provides fixtures that allow testing of modules that normally
require Flask initialization, by mocking the necessary dependencies.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(scope="session", autouse=True)
def mock_external_dependencies():
    """
    Mock external dependencies (Flask, OpenAI, Zep) to allow testing
    without initializing the full Flask app or requiring API keys.
    """
    mock_logger = MagicMock()
    mock_locale = MagicMock()
    mock_locale.get_locale.return_value = 'zh'
    mock_locale.set_locale.return_value = None
    mock_locale.get_language_instruction.return_value = 'Please answer in English.'
    mock_locale.t.return_value = 'test'

    mock_config = MagicMock()
    mock_config.LLM_API_KEY = None
    mock_config.LLM_BASE_URL = None
    mock_config.LLM_MODEL_NAME = None
    mock_config.ZEP_API_KEY = None

    # Clear any previously imported app modules
    for mod_name in list(sys.modules.keys()):
        if mod_name.startswith('app.'):
            del sys.modules[mod_name]

    with patch.dict('sys.modules', {
        'flask': MagicMock(),
        'flask_cors': MagicMock(),
        'openai': MagicMock(),
        'zep_cloud': MagicMock(),
        'zep_cloud.client': MagicMock(),
        'app': MagicMock(),
        'app.config': mock_config,
        'app.utils': MagicMock(),
        'app.utils.logger': mock_logger,
        'app.utils.locale': mock_locale,
        'app.services.zep_entity_reader': MagicMock(),
    }):
        yield