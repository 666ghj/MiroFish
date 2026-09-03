from app.services.simulation_config_generator import (
    AgentActivityConfig,
    EventConfig,
    SimulationConfigGenerator,
)


def _agent(agent_id: int, name: str, entity_type: str, influence: float = 1.0):
    return AgentActivityConfig(
        agent_id=agent_id,
        entity_uuid=f"uuid-{agent_id}",
        entity_name=name,
        entity_type=entity_type,
        influence_weight=influence,
    )


def _generator() -> SimulationConfigGenerator:
    # 跳过 __init__（无需 API key），与现有测试的构造方式一致
    return object.__new__(SimulationConfigGenerator)


def test_assign_agents_resolves_poster_type_for_initial_posts_and_scheduled_events():
    generator = _generator()
    agents = [_agent(0, "官方", "Official"), _agent(1, "新闻台", "MediaOutlet")]

    event_config = EventConfig(
        initial_posts=[{"content": "初始帖子", "poster_type": "Official"}],
        scheduled_events=[{"round": 2, "content": "定时事件", "poster_type": "MediaOutlet"}],
    )

    updated = generator._assign_initial_post_agents(event_config, agents)

    assert updated.initial_posts[0]["poster_agent_id"] == 0
    assert updated.scheduled_events[0]["poster_agent_id"] == 1
    # 定时事件需保留其轮次信息
    assert updated.scheduled_events[0]["round"] == 2


def test_anti_repetition_carries_across_both_lists():
    generator = _generator()
    agents = [_agent(0, "甲", "Official"), _agent(1, "乙", "Official")]

    event_config = EventConfig(
        initial_posts=[{"content": "第一帖", "poster_type": "Official"}],
        scheduled_events=[{"round": 2, "content": "第二帖", "poster_type": "Official"}],
    )

    updated = generator._assign_initial_post_agents(event_config, agents)

    # used_indices 跨两个列表共享：第一帖用 agent 0，第二帖轮转到 agent 1
    assert updated.initial_posts[0]["poster_agent_id"] == 0
    assert updated.scheduled_events[0]["poster_agent_id"] == 1


def test_empty_lists_are_a_no_op():
    generator = _generator()
    event_config = EventConfig(initial_posts=[], scheduled_events=[])

    updated = generator._assign_initial_post_agents(event_config, [_agent(0, "官方", "Official")])

    assert updated is event_config
    assert updated.initial_posts == []
    assert updated.scheduled_events == []


def test_unknown_poster_type_falls_back_to_highest_influence_agent():
    generator = _generator()
    agents = [
        _agent(0, "低影响", "Student", influence=0.5),
        _agent(1, "高影响", "Professor", influence=2.0),
    ]

    updated = generator._assign_agents_to_posts(
        [{"content": "未知类型", "poster_type": "Alien"}], agents
    )

    assert updated[0]["poster_agent_id"] == 1
