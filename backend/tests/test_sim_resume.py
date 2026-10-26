"""Resume points, checkpoints and the scheduling replay (scripts/sim_resume.py)."""

import copy
import json
import sqlite3
from datetime import datetime
from types import SimpleNamespace

import pytest

import sim_behavior
import sim_resume


# --- building logs -------------------------------------------------------------

def write_log(path, records, trailing=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as handle:
        for record in records:
            handle.write((json.dumps(record) + "\n").encode("utf-8"))
        handle.write(trailing.encode("utf-8"))


def action(round_num, agent_id=1, **extra):
    return {"round": round_num, "agent_id": agent_id, "agent_name": f"A{agent_id}", "action_type": "CREATE_POST",
            "action_args": {}, "success": True, **extra}


def round_start(n, ids):
    return {"round": n, "event_type": "round_start", "simulated_hour": n, "active_agent_ids": ids}


def round_end(n, count=0):
    return {"round": n, "event_type": "round_end", "actions_count": count}


def finished_rounds(count):
    """Setup (two follow records, one initial post) and ``count`` finished rounds of two actions each."""
    records = [
        round_start(0, []),
        action(0, 1, phase="setup", action_type="FOLLOW"),
        action(0, 2, phase="setup", action_type="FOLLOW"),
        action(0, 3),
        round_end(0, 1),
    ]
    for n in range(1, count + 1):
        records += [round_start(n, [n, n + 1]), action(n, n), action(n, n + 1), round_end(n, 2)]
    return records


# --- scanning the log --------------------------------------------------------------

def test_the_last_finished_round_is_the_last_round_end(tmp_path):
    log = tmp_path / "actions.jsonl"
    write_log(log, finished_rounds(3) + [round_start(4, [9, 8]), action(4, 9)])

    scan = sim_resume.scan_log(str(log))

    assert scan.setup_done and scan.last_round == 3
    assert scan.started[4] == [9, 8]                       # the unfinished round is known, not finished
    assert 4 not in scan.round_offsets
    # setup follows and the poll do not count as actions; the initial post and every round action do
    assert scan.round_totals[0] == 1 and scan.round_totals[3] == 1 + 3 * 2


def test_the_offset_is_the_end_of_the_round_end_line(tmp_path):
    log = tmp_path / "actions.jsonl"
    write_log(log, finished_rounds(2) + [round_start(3, [1]), action(3, 1)])
    scan = sim_resume.scan_log(str(log))

    kept = log.read_bytes()[: scan.round_offsets[2]].decode("utf-8").splitlines()

    assert json.loads(kept[-1]) == round_end(2, 2)
    sim_resume.truncate_log(str(log), scan.round_offsets[2])
    assert log.read_bytes().decode("utf-8").splitlines() == kept


def test_a_line_still_being_written_is_ignored(tmp_path):
    log = tmp_path / "actions.jsonl"
    write_log(log, finished_rounds(1), trailing='{"round": 2, "event_type": "round_en')
    assert sim_resume.scan_log(str(log)).last_round == 1


def test_a_run_that_stopped_during_setup_has_no_resume_point(tmp_path):
    log = tmp_path / "twitter" / "actions.jsonl"
    write_log(log, [round_start(0, []), action(0, 1, phase="setup")])
    plan = sim_resume.plan_resume(str(tmp_path), "twitter")
    assert not plan.resumable and "setting up" in plan.reason


def test_a_missing_log_is_not_resumable(tmp_path):
    plan = sim_resume.plan_resume(str(tmp_path), "twitter")
    assert not plan.resumable and "no action log" in plan.reason


def test_events_the_loop_does_not_count_are_not_actions(tmp_path):
    log = tmp_path / "actions.jsonl"
    records = finished_rounds(1)
    records.insert(-1, action(1, 7, phase="poll"))
    records.insert(-1, action(1, 8, phase="injected"))
    records.insert(-1, {"round": 1, "event_type": "agent_error", "agent_id": 2})
    write_log(log, records)
    assert sim_resume.scan_log(str(log)).round_totals[1] == 1 + 2 + 1      # initial post, two actions, one injected


# --- checkpoints -------------------------------------------------------------------

def make_db(path, rows):
    connection = sqlite3.connect(str(path))
    connection.execute("CREATE TABLE IF NOT EXISTS post (id INTEGER PRIMARY KEY, content TEXT)")
    connection.execute("DELETE FROM post")
    connection.executemany("INSERT INTO post (content) VALUES (?)", [(row,) for row in rows])
    connection.commit()
    connection.close()


def posts(path):
    connection = sqlite3.connect(str(path))
    try:
        return [row[0] for row in connection.execute("SELECT content FROM post ORDER BY id")]
    finally:
        connection.close()


def test_a_checkpoint_restores_the_database_and_knows_its_round(tmp_path):
    db = tmp_path / "twitter_simulation.db"
    make_db(db, ["one", "two"])
    sim_resume.write_checkpoint(str(db), 2, {"time_step": 5})

    make_db(db, ["one", "two", "written by the unfinished round"])
    assert sim_resume.read_checkpoint_info(str(db)) == {"round": 2, "clock": {"time_step": 5}}

    sim_resume.restore_checkpoint(str(db))

    assert posts(db) == ["one", "two"]
    assert sim_resume.read_db_marker(str(db))["round"] == 2           # the restored database carries it too


def test_a_newer_checkpoint_replaces_the_older_one(tmp_path):
    db = tmp_path / "x.db"
    make_db(db, ["a"])
    sim_resume.write_checkpoint(str(db), 1)
    make_db(db, ["a", "b"])
    sim_resume.write_checkpoint(str(db), 2)
    assert sim_resume.read_checkpoint_info(str(db))["round"] == 2


def test_without_a_checkpoint_the_info_is_none(tmp_path):
    db = tmp_path / "x.db"
    make_db(db, ["a"])
    assert sim_resume.read_checkpoint_info(str(db)) is None
    assert sim_resume.read_db_marker(str(db)) is None


def prepare_platform(tmp_path, platform, rounds, *, checkpoint_round=None, unfinished=True):
    records = finished_rounds(rounds) + ([round_start(rounds + 1, [4, 5]), action(rounds + 1, 4)] if unfinished else [])
    write_log(tmp_path / platform / "actions.jsonl", records)
    db = tmp_path / f"{platform}_simulation.db"
    make_db(db, ["p"])
    if checkpoint_round is not None:
        sim_resume.write_checkpoint(str(db), checkpoint_round)
    return db


def test_with_a_matching_checkpoint_the_resume_is_exact(tmp_path):
    prepare_platform(tmp_path, "twitter", 3, checkpoint_round=3)
    plan = sim_resume.plan_resume(str(tmp_path), "twitter")
    assert plan.resumable and plan.round == 3 and plan.exact
    assert plan.unfinished_ids == [4, 5]                                # round 4 will be redone


def test_a_log_one_round_ahead_of_the_checkpoint_goes_back_to_the_checkpoint(tmp_path):
    prepare_platform(tmp_path, "twitter", 3, checkpoint_round=2, unfinished=False)
    plan = sim_resume.plan_resume(str(tmp_path), "twitter")
    assert plan.round == 2 and plan.exact
    assert plan.total_actions == 1 + 2 * 2                              # actions of the rounds that are kept


def test_without_a_checkpoint_it_resumes_from_the_log_but_not_exactly(tmp_path):
    prepare_platform(tmp_path, "twitter", 3)
    plan = sim_resume.plan_resume(str(tmp_path), "twitter")
    assert plan.resumable and plan.round == 3 and not plan.exact


def test_a_checkpoint_from_after_the_log_is_not_trusted(tmp_path):
    prepare_platform(tmp_path, "twitter", 2, checkpoint_round=5)
    plan = sim_resume.plan_resume(str(tmp_path), "twitter")
    assert plan.round == 2 and not plan.exact


def test_no_database_and_no_checkpoint_is_not_resumable(tmp_path):
    prepare_platform(tmp_path, "twitter", 2)
    (tmp_path / "twitter_simulation.db").unlink()
    plan = sim_resume.plan_resume(str(tmp_path), "twitter")
    assert not plan.resumable and "database" in plan.reason


# --- replaying the scheduling ----------------------------------------------------------

def make_config(**overrides):
    agents = [
        {"agent_id": i, "entity_name": f"A{i}", "activity_level": 0.6, "posts_per_hour": 1.0,
         "comments_per_hour": 2.0, "response_delay_min": 5, "response_delay_max": 90,
         "active_hours": list(range(24)), "stance": "neutral"}
        for i in range(12)
    ]
    config = {
        "behavior_version": 2,
        "time_config": {"total_simulation_hours": 48, "minutes_per_round": 60,
                        "agents_per_hour_min": 2, "agents_per_hour_max": 6},
        "agent_configs": agents,
        "event_config": {
            "initial_posts": [{"poster_agent_id": 0, "content": "x"}],
            "scheduled_events": [
                {"id": "e1", "at_sim_hour": 3, "poster_agent_id": 1, "content": "news", "enabled": True},
                {"id": "e2", "at_sim_hour": 7, "poster_agent_id": 2, "content": "more", "enabled": True},
            ],
        },
    }
    config.update(overrides)
    return config


def run_live(config, seed, rounds, platform="twitter"):
    """The run loop's scheduling, round by round, exactly as run_parallel_simulation does it."""
    behavior = sim_behavior.PlatformBehavior(config, platform, seed)
    behavior.planned_follows()                      # consumed once during setup of a fresh run
    if behavior.v2:
        behavior.initial_posts_published()
    chosen = []
    for loop_round in range(rounds):
        hour = ((loop_round * behavior.minutes_per_round) // 60) % 24
        if behavior.v2:
            behavior.events_due(loop_round)
        chosen.append(behavior.select_active(loop_round, hour))
    return chosen


def continue_after_replay(config, seed, replayed_rounds, total_rounds, logged, platform="twitter"):
    behavior = sim_behavior.PlatformBehavior(config, platform, seed)
    sim_resume.replay_schedule(
        behavior, replayed_rounds, agent_exists=lambda _id: True, initial_posted=True, logged_ids=logged,
    )
    chosen = []
    for loop_round in range(replayed_rounds, total_rounds):
        hour = ((loop_round * behavior.minutes_per_round) // 60) % 24
        if behavior.v2:
            behavior.events_due(loop_round)
        chosen.append(behavior.select_active(loop_round, hour))
    return chosen


@pytest.mark.parametrize("version", [2, 1])
@pytest.mark.parametrize("stop_after", [1, 4, 9, 20])
def test_after_the_replay_the_run_continues_exactly_like_an_uninterrupted_one(version, stop_after):
    config = make_config(behavior_version=version)
    reference = run_live(config, seed=1234, rounds=30)
    logged = {n + 1: ids for n, ids in enumerate(reference[:stop_after])}

    resumed = continue_after_replay(config, 1234, stop_after, 30, logged)

    assert resumed == reference[stop_after:]


def test_reaction_delays_and_scheduled_events_are_part_of_the_replayed_state():
    """Stopping between the two scheduled events must not forget the first one's reaction delays."""
    config = make_config()
    reference = run_live(config, seed=99, rounds=14)
    logged = {n + 1: ids for n, ids in enumerate(reference[:5])}
    assert continue_after_replay(config, 99, 5, 14, logged) == reference[5:]


def test_the_two_platforms_replay_independently():
    config = make_config()
    for platform in ("twitter", "reddit"):
        reference = run_live(config, seed=5, rounds=12, platform=platform)
        logged = {n + 1: ids for n, ids in enumerate(reference[:6])}
        assert continue_after_replay(config, 5, 6, 12, logged, platform) == reference[6:]


def test_a_changed_configuration_is_detected_against_the_logged_agents():
    config = make_config()
    reference = run_live(config, seed=1234, rounds=10)
    logged = {n + 1: ids for n, ids in enumerate(reference[:6])}

    changed = copy.deepcopy(config)
    changed["time_config"]["agents_per_hour_max"] = 2
    with pytest.raises(sim_resume.ScheduleMismatch) as raised:
        continue_after_replay(changed, 1234, 6, 10, logged)
    assert "round" in str(raised.value) and "configuration or the seed" in str(raised.value)


def test_a_different_seed_is_detected():
    config = make_config()
    reference = run_live(config, seed=1, rounds=10)
    logged = {n + 1: ids for n, ids in enumerate(reference[:8])}
    with pytest.raises(sim_resume.ScheduleMismatch):
        continue_after_replay(config, 2, 8, 10, logged)


def test_rounds_without_a_logged_start_are_replayed_but_not_checked():
    config = make_config()
    reference = run_live(config, seed=3, rounds=8)
    assert continue_after_replay(config, 3, 5, 8, {}) == reference[5:]


def test_agents_missing_from_the_graph_are_filtered_like_the_run_loop_does():
    config = make_config()
    behavior = sim_behavior.PlatformBehavior(config, "twitter", 8)
    behavior.initial_posts_published()
    expected = [i for i in behavior.select_active(0, 0) if i != 3]

    replayed = sim_resume.replay_schedule(
        sim_behavior.PlatformBehavior(config, "twitter", 8), 1,
        agent_exists=lambda agent_id: agent_id != 3, initial_posted=True, logged_ids={1: expected},
    )
    assert replayed == [expected]


# --- restoring the clocks ------------------------------------------------------------------

def make_trace(path, created):
    connection = sqlite3.connect(str(path))
    connection.execute("CREATE TABLE trace (user_id INTEGER, created_at DATETIME, action TEXT, info TEXT)")
    connection.executemany("INSERT INTO trace VALUES (1, ?, 'x', '')", [(value,) for value in created])
    connection.commit()
    connection.close()


def test_the_twitter_step_counter_continues_from_the_checkpoint(tmp_path):
    platform = SimpleNamespace(sandbox_clock=SimpleNamespace(time_step=0))
    note = sim_resume.restore_clock("twitter", platform, str(tmp_path / "none.db"), {"time_step": 7})
    assert platform.sandbox_clock.time_step == 7 and "7" in note


def test_the_twitter_step_counter_is_derived_from_the_trace_without_a_checkpoint(tmp_path):
    db = tmp_path / "t.db"
    make_trace(db, ["1", "2", "10"])                         # stored as text; 10 > 9 numerically, not as a string
    platform = SimpleNamespace(sandbox_clock=SimpleNamespace(time_step=0))
    sim_resume.restore_clock("twitter", platform, str(db), None)
    assert platform.sandbox_clock.time_step == 11


def test_the_reddit_clock_continues_from_the_last_simulated_time(tmp_path):
    db = tmp_path / "r.db"
    make_trace(db, ["2026-01-02 10:00:00.000000", "2026-01-03 04:30:00.000000"])
    clock = SimpleNamespace(real_start_time=datetime(2000, 1, 1))
    platform = SimpleNamespace(sandbox_clock=clock, start_time=datetime(2000, 1, 1))

    sim_resume.restore_clock("reddit", platform, str(db), None)

    assert platform.start_time == datetime(2026, 1, 3, 4, 30)
    assert (datetime.now() - clock.real_start_time).total_seconds() < 5      # simulated time continues from "now"


def test_an_unreadable_clock_is_left_alone(tmp_path):
    platform = SimpleNamespace(sandbox_clock=SimpleNamespace(time_step=0))
    assert sim_resume.restore_clock("twitter", platform, str(tmp_path / "missing.db"), None) is None
    assert platform.sandbox_clock.time_step == 0


# --- the agents' chat memory travels with the checkpoint ----------------------------------------------

def test_a_checkpoint_carries_the_memory_and_a_restored_database_has_it_too(tmp_path):
    db = tmp_path / "twitter_simulation.db"
    make_db(db, ["a"])
    memories = {0: '[{"agent": 0}]', 3: '[{"agent": 3}]'}

    sim_resume.write_checkpoint(str(db), 2, {}, memories=memories)

    assert sim_resume.read_memories(sim_resume.checkpoint_path(str(db))) == memories
    assert sim_resume.checkpoint_has_memory(str(db))
    sim_resume.restore_checkpoint(str(db))                                   # the live database now has it too
    assert sim_resume.read_memories(str(db), expect_round=2) == memories
    assert posts(db) == ["a"]                                                # the table is not part of the platform's data


def test_memory_of_another_round_is_never_returned(tmp_path):
    """A database that kept the memory of an older checkpoint must not give it to a resume of a later round."""
    db = tmp_path / "x.db"
    make_db(db, ["a"])
    sim_resume.write_checkpoint(str(db), 2, memories={0: "round two"})
    sim_resume.restore_checkpoint(str(db))

    assert sim_resume.read_memories(str(db), expect_round=2) == {0: "round two"}
    assert sim_resume.read_memories(str(db), expect_round=5) == {}
    assert sim_resume.checkpoint_has_memory(str(db), expect_round=5) is False


def test_memory_can_be_read_while_another_connection_holds_a_write_lock(tmp_path):
    """The platform's own connection keeps a transaction open after a failed sign-up; reading must not need the lock."""
    db = tmp_path / "x.db"
    make_db(db, ["a"])
    sim_resume.write_checkpoint(str(db), 1, memories={0: "m"})
    sim_resume.restore_checkpoint(str(db))

    holder = sqlite3.connect(str(db))
    try:
        holder.execute("INSERT INTO post (content) VALUES ('uncommitted')")       # opens a write transaction, never committed
        assert sim_resume.read_memories(str(db), expect_round=1) == {0: "m"}
    finally:
        holder.rollback()
        holder.close()


def test_a_checkpoint_without_memory_replaces_the_memory_of_the_database_it_was_copied_from(tmp_path):
    db = tmp_path / "x.db"
    make_db(db, ["a"])
    sim_resume.write_checkpoint(str(db), 1, memories={0: "old"})
    sim_resume.restore_checkpoint(str(db))
    sim_resume.write_checkpoint(str(db), 2)                                  # e.g. the memory could not be dumped this round

    assert sim_resume.read_memories(sim_resume.checkpoint_path(str(db))) == {}
    assert not sim_resume.checkpoint_has_memory(str(db))


def test_newer_memory_replaces_older_memory(tmp_path):
    db = tmp_path / "x.db"
    make_db(db, ["a"])
    sim_resume.write_checkpoint(str(db), 1, memories={0: "round one", 1: "also one"})
    sim_resume.write_checkpoint(str(db), 2, memories={0: "round two"})
    assert sim_resume.read_memories(sim_resume.checkpoint_path(str(db))) == {0: "round two"}


def test_reading_memory_from_a_missing_or_broken_file_is_empty(tmp_path):
    assert sim_resume.read_memories(str(tmp_path / "nope.db")) == {}
    (tmp_path / "broken.db").write_bytes(b"not a database")
    assert sim_resume.read_memories(str(tmp_path / "broken.db")) == {}


def test_the_plan_says_whether_the_memory_will_come_back(tmp_path):
    with_memory = prepare_platform(tmp_path, "twitter", 3)
    sim_resume.write_checkpoint(str(with_memory), 3, memories={0: "[]"})
    assert sim_resume.plan_resume(str(tmp_path), "twitter").memory is True

    prepare_platform(tmp_path, "reddit", 3, checkpoint_round=3)               # a checkpoint of the older kind
    plan = sim_resume.plan_resume(str(tmp_path), "reddit")
    assert plan.exact and plan.memory is False

    prepare_platform(tmp_path / "other", "twitter", 3)                          # no checkpoint at all
    assert sim_resume.plan_resume(str(tmp_path / "other"), "twitter").memory is False
