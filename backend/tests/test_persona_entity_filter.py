import json
import logging
import os

import pytest

from app.config import Config
from app.services import oasis_profile_generator as generator_module
from app.services import simulation_manager as simulation_manager_module
from app.services.oasis_profile_generator import (
    OasisProfileGenerator,
    _persona_entity_reject_reason,
    partition_persona_entities,
)
from app.services.simulation_config_generator import SimulationConfigGenerator
from app.services.simulation_manager import SimulationManager, SimulationState
from app.services.zep_entity_reader import EntityNode, FilteredEntities
from app.utils.locale import t


# 来自 issue #759 的真实抽取结果。注意 "market event" 不在此列：
# 唯一能抓住它的规则（全小写多词短语）同时会误伤 "elon musk"/"goldman sachs"/
# "bell hooks"，而且那条规则只认小写拼法，"Market Event" 从来就漏网，
# 所以它已被移除。详见 docs 与 PR 说明。
REPORTED_JUNK_NAMES = {
    "None": "placeholder",
    "edges": "placeholder",
    "Posts 3-5 times daily: cross-asset takes, historical analogies "
    "('I've seen this movie before'), decay-of-panic arguments.": "prose_fragment",
    "supply chain detail, management call parsing, unit economics": "clause_list",
    "MiroFish": "self_reference",
}

# 报告里明确提到、但当前规则集**不会**拦下的名字。
# 固定住这一点，避免日后误以为它们已被覆盖。
KNOWN_UNCAUGHT_JUNK = [
    "market event",
    "bear case",
    "Market Event",
    "Person",
    "Client",
    "HedgeFundManager",
    "The deal closed.",
    "Breaking News",
    "市场事件",
]

PERSON_NAMES = [
    "Elon Musk",
    "Dr. Jane Goodall",
    "Jean-Luc Picard",
    "O'Brien",
    "Smith, John, Jr.",
    "张伟",
    "山田太郎",
    "김정은",
    "Владимир Путин",
    "محمد بن سلمان",
    "नरेंद्र मोदी",
    "Ludwig Mies van der Rohe",
    "Ana de la Cruz",
    "Jean-Baptiste Poquelin dit Molière",
    # 带头衔缩写的人名：五个词以上且以句点结尾，旧的"句子"规则会误伤
    "Rev. Dr. Martin Luther King Jr.",
    "Martin Luther King Jr.",
    # 本人就用小写书写的真实姓名
    "bell hooks",
    "k.d. lang",
    "danah boyd",
    "e e cummings",
    # 全小写来源文档里的普通人名（旧规则会把整份名册清空）
    "elon musk",
    "john smith",
    "zhang wei",
    "kim jong un",
    "mohammed bin salman",
    "nguyen van an",
    "van der berg",
    "de la cruz",
]

# 群体/机构人设是有意支持的能力（_build_group_persona_prompt），不能被过滤掉
GROUP_NAMES = [
    "Goldman Sachs",
    "Tsinghua University",
    "Reuters",
    "OpenAI",
    "The Federal Reserve Board of Governors",
    "National Oceanic and Atmospheric Administration",
    "Acme Co.",
    "Berkshire Hathaway Inc.",
    "国家发展和改革委员会",
    "中国科学院自动化研究所类脑智能研究中心",
    "独立行政法人情報処理推進機構",
    # 五到八个词、以法律后缀（句点）结尾的注册名
    "The Goldman Sachs Group, Inc.",
    "United Parcel Service of America, Inc.",
    "Taiwan Semiconductor Manufacturing Company Ltd.",
    "Industrial and Commercial Bank of China Ltd.",
    "Bank of New York Mellon Corp.",
    "The Procter & Gamble Distributing Co.",
    "Hong Kong and Shanghai Banking Corp.",
    "John Wiley & Sons, Inc.",
    "E. I. du Pont de Nemours and Co.",
    "Her Majesty's Revenue and Customs Dept.",
    # 多逗号但以并列连词收尾的真实机构名
    "Bureau of Alcohol, Tobacco, Firearms and Explosives",
    "Bureau of Alcohol, Tobacco, Firearms, and Explosives",
    "Skadden, Arps, Slate, Meagher & Flom",
    "Paul, Weiss, Rifkind, Wharton & Garrison",
    "United Nations Educational, Scientific and Cultural Organization",
    # 超长但真实的机构名（99字符）
    "Massachusetts Institute of Technology Computer Science and Artificial "
    "Intelligence Laboratory",
    "Chinese Academy of Sciences Institute of Automation Research Center for "
    "Brain-Inspired Intelligence",
    "National Institute of Standards and Technology Information Technology Laboratory",
    # 名字里带感叹号/问号的真实品牌
    "Yahoo!",
    "Wham!",
    "Guess Who?",
    "Panic! at the Disco",
    "AT&T",
    # 小写书写的真实品牌
    "eBay",
    "openai",
    "adidas",
    "will.i.am",
    "ing bank",
    "lululemon athletica",
    "3m company",
    "ing groep n.v.",
]

