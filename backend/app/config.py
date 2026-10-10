"""\n配置管理\n统一从项目根目录的 .env 文件加载配置\n"""

import math
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


def _optional_float(key: str, *, minimum: float, maximum: float) -> float | None:
    """Read an optional float setting, returning None when it is not usable.

    未设置、留空、无法解析、非有限值或超出 [minimum, maximum] 时都返回 None，
    调用方据此沿用内置默认值，避免一个手误的配置值让整个应用启动失败。

    取值范围是必填参数：float() 会接受 'inf'/'-inf'/'nan'，也会把 '1e400'
    这类溢出字面量静默变成 inf，只靠捕获 ValueError 挡不住它们。
    """
    import warnings

    raw = os.environ.get(key)
    if raw is None or not raw.strip():
        return None

    try:
        value = float(raw)
    except ValueError:
        warnings.warn(
            f"{key}={raw!r} is not a number; falling back to the built-in defaults.",
            RuntimeWarning,
        )
        return None

    # isfinite 先挡住 inf/-inf/nan（nan 参与任何比较都是 False，单看区间判断
    # 读者得自己推一遍 IEEE 语义才知道它被排除了），再做区间检查。
    if not math.isfinite(value) or not minimum <= value <= maximum:
        warnings.warn(
            f"{key}={raw!r} is outside the supported range "
            f"[{minimum}, {maximum}]; falling back to the built-in defaults.",
            RuntimeWarning,
        )
        return None

    return value


class Config:
    """Flask配置类"""
    
    # Flask配置
    SECRET_KEY = os.environ.get('SECRET_KEY', 'mirofish-secret-key')
    DEBUG = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    
    # JSON配置 - 禁用ASCII转义，让中文直接显示
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
    
    # 人群构建配置（本体 -> 实体 -> 人设 这条链路上的采样温度）
    # 不设置时每个阶段沿用自己的历史默认值。
    # 设为 0 可固定这三处的采样，把温度从变量里排除掉——但这不等于人群可复现：
    # 实体抽取在 Zep 侧完成，本配置管不到，同一输入重复跑仍会得到不同的实体集合
    # （#751 实测：同一容器内温度全设为 0，两次抽取仍是 27 和 26 个实体，只有 24 个相同）。
    # OpenAI 兼容接口的 temperature 取值范围是 [0, 2]，超出范围服务端会直接拒绝请求
    COHORT_TEMPERATURE_MIN = 0.0
    COHORT_TEMPERATURE_MAX = 2.0
    COHORT_TEMPERATURE = _optional_float(
        'COHORT_TEMPERATURE',
        minimum=COHORT_TEMPERATURE_MIN,
        maximum=COHORT_TEMPERATURE_MAX,
    )
    # 重试阶梯每次下调的幅度（见各调用点的"每次重试降低温度"）
    COHORT_TEMPERATURE_RETRY_STEP = 0.1

    @classmethod
    def cohort_temperature(cls, default: float, attempt: int = 0) -> float:
        """Resolve the cohort-construction temperature for one LLM attempt.

        未配置 COHORT_TEMPERATURE 时返回调用点传入的历史默认值，行为与之前完全一致；
        配置后三个阶段共用同一个基准值。重试阶梯依旧每次降低 0.1，但下限截断在 0：
        基准值本身已在 [0, 2] 内（越界的值在 _optional_float 里就被拒掉了），
        截断只为挡住阶梯算出来的负数，例如基准 0.05 在第三次尝试会降到 -0.05。

        Args:
            default: 该阶段的历史默认温度（未配置时使用）
            attempt: 第几次尝试，从 0 开始

        Returns:
            本次请求使用的温度，始终 >= 0
        """
        base = cls.COHORT_TEMPERATURE
        if base is None:
            base = default
        return max(0.0, base - (attempt * cls.COHORT_TEMPERATURE_RETRY_STEP))

    @classmethod
    def validate(cls) -> list[str]:
        """验证必要配置"""
        errors: list[str] = []
        if not cls.LLM_API_KEY:
            errors.append("LLM_API_KEY 未配置")
        if not cls.ZEP_API_KEY:
            errors.append("ZEP_API_KEY 未配置")
        if os.environ.get("ZEP_API_URL"):
            errors.append("ZEP_API_URL 不受支持；MiroFish 仅连接 Zep Cloud")
        if cls.DEBUG:
            import warnings
            warnings.warn("Flask DEBUG mode is enabled. Do not use in production.", RuntimeWarning)
        if cls.COHORT_TEMPERATURE is not None:
            # 延迟导入：app.utils 的包初始化会 import llm_client，而后者 import 本模块，
            # 放在模块顶层会形成循环导入。
            from .utils.openai_chat_compat import is_gpt5_family
            if is_gpt5_family(cls.LLM_MODEL_NAME):
                import warnings
                warnings.warn(
                    f"COHORT_TEMPERATURE={cls.COHORT_TEMPERATURE} has no effect with "
                    f"LLM_MODEL_NAME={cls.LLM_MODEL_NAME!r}: the GPT-5 family rejects "
                    "the temperature parameter, so it is not sent at all and cohort "
                    "construction stays unpinned.",
                    RuntimeWarning,
                )
        return errors
