"""
配置管理
本地优先从可预测位置加载配置（支持 MiroFish-config/.env）
"""

import os
from dotenv import load_dotenv

def _normalize_openai_base_url(url: str) -> str:
    s = (url or "").strip()
    if not s:
        return s
    s = s.rstrip("/")
    # OpenAI SDK expects base_url to include the API prefix (typically /v1).
    if s.endswith("/v1") or "/v1/" in s:
        return s
    return f"{s}/v1"

def _load_env():
    """
    加载运行时环境变量（按优先级）
    1) 显式指定: MIROFISH_ENV_FILE
    2) 仓库根目录: .env
    3) 本地配置目录: MiroFish-config/.env
    4) 兜底: 使用当前进程环境变量
    """
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../'))

    explicit_env = os.environ.get('MIROFISH_ENV_FILE')
    if explicit_env and os.path.exists(explicit_env):
        load_dotenv(explicit_env)
        return

    repo_env = os.path.join(repo_root, '.env')
    if os.path.exists(repo_env):
        load_dotenv(repo_env)
        return

    local_env = os.path.join(repo_root, 'MiroFish-config', '.env')
    if os.path.exists(local_env):
        load_dotenv(local_env)
        return

    load_dotenv()


_load_env()


class Config:
    """Flask配置类"""
    
    # Flask配置
    SECRET_KEY = os.environ.get('SECRET_KEY', 'mirofish-secret-key')
    DEBUG = os.environ.get('FLASK_DEBUG', 'True').lower() == 'true'
    
    # JSON配置 - 禁用ASCII转义，让中文直接显示（而不是 \uXXXX 格式）
    JSON_AS_ASCII = False
    
    # LLM配置（统一使用OpenAI格式）
    LLM_API_KEY = os.environ.get('LLM_API_KEY')
    LLM_BASE_URL = _normalize_openai_base_url(os.environ.get('LLM_BASE_URL', 'https://api.openai.com/v1'))
    LLM_MODEL_NAME = os.environ.get('LLM_MODEL_NAME', 'gpt-4o-mini')
    
    # Zep配置
    ZEP_API_KEY = os.environ.get('ZEP_API_KEY')
    
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

    # Simulation lifecycle (local)
    # When enabled, backend shutdown will NOT terminate running simulation processes.
    # This is required to keep the interview environment alive across backend restarts.
    SIMULATION_DETACH_ON_BACKEND_EXIT = os.environ.get('SIMULATION_DETACH_ON_BACKEND_EXIT', 'False').lower() == 'true'
    
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
        if not cls.ZEP_API_KEY:
            errors.append("ZEP_API_KEY 未配置")
        return errors
