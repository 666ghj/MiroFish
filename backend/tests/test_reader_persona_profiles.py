"""显式读者 Persona 的确定性 profile 注入（novel-mac fork，改造 ②）。

ReaderPersona 实体（novel seed 写入）的 OASIS profile 一律确定性生成：
不经 LLM、数值字段不随机、同实体两次生成完全一致。其他实体类型保持
既有 LLM/规则路径不变。
"""

from __future__ import annotations

import pytest

from app.services.oasis_profile_generator import OasisProfileGenerator
from app.services.zep_entity_reader import EntityNode


def _persona_entity() -> EntityNode:
    return EntityNode(
        uuid="novel_wugang_mystery-reader",
        name="悬疑读者",
        labels=["Entity", "ReaderPersona"],
        summary="追线索、讨厌降智",
        attributes={
            "id": "mystery-reader",
            "name": "悬疑读者",
            "description": "追线索、讨厌降智，重视信息差公平性",
            "readingHistory": "读过上架前三章",
        },
    )


def _character_entity() -> EntityNode:
    return EntityNode(
        uuid="novel_wugang_linyan",
        name="林砚",
        labels=["Entity", "Character"],
        summary="雾港夜班航标维护员",
        attributes={"id": "linyan", "name": "林砚"},
    )


@pytest.fixture()
def no_llm(monkeypatch):
    def _must_not_call_llm(*_args, **_kwargs):
        raise AssertionError("ReaderPersona/Character 走了 LLM 路径")

    monkeypatch.setattr(
        OasisProfileGenerator, "_generate_profile_with_llm", _must_not_call_llm
    )


def test_reader_persona_profile_is_deterministic_without_llm(no_llm):
    generator = OasisProfileGenerator()
    entity = _persona_entity()

    first = generator.generate_profile_from_entity(entity, user_id=0, use_llm=True)
    second = generator.generate_profile_from_entity(entity, user_id=0, use_llm=True)

    assert first is not None
    assert first.persona == second.persona
    assert first.to_dict() == second.to_dict()
    assert "追线索、讨厌降智" in first.persona
    assert "读过上架前三章" in first.persona
    assert first.source_entity_type == "ReaderPersona"
    assert first.user_name  # username 可用作 OASIS 账号


def test_reader_persona_platform_formats_carry_persona(no_llm):
    generator = OasisProfileGenerator()
    profile = generator.generate_profile_from_entity(
        _persona_entity(), user_id=3, use_llm=True
    )

    reddit = profile.to_reddit_format()
    assert reddit["username"] == profile.user_name
    assert "追线索" in reddit["persona"]
    assert reddit["user_id"] == 3

    twitter = profile.to_twitter_format()
    assert twitter["username"] == profile.user_name
    assert "追线索" in twitter["persona"]


def test_non_persona_entities_still_use_configured_paths(no_llm):
    generator = OasisProfileGenerator()

    # use_llm=True 且 LLM 被钉死抛错：Character 必须仍走 LLM 路径（异常透传），
    # 证明 ReaderPersona 分支没有劫持普通实体。
    with pytest.raises(AssertionError, match="LLM 路径"):
        generator.generate_profile_from_entity(
            _character_entity(), user_id=0, use_llm=True
        )

    # use_llm=False 时走既有规则路径，正常返回。
    rule_based = generator.generate_profile_from_entity(
        _character_entity(), user_id=1, use_llm=False
    )
    assert rule_based.source_entity_type == "Character"
    assert rule_based.persona
