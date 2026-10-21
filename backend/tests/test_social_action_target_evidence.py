"""Preserve the pinned OASIS mute trace target through action and memory exports."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
from types import ModuleType, SimpleNamespace

import pytest

from app.services import simulation_runner as runner_module
from app.services.simulation_runner import SimulationRunState, SimulationRunner
from app.services.zep_graph_memory_updater import AgentActivity


@pytest.fixture
def runner_script(monkeypatch):
    # Load complete production scripts; only optional SDK import-time names
    # are doubled. No SDK function, model, or simulation is executed here.
    camel = ModuleType("camel")
    models = ModuleType("camel.models")
    models.ModelFactory = object()
    types = ModuleType("camel.types")
    types.ModelPlatformType = SimpleNamespace(OPENAI="openai")
    oasis = ModuleType("oasis")
    names = ("CREATE_POST LIKE_POST REPOST FOLLOW DO_NOTHING QUOTE_POST DISLIKE_POST "
             "CREATE_COMMENT LIKE_COMMENT DISLIKE_COMMENT SEARCH_POSTS SEARCH_USER "
             "TREND REFRESH MUTE INTERVIEW").split()
    oasis.ActionType = SimpleNamespace(**{name: SimpleNamespace(value=name.lower()) for name in names})
    for name in ["LLMAction", "ManualAction", "generate_twitter_agent_graph", "generate_reddit_agent_graph"]:
        setattr(oasis, name, object())
    for name, module in [("camel", camel), ("camel.models", models), ("camel.types", types), ("oasis", oasis)]:
        monkeypatch.setitem(sys.modules, name, module)
    scripts = Path(runner_module.__file__).resolve().parents[2] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location("mute_runner", scripts / "run_parallel_simulation.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    logger_spec = importlib.util.spec_from_file_location("mute_logger", scripts / "action_logger.py")
    logger_module = importlib.util.module_from_spec(logger_spec)
    logger_spec.loader.exec_module(logger_module)
    return module, logger_module


@pytest.mark.parametrize("action_type,target_id", [("mute", 0), ("mute", 7), ("follow", 0),
                                                  ("create_comment", 0), ("create_comment_explicit", 0)])
def test_target_name_survives_trace_action_log_monitor_and_memory(
    runner_script, monkeypatch, tmp_path, action_type, target_id
):
    module, logger_module = runner_script
    database = tmp_path / "trace.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE trace (user_id INTEGER, action TEXT, info TEXT)")
        connection.execute("CREATE TABLE user (user_id INTEGER, agent_id INTEGER, name TEXT, user_name TEXT)")
        connection.execute("INSERT INTO user VALUES (?, ?, ?, ?)", (target_id, target_id, "Target User", "target"))
        connection.execute("CREATE TABLE follow (follow_id INTEGER, followee_id INTEGER)")
        connection.execute("INSERT INTO follow VALUES (1, ?)", (target_id,))
        connection.execute("CREATE TABLE post (post_id INTEGER, content TEXT, user_id INTEGER)")
        connection.execute("INSERT INTO post VALUES (4, 'Original discussion', ?)", (target_id,))
        connection.execute("CREATE TABLE comment (comment_id INTEGER, post_id INTEGER)")
        connection.execute("INSERT INTO comment VALUES (22, 4)")
        if action_type.startswith("create_comment"):
            info = {"content": "A reply", "comment_id": 22}
            if action_type == "create_comment_explicit":
                info["post_id"] = 4
            trace_type = "create_comment"
        else:
            info = {"mutee_id": target_id} if action_type == "mute" else {"follow_id": 1}
            trace_type = action_type
        connection.execute("INSERT INTO trace VALUES (9, ?, ?)", (trace_type, json.dumps(info)))
    actions, last_row = module.fetch_new_actions_from_db(str(database), 0, {9: "Actor", target_id: "Target User"})
    assert last_row == 1
    assert len(actions) == 1
    writer = logger_module.PlatformActionLogger("reddit", str(tmp_path / "simulation"))
    writer.log_action(round_num=1, **actions[0])
    monkeypatch.setattr(SimulationRunner, "_graph_memory_enabled", {})
    state = SimulationRunState(simulation_id="simulation")
    SimulationRunner._read_action_log(writer.log_path, 0, state, "reddit")
    action = state.recent_actions[0]
    if action_type.startswith("create_comment"):
        assert action.action_args["post_id"] == 4
        assert action.action_args["post_content"] == "Original discussion"
        assert action.action_args["post_author_name"] == "Target User"
    else:
        assert action.action_args["target_user_name"] == "Target User"
    if action_type == "mute":
        assert action.action_args["mutee_id"] == target_id
    activity = AgentActivity(
        platform="reddit", agent_id=9, agent_name="Actor", action_type=action.action_type,
        action_args=action.action_args, round_num=1, timestamp=action.timestamp,
    )
    assert "Target User" in activity.to_episode_text()
    if action_type.startswith("create_comment"):
        assert "Original discussion" in activity.to_episode_text()
        assert "A reply" in activity.to_episode_text()
