"""A timed-out client may remove its command during server enumeration."""
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

from app.services import simulation_ipc as ipc_module
from app.services.simulation_ipc import SimulationIPCServer


@pytest.fixture(params=["server", "twitter", "reddit", "parallel"])
def ipc_handler(request, monkeypatch, tmp_path):
    if request.param == "server":
        return SimulationIPCServer(str(tmp_path))

    # Import the complete production scripts without installing or invoking
    # optional model/simulation SDKs. Only their import-time names are needed
    # for these filesystem-only polling tests; no simulated activity is run.
    camel = ModuleType("camel")
    models = ModuleType("camel.models")
    models.ModelFactory = object()
    types = ModuleType("camel.types")
    types.ModelPlatformType = SimpleNamespace(OPENAI="openai")
    oasis = ModuleType("oasis")
    action_names = (
        "CREATE_POST LIKE_POST REPOST FOLLOW DO_NOTHING QUOTE_POST DISLIKE_POST "
        "CREATE_COMMENT LIKE_COMMENT DISLIKE_COMMENT SEARCH_POSTS SEARCH_USER "
        "TREND REFRESH MUTE INTERVIEW"
    ).split()
    oasis.ActionType = SimpleNamespace(**{
        name: SimpleNamespace(value=name.lower()) for name in action_names
    })
    for name in ["LLMAction", "ManualAction", "generate_twitter_agent_graph", "generate_reddit_agent_graph"]:
        setattr(oasis, name, object())
    for name, module in [("camel", camel), ("camel.models", models), ("camel.types", types), ("oasis", oasis)]:
        monkeypatch.setitem(sys.modules, name, module)
    scripts_dir = Path(ipc_module.__file__).resolve().parents[2] / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))
    spec = importlib.util.spec_from_file_location(
        f"ipc_poll_{request.param}", scripts_dir / f"run_{request.param}_simulation.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if request.param == "parallel":
        return module.ParallelIPCHandler(str(tmp_path))
    return module.IPCHandler(str(tmp_path), env=None, agent_graph=None)


@pytest.mark.parametrize("healthy_command", [False, True])
def test_poll_ignores_command_expiring_after_directory_listing(
    ipc_handler, monkeypatch, healthy_command
):
    commands = Path(ipc_handler.commands_dir)
    expired = commands / "expired.json"
    expired.write_text("{}", encoding="utf-8")
    if healthy_command:
        (commands / "healthy.json").write_text(json.dumps({
            "command_id": "healthy", "command_type": "close_env", "args": {}
        }), encoding="utf-8")
    import os
    original_getmtime = os.path.getmtime
    expired_during_poll = []

    def client_timeout_before_stat(path):
        if Path(path) == expired:
            expired.unlink()
            expired_during_poll.append(True)
        return original_getmtime(path)

    monkeypatch.setattr(os.path, "getmtime", client_timeout_before_stat)
    poll = getattr(ipc_handler, "poll_commands", None) or ipc_handler.poll_command
    result = poll()
    assert expired_during_poll == [True]
    if healthy_command:
        command_id = result["command_id"] if isinstance(result, dict) else result.command_id
        assert command_id == "healthy"
    else:
        assert result is None
