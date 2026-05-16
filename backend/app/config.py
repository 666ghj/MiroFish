"""
Configuration management
Loads config uniformly from the .env file at the project root
"""

import os
from datetime import timedelta
from dotenv import load_dotenv

# Load the .env file from the project root
# Path: MiroFish/.env (relative to backend/app/config.py)
project_root_env = os.path.join(os.path.dirname(__file__), '../../.env')

if os.path.exists(project_root_env):
    load_dotenv(project_root_env, override=True)
else:
    # If no root-level .env file found, load from environment variables (production)
    load_dotenv(override=True)


class Config:
    """Flask configuration class"""

    # Flask settings
    SECRET_KEY = os.environ.get('SECRET_KEY', 'mirofish-secret-key')
    DEMO_PASSWORD = os.environ.get('DEMO_PASSWORD', '')
    DEBUG = os.environ.get('FLASK_DEBUG', 'True').lower() == 'true'

    # JSON settings - disable ASCII escaping so non-ASCII chars are output directly (not as \uXXXX)
    JSON_AS_ASCII = False

    # LLM settings (unified OpenAI-compatible format)
    LLM_API_KEY = os.environ.get('LLM_API_KEY')
    LLM_BASE_URL = os.environ.get('LLM_BASE_URL', 'https://api.openai.com/v1')
    LLM_MODEL_NAME = os.environ.get('LLM_MODEL_NAME', 'gpt-4o-mini')

    # Embedding LLM (used by Graphiti for vector indexing)
    # Falls back to LLM_* values if not set
    LLM_EMBED_API_KEY = os.environ.get('LLM_EMBED_API_KEY') or os.environ.get('LLM_API_KEY')
    LLM_EMBED_BASE_URL = os.environ.get('LLM_EMBED_BASE_URL') or os.environ.get('LLM_BASE_URL', 'https://api.openai.com/v1')
    LLM_EMBED_MODEL_NAME = os.environ.get('LLM_EMBED_MODEL_NAME', 'text-embedding-3-small')

    # Small/fast LLM (used by Graphiti for lightweight tasks like reranking)
    # Falls back to LLM_* values if not set
    LLM_SMALL_API_KEY = os.environ.get('LLM_SMALL_API_KEY') or os.environ.get('LLM_API_KEY')
    LLM_SMALL_BASE_URL = os.environ.get('LLM_SMALL_BASE_URL') or os.environ.get('LLM_BASE_URL', 'https://api.openai.com/v1')
    LLM_SMALL_MODEL_NAME = os.environ.get('LLM_SMALL_MODEL_NAME') or os.environ.get('LLM_MODEL_NAME', 'gpt-4o-mini')
    
    # Graph backend: "zep" (default, cloud) o "graphiti" (Neo4j local)
    GRAPH_BACKEND = os.environ.get('GRAPH_BACKEND', 'zep')

    # Zep Cloud
    ZEP_API_KEY = os.environ.get('ZEP_API_KEY')

    # Graphiti + Neo4j
    NEO4J_URI = os.environ.get('NEO4J_URI', 'bolt://localhost:7687')
    NEO4J_USER = os.environ.get('NEO4J_USER', 'neo4j')
    NEO4J_PASSWORD = os.environ.get('NEO4J_PASSWORD')
    GRAPHITI_BATCH_SIZE = int(os.environ.get('GRAPHITI_BATCH_SIZE', '10'))

    # LLM provider ("" = OpenAI-compatible per defecte, "gemini" = Google AI Studio)
    LLM_PROVIDER = os.environ.get('LLM_PROVIDER', '')

    # File upload settings
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB
    UPLOAD_FOLDER = os.environ.get(
        'UPLOAD_FOLDER',
        os.path.join(os.path.dirname(__file__), '../uploads')
    )
    ALLOWED_EXTENSIONS = {'pdf', 'md', 'txt', 'markdown'}
    
    # Text processing settings
    DEFAULT_CHUNK_SIZE = 500  # default chunk size
    DEFAULT_CHUNK_OVERLAP = 50  # default overlap size

    # Ontology generation limits
    ONTOLOGY_MAX_ENTITY_TYPES = int(os.environ.get('ONTOLOGY_MAX_ENTITY_TYPES', '12'))
    ONTOLOGY_MAX_EDGE_TYPES = int(os.environ.get('ONTOLOGY_MAX_EDGE_TYPES', '10'))

    # OASIS simulation settings
    OASIS_DEFAULT_MAX_ROUNDS = int(os.environ.get('OASIS_DEFAULT_MAX_ROUNDS', '10'))
    OASIS_SIMULATION_DATA_DIR = os.environ.get(
        'OASIS_SIMULATION_DATA_DIR',
        os.path.join(os.path.dirname(__file__), '../uploads/simulations')
    )
    
    # OASIS platform available actions
    OASIS_TWITTER_ACTIONS = [
        'CREATE_POST', 'LIKE_POST', 'REPOST', 'FOLLOW', 'DO_NOTHING', 'QUOTE_POST'
    ]
    OASIS_REDDIT_ACTIONS = [
        'LIKE_POST', 'DISLIKE_POST', 'CREATE_POST', 'CREATE_COMMENT',
        'LIKE_COMMENT', 'DISLIKE_COMMENT', 'SEARCH_POSTS', 'SEARCH_USER',
        'TREND', 'REFRESH', 'DO_NOTHING', 'FOLLOW', 'MUTE'
    ]
    
    # Report Agent settings
    REPORT_AGENT_MAX_TOOL_CALLS = int(os.environ.get('REPORT_AGENT_MAX_TOOL_CALLS', '5'))
    REPORT_AGENT_MAX_REFLECTION_ROUNDS = int(os.environ.get('REPORT_AGENT_MAX_REFLECTION_ROUNDS', '2'))
    REPORT_AGENT_TEMPERATURE = float(os.environ.get('REPORT_AGENT_TEMPERATURE', '0.5'))

    # ── Persistència ──────────────────────────────────────────────
    # Base de dades
    DATABASE_URL = os.environ.get('DATABASE_URL', 'sqlite:///mirofish_dev.db')

    # Storage de fitxers
    STORAGE_TYPE = os.environ.get('STORAGE_TYPE', 'local')          # local | azure
    STORAGE_LOCAL_PATH = os.environ.get(
        'STORAGE_LOCAL_PATH',
        os.path.join(os.path.dirname(__file__), '../uploads')
    )
    AZURE_STORAGE_CONNECTION_STRING = os.environ.get('AZURE_STORAGE_CONNECTION_STRING', '')
    AZURE_STORAGE_CONTAINER = os.environ.get('AZURE_STORAGE_CONTAINER', 'mirofish')

    # Auth JWT (flask-jwt-extended)
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', 'change-me-in-production')
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(
        seconds=int(os.environ.get('JWT_ACCESS_TOKEN_EXPIRES', '28800'))   # 8h
    )
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(
        seconds=int(os.environ.get('JWT_REFRESH_TOKEN_EXPIRES', '604800'))  # 7d
    )
    JWT_COOKIE_SECURE = os.environ.get('FLASK_DEBUG', 'True').lower() != 'true'
    JWT_COOKIE_CSRF_PROTECT = False
    JWT_REFRESH_COOKIE_PATH = '/api/auth/refresh'

    # Admin inicial (per init_system.py)
    ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', '')
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', '')

    # Azure Communication Services
    ACS_CONNECTION_STRING = os.environ.get('ACS_CONNECTION_STRING', '')
    ACS_SENDER_ADDRESS = os.environ.get('ACS_SENDER_ADDRESS', 'donotreply@mirofish.local')
    ACS_INVITATION_TTL_HOURS = int(os.environ.get('ACS_INVITATION_TTL_HOURS', '48'))
    ACS_RESET_PASSWORD_TTL_HOURS = int(os.environ.get('ACS_RESET_PASSWORD_TTL_HOURS', '1'))

    @classmethod
    def get_graph_config_errors(cls) -> list:
        errors = []
        if cls.GRAPH_BACKEND == 'zep':
            if not cls.ZEP_API_KEY:
                errors.append("ZEP_API_KEY is not configured (required when GRAPH_BACKEND=zep)")
        elif cls.GRAPH_BACKEND == 'graphiti':
            if not cls.NEO4J_PASSWORD:
                errors.append("NEO4J_PASSWORD is not configured (required when GRAPH_BACKEND=graphiti)")
        else:
            errors.append(f"Unknown GRAPH_BACKEND value: '{cls.GRAPH_BACKEND}'. Use 'zep' or 'graphiti'.")
        return errors

    @classmethod
    def validate(cls):
        """Validate required configuration"""
        errors = []
        if not cls.LLM_API_KEY:
            errors.append("LLM_API_KEY is not configured")
        errors.extend(cls.get_graph_config_errors())
        return errors

