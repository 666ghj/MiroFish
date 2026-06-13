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
    # 注意：SECRET_KEY 的默认值是公开值，仅供 DEBUG 模式使用；生产模式（DEBUG=false）
    # 必须通过环境变量设置自定义值（见 validate()）。
    SECRET_KEY = os.environ.get('SECRET_KEY', 'mirofish-secret-key')
    # 安全默认（C1）：DEBUG 默认关闭，避免误把 Werkzeug 交互式调试器（可远程 RCE）暴露到网络。
    DEBUG = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'

    # 认证配置（C2）：所有 /api/* 端点强制 API Key 鉴权
    # AUTH_ENABLED 默认开启；本地开发可显式设 AUTH_ENABLED=false 关闭。
    # fail-closed 解析：仅显式 false/0/no/off 才关闭鉴权；其余任何值（含空白、拼写错误、
    # 带尾换行的 'true\n'、'1'、'yes' 等）一律视为开启，避免 env 配置失误悄悄回到零鉴权。
    API_KEY = os.environ.get('API_KEY')
    AUTH_ENABLED = os.environ.get('AUTH_ENABLED', 'true').strip().lower() not in ('false', '0', 'no', 'off')

    # CORS 允许来源（H4）：不再用通配 '*'。默认仅本地前端开发/预览源；生产用逗号分隔的
    # ALLOWED_ORIGINS 指定前端域名（例如 https://app.example.com）。'*' 仍可显式设置但不推荐。
    ALLOWED_ORIGINS = [
        o.strip() for o in os.environ.get(
            'ALLOWED_ORIGINS', 'http://localhost:3000,http://127.0.0.1:3000'
        ).split(',') if o.strip()
    ]

    # JSON配置 - 禁用ASCII转义，让中文直接显示（而不是 \uXXXX 格式）
    JSON_AS_ASCII = False
    
    # LLM配置（统一使用OpenAI格式）
    LLM_API_KEY = os.environ.get('LLM_API_KEY')
    LLM_BASE_URL = os.environ.get('LLM_BASE_URL', 'https://api.openai.com/v1')
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
    # OASIS_DEFAULT_MAX_ROUNDS（C3）：客户端未显式传 max_rounds 时应用的默认轮数上限。
    # 之前此常量从未被引用（dead config），现已在 SimulationRunner 中生效。默认 150 覆盖
    # 典型配置（72h/30min = 144 轮）以免悄悄截断标准演示；更长的配置会被截到此值，且无论如何
    # 都不会超过硬上限 OASIS_MAX_ROUNDS_CAP。匿名 denial-of-wallet 已由 C2 鉴权堵住，此处
    # 仅约束“已鉴权客户端”单次运行的成本上界。
    OASIS_DEFAULT_MAX_ROUNDS = int(os.environ.get('OASIS_DEFAULT_MAX_ROUNDS', '150'))
    # 硬上限（C3，denial-of-wallet 防护）：无论客户端传入何值，轮数/agent 数都不得超过这些上限。
    OASIS_MAX_ROUNDS_CAP = int(os.environ.get('OASIS_MAX_ROUNDS_CAP', '200'))
    OASIS_MAX_AGENTS_CAP = int(os.environ.get('OASIS_MAX_AGENTS_CAP', '1000'))
    # 模拟超时（C4，秒）：每轮 env.step 超时 + 整轮模拟总超时。子进程读取同名环境变量。
    OASIS_ROUND_TIMEOUT_SEC = int(os.environ.get('OASIS_ROUND_TIMEOUT_SEC', '600'))
    OASIS_RUN_TIMEOUT_SEC = int(os.environ.get('OASIS_RUN_TIMEOUT_SEC', '7200'))
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
    def validate(cls) -> list[str]:
        """验证必要配置"""
        errors: list[str] = []
        if not cls.LLM_API_KEY:
            errors.append("LLM_API_KEY 未配置")
        if not cls.ZEP_API_KEY:
            errors.append("ZEP_API_KEY 未配置")
        # C1：生产模式必须设置自定义 SECRET_KEY（默认值是公开值，可伪造签名 / 削弱调试器 PIN）
        if not cls.DEBUG and cls.SECRET_KEY == 'mirofish-secret-key':
            errors.append("生产模式（FLASK_DEBUG=false）必须设置自定义 SECRET_KEY")
        # C2：开启鉴权时必须配置 API_KEY，否则所有 /api/* 都会 401
        if cls.AUTH_ENABLED and not cls.API_KEY:
            errors.append("AUTH_ENABLED=true 时必须设置 API_KEY（或显式 AUTH_ENABLED=false 关闭鉴权）")
        return errors

