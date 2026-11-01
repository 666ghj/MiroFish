import asyncio
import json
import os

import pytest

import sim_control


def run(coroutine):
    return asyncio.run(coroutine)


def test_a_missing_corrupt_or_unknown_request_means_keep_running(tmp_path):
    folder = str(tmp_path)
    assert sim_control.read_action(folder) == "run"                       # no file
    (tmp_path / "control.json").write_text("{not json", encoding="utf-8")
    assert sim_control.read_action(folder) == "run"                       # half-written
    (tmp_path / "control.json").write_text(json.dumps({"action": "explode"}), encoding="utf-8")
    assert sim_control.read_action(folder) == "run"                       # unknown
    (tmp_path / "control.json").write_text("[1, 2]", encoding="utf-8")
    assert sim_control.read_action(folder) == "run"                       # not an object


def test_a_request_round_trips_and_can_be_cleared(tmp_path):
    folder = str(tmp_path)
    for action in ("pause", "stop", "run"):
        sim_control.write_action(folder, action)
        assert sim_control.read_action(folder) == action
    with pytest.raises(ValueError):
        sim_control.write_action(folder, "explode")
    sim_control.write_action(folder, "stop")
    sim_control.clear(folder)
    assert not os.path.exists(sim_control.control_path(folder))
    sim_control.clear(folder)                                              # clearing nothing is fine
    assert sim_control.read_action(folder) == "run"


def test_nothing_requested_costs_no_waiting(tmp_path):
    lines = []
    assert run(sim_control.honour(str(tmp_path), lines.append, "Twitter", 3)) == "run"
    assert lines == []


def test_a_stop_request_ends_the_run_before_the_round(tmp_path):
    sim_control.write_action(str(tmp_path), "stop")
    lines = []
    assert run(sim_control.honour(str(tmp_path), lines.append, "Twitter", 7)) == "stop"
    assert len(lines) == 1 and "Twitter" in lines[0] and "7" in lines[0]


def test_a_pause_waits_at_the_boundary_until_it_is_lifted(tmp_path):
    folder = str(tmp_path)
    sim_control.write_action(folder, "pause")
    sleeps = []

    async def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 3:
            sim_control.write_action(folder, "run")                       # the user clicks Continue

    lines = []
    assert run(sim_control.honour(folder, lines.append, "Reddit", 5, sleep=sleep)) == "run"
    assert len(sleeps) == 3
    assert len(lines) == 2 and "paused" in lines[0] and "continuing" in lines[1]   # said once each, not every second


def test_a_stop_while_paused_stops_instead_of_resuming(tmp_path):
    folder = str(tmp_path)
    sim_control.write_action(folder, "pause")

    async def sleep(_seconds):
        sim_control.write_action(folder, "stop")

    assert run(sim_control.honour(folder, lambda _m: None, "Reddit", 5, sleep=sleep)) == "stop"


def test_the_processs_own_shutdown_flag_ends_a_pause(tmp_path):
    folder = str(tmp_path)
    sim_control.write_action(folder, "pause")
    polls = []

    async def sleep(_seconds):
        polls.append(1)

    # a SIGTERM must never be held up by a pause
    assert run(sim_control.honour(folder, lambda _m: None, "Reddit", 5, should_abort=lambda: len(polls) >= 2, sleep=sleep)) == "run"
    assert len(polls) == 2