# 结构上明确不是名字的输入
STRUCTURAL_JUNK = {
    # 占位符词汇（中英日）
    "null": "placeholder",
    "n/a": "placeholder",
    "undefined": "placeholder",
    "nodes": "placeholder",
    "entity": "placeholder",
    "无": "placeholder",
    "未知": "placeholder",
    "节点": "placeholder",
    "边": "placeholder",
    "实体": "placeholder",
    "空": "placeholder",
    "なし": "placeholder",
    "不明": "placeholder",
    # 带空白的占位符仍然命中（归一化后整词匹配）
    "  None  ": "placeholder",
    "　节点　": "placeholder",
    # "标签: 内容" 结构
    "Summary: a two-sided market event": "prose_fragment",
    "Role: hedge fund manager": "prose_fragment",
    "简介：对冲基金经理": "prose_fragment",
    # 中文句末句号
    "他说这笔交易将会完成。": "prose_fragment",
    # 行内换行
    "First line\nsecond line": "prose_fragment",
    # 兜底长度上限
    "x" * 161: "prose_fragment",
    # 中文顿号枚举
    "供应链细节、管理层电话会议解析、单位经济效益": "clause_list",
    # 用不换行空格 / 制表符分词的枚举：归一化后仍被识别为清单
    "supply chain detail, management call parsing, unit economics": "clause_list",
    "supply chain detail,\tmanagement call parsing,\tunit economics": "clause_list",
}


class _LogRecorder(logging.Handler):
    """Collect formatted log messages emitted by the generator logger."""

    def __init__(self):
        super().__init__()
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def _entity(name, label="Person"):
    return EntityNode(
        uuid=f"uuid::{name}",
        name=name,
        labels=["Entity", label],
        summary=f"Summary of {name}",
        attributes={},
    )


def _stub_generator(monkeypatch):
    """Build a generator that never touches the network (no LLM, no Zep)."""
    generator = object.__new__(OasisProfileGenerator)
    generator.client = None
    generator.model_name = "stub-model"
    generator.zep_client = None
    generator.graph_id = None

    def _fail_on_llm_call(*args, **kwargs):
        raise AssertionError("LLM must not be called from tests")

    monkeypatch.setattr(generator_module, "create_chat_completion", _fail_on_llm_call)
    return generator


