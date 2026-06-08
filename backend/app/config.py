"""
配置管理
统一从项目根目录的 .env 文件加载配置
"""

import os
from dotenv import load_dotenv

# 加载项目根目录的 .env 文件
# 路径: Foresight/.env (相对于 backend/app/config.py)
project_root_env = os.path.join(os.path.dirname(__file__), '../../.env')

if os.path.exists(project_root_env):
    load_dotenv(project_root_env, override=True)
else:
    # 如果根目录没有 .env，尝试加载环境变量（用于生产环境）
    load_dotenv(override=True)


class Config:
    """Flask配置类"""
    
    # Flask配置
    SECRET_KEY = os.environ.get('SECRET_KEY', 'foresight-secret-key')
    DEBUG = os.environ.get('FLASK_DEBUG', 'True').lower() == 'true'
    
    # JSON配置 - 禁用ASCII转义，让中文直接显示（而不是 \uXXXX 格式）
    JSON_AS_ASCII = False
    
    # LLM配置（统一使用OpenAI格式）
    LLM_API_KEY = os.environ.get('LLM_API_KEY')
    LLM_BASE_URL = os.environ.get('LLM_BASE_URL', 'https://api.openai.com/v1')
    LLM_MODEL_NAME = os.environ.get('LLM_MODEL_NAME', 'gpt-4o-mini')
    LLM_TIMEOUT_SECONDS = float(os.environ.get('LLM_TIMEOUT_SECONDS', '12'))
    LLM_MAX_RETRIES = int(os.environ.get('LLM_MAX_RETRIES', '0'))
    
    # Neo4j / Graphiti 配置
    NEO4J_URI = os.environ.get('NEO4J_URI', 'bolt://localhost:7687')
    NEO4J_USER = os.environ.get('NEO4J_USER', 'neo4j')
    NEO4J_PASSWORD = os.environ.get('NEO4J_PASSWORD', 'foresight2026')

    # Graphiti LLM 配置（SiliconFlow，用于图谱构建的 structured output）
    GRAPHITI_LLM_API_KEY = os.environ.get('GRAPHITI_LLM_API_KEY')
    GRAPHITI_LLM_BASE_URL = os.environ.get('GRAPHITI_LLM_BASE_URL', 'https://api.siliconflow.cn/v1')
    GRAPHITI_LLM_MODEL = os.environ.get('GRAPHITI_LLM_MODEL', 'Qwen/Qwen2.5-7B-Instruct')

    # Embedding 配置（SiliconFlow 免费 BAAI/bge-m3）
    EMBEDDING_API_KEY = os.environ.get('EMBEDDING_API_KEY')
    EMBEDDING_BASE_URL = os.environ.get('EMBEDDING_BASE_URL', 'https://api.siliconflow.cn/v1')
    EMBEDDING_MODEL = os.environ.get('EMBEDDING_MODEL', 'BAAI/bge-m3')

    # 兼容旧配置：ZEP_API_KEY 不再需要
    ZEP_API_KEY = os.environ.get('ZEP_API_KEY', 'deprecated')
    
    # 文件上传配置
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), '../uploads')
    ALLOWED_EXTENSIONS = {'pdf', 'md', 'txt', 'markdown'}
    
    # 文本处理配置（大 chunk 减少 LLM 调用次数，加速图谱构建）
    DEFAULT_CHUNK_SIZE = 2000  # 默认切块大小
    DEFAULT_CHUNK_OVERLAP = 200  # 默认重叠大小
    
    # OASIS模拟配置
    OASIS_DEFAULT_MAX_ROUNDS = int(os.environ.get('OASIS_DEFAULT_MAX_ROUNDS', '10'))
    OASIS_SIMULATION_DATA_DIR = os.path.join(os.path.dirname(__file__), '../uploads/simulations')
    SIMULATION_MAX_AGENTS = int(os.environ.get('SIMULATION_MAX_AGENTS', '30'))
    GRAPH_VISUAL_MAX_NODES = int(os.environ.get('GRAPH_VISUAL_MAX_NODES', '30'))
    
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
    def validate(cls):
        """验证必要配置"""
        errors = []
        if not cls.LLM_API_KEY:
            errors.append("LLM_API_KEY 未配置")
        if not cls.NEO4J_PASSWORD:
            errors.append("NEO4J_PASSWORD 未配置")
        return errors
