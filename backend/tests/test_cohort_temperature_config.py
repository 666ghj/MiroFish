"""COHORT_TEMPERATURE 覆盖人群构建链路上的三个采样点：

1. 本体生成 (OntologyGenerator.generate)
2. 人设生成 (OasisProfileGenerator._generate_profile_with_llm)
3. 模拟配置生成 (SimulationConfigGenerator._call_llm_with_retry，经 prepare_simulation 触发)

另外覆盖配置边界：未设置时三处必须一字不差地沿用历史默认值；取值被限定在
[0, 2] 内，越界或无法解析时告警并回退；以及配置了但模型会丢掉 temperature
时 Config.validate() 要提醒。
"""

import importlib.util
import os
import time

import pytest

from app.config import Config
from app.services import oasis_profile_generator as profile_module
from app.services import simulation_config_generator as sim_config_module
from app.services.oasis_profile_generator import OasisProfileGenerator
from app.services.ontology_generator import OntologyGenerator
from app.services.simulation_config_generator import SimulationConfigGenerator

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app", "config.py")

# 历史默认值：本体 0.3，人设/模拟配置 0.7 并在每次重试时降低 0.1。
# 第三级写成 0.49999999999999994 而不是 0.5，因为这是 `0.7 - (2 * 0.1)` 的精确结果，
# 未配置时必须一字不差地保持原样。
LEGACY_ONTOLOGY_TEMPERATURE = 0.3
LEGACY_RETRY_LADDER = [0.7, 0.6, 0.49999999999999994]


class OntologyClientStub:
    """记录 chat_json 收到的 temperature"""

    def __init__(self):
        self.temperatures = []

    def chat_json(self, **kwargs):
        self.temperatures.append(kwargs["temperature"])
        return {"entity_types": [], "edge_types": [], "analysis_summary": "ok"}


class ChatCompletionStub:
    """记录每次请求的 temperature，并始终失败以走完整条重试阶梯"""

    def __init__(self):
        self.temperatures = []

    def __call__(self, client, *, model, messages, temperature=None, **kwargs):
        self.temperatures.append(temperature)
        raise RuntimeError("stubbed provider failure")


def _pin_cohort_temperature_unset(monkeypatch):
    """把配置固定为未设置状态，使默认值测试不受运行环境影响"""
    monkeypatch.delenv("COHORT_TEMPERATURE", raising=False)
    monkeypatch.setattr(Config, "COHORT_TEMPERATURE", None, raising=False)


def _ontology_temperature() -> float:
    client = OntologyClientStub()
    OntologyGenerator(llm_client=client).generate(
        document_texts=["一份很短的素材。"],
        simulation_requirement="模拟公众讨论。",
    )
    return client.temperatures[0]


def _persona_retry_ladder(monkeypatch) -> list:
    stub = ChatCompletionStub()
    monkeypatch.setattr(profile_module, "create_chat_completion", stub)
    monkeypatch.setattr(time, "sleep", lambda *_: None)

    generator = object.__new__(OasisProfileGenerator)
    generator.client = object()
    generator.model_name = "compatible-model"
    generator._generate_profile_with_llm(
        entity_name="张三",
        entity_type="PublicFigure",
        entity_summary="事件当事人",
        entity_attributes={},
        context="",
    )
    return stub.temperatures


def _simulation_config_retry_ladder(monkeypatch) -> list:
    stub = ChatCompletionStub()
    monkeypatch.setattr(sim_config_module, "create_chat_completion", stub)
    monkeypatch.setattr(time, "sleep", lambda *_: None)

    generator = object.__new__(SimulationConfigGenerator)
    generator.client = object()
    generator.model_name = "compatible-model"
    with pytest.raises(RuntimeError):
        generator._call_llm_with_retry("prompt", "system prompt")
    return stub.temperatures


