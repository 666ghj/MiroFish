"""
配置管理
统一从项目根目录的 .env 文件加载配置
"""

import os
from dotenv import load_dotenv

# 加载项目根目录的 .env 文件
# 路径: MiroFish/.env (相对于 backend/app/config.py)
project_root_env = os.path.join(os.path.dirname(__file__), '../../.env')

if os.path.exists(project_root_env):
    load_dotenv(project_root_env, override=True)
else:
    # 如果根目录没有 .env，尝试加载环境变量（用于生产环境）
    load_dotenv(override=True)


class Config:
    """Flask配置类"""
    
    # Flask配置
    SECRET_KEY = os.environ.get('SECRET_KEY', 'mirofish-secret-key')
    DEBUG = os.environ.get('FLASK_DEBUG', 'True').lower() == 'true'
    
    # JSON配置 - 禁用ASCII转义，让中文直接显示（而不是 \uXXXX 格式）
    JSON_AS_ASCII = False
    
    # LLM配置（统一使用OpenAI格式）
    LLM_API_KEY = os.environ.get('LLM_API_KEY')
    LLM_BASE_URL = os.environ.get('LLM_BASE_URL', 'https://api.openai.com/v1')
    LLM_MODEL_NAME = os.environ.get('LLM_MODEL_NAME', 'gpt-4o-mini')
    
    # Zep配置
    ZEP_MODE = os.environ.get('ZEP_MODE', 'cloud').lower()
    ZEP_API_KEY = os.environ.get('ZEP_API_KEY')
    ZEP_BASE_URL = os.environ.get('ZEP_BASE_URL')
    OPENZEP_EMBEDDER_API_KEY = os.environ.get('OPENZEP_EMBEDDER_API_KEY') or None
    OPENZEP_EMBEDDER_BASE_URL = os.environ.get('OPENZEP_EMBEDDER_BASE_URL') or None
    OPENZEP_EMBEDDER_MODEL = os.environ.get('OPENZEP_EMBEDDER_MODEL') or None

    # 图后端配置
    GRAPH_BACKEND = os.environ.get('GRAPH_BACKEND', 'graphiti').lower()
    GRAPH_SEARCH_RERANKER = os.environ.get('GRAPH_SEARCH_RERANKER', 'rrf').strip() or None
    GRAPH_SEARCH_APP_RERANKER = (os.environ.get('GRAPH_SEARCH_APP_RERANKER', 'embedding_rrf').strip().lower() or 'embedding_rrf')
    GRAPH_SEARCH_APP_RERANK_FUSION_K = max(1, int(os.environ.get('GRAPH_SEARCH_APP_RERANK_FUSION_K', '60')))
    GRAPH_SEARCH_APP_SEMANTIC_WEIGHT = max(0.0, float(os.environ.get('GRAPH_SEARCH_APP_SEMANTIC_WEIGHT', '2.0')))
    GRAPH_SEARCH_APP_EMBEDDER_API_KEY = os.environ.get('GRAPH_SEARCH_APP_EMBEDDER_API_KEY') or None
    GRAPH_SEARCH_APP_EMBEDDER_BASE_URL = os.environ.get('GRAPH_SEARCH_APP_EMBEDDER_BASE_URL') or None
    GRAPH_SEARCH_APP_EMBEDDER_MODEL = os.environ.get('GRAPH_SEARCH_APP_EMBEDDER_MODEL') or None
    GRAPH_SEARCH_APP_EMBED_BATCH_SIZE = max(1, int(os.environ.get('GRAPH_SEARCH_APP_EMBED_BATCH_SIZE', '32')))
    GRAPH_SEARCH_APP_RERANKER_API_KEY = os.environ.get('GRAPH_SEARCH_APP_RERANKER_API_KEY') or None
    GRAPH_SEARCH_APP_RERANKER_BASE_URL = os.environ.get('GRAPH_SEARCH_APP_RERANKER_BASE_URL') or None
    GRAPH_SEARCH_APP_RERANKER_MODEL = os.environ.get('GRAPH_SEARCH_APP_RERANKER_MODEL') or None
    GRAPH_SEARCH_APP_RERANKER_PROVIDER = (os.environ.get('GRAPH_SEARCH_APP_RERANKER_PROVIDER', 'auto').strip().lower() or 'auto')
    GRAPH_SEARCH_APP_RERANKER_TIMEOUT = max(1.0, float(os.environ.get('GRAPH_SEARCH_APP_RERANKER_TIMEOUT', '20')))
    GRAPH_SEARCH_INCLUDE_NODES = os.environ.get('GRAPH_SEARCH_INCLUDE_NODES', 'true').lower() == 'true'
    GRAPH_SEARCH_EDGE_LIMIT_MULTIPLIER = max(1, int(os.environ.get('GRAPH_SEARCH_EDGE_LIMIT_MULTIPLIER', '2')))
    GRAPH_SEARCH_NODE_LIMIT_MULTIPLIER = max(1, int(os.environ.get('GRAPH_SEARCH_NODE_LIMIT_MULTIPLIER', '1')))
    GRAPH_SEARCH_NODE_SUMMARY_LIMIT = max(1, int(os.environ.get('GRAPH_SEARCH_NODE_SUMMARY_LIMIT', '5')))
    GRAPH_SEARCH_EXPAND_EDGES_FROM_NODES = os.environ.get('GRAPH_SEARCH_EXPAND_EDGES_FROM_NODES', 'true').lower() == 'true'
    GRAPH_SEARCH_NODE_EDGE_EXPANSION_LIMIT = max(0, int(os.environ.get('GRAPH_SEARCH_NODE_EDGE_EXPANSION_LIMIT', '2')))
    GRAPH_SEARCH_NODE_EDGE_PER_NODE_LIMIT = max(1, int(os.environ.get('GRAPH_SEARCH_NODE_EDGE_PER_NODE_LIMIT', '8')))
    GRAPHITI_URI = os.environ.get('GRAPHITI_URI')
    GRAPHITI_USER = os.environ.get('GRAPHITI_USER', 'neo4j')
    GRAPHITI_PASSWORD = os.environ.get('GRAPHITI_PASSWORD')
    GRAPHITI_DATABASE = os.environ.get('GRAPHITI_DATABASE', 'neo4j')
    GRAPHITI_LLM_API_KEY = os.environ.get('GRAPHITI_LLM_API_KEY') or LLM_API_KEY
    GRAPHITI_LLM_BASE_URL = os.environ.get('GRAPHITI_LLM_BASE_URL') or LLM_BASE_URL
    GRAPHITI_LLM_MODEL = os.environ.get('GRAPHITI_LLM_MODEL') or LLM_MODEL_NAME
    GRAPHITI_LLM_SMALL_MODEL = os.environ.get('GRAPHITI_LLM_SMALL_MODEL') or GRAPHITI_LLM_MODEL
    GRAPHITI_LLM_CLIENT_MODE = os.environ.get('GRAPHITI_LLM_CLIENT_MODE', 'openai').lower()
    GRAPHITI_LLM_MAX_TOKENS = max(1024, int(os.environ.get('GRAPHITI_LLM_MAX_TOKENS', '16384')))
    GRAPHITI_EMBEDDER_API_KEY = os.environ.get('GRAPHITI_EMBEDDER_API_KEY') or GRAPHITI_LLM_API_KEY
    GRAPHITI_EMBEDDER_BASE_URL = os.environ.get('GRAPHITI_EMBEDDER_BASE_URL') or GRAPHITI_LLM_BASE_URL
    GRAPHITI_EMBEDDER_MODEL = os.environ.get('GRAPHITI_EMBEDDER_MODEL', 'qwen3-embedding:8b')
    GRAPHITI_EMBEDDER_DIM = max(128, int(os.environ.get('GRAPHITI_EMBEDDER_DIM', '1024')))
    GRAPHITI_RERANKER_API_KEY = os.environ.get('GRAPHITI_RERANKER_API_KEY') or GRAPHITI_LLM_API_KEY
    GRAPHITI_RERANKER_BASE_URL = os.environ.get('GRAPHITI_RERANKER_BASE_URL') or GRAPHITI_LLM_BASE_URL
    GRAPHITI_RERANKER_MODEL = os.environ.get('GRAPHITI_RERANKER_MODEL') or GRAPHITI_LLM_MODEL
    GRAPHITI_ENABLE_CROSS_ENCODER = os.environ.get('GRAPHITI_ENABLE_CROSS_ENCODER', 'false').lower() == 'true'
    GRAPHITI_MAX_COROUTINES = max(1, int(os.environ.get('GRAPHITI_MAX_COROUTINES', '20')))
    
    # 文件上传配置
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), '../uploads')
    ALLOWED_EXTENSIONS = {'pdf', 'md', 'txt', 'markdown'}
    
    # 文本处理配置
    DEFAULT_CHUNK_SIZE = 500  # 默认切块大小
    DEFAULT_CHUNK_OVERLAP = 50  # 默认重叠大小
    
    # OASIS模拟配置
    OASIS_DEFAULT_MAX_ROUNDS = int(os.environ.get('OASIS_DEFAULT_MAX_ROUNDS', '10'))
    OASIS_SIMULATION_DATA_DIR = os.path.join(os.path.dirname(__file__), '../uploads/simulations')
    
    # OASIS平台可用动作配置
    OASIS_TWITTER_ACTIONS = [
        'CREATE_POST', 'LIKE_POST', 'REPOST', 'FOLLOW', 'DO_NOTHING', 'QUOTE_POST'
    ]
    OASIS_REDDIT_ACTIONS = [
        'LIKE_POST', 'DISLIKE_POST', 'CREATE_POST', 'CREATE_COMMENT',
        'LIKE_COMMENT', 'DISLIKE_COMMENT', 'SEARCH_POSTS', 'SEARCH_USER',
        'TREND', 'REFRESH', 'DO_NOTHING', 'FOLLOW', 'MUTE'
    ]
    
    # Report Agent配置
    REPORT_AGENT_MAX_TOOL_CALLS = int(os.environ.get('REPORT_AGENT_MAX_TOOL_CALLS', '5'))
    REPORT_AGENT_MAX_REFLECTION_ROUNDS = int(os.environ.get('REPORT_AGENT_MAX_REFLECTION_ROUNDS', '2'))
    REPORT_AGENT_TEMPERATURE = float(os.environ.get('REPORT_AGENT_TEMPERATURE', '0.5'))

    @classmethod
    def use_openzep(cls):
        """是否启用 OpenZep / 自定义 Zep endpoint。"""
        return cls.ZEP_MODE == 'openzep' or bool(cls.ZEP_BASE_URL)

    @classmethod
    def is_zep_configured(cls, api_key=None):
        """检查 Zep/OpenZep 是否已完成最小配置。"""
        resolved_api_key = cls.ZEP_API_KEY if api_key is None else api_key

        if cls.use_openzep():
            return bool(cls.ZEP_BASE_URL)

        return bool(resolved_api_key)

    @classmethod
    def get_zep_client_kwargs(cls, api_key=None):
        """生成 Zep 客户端初始化参数。"""
        resolved_api_key = cls.ZEP_API_KEY if api_key is None else api_key
        kwargs = {}

        # OpenZep 场景允许关闭鉴权；此时不要传空字符串 api_key，
        # 否则 zep sdk 会构造出非法的 `Api-Key:` 请求头，httpx 会直接拒绝。
        if resolved_api_key:
            kwargs['api_key'] = resolved_api_key
        if cls.ZEP_BASE_URL:
            kwargs['base_url'] = cls.ZEP_BASE_URL

        return kwargs

    @classmethod
    def get_zep_config_errors(cls, api_key=None):
        """返回 Zep/OpenZep 的配置错误。"""
        if cls.is_zep_configured(api_key=api_key):
            return []

        if cls.use_openzep():
            return ["ZEP_BASE_URL 未配置"]

        return ["ZEP_API_KEY 未配置"]

    @classmethod
    def get_graph_search_embedder_config(cls):
        """返回 app-side 图搜索语义重排使用的 embedding 配置。"""
        api_key = cls.GRAPH_SEARCH_APP_EMBEDDER_API_KEY
        base_url = cls.GRAPH_SEARCH_APP_EMBEDDER_BASE_URL
        model = cls.GRAPH_SEARCH_APP_EMBEDDER_MODEL

        backend = (cls.GRAPH_BACKEND or 'graphiti').lower()
        if backend == 'graphiti':
            api_key = api_key or cls.GRAPHITI_EMBEDDER_API_KEY
            base_url = base_url or cls.GRAPHITI_EMBEDDER_BASE_URL
            model = model or cls.GRAPHITI_EMBEDDER_MODEL
        elif cls.use_openzep():
            api_key = api_key or cls.OPENZEP_EMBEDDER_API_KEY
            base_url = base_url or cls.OPENZEP_EMBEDDER_BASE_URL
            model = model or cls.OPENZEP_EMBEDDER_MODEL

        if model and not api_key:
            api_key = 'ollama'

        return {
            'api_key': api_key,
            'base_url': base_url,
            'model': model,
        }

    @classmethod
    def get_graph_search_reranker_config(cls):
        """返回 app-side 图搜索交叉编码重排使用的 reranker 配置。"""
        api_key = cls.GRAPH_SEARCH_APP_RERANKER_API_KEY
        base_url = cls.GRAPH_SEARCH_APP_RERANKER_BASE_URL
        model = cls.GRAPH_SEARCH_APP_RERANKER_MODEL
        provider = cls.GRAPH_SEARCH_APP_RERANKER_PROVIDER

        graphiti_reranker_base_url = os.environ.get('GRAPHITI_RERANKER_BASE_URL') or None
        if graphiti_reranker_base_url:
            api_key = api_key or (os.environ.get('GRAPHITI_RERANKER_API_KEY') or None)
            base_url = base_url or graphiti_reranker_base_url
            model = model or (os.environ.get('GRAPHITI_RERANKER_MODEL') or None)

        return {
            'api_key': api_key,
            'base_url': base_url,
            'model': model,
            'provider': provider,
            'timeout': cls.GRAPH_SEARCH_APP_RERANKER_TIMEOUT,
        }

    @classmethod
    def get_graphiti_config_errors(cls):
        """返回 Graphiti + Neo4j 的配置错误。"""
        errors = []
        if not cls.GRAPHITI_URI:
            errors.append("GRAPHITI_URI 未配置")
        if not cls.GRAPHITI_DATABASE:
            errors.append("GRAPHITI_DATABASE 未配置")
        if not cls.GRAPHITI_LLM_MODEL:
            errors.append("GRAPHITI_LLM_MODEL 未配置")
        if not cls.GRAPHITI_EMBEDDER_MODEL:
            errors.append("GRAPHITI_EMBEDDER_MODEL 未配置")
        return errors

    @classmethod
    def get_graph_backend_config_errors(cls, api_key=None):
        """根据当前 GRAPH_BACKEND 返回对应的配置错误。"""
        backend = (cls.GRAPH_BACKEND or 'graphiti').lower()
        if backend in {'zep', 'openzep'}:
            return cls.get_zep_config_errors(api_key=api_key)
        if backend == 'graphiti':
            return cls.get_graphiti_config_errors()
        return [f"不支持的 GRAPH_BACKEND: {backend}"]

    @classmethod
    def is_graph_backend_configured(cls, api_key=None):
        return len(cls.get_graph_backend_config_errors(api_key=api_key)) == 0
    
    @classmethod
    def validate(cls):
        """验证必要配置"""
        errors = []
        if not cls.LLM_API_KEY:
            errors.append("LLM_API_KEY 未配置")
        errors.extend(cls.get_graph_backend_config_errors())
        return errors
