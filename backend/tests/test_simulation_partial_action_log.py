from types import SimpleNamespace
import json

import pytest

from app.services import simulation_runner as runner_module
from app.services.simulation_runner import SimulationRunState, SimulationRunner


@pytest.mark.parametrize("split_inside_utf8", [False, True])
@pytest.mark.parametrize("graph_enabled", [False, True])
def test_action_monitor_retries_partial_record_without_replaying_completed_actions(
    monkeypatch, tmp_path, split_inside_utf8, graph_enabled
):
    simulation_id = "partial-action-log"
    monkeypatch.setattr(
        SimulationRunner, "_graph_memory_enabled", {simulation_id: graph_enabled}
    )
    graph_activities = []
    updater = SimpleNamespace(
        add_activity_from_dict=lambda data, platform: graph_activities.append(data["agent_id"])
    )
    monkeypatch.setattr(
        runner_module.ZepGraphMemoryManager, "get_updater", lambda _simulation_id: updater
    )
    state = SimulationRunState(simulation_id=simulation_id)
    log_path = tmp_path / "actions.jsonl"
    first = json.dumps({"agent_id": 1, "action_type": "CREATE_POST"}).encode() + b"\n"
    second = json.dumps(
        {"agent_id": 2, "action_type": "CREATE_POST", "agent_name": "中文"},
        ensure_ascii=False,
    ).encode() + b"\n"
    split = second.index("中".encode()) + 1 if split_inside_utf8 else 15
    log_path.write_bytes(first + second[:split])

    position = SimulationRunner._read_action_log(str(log_path), 0, state, "twitter")
    assert position == len(first)
    assert [action.agent_id for action in state.recent_actions] == [1]

    with log_path.open("ab") as stream:
        stream.write(second[split:])
    position = SimulationRunner._read_action_log(str(log_path), position, state, "twitter")
    assert position == len(first + second)
    assert sorted(action.agent_id for action in state.recent_actions) == [1, 2]
    assert next(action for action in state.recent_actions if action.agent_id == 2).agent_name == "中文"

    assert SimulationRunner._read_action_log(str(log_path), position, state, "twitter") == position
    assert len(state.recent_actions) == 2
    assert graph_activities == ([1, 2] if graph_enabled else [])