def _load_config_with_env(monkeypatch, raw_value):
    """用给定的环境变量值重新加载一份独立的 config 模块（不污染 sys.modules）"""
    if raw_value is None:
        monkeypatch.delenv("COHORT_TEMPERATURE", raising=False)
    else:
        monkeypatch.setenv("COHORT_TEMPERATURE", raw_value)
    # 本地 .env 不应影响测试结果
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: None)

    spec = importlib.util.spec_from_file_location("cohort_config_under_test", CONFIG_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Config


def test_unset_keeps_ontology_temperature(monkeypatch):
    _pin_cohort_temperature_unset(monkeypatch)

    assert _ontology_temperature() == LEGACY_ONTOLOGY_TEMPERATURE


def test_unset_keeps_persona_retry_ladder(monkeypatch):
    _pin_cohort_temperature_unset(monkeypatch)

    assert _persona_retry_ladder(monkeypatch) == LEGACY_RETRY_LADDER


def test_unset_keeps_simulation_config_retry_ladder(monkeypatch):
    _pin_cohort_temperature_unset(monkeypatch)

    assert _simulation_config_retry_ladder(monkeypatch) == LEGACY_RETRY_LADDER


def test_zero_pins_every_cohort_stage(monkeypatch):
    monkeypatch.setattr(Config, "COHORT_TEMPERATURE", 0.0)

    assert _ontology_temperature() == 0.0
    assert _persona_retry_ladder(monkeypatch) == [0.0, 0.0, 0.0]
    assert _simulation_config_retry_ladder(monkeypatch) == [0.0, 0.0, 0.0]


def test_configured_base_steps_down_and_stops_at_zero(monkeypatch):
    monkeypatch.setattr(Config, "COHORT_TEMPERATURE", 0.2)

    assert _ontology_temperature() == 0.2
    assert _persona_retry_ladder(monkeypatch) == [0.2, 0.1, 0.0]
    assert _simulation_config_retry_ladder(monkeypatch) == [0.2, 0.1, 0.0]


@pytest.mark.parametrize("base", [0.0, 0.05, 0.1, 0.2])
def test_no_retry_rung_is_ever_negative(monkeypatch, base):
    """截断是为阶梯算术而存在的：0.05 到第三次尝试会算出 -0.05。

    负的基准值本身不走到这里——它在 _optional_float 的区间检查里就被拒掉了，
    见 test_out_of_range_env_value_warns_and_keeps_legacy_defaults。
    """
    monkeypatch.setattr(Config, "COHORT_TEMPERATURE", base)

    for ladder in (
        _persona_retry_ladder(monkeypatch),
        _simulation_config_retry_ladder(monkeypatch),
    ):
        assert len(ladder) == 3
        assert all(value >= 0.0 for value in ladder), ladder


def test_env_value_reaches_the_cohort_stages(monkeypatch):
    config = _load_config_with_env(monkeypatch, "0")

    assert config.COHORT_TEMPERATURE == 0.0
    assert [config.cohort_temperature(0.7, attempt) for attempt in range(3)] == [0.0, 0.0, 0.0]
    assert config.cohort_temperature(0.3) == 0.0


@pytest.mark.parametrize("raw_value", [None, "", "   "])
def test_missing_or_blank_env_value_keeps_legacy_defaults(monkeypatch, raw_value):
    config = _load_config_with_env(monkeypatch, raw_value)

    assert config.COHORT_TEMPERATURE is None
    assert config.cohort_temperature(0.3) == LEGACY_ONTOLOGY_TEMPERATURE
    assert [
        config.cohort_temperature(0.7, attempt) for attempt in range(3)
    ] == LEGACY_RETRY_LADDER


@pytest.mark.parametrize("raw_value", ["abc", "0.3abc", "0,3", "low"])
def test_unparsable_env_value_warns_and_keeps_legacy_defaults(monkeypatch, raw_value):
    with pytest.warns(RuntimeWarning, match="is not a number"):
        config = _load_config_with_env(monkeypatch, raw_value)

    assert config.COHORT_TEMPERATURE is None
    assert config.cohort_temperature(0.3) == LEGACY_ONTOLOGY_TEMPERATURE
    assert [
        config.cohort_temperature(0.7, attempt) for attempt in range(3)
    ] == LEGACY_RETRY_LADDER


# float() 不会对这些值抛 ValueError：'inf'/'-inf'/'nan' 是合法字面量，
# '1e400' 会静默溢出成 inf，而 '7' 只是把 '0.7' 的小数点漏掉了。
# 它们都不是能发给 provider 的温度，所以必须在配置边界上挡掉。
@pytest.mark.parametrize(
    "raw_value",
    [
        "inf", "+inf", "Infinity", "1e400",   # 正无穷：过去会被原样发给 provider
        "-inf", "nan",                        # 过去被 max() 静默压成 0
        "7", "2.0001",                        # 超出 OpenAI 兼容区间的上界
        "-1", "-0.0001",                      # 负数：不该被静默当成 0
    ],
)
def test_out_of_range_env_value_warns_and_keeps_legacy_defaults(monkeypatch, raw_value):
    with pytest.warns(RuntimeWarning, match="outside the supported range"):
        config = _load_config_with_env(monkeypatch, raw_value)

    assert config.COHORT_TEMPERATURE is None
    assert config.cohort_temperature(0.3) == LEGACY_ONTOLOGY_TEMPERATURE
    assert [
        config.cohort_temperature(0.7, attempt) for attempt in range(3)
    ] == LEGACY_RETRY_LADDER


@pytest.mark.parametrize(
    "raw_value, expected",
    [
        ("0", 0.0),
        ("0.05", 0.05),
        ("0.2", 0.2),
        ("0.7", 0.7),
        ("2", 2.0),          # 上界本身是合法的
        ("  0.5  ", 0.5),    # 顺手容忍 .env 里的空白
    ],
)
def test_in_range_env_value_is_accepted_without_warning(monkeypatch, recwarn, raw_value, expected):
    config = _load_config_with_env(monkeypatch, raw_value)

    assert config.COHORT_TEMPERATURE == expected
    assert config.cohort_temperature(0.3) == expected
    assert config.cohort_temperature(0.7) == expected
    assert [str(w.message) for w in recwarn if "COHORT_TEMPERATURE" in str(w.message)] == []


def test_rejected_value_never_reaches_a_cohort_stage(monkeypatch):
    """区间检查最该挡住的一个值，端到端验证一遍。

    'inf' 能通过 float()，而 max(0.0, inf) 也不会把它拉回来，所以在加区间检查
    之前它会被原样发给 provider；人设阶段的 except Exception 又会把随之而来的
    失败咽掉，退回规则生成，调用方只看到"成功"。
    """
    with pytest.warns(RuntimeWarning, match="outside the supported range"):
        config = _load_config_with_env(monkeypatch, "inf")

    # 把解析结果搬到调用点真正读取的 Config 上，再把三个阶段都走一遍
    monkeypatch.setattr(Config, "COHORT_TEMPERATURE", config.COHORT_TEMPERATURE)

    assert _ontology_temperature() == LEGACY_ONTOLOGY_TEMPERATURE
    assert _persona_retry_ladder(monkeypatch) == LEGACY_RETRY_LADDER
    assert _simulation_config_retry_ladder(monkeypatch) == LEGACY_RETRY_LADDER


# GPT-5 系列会拒收 temperature，兼容层因此根本不发这个参数
# （见 app/utils/openai_chat_compat.py）。配置就位但注定无效时得说一声。
@pytest.mark.parametrize("model_name", ["gpt-5", "gpt-5-mini-2025-08-07", "GPT-5-Turbo"])
def test_validate_warns_when_the_model_drops_the_temperature(monkeypatch, model_name):
    monkeypatch.setattr(Config, "COHORT_TEMPERATURE", 0.0)
    monkeypatch.setattr(Config, "LLM_MODEL_NAME", model_name)

    with pytest.warns(RuntimeWarning, match="COHORT_TEMPERATURE=0.0 has no effect") as caught:
        Config.validate()

    # 告警要说清是哪个模型，否则运维无从下手
    assert any(model_name in str(w.message) for w in caught)


@pytest.mark.parametrize("model_name", ["qwen-plus", "gpt-4o-mini"])
def test_validate_is_quiet_for_models_that_honour_temperature(monkeypatch, recwarn, model_name):
    monkeypatch.setattr(Config, "COHORT_TEMPERATURE", 0.0)
    monkeypatch.setattr(Config, "LLM_MODEL_NAME", model_name)

    Config.validate()

    assert [str(w.message) for w in recwarn if "COHORT_TEMPERATURE" in str(w.message)] == []


def test_validate_is_quiet_when_cohort_temperature_is_unset(monkeypatch, recwarn):
    """没配置就没什么可提醒的，即便这个模型确实会丢掉 temperature"""
    _pin_cohort_temperature_unset(monkeypatch)
    monkeypatch.setattr(Config, "LLM_MODEL_NAME", "gpt-5")

    Config.validate()

    assert [str(w.message) for w in recwarn if "COHORT_TEMPERATURE" in str(w.message)] == []
