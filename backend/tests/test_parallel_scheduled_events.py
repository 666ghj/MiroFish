import asyncio
import json
import sqlite3

import pytest

pytest.importorskip("oasis")

from scripts import run_parallel_simulation as rps  # noqa: E402


class FakeAgent:
    def __init__(self, agent_id):
        self.agent_id = agent_id
        self.name = f"agent_{agent_id}"


class FakeAgentGraph:
    def __init__(self, count):
        self._agents = {i: FakeAgent(i) for i in range(count)}

    def get_agent(self, agent_id):
        return self._agents[agent_id]

    def get_agents(self):
        return list(self._agents.items())


class FakeEnv:
    """记录 env.step() 调用，并像 OASIS 一样把执行的动作写入 trace 表"""

    def __init__(self, agent_graph, database_path):
        self.agent_graph = agent_graph
        self.database_path = database_path
        self.steps = []
        conn = sqlite3.connect(database_path)
        conn.execute("CREATE TABLE trace (user_id INTEGER, created_at TEXT, action TEXT, info TEXT)")
        conn.commit()
        conn.close()

    async def reset(self):
        pass

    async def step(self, actions):
        self.steps.append(actions)
        conn = sqlite3.connect(self.database_path)
        for agent, action in actions.items():
            for single in action if isinstance(action, list) else [action]:
                if isinstance(single, rps.ManualAction):
                    conn.execute(
                        "INSERT INTO trace VALUES (?, '', ?, ?)",
                        (agent.agent_id, single.action_type.value, json.dumps(single.action_args)),
                    )
                else:
                    conn.execute(
                        "INSERT INTO trace VALUES (?, '', 'do_nothing', '{}')",
                        (agent.agent_id,),
                    )
        conn.commit()
        conn.close()


PLATFORMS = {
    "twitter": (rps.run_twitter_simulation, "generate_twitter_agent_graph", "twitter_profiles.csv"),
    "reddit": (rps.run_reddit_simulation, "generate_reddit_agent_graph", "reddit_profiles.json"),
}


def _config(scheduled_events, agent_configs=None):
    return {
        "time_config": {
            "total_simulation_hours": 4,
            "minutes_per_round": 60,
            "agents_per_hour_min": 2,
            "agents_per_hour_max": 2,
            "peak_hours": [],
            "off_peak_hours": [],
        },
        "agent_configs": agent_configs or [],
        "event_config": {"initial_posts": [], "scheduled_events": scheduled_events},
    }


