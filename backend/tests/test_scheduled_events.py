from scripts.scheduled_events import build_post_actions, group_events_by_round


def _event(round_value, content="内容", poster_agent_id=0):
    return {"round": round_value, "content": content, "poster_agent_id": poster_agent_id}


def test_groups_valid_events_by_round_in_input_order():
    events = [_event(2, "甲"), _event(1, "乙"), _event(2, "丙")]

    by_round, warnings = group_events_by_round(events, total_rounds=3)

    assert warnings == []
    assert [e["content"] for e in by_round[1]] == ["乙"]
    assert [e["content"] for e in by_round[2]] == ["甲", "丙"]


def test_empty_or_missing_list_is_a_no_op():
    for value in ([], None):
        by_round, warnings = group_events_by_round(value, total_rounds=3)
        assert by_round == {}
        assert warnings == []


def test_integral_numeric_strings_and_floats_are_accepted():
    by_round, warnings = group_events_by_round(
        [_event("2", "字符串"), _event(3.0, "浮点")], total_rounds=3
    )

    assert warnings == []
    assert [e["content"] for e in by_round[2]] == ["字符串"]
    assert [e["content"] for e in by_round[3]] == ["浮点"]


def test_malformed_events_are_skipped_with_a_warning_and_valid_ones_survive():
    events = [
        "不是对象",
        {"content": "缺少轮次"},
        _event(None, "空轮次"),
        _event("abc", "非数字"),
        _event(2.5, "非整数"),
        _event(True, "布尔值"),
        _event(1, ""),
        _event(1, "   "),
        {"round": 1, "content": None},
        _event(1, "有效"),
    ]

    by_round, warnings = group_events_by_round(events, total_rounds=3)

    assert [e["content"] for e in by_round[1]] == ["有效"]
    assert sum(len(v) for v in by_round.values()) == 1
    assert len(warnings) == 9


def test_non_list_value_is_ignored_with_a_warning():
    by_round, warnings = group_events_by_round({"round": 1, "content": "x"}, total_rounds=3)

    assert by_round == {}
    assert len(warnings) == 1


def test_out_of_range_rounds_are_dropped_with_one_explicit_warning():
    events = [_event(0, "零"), _event(-1, "负数"), _event(4, "超出"), _event(4, "超出2"), _event(3, "边界")]

    by_round, warnings = group_events_by_round(events, total_rounds=3)

    assert list(by_round) == [3]
    assert len(warnings) == 1
    assert "4 条" in warnings[0]
    assert "[-1, 0, 4]" in warnings[0]


class _Agent:
    def __init__(self, agent_id):
        self.agent_id = agent_id


def _get_agent_from(agents):
    def get_agent(agent_id):
        return agents[agent_id]
    return get_agent


def test_same_agent_posts_in_one_round_are_kept_as_a_list_in_order():
    agents = {0: _Agent(0), 1: _Agent(1)}
    posts = [
        {"poster_agent_id": 1, "content": "第一条"},
        {"poster_agent_id": 0, "content": "其他"},
        {"poster_agent_id": 1, "content": "第二条"},
        {"poster_agent_id": 1, "content": "第三条"},
    ]

    actions, posted, warnings = build_post_actions(posts, _get_agent_from(agents), lambda c: c)

    assert warnings == []
    assert actions[agents[1]] == ["第一条", "第二条", "第三条"]
    assert actions[agents[0]] == "其他"
    assert posted == [(1, "第一条"), (0, "其他"), (1, "第二条"), (1, "第三条")]


def test_unknown_agent_is_skipped_with_a_warning():
    agents = {0: _Agent(0)}
    posts = [{"poster_agent_id": 99, "content": "幽灵"}, {"poster_agent_id": 0, "content": "正常"}]

    actions, posted, warnings = build_post_actions(posts, _get_agent_from(agents), lambda c: c)

    assert actions == {agents[0]: "正常"}
    assert posted == [(0, "正常")]
    assert len(warnings) == 1
    assert "99" in warnings[0]


def test_missing_poster_agent_id_defaults_to_agent_zero():
    agents = {0: _Agent(0)}

    actions, posted, _ = build_post_actions([{"content": "默认"}], _get_agent_from(agents), lambda c: c)

    assert actions == {agents[0]: "默认"}
    assert posted == [(0, "默认")]
