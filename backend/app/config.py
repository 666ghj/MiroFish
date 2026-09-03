"""
Configuration.

Every setting is loaded from the .env file at the repository root.
"""

import os
from dotenv import load_dotenv

# The .env at the repository root, resolved from backend/app/config.py.
project_root_env = os.path.join(os.path.dirname(__file__), '../../.env')

if os.path.exists(project_root_env):
    load_dotenv(project_root_env, override=True)
else:
    # No .env at the root, so fall back to the ambient environment. This is the
    # normal case in production.
    load_dotenv(override=True)


class Config:
    """Flask configuration."""

    # Flask
    SECRET_KEY = os.environ.get('SECRET_KEY', 'sosim-secret-key')
    DEBUG = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'

    # JSON - keep responses as UTF-8 instead of escaping non-ASCII characters.
    JSON_AS_ASCII = False

    # LLM (always addressed through the OpenAI-compatible API)
    LLM_API_KEY = os.environ.get('LLM_API_KEY')
    LLM_BASE_URL = os.environ.get('LLM_BASE_URL', 'https://api.openai.com/v1')
    LLM_MODEL_NAME = os.environ.get('LLM_MODEL_NAME', 'gpt-4o-mini')

    # Zep
    ZEP_API_KEY = os.environ.get('ZEP_API_KEY')
    # UXE fork: empty => Zep Cloud. Set to the local Graphiti-backed shim, e.g.
    # http://127.0.0.1:8088/api/v2 — see third_party/graphiti/server/graph_service/zep_compat.
    ZEP_BASE_URL = os.environ.get('ZEP_BASE_URL')

    # File uploads
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), '../uploads')
    ALLOWED_EXTENSIONS = {'pdf', 'md', 'txt', 'markdown'}

    # Text processing
    DEFAULT_CHUNK_SIZE = 500  # Default chunk size, in characters
    DEFAULT_CHUNK_OVERLAP = 50  # Default overlap between chunks, in characters

    # OASIS simulation
    OASIS_DEFAULT_MAX_ROUNDS = int(os.environ.get('OASIS_DEFAULT_MAX_ROUNDS', '10'))
    OASIS_SIMULATION_DATA_DIR = os.path.join(os.path.dirname(__file__), '../uploads/simulations')

    # Actions each OASIS platform makes available
    OASIS_TWITTER_ACTIONS = [
        'CREATE_POST', 'LIKE_POST', 'REPOST', 'FOLLOW', 'DO_NOTHING', 'QUOTE_POST'
    ]
    OASIS_REDDIT_ACTIONS = [
        'LIKE_POST', 'DISLIKE_POST', 'CREATE_POST', 'CREATE_COMMENT',
        'LIKE_COMMENT', 'DISLIKE_COMMENT', 'SEARCH_POSTS', 'SEARCH_USER',
        'TREND', 'REFRESH', 'DO_NOTHING', 'FOLLOW', 'MUTE'
    ]

    # Report agent
    REPORT_AGENT_MAX_TOOL_CALLS = int(os.environ.get('REPORT_AGENT_MAX_TOOL_CALLS', '5'))
    REPORT_AGENT_MAX_REFLECTION_ROUNDS = int(os.environ.get('REPORT_AGENT_MAX_REFLECTION_ROUNDS', '2'))
    REPORT_AGENT_TEMPERATURE = float(os.environ.get('REPORT_AGENT_TEMPERATURE', '0.5'))

    @classmethod
    def validate(cls) -> list[str]:
        """Return one message per missing or unusable required setting."""
        errors: list[str] = []
        if not cls.LLM_API_KEY:
            errors.append("LLM_API_KEY is not configured.")
        if not cls.ZEP_API_KEY:
            # Still required when ZEP_BASE_URL points at the local shim: the SDK
            # refuses to construct without a key. Any non-empty value works there.
            errors.append("ZEP_API_KEY is not configured.")
        if os.environ.get("ZEP_API_URL"):
            errors.append(
                "ZEP_API_URL is not supported. Use ZEP_BASE_URL to point at the "
                "local Zep-compatible service."
            )
        if cls.DEBUG:
            import warnings
            warnings.warn("Flask DEBUG mode is enabled. Do not use in production.", RuntimeWarning)
        return errors