def _run(monkeypatch, tmp_path, platform, config, agent_count=2):
    runner, graph_factory, profile_name = PLATFORMS[platform]
    (tmp_path / profile_name).write_text("", encoding="utf-8")
    graph = FakeAgentGraph(agent_count)

    async def fake_graph(**_kwargs):
        return graph

    envs = []

    def fake_make(**kwargs):
        envs.append(FakeEnv(kwargs["agent_graph"], kwargs["database_path"]))
        return envs[-1]

    monkeypatch.setattr(rps, "create_model", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(rps, graph_factory, fake_graph)
    monkeypatch.setattr(rps.oasis, "make", fake_make)

    logger = rps.PlatformActionLogger(platform, str(tmp_path))
    result = asyncio.run(runner(config, str(tmp_path), action_logger=logger))
    entries = [
        json.loads(line)
        for line in (tmp_path / platform / "actions.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    return envs[0], result, entries


def _manual_steps(env):
    return [
        step for step in env.steps
        if any(
            isinstance(a, rps.ManualAction)
            for action in step.values()
            for a in (action if isinstance(action, list) else [action])
        )
    ]


def _posts(entries):
    return [
        (e["round"], e["agent_id"], e["action_args"].get("content"))
        for e in entries
        if e.get("action_type") == "CREATE_POST"
    ]


def _round_end_counts(entries):
    return {e["round"]: e["actions_count"] for e in entries if e.get("event_type") == "round_end"}


@pytest.mark.parametrize("platform", ["twitter", "reddit"])
def test_events_fire_in_their_round_with_no_active_agents_and_are_logged(monkeypatch, tmp_path, platform):
    events = [
        {"round": 2, "content": "甲一", "poster_agent_id": 1},
        {"round": 2, "content": "乙", "poster_agent_id": 0},
        {"round": 2, "content": "甲二", "poster_agent_id": 1},
        {"round": 3, "content": "丙", "poster_agent_id": 0},
    ]

    env, result, entries = _run(monkeypatch, tmp_path, platform, _config(events))

    # 默认并行路径：本轮没有活跃 Agent 时，定时事件依然触发
    steps = _manual_steps(env)
    assert len(steps) == 2

    # 同一 Agent 同一轮的多条帖子合并为列表，不互相覆盖
    agent_0 = env.agent_graph.get_agent(0)
    agent_1 = env.agent_graph.get_agent(1)
    assert [a.action_args["content"] for a in steps[0][agent_1]] == ["甲一", "甲二"]
    assert steps[0][agent_0].action_args["content"] == "乙"

    # 动作日志：每条帖子只记录一次，记录在其触发轮次
    assert sorted(_posts(entries)) == sorted([
        (2, 1, "甲一"), (2, 0, "乙"), (2, 1, "甲二"), (3, 0, "丙"),
    ])
    assert _round_end_counts(entries) == {0: 0, 1: 0, 2: 3, 3: 1, 4: 0}
    assert result.total_actions == 4
    assert entries[-1]["event_type"] == "simulation_end"
    assert entries[-1]["total_actions"] == 4


@pytest.mark.parametrize("platform", ["twitter", "reddit"])
def test_malformed_and_unresolvable_events_do_not_abort_the_run(monkeypatch, tmp_path, platform):
    events = [
        "不是对象",
        {"round": "abc", "content": "非数字轮次", "poster_agent_id": 0},
        {"round": 2.5, "content": "非整数轮次", "poster_agent_id": 0},
        {"round": 1, "content": "", "poster_agent_id": 0},
        {"round": 9, "content": "超出轮数", "poster_agent_id": 0},
        {"round": 1, "content": "未知 Agent", "poster_agent_id": 99},
        {"round": 1, "content": "有效", "poster_agent_id": 0},
    ]

    env, result, entries = _run(monkeypatch, tmp_path, platform, _config(events))

    assert _posts(entries) == [(1, 0, "有效")]
    assert len(_manual_steps(env)) == 1
    assert _round_end_counts(entries) == {0: 0, 1: 1, 2: 0, 3: 0, 4: 0}
    assert entries[-1]["event_type"] == "simulation_end"


@pytest.mark.parametrize("platform", ["twitter", "reddit"])
def test_events_publish_before_active_agents_act_and_are_not_logged_twice(monkeypatch, tmp_path, platform):
    agent_configs = [
        {"agent_id": i, "active_hours": list(range(24)), "activity_level": 1.0}
        for i in range(2)
    ]
    events = [{"round": 2, "content": "事件", "poster_agent_id": 0}]

    env, result, entries = _run(
        monkeypatch, tmp_path, platform, _config(events, agent_configs)
    )

    # 第 2 轮：先发布定时事件，再执行 LLM 动作
    manual = _manual_steps(env)
    assert len(manual) == 1
    event_index = env.steps.index(manual[0])
    assert all(isinstance(a, rps.LLMAction) for a in env.steps[event_index + 1].values())

    assert _posts(entries) == [(2, 0, "事件")]
    # 每轮 2 个活跃 Agent 各一个动作；第 2 轮另加定时事件
    assert _round_end_counts(entries) == {0: 0, 1: 2, 2: 3, 3: 2, 4: 2}
    assert result.total_actions == 9


@pytest.mark.parametrize("platform", ["twitter", "reddit"])
def test_empty_scheduled_events_leave_the_step_sequence_unchanged(monkeypatch, tmp_path, platform):
    agent_configs = [
        {"agent_id": i, "active_hours": list(range(24)), "activity_level": 1.0}
        for i in range(2)
    ]

    env, result, entries = _run(monkeypatch, tmp_path, platform, _config([], agent_configs))

    assert _manual_steps(env) == []
    assert len(env.steps) == 4
    assert _posts(entries) == []
    assert _round_end_counts(entries) == {0: 0, 1: 2, 2: 2, 3: 2, 4: 2}
