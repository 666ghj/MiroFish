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
    load_dotenv(project_root_env)
else:
    # 如果根目录没有 .env，尝试加载环境变量（用于生产环境）
    load_dotenv()


class Config:
    """Flask配置类"""
    
    # 存储后端配置
    # - zep: 使用 Zep Cloud 图谱（现有实现）
    # - local: Neo4j + Qdrant（本地化存储）
    GRAPH_BACKEND = os.environ.get('GRAPH_BACKEND', 'zep').lower()
    VECTOR_BACKEND = os.environ.get('VECTOR_BACKEND', 'qdrant').lower()  # qdrant | none

    # Flask配置
    SECRET_KEY = os.environ.get('SECRET_KEY', 'mirofish-secret-key')
    DEBUG = os.environ.get('FLASK_DEBUG', 'True').lower() == 'true'
    
    # JSON配置 - 禁用ASCII转义，让中文直接显示（而不是 \uXXXX 格式）
    JSON_AS_ASCII = False
    
    # LLM配置（统一使用OpenAI格式）
    LLM_API_KEY = os.environ.get('LLM_API_KEY')
    LLM_BASE_URL = os.environ.get('LLM_BASE_URL', 'https://api.openai.com/v1')
    LLM_MODEL_NAME = os.environ.get('LLM_MODEL_NAME', 'gpt-4o-mini')

    # 结构化抽取 LLM（用于本体生成/实体关系抽取等 JSON 任务；默认复用 LLM 配置）
    # 有些供应商会对"输出内容审核"更严格，导致 data_inspection_failed，可单独切换到更合适的模型/供应商。
    EXTRACT_API_KEY = os.environ.get('EXTRACT_API_KEY') or LLM_API_KEY
    EXTRACT_BASE_URL = os.environ.get('EXTRACT_BASE_URL') or LLM_BASE_URL
    EXTRACT_MODEL_NAME = os.environ.get('EXTRACT_MODEL_NAME') or LLM_MODEL_NAME

    # 报告生成LLM（默认复用 LLM 配置）
    # 说明：部分国内供应商对"输入内容审核"更严格，报告生成时会携带模拟/检索到的原始内容，可能触发 data_inspection_failed。
    #       可单独将报告生成切换到更合适的 OpenAI 兼容供应商/模型。
    REPORT_API_KEY = os.environ.get('REPORT_API_KEY') or LLM_API_KEY
    REPORT_BASE_URL = os.environ.get('REPORT_BASE_URL') or LLM_BASE_URL
    REPORT_MODEL_NAME = os.environ.get('REPORT_MODEL_NAME') or LLM_MODEL_NAME

    # Embedding 配置（默认复用 LLM 配置）
    EMBEDDING_API_KEY = os.environ.get('EMBEDDING_API_KEY') or LLM_API_KEY
    EMBEDDING_BASE_URL = os.environ.get('EMBEDDING_BASE_URL') or LLM_BASE_URL
    EMBEDDING_MODEL_NAME = os.environ.get('EMBEDDING_MODEL_NAME', 'text-embedding-3-small')
    
    # Zep配置
    ZEP_API_KEY = os.environ.get('ZEP_API_KEY')

    # Neo4j 配置（GRAPH_BACKEND=local）
    NEO4J_URI = os.environ.get('NEO4J_URI', 'bolt://localhost:7687')
    NEO4J_USER = os.environ.get('NEO4J_USER', 'neo4j')
    NEO4J_PASSWORD = os.environ.get('NEO4J_PASSWORD')
    NEO4J_DATABASE = os.environ.get('NEO4J_DATABASE', 'neo4j')

    # Qdrant 配置（VECTOR_BACKEND=qdrant）
    QDRANT_URL = os.environ.get('QDRANT_URL', 'http://localhost:6333')
    QDRANT_API_KEY = os.environ.get('QDRANT_API_KEY')
    QDRANT_COLLECTION_CHUNKS = os.environ.get('QDRANT_COLLECTION_CHUNKS', 'mirofish_chunks')
    
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
    def validate(cls):
        """验证必要配置"""
        errors = []
        if not cls.LLM_API_KEY:
            errors.append("LLM_API_KEY 未配置")
        if cls.GRAPH_BACKEND not in {"zep", "local"}:
            errors.append("GRAPH_BACKEND 仅支持 zep 或 local")

        if cls.GRAPH_BACKEND == "zep":
            if not cls.ZEP_API_KEY:
                errors.append("ZEP_API_KEY 未配置（GRAPH_BACKEND=zep）")

        if cls.GRAPH_BACKEND == "local":
            if not cls.NEO4J_PASSWORD:
                errors.append("NEO4J_PASSWORD 未配置（GRAPH_BACKEND=local）")
            if cls.VECTOR_BACKEND not in {"qdrant", "none"}:
                errors.append("VECTOR_BACKEND 仅支持 qdrant 或 none")
            if cls.VECTOR_BACKEND == "qdrant":
                if not cls.QDRANT_URL:
                    errors.append("QDRANT_URL 未配置（VECTOR_BACKEND=qdrant）")
        return errors