def _offline_real_generator(monkeypatch):
    """Let the *real* OasisProfileGenerator be constructed without network."""

    class _DummyOpenAI:
        def __init__(self, *args, **kwargs):
            pass

    monkeypatch.setattr(Config, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(Config, "LLM_BASE_URL", "http://localhost")
    monkeypatch.setattr(Config, "LLM_MODEL_NAME", "stub-model")
    monkeypatch.setattr(Config, "ZEP_API_KEY", "")
    monkeypatch.setattr(generator_module, "OpenAI", _DummyOpenAI)

    def _fail_on_llm_call(*args, **kwargs):
        raise AssertionError("LLM must not be called from tests")

    monkeypatch.setattr(generator_module, "create_chat_completion", _fail_on_llm_call)


@pytest.mark.parametrize("name, expected_reason", sorted(REPORTED_JUNK_NAMES.items()))
def test_reported_junk_names_are_rejected(name, expected_reason):
    assert _persona_entity_reject_reason(name) == expected_reason


@pytest.mark.parametrize("name, expected_reason", sorted(STRUCTURAL_JUNK.items()))
def test_structural_junk_is_rejected(name, expected_reason):
    assert _persona_entity_reject_reason(name) == expected_reason


@pytest.mark.parametrize("name", ["", "   ", "\n", " ", None, 42])
def test_empty_and_non_string_names_are_rejected(name):
    assert _persona_entity_reject_reason(name) == "empty_name"


@pytest.mark.parametrize("name", PERSON_NAMES)
def test_person_names_are_accepted(name):
    assert _persona_entity_reject_reason(name) is None


@pytest.mark.parametrize("name", GROUP_NAMES)
def test_organization_and_group_names_are_accepted(name):
    assert _persona_entity_reject_reason(name) is None


@pytest.mark.parametrize("name", KNOWN_UNCAUGHT_JUNK)
def test_known_uncaught_junk_is_documented_as_accepted(name):
    """These are junk the predicate deliberately no longer rejects.

    Pinned so that the coverage gap stays visible: the rules that caught them
    also rejected real participants. If a future rule catches one of these
    without reintroducing a false positive, update this list.
    """
    assert _persona_entity_reject_reason(name) is None


def test_whole_name_match_only_for_vocabulary_rules():
    """Placeholder / self-reference lists must not match prefixes or substrings."""
    for name in [
        "Nonesuch Capital",
        "Edgewater Partners",
        "Node Labs",
        "Unknown Pleasures Records",
        "MiroFish Analytics Ltd.",
        "无锡市政府",
        "空客中国",
    ]:
        assert _persona_entity_reject_reason(name) is None, name


def test_invalid_entities_are_dropped_without_leaving_holes(monkeypatch, tmp_path):
    generator = _stub_generator(monkeypatch)
    output_path = tmp_path / "reddit_profiles.json"
    entities = [
        _entity("Elon Musk"),
        _entity("None"),
        _entity("Goldman Sachs", label="Company"),
        _entity("节点"),
        _entity("MiroFish"),
        _entity("Tsinghua University", label="University"),
    ]

    profiles = generator.generate_profiles_from_entities(
        entities=entities,
        use_llm=False,
        parallel_count=1,
        realtime_output_path=str(output_path),
        output_platform="reddit",
    )

    assert [p.name for p in profiles] == [
        "Elon Musk",
        "Goldman Sachs",
        "Tsinghua University",
    ]
    assert [p.user_id for p in profiles] == [0, 1, 2]
    assert all(profile is not None for profile in profiles)

    saved = json.loads(output_path.read_text(encoding="utf-8"))
    assert [row["user_id"] for row in saved] == [0, 1, 2]
    assert [row["name"] for row in saved] == [p.name for p in profiles]


def test_skipped_entities_are_logged_and_surfaced_in_progress(monkeypatch):
    generator = _stub_generator(monkeypatch)
    recorder = _LogRecorder()
    generator_module.logger.addHandler(recorder)
    events = []

    try:
        profiles = generator.generate_profiles_from_entities(
            entities=[_entity("Elon Musk"), _entity("edges"), _entity("实体")],
            use_llm=False,
            progress_callback=lambda current, total, message: events.append(
                (current, total, message)
            ),
            parallel_count=1,
        )
    finally:
        generator_module.logger.removeHandler(recorder)

    assert [p.name for p in profiles] == ["Elon Musk"]
    assert t('progress.personaEntitySkipped', name='edges', reason='placeholder') in recorder.messages
    assert t(
        'progress.personaEntitySkipped', name='实体', reason='placeholder'
    ) in recorder.messages
    assert events[0] == (0, 1, t('progress.personaEntitiesSkipped', count=2, total=1))


def test_partition_is_idempotent_and_pure():
    entities = [_entity("Elon Musk"), _entity("None"), _entity("节点")]
    original_names = [e.name for e in entities]

    first_pass, first_skipped = partition_persona_entities(entities)
    second_pass, second_skipped = partition_persona_entities(first_pass)

    assert [e.name for e in first_pass] == ["Elon Musk"]
    assert len(first_skipped) == 2
    # 纯函数：对已过滤的列表再过滤是空操作，所以兜底过滤不会二次改变编号
    assert second_pass == first_pass
    assert second_skipped == []
    # 不修改入参
    assert [e.name for e in entities] == original_names
    assert first_pass is not entities
    assert all(any(kept is original for original in entities) for kept in first_pass)


class _StubReader:
    entities = []

    def __init__(self, *args, **kwargs):
        pass

    def filter_defined_entities(self, **kwargs):
        return FilteredEntities(
            entities=list(type(self).entities),
            entity_types={"Person", "Company", "University"},
            total_count=len(type(self).entities),
            filtered_count=len(type(self).entities),
        )


class _StubParameters:
    generation_reasoning = "stub reasoning"

    def to_json(self):
        return "{}"


def _make_reader(entities):
    return type("_Reader", (_StubReader,), {"entities": list(entities)})


def _prepared_manager(tmp_path, simulation_id="sim_filter", **state_kwargs):
    manager = SimulationManager()
    manager.SIMULATION_DATA_DIR = str(tmp_path)
    defaults = dict(
        simulation_id=simulation_id,
        project_id="proj_filter",
        graph_id="graph_filter",
        enable_twitter=False,
        enable_reddit=True,
    )
    defaults.update(state_kwargs)
    manager._save_simulation_state(SimulationState(**defaults))
    return manager


def test_prepare_simulation_uses_one_entity_list_for_profiles_and_configs(tmp_path, monkeypatch):
    entities = [
        _entity("Elon Musk"),
        _entity("None"),
        _entity("Goldman Sachs", label="Company"),
        _entity("节点"),
        _entity("Tsinghua University", label="University"),
    ]
    seen = {}

    class StubProfileGenerator:
        def __init__(self, *args, **kwargs):
            pass

        def generate_profiles_from_entities(self, entities, **kwargs):
            seen["profiles"] = list(entities)
            return [
                generator_module.OasisAgentProfile(
                    user_id=idx,
                    user_name=f"user_{idx}",
                    name=entity.name,
                    bio="",
                    persona="",
                )
                for idx, entity in enumerate(entities)
            ]

        def save_profiles(self, **kwargs):
            seen["saved_platform"] = kwargs.get("platform")

    class StubConfigGenerator:
        def __init__(self, *args, **kwargs):
            pass

        def generate_config(self, entities, **kwargs):
            seen["configs"] = list(entities)
            return _StubParameters()

    monkeypatch.setattr(simulation_manager_module, "ZepEntityReader", _make_reader(entities))
    monkeypatch.setattr(simulation_manager_module, "OasisProfileGenerator", StubProfileGenerator)
    monkeypatch.setattr(
        simulation_manager_module, "SimulationConfigGenerator", StubConfigGenerator
    )

    state = _prepared_manager(tmp_path).prepare_simulation(
        simulation_id="sim_filter",
        simulation_requirement="requirement",
        document_text="document",
    )

    # 人设和Agent活动配置必须收到完全相同的实体列表，
    # 否则 profile 的 user_id 会和 agent_config 的 agent_id 指向不同实体
    assert [e.name for e in seen["profiles"]] == [
        "Elon Musk",
        "Goldman Sachs",
        "Tsinghua University",
    ]
    assert seen["profiles"] == seen["configs"]
    assert all(left is right for left, right in zip(seen["profiles"], seen["configs"]))
    assert state.entities_count == len(seen["profiles"]) == state.profiles_count


def test_prepare_simulation_binds_real_profiles_to_real_agent_configs(tmp_path, monkeypatch):
    """End-to-end positional invariant, with the *real* profile generator.

    The stubbed invariant test above cannot see the generator's own safety-net
    filter, which is the thing that could renumber ``user_id`` after
    ``agent_id`` has already been handed out. This one runs the real
    ``generate_profiles_from_entities`` and the real
    ``_generate_agent_configs_batch`` (LLM forced onto its rule-based path) and
    checks the join the runtime actually performs: agent graph built from the
    profiles file, looked up by the config's ``agent_id``.
    """
    _offline_real_generator(monkeypatch)
    entities = [
        _entity("Elon Musk"),
        _entity("None"),
        _entity("Goldman Sachs", label="Company"),
        _entity("供应链细节、管理层电话会议解析、单位经济效益"),
        _entity("MiroFish"),
        _entity("Tsinghua University", label="University"),
    ]
    captured = {}

    class RealishConfigGenerator(SimulationConfigGenerator):
        # 小批量，确保跨批次的 start_idx 偏移也被覆盖
        AGENTS_PER_BATCH = 2

        def __init__(self, *args, **kwargs):
            pass

        def _call_llm_with_retry(self, *args, **kwargs):
            raise RuntimeError("no LLM in tests")

        def generate_config(self, entities, **kwargs):
            configs = []
            for start in range(0, len(entities), self.AGENTS_PER_BATCH):
                configs.extend(self._generate_agent_configs_batch(
                    context="context",
                    entities=entities[start:start + self.AGENTS_PER_BATCH],
                    start_idx=start,
                    simulation_requirement="requirement",
                ))
            captured["configs"] = configs
            return _StubParameters()

    monkeypatch.setattr(simulation_manager_module, "ZepEntityReader", _make_reader(entities))
    monkeypatch.setattr(
        simulation_manager_module, "SimulationConfigGenerator", RealishConfigGenerator
    )

    manager = _prepared_manager(tmp_path, simulation_id="sim_real")
    state = manager.prepare_simulation(
        simulation_id="sim_real",
        simulation_requirement="requirement",
        document_text="document",
        use_llm_for_profiles=False,
        parallel_profile_count=1,
    )

    # 运行期的 agent graph 是从这个文件建的
    profiles_file = os.path.join(str(tmp_path), "sim_real", "reddit_profiles.json")
    rows = json.loads(open(profiles_file, encoding="utf-8").read())
    agent_graph = {row["user_id"]: row["name"] for row in rows}

    assert [row["name"] for row in rows] == [
        "Elon Musk",
        "Goldman Sachs",
        "Tsinghua University",
    ]
    assert sorted(agent_graph) == [0, 1, 2]

    configs = captured["configs"]
    assert [c.agent_id for c in configs] == [0, 1, 2]
    # 每条活动配置必须落在它自己那个人设上
    for config in configs:
        assert config.agent_id in agent_graph, config.agent_id
        assert agent_graph[config.agent_id] == config.entity_name
    assert state.entities_count == state.profiles_count == 3


def test_prepare_simulation_rejects_profile_count_mismatch(tmp_path, monkeypatch):
    """The backstop: a generator that returns fewer profiles must abort the run.

    Without it, ``user_id`` and ``agent_id`` drift apart silently.
    """
    entities = [_entity("Elon Musk"), _entity("Goldman Sachs", label="Company")]

    class ShrinkingProfileGenerator:
        def __init__(self, *args, **kwargs):
            pass

        def generate_profiles_from_entities(self, entities, **kwargs):
            return [
                generator_module.OasisAgentProfile(
                    user_id=0, user_name="user_0", name=entities[0].name,
                    bio="", persona="",
                )
            ]

        def save_profiles(self, **kwargs):
            raise AssertionError("must abort before saving profiles")

    class ExplodingConfigGenerator:
        def __init__(self, *args, **kwargs):
            pass

        def generate_config(self, **kwargs):
            raise AssertionError("must abort before generating agent configs")

    monkeypatch.setattr(simulation_manager_module, "ZepEntityReader", _make_reader(entities))
    monkeypatch.setattr(
        simulation_manager_module, "OasisProfileGenerator", ShrinkingProfileGenerator
    )
    monkeypatch.setattr(
        simulation_manager_module, "SimulationConfigGenerator", ExplodingConfigGenerator
    )

    manager = _prepared_manager(tmp_path, simulation_id="sim_mismatch")
    with pytest.raises(ValueError, match="人设数量与实体数量不一致"):
        manager.prepare_simulation(
            simulation_id="sim_mismatch",
            simulation_requirement="requirement",
            document_text="document",
        )


def test_all_entities_rejected_reports_the_filter_not_the_graph(tmp_path, monkeypatch):
    """The error must not blame graph construction when the graph was fine."""
    entities = [_entity("None"), _entity("节点"), _entity("MiroFish")]

    monkeypatch.setattr(simulation_manager_module, "ZepEntityReader", _make_reader(entities))

    manager = _prepared_manager(tmp_path, simulation_id="sim_all_rejected")
    expected = t('progress.allPersonaEntitiesSkipped', count=3)

    with pytest.raises(ValueError) as excinfo:
        manager.prepare_simulation(
            simulation_id="sim_all_rejected",
            simulation_requirement="requirement",
            document_text="document",
        )

    assert str(excinfo.value) == expected
    assert "图谱是否正确构建" not in str(excinfo.value)
    persisted = json.loads(
        (tmp_path / "sim_all_rejected" / "state.json").read_text(encoding="utf-8")
    )
    assert persisted["error"] == expected
    assert persisted["status"] == "failed"


def test_all_invalid_entities_yield_no_profiles_and_no_progress_callback(monkeypatch):
    generator = _stub_generator(monkeypatch)
    events = []

    profiles = generator.generate_profiles_from_entities(
        entities=[_entity("None"), _entity("  "), _entity("edges")],
        use_llm=False,
        progress_callback=lambda current, total, message: events.append(
            (current, total, message)
        ),
        parallel_count=1,
    )

    assert profiles == []
    # total为0时不能回调，否则调用方 int(current / total * 100) 会除零
    assert events == []
