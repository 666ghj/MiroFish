"""
集成模拟（Ensemble Simulation）测试

覆盖 app/services/ensemble_runner.py：
- 输入校验（run_count 边界、来源模拟不存在/未准备好）
- 成功路径：N 个成员被独立启动，人设/配置文件被原样拷贝，owner_id/
  random_seed 被正确继承
- 单个成员启动失败不应该让整个集成失败（记录在该成员的 start_error 上）
- 聚合统计只在所有成员到达终态后现算：运行中 -> completed=0 的聚合为 None；
  全部完成 -> 中位数/方差/置信区间/结果频率/敏感度都被正确计算；
  全部失败 -> 整体状态为 failed 且没有聚合
- stop_ensemble 只停止仍处于非终态的成员，跳过启动失败/已终态的成员
"""

import json
import os
import sqlite3
import threading
import uuid

# The _isolated_dirs fixture below replaces threading.Thread globally (via
# monkeypatch.setattr(runner_module.threading, "Thread", NoOpThread)) so
# SimulationRunner's own monitor thread never actually runs during tests.
# Since runner_module.threading IS the real threading module object, that
# patch affects every `threading.Thread(...)` call for the rest of the test,
# including ones written directly in this file. Capture the real class here,
# at module import time (before any fixture has run), so tests that need a
# genuine background thread (real concurrency, not SimulationRunner's
# internal monitor) can bypass the patched threading.Thread.
_RealThread = threading.Thread

import pytest

from app.services import ensemble_runner as ensemble_runner_module
from app.services.ensemble_runner import (
    MAX_ENSEMBLE_RUN_COUNT,
    MIN_ENSEMBLE_RUN_COUNT,
    EnsembleMemberRecord,
    EnsembleRecord,
    EnsembleRunner,
)
from app.services import simulation_runner as runner_module
from app.services.simulation_runner import RunnerStatus, SimulationRunner, SimulationRunState
from app.services.simulation_manager import SimulationManager, SimulationState, SimulationStatus


class FakeProcess:
    pid = 4242

    def poll(self):
        return None


class NoOpThread:
    """Replaces threading.Thread so _monitor_simulation never actually runs;
    the member's run_state stays exactly as start_simulation itself left it
    (RUNNING), which is all these tests need."""

    def __init__(self, **_kwargs):
        pass

    def start(self):
        pass


@pytest.fixture(autouse=True)
def _isolated_dirs(tmp_path, monkeypatch):
    simulations_dir = tmp_path / "simulations"
    scripts_dir = tmp_path / "scripts"
    ensembles_dir = tmp_path / "ensembles"
    simulations_dir.mkdir()
    scripts_dir.mkdir()

    for script_name in (
        "run_parallel_simulation.py",
        "run_twitter_simulation.py",
        "run_reddit_simulation.py",
    ):
        (scripts_dir / script_name).write_text("pass\n", encoding="utf-8")

    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(simulations_dir))
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(simulations_dir))
    monkeypatch.setattr(SimulationRunner, "SCRIPTS_DIR", str(scripts_dir))
    monkeypatch.setattr(EnsembleRunner, "ENSEMBLE_DATA_DIR", str(ensembles_dir))

    monkeypatch.setattr(SimulationRunner, "_run_states", {})
    monkeypatch.setattr(SimulationRunner, "_processes", {})
    monkeypatch.setattr(SimulationRunner, "_action_queues", {})
    monkeypatch.setattr(SimulationRunner, "_monitor_threads", {})
    monkeypatch.setattr(SimulationRunner, "_stdout_files", {})
    monkeypatch.setattr(SimulationRunner, "_stderr_files", {})
    monkeypatch.setattr(SimulationRunner, "_graph_memory_enabled", {})
    monkeypatch.setattr(SimulationRunner, "_manual_stop_requests", set())

    monkeypatch.setattr(runner_module.subprocess, "Popen", lambda *_a, **_k: FakeProcess())
    monkeypatch.setattr(runner_module.threading, "Thread", NoOpThread)
    monkeypatch.setattr(
        SimulationRunner, "_sync_simulation_status", classmethod(lambda *a, **k: None)
    )

    yield


def _make_source_simulation(
    simulation_id="sim_source12345",
    owner_id="user-1",
    enable_reddit=True,
    enable_twitter=False,
    random_seed=777,
):
    manager = SimulationManager()
    state = SimulationState(
        simulation_id=simulation_id,
        project_id="proj_test1234",
        graph_id="graph-test-1",
        enable_twitter=enable_twitter,
        enable_reddit=enable_reddit,
        status=SimulationStatus.READY,
        profiles_generated=True,
        config_generated=True,
        owner_id=owner_id,
        random_seed=random_seed,
    )
    manager._save_simulation_state(state)

    sim_dir = manager._get_simulation_dir(simulation_id)
    with open(os.path.join(sim_dir, "simulation_config.json"), "w", encoding="utf-8") as f:
        json.dump({"time_config": {"total_simulation_hours": 1, "minutes_per_round": 60}}, f)

    if enable_reddit:
        with open(os.path.join(sim_dir, "reddit_profiles.json"), "w", encoding="utf-8") as f:
            json.dump([{"id": 1, "username": "alice"}], f)
    if enable_twitter:
        with open(os.path.join(sim_dir, "twitter_profiles.csv"), "w", encoding="utf-8") as f:
            f.write("user_id,username\n1,alice\n")

    return state


class TestStartEnsembleValidation:
    def test_run_count_below_minimum_rejected(self):
        _make_source_simulation()
        with pytest.raises(ValueError, match="run_count"):
            EnsembleRunner.start_ensemble("sim_source12345", run_count=MIN_ENSEMBLE_RUN_COUNT - 1)

    def test_run_count_above_maximum_rejected(self):
        _make_source_simulation()
        with pytest.raises(ValueError, match="run_count"):
            EnsembleRunner.start_ensemble("sim_source12345", run_count=MAX_ENSEMBLE_RUN_COUNT + 1)

    def test_non_integer_run_count_rejected(self):
        _make_source_simulation()
        with pytest.raises(ValueError, match="run_count"):
            EnsembleRunner.start_ensemble("sim_source12345", run_count=3.5)

    def test_bool_run_count_rejected(self):
        # isinstance(True, int) is True in Python; must be explicitly excluded.
        _make_source_simulation()
        with pytest.raises(ValueError, match="run_count"):
            EnsembleRunner.start_ensemble("sim_source12345", run_count=True)

    def test_missing_source_simulation_rejected(self):
        with pytest.raises(ValueError, match="不存在"):
            EnsembleRunner.start_ensemble("sim_doesnotexist", run_count=3)

    def test_unprepared_source_simulation_rejected(self):
        manager = SimulationManager()
        state = SimulationState(
            simulation_id="sim_unprepared1",
            project_id="proj_test1234",
            graph_id="graph-test-1",
            status=SimulationStatus.CREATED,
            profiles_generated=False,
            config_generated=False,
        )
        manager._save_simulation_state(state)

        with pytest.raises(ValueError, match="准备"):
            EnsembleRunner.start_ensemble("sim_unprepared1", run_count=3)


class TestStartEnsembleHappyPath:
    def test_members_are_independently_started_from_shared_source(self):
        source = _make_source_simulation()
        manager = SimulationManager()

        record = EnsembleRunner.start_ensemble(
            "sim_source12345", run_count=3, platform="reddit"
        )

        assert record.run_count == 3
        assert len(record.members) == 3
        assert all(m.start_error is None for m in record.members)

        member_ids = [m.simulation_id for m in record.members]
        assert len(set(member_ids)) == 3  # all distinct

        for member in record.members:
            member_state = manager.get_simulation(member.simulation_id)
            assert member_state is not None
            assert member_state.status == SimulationStatus.READY
            assert member_state.config_generated is True
            assert member_state.profiles_generated is True
            assert member_state.owner_id == source.owner_id
            assert member_state.random_seed == source.random_seed

            member_dir = manager._get_simulation_dir(member.simulation_id)
            with open(os.path.join(member_dir, "reddit_profiles.json"), encoding="utf-8") as f:
                assert json.load(f) == [{"id": 1, "username": "alice"}]

            run_state = SimulationRunner.get_run_state(member.simulation_id)
            assert run_state is not None
            assert run_state.runner_status == RunnerStatus.RUNNING

        # The ensemble record itself is persisted and reloadable.
        reloaded = EnsembleRunner.get_ensemble_record(record.ensemble_id)
        assert reloaded is not None
        assert [m.simulation_id for m in reloaded.members] == member_ids

    def test_platform_defaults_to_source_default_platform(self):
        _make_source_simulation(enable_reddit=True, enable_twitter=False)
        record = EnsembleRunner.start_ensemble("sim_source12345", run_count=2)
        assert record.platform == "reddit"

    def test_twitter_only_source_only_copies_csv_profiles(self):
        _make_source_simulation(
            simulation_id="sim_twsource123",
            enable_reddit=False,
            enable_twitter=True,
        )
        manager = SimulationManager()

        record = EnsembleRunner.start_ensemble("sim_twsource123", run_count=2)

        for member in record.members:
            member_dir = manager._get_simulation_dir(member.simulation_id)
            assert os.path.exists(os.path.join(member_dir, "twitter_profiles.csv"))
            assert not os.path.exists(os.path.join(member_dir, "reddit_profiles.json"))


class TestPartialMemberStartFailure:
    def test_one_member_failing_to_start_does_not_abort_the_others(self, monkeypatch):
        _make_source_simulation()

        call_count = {"n": 0}

        def flaky_popen(*_a, **_k):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise OSError("simulated launch failure")
            return FakeProcess()

        monkeypatch.setattr(runner_module.subprocess, "Popen", flaky_popen)

        record = EnsembleRunner.start_ensemble("sim_source12345", run_count=3)

        errors = [m.start_error for m in record.members]
        assert errors[0] is None
        assert errors[1] is not None and "simulated launch failure" in errors[1]
        assert errors[2] is None

        summary = EnsembleRunner.get_ensemble_summary(record.ensemble_id)
        assert summary["status"] == "running"  # members 0 and 2 are still RUNNING
        assert summary["member_counts"]["failed"] == 1
        assert summary["member_counts"]["running"] == 2
        assert summary["aggregate"] is None


class TestEnsembleMembersRunNonInteractively:
    def test_members_are_started_with_no_wait(self, monkeypatch):
        # Ensemble members have no human operator to send interview/close
        # commands; without --no-wait the child process would sit in the
        # post-rounds command loop forever and the member would never reach
        # COMPLETED, so the ensemble could never aggregate.
        _make_source_simulation()

        captured_cmds = []
        real_popen = runner_module.subprocess.Popen

        def capturing_popen(cmd, *args, **kwargs):
            captured_cmds.append(cmd)
            return FakeProcess()

        monkeypatch.setattr(runner_module.subprocess, "Popen", capturing_popen)

        EnsembleRunner.start_ensemble("sim_source12345", run_count=2)

        assert len(captured_cmds) == 2
        assert all("--no-wait" in cmd for cmd in captured_cmds)


class TestEnsemblePlatformMustMatchPreparedProfiles:
    def test_twitter_platform_rejected_when_source_has_no_twitter_profiles(self):
        _make_source_simulation(enable_reddit=True, enable_twitter=False)
        with pytest.raises(ValueError, match="Twitter"):
            EnsembleRunner.start_ensemble(
                "sim_source12345", run_count=2, platform="twitter"
            )

    def test_reddit_platform_rejected_when_source_has_no_reddit_profiles(self):
        _make_source_simulation(
            simulation_id="sim_tw_only1234", enable_reddit=False, enable_twitter=True
        )
        with pytest.raises(ValueError, match="Reddit"):
            EnsembleRunner.start_ensemble(
                "sim_tw_only1234", run_count=2, platform="reddit"
            )

    def test_parallel_platform_rejected_when_source_is_single_platform(self):
        _make_source_simulation(enable_reddit=True, enable_twitter=False)
        with pytest.raises(ValueError, match="Twitter"):
            EnsembleRunner.start_ensemble(
                "sim_source12345", run_count=2, platform="parallel"
            )

    def test_matching_platform_is_accepted(self):
        _make_source_simulation(enable_reddit=True, enable_twitter=False)
        record = EnsembleRunner.start_ensemble(
            "sim_source12345", run_count=2, platform="reddit"
        )
        assert record.platform == "reddit"


class TestEnsembleRecordPersistedBeforeMembersLaunch:
    def test_ensemble_is_discoverable_even_if_launch_loop_never_completes(self, monkeypatch):
        # Simulate a crash partway through the launch loop (e.g. the process
        # is killed after member 0 starts but before member 1 is attempted).
        # The provisional record written before the loop must already make
        # the ensemble (and its deterministic member ids) discoverable, so a
        # crash never leaves orphaned simulation subprocesses with no
        # ensemble record pointing at them.
        _make_source_simulation()

        original_start = SimulationRunner.start_simulation
        call_count = {"n": 0}

        def crash_after_first_member(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise KeyboardInterrupt("simulated worker crash mid-loop")
            return original_start(*args, **kwargs)

        monkeypatch.setattr(
            SimulationRunner, "start_simulation", classmethod(
                lambda cls, *a, **k: crash_after_first_member(*a, **k)
            )
        )

        captured_ensemble_id = {}
        real_write = ensemble_runner_module.atomic_write_json

        def spying_write(path, data):
            if "ensemble_id" in data and data.get("members"):
                captured_ensemble_id["id"] = data["ensemble_id"]
            real_write(path, data)

        monkeypatch.setattr(ensemble_runner_module, "atomic_write_json", spying_write)

        with pytest.raises(KeyboardInterrupt):
            EnsembleRunner.start_ensemble("sim_source12345", run_count=3)

        ensemble_id = captured_ensemble_id["id"]
        reloaded = EnsembleRunner.get_ensemble_record(ensemble_id)
        assert reloaded is not None
        assert len(reloaded.members) == 3  # full deterministic member list, not just member 0

    def test_final_write_failure_does_not_abort_already_started_members(self, monkeypatch):
        # If the final (detailed start_error) write fails, already-launched
        # member processes must not be torn down just because bookkeeping
        # failed — they are real, possibly-costly running simulations.
        _make_source_simulation()

        real_write = ensemble_runner_module.atomic_write_json
        write_count = {"n": 0}

        def flaky_final_write(path, data):
            write_count["n"] += 1
            if write_count["n"] == 2:  # first call is the provisional write
                raise OSError("simulated disk failure on final write")
            real_write(path, data)

        monkeypatch.setattr(ensemble_runner_module, "atomic_write_json", flaky_final_write)

        record = EnsembleRunner.start_ensemble("sim_source12345", run_count=2)

        for member in record.members:
            run_state = SimulationRunner.get_run_state(member.simulation_id)
            assert run_state is not None
            assert run_state.runner_status == RunnerStatus.RUNNING

        reloaded = EnsembleRunner.get_ensemble_record(record.ensemble_id)
        assert reloaded is not None
        assert len(reloaded.members) == 2

    def test_last_iterations_write_failure_is_repaired_after_the_loop(self, monkeypatch):
        # Unlike the earlier-iteration case above (superseded by a later
        # write), a failure on the *last* member's snapshot write has no
        # subsequent loop iteration to fix it -- without a post-loop repair
        # pass, that member would stay stuck showing start_error=None with
        # no run_state, and get_ensemble_summary would classify it as
        # "starting" forever even though start_ensemble already returned.
        _make_source_simulation()

        real_write = ensemble_runner_module.atomic_write_json
        write_count = {"n": 0}

        def fail_last_write(path, data):
            write_count["n"] += 1
            # writes: 1=provisional, 2=member0 snapshot, 3=member1 snapshot (last)
            if write_count["n"] == 3:
                raise OSError("simulated disk failure on the last member's write")
            real_write(path, data)

        monkeypatch.setattr(ensemble_runner_module, "atomic_write_json", fail_last_write)

        record = EnsembleRunner.start_ensemble("sim_source12345", run_count=2)

        # The repair pass (outside the failing monkeypatch window, since it
        # only fails call #3) should have fixed member 1 up on disk.
        assert record.members[1].start_error is None
        reloaded = EnsembleRunner.get_ensemble_record(record.ensemble_id)
        assert reloaded.members[1].start_error is None

        summary = EnsembleRunner.get_ensemble_summary(record.ensemble_id)
        assert summary["member_counts"]["running"] == 2


class TestStopEnsembleCancellationPersistFailure:
    def test_stop_raises_when_cancellation_flag_cannot_be_persisted(self, monkeypatch):
        # If the cancellation flag can't be written to disk, the launch
        # loop (if one is still in flight) will never see it and may keep
        # launching members -- returning "success" here would be a lie.
        _make_source_simulation()
        record = EnsembleRunner.start_ensemble("sim_source12345", run_count=2)

        def failing_write(path, data):
            raise OSError("simulated disk failure")

        monkeypatch.setattr(ensemble_runner_module, "atomic_write_json", failing_write)

        with pytest.raises(RuntimeError):
            EnsembleRunner.stop_ensemble(record.ensemble_id)

    def test_stop_still_stops_existing_members_even_if_flag_persist_fails(self, monkeypatch):
        # The best-effort stop of already-running members should still
        # happen even though the call ultimately raises.
        _make_source_simulation()
        record = EnsembleRunner.start_ensemble("sim_source12345", run_count=2)
        member_ids = [m.simulation_id for m in record.members]

        def fake_stop_simulation(cls, simulation_id):
            state = SimulationRunner.get_run_state(simulation_id)
            state.runner_status = RunnerStatus.STOPPED
            SimulationRunner._save_run_state(state)
            return state

        monkeypatch.setattr(
            SimulationRunner, "stop_simulation", classmethod(fake_stop_simulation)
        )

        real_write = ensemble_runner_module.atomic_write_json

        def fail_only_cancellation_write(path, data):
            if data.get("cancelled") is True:
                raise OSError("simulated disk failure")
            real_write(path, data)

        monkeypatch.setattr(
            ensemble_runner_module, "atomic_write_json", fail_only_cancellation_write
        )

        with pytest.raises(RuntimeError):
            EnsembleRunner.stop_ensemble(record.ensemble_id)

        for member_id in member_ids:
            run_state = SimulationRunner.get_run_state(member_id)
            assert run_state.runner_status == RunnerStatus.STOPPED


def _complete_member(member_id, twitter_actions=0, reddit_actions=0, rounds_reached=0):
    state = SimulationRunner.get_run_state(member_id)
    state.runner_status = RunnerStatus.COMPLETED
    state.twitter_actions_count = twitter_actions
    state.reddit_actions_count = reddit_actions
    state.current_round = rounds_reached
    SimulationRunner._save_run_state(state)


def _fail_member(member_id):
    state = SimulationRunner.get_run_state(member_id)
    state.runner_status = RunnerStatus.FAILED
    state.error = "simulated failure"
    SimulationRunner._save_run_state(state)


def _write_action_log(member_id, platform, action_types):
    manager = SimulationManager()
    member_dir = manager._get_simulation_dir(member_id)
    platform_dir = os.path.join(member_dir, platform)
    os.makedirs(platform_dir, exist_ok=True)
    with open(os.path.join(platform_dir, "actions.jsonl"), "w", encoding="utf-8") as f:
        for action_type in action_types:
            f.write(json.dumps({"action_type": action_type, "round": 1}) + "\n")
        f.write(json.dumps({"event_type": "round_end", "round": 1}) + "\n")


class TestEnsembleSummaryAggregation:
    def test_status_is_running_until_every_member_reaches_a_terminal_state(self):
        _make_source_simulation()
        record = EnsembleRunner.start_ensemble("sim_source12345", run_count=3)
        member_ids = [m.simulation_id for m in record.members]

        _complete_member(member_ids[0], twitter_actions=0, reddit_actions=5, rounds_reached=2)
        # member_ids[1] and [2] stay RUNNING.

        summary = EnsembleRunner.get_ensemble_summary(record.ensemble_id)
        assert summary["status"] == "running"
        assert summary["aggregate"] is None

    def test_status_is_failed_when_no_member_completes(self):
        _make_source_simulation()
        record = EnsembleRunner.start_ensemble("sim_source12345", run_count=2)
        member_ids = [m.simulation_id for m in record.members]

        for member_id in member_ids:
            _fail_member(member_id)

        summary = EnsembleRunner.get_ensemble_summary(record.ensemble_id)
        assert summary["status"] == "failed"
        assert summary["member_counts"]["failed"] == 2
        assert summary["aggregate"] is None

    def test_aggregate_computed_once_all_members_terminal(self):
        # platform="parallel" specifically: it's the only mode whose run
        # script mirrors the SQLite trace table into actions.jsonl and keeps
        # run_state's action counters/current_round in sync, which is what
        # this test's fixtures (_complete_member, _write_action_log) drive.
        # Single-platform (twitter/reddit) aggregation is covered separately
        # in TestSinglePlatformAggregationReadsTraceDb below.
        _make_source_simulation(enable_reddit=True, enable_twitter=True)
        record = EnsembleRunner.start_ensemble(
            "sim_source12345", run_count=3, platform="parallel"
        )
        member_ids = [m.simulation_id for m in record.members]

        _complete_member(member_ids[0], reddit_actions=10, rounds_reached=4)
        _complete_member(member_ids[1], reddit_actions=20, rounds_reached=6)
        _fail_member(member_ids[2])

        _write_action_log(member_ids[0], "reddit", ["CREATE_POST", "LIKE_POST"])
        _write_action_log(member_ids[1], "reddit", ["CREATE_POST", "CREATE_POST"])

        summary = EnsembleRunner.get_ensemble_summary(record.ensemble_id)
        assert summary["status"] == "completed"
        assert summary["member_counts"] == {
            "total": 3, "completed": 2, "failed": 1, "stopped": 0, "running": 0,
        }

        aggregate = summary["aggregate"]
        assert aggregate["completed_run_count"] == 2

        reddit_metric = aggregate["metrics"]["reddit_actions_count"]
        assert reddit_metric["count"] == 2
        assert reddit_metric["mean"] == 15
        assert reddit_metric["median"] == 15
        assert reddit_metric["min"] == 10
        assert reddit_metric["max"] == 20
        assert reddit_metric["confidence_interval_95"] is not None
        # Jackknife sensitivity is undefined (None) below 3 samples.
        assert reddit_metric["sensitivity"] is None

        rounds_metric = aggregate["metrics"]["rounds_reached"]
        assert rounds_metric["mean"] == 5

        freq = aggregate["outcome_frequency"]
        assert freq["CREATE_POST"]["run_occurrence_count"] == 2
        assert freq["CREATE_POST"]["run_occurrence_rate"] == 1.0
        assert freq["CREATE_POST"]["total_count"] == 3  # 1 + 2
        assert freq["LIKE_POST"]["run_occurrence_count"] == 1
        assert freq["LIKE_POST"]["run_occurrence_rate"] == 0.5
        assert freq["LIKE_POST"]["total_count"] == 1

    def test_sensitivity_reported_with_three_or_more_completed_members(self):
        _make_source_simulation(enable_reddit=True, enable_twitter=True)
        record = EnsembleRunner.start_ensemble(
            "sim_source12345", run_count=3, platform="parallel"
        )
        member_ids = [m.simulation_id for m in record.members]

        _complete_member(member_ids[0], reddit_actions=10)
        _complete_member(member_ids[1], reddit_actions=20)
        _complete_member(member_ids[2], reddit_actions=90)  # outlier

        summary = EnsembleRunner.get_ensemble_summary(record.ensemble_id)
        sensitivity = summary["aggregate"]["metrics"]["reddit_actions_count"]["sensitivity"]
        assert sensitivity is not None
        assert sensitivity > 0


def _write_trace_db(member_id, platform, raw_actions):
    """
    Writes a <platform>_simulation.db with the same `trace` table schema
    OASIS itself creates (see .venv/.../oasis/social_platform/sql/trace.sql),
    populated the way run_twitter_simulation.py/run_reddit_simulation.py
    actually populate it (one row per action, via pl_utils._record_trace) —
    unlike run_parallel_simulation.py, these single-platform scripts never
    mirror it into actions.jsonl.
    """
    manager = SimulationManager()
    member_dir = manager._get_simulation_dir(member_id)
    db_path = os.path.join(member_dir, f"{platform}_simulation.db")
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE trace (user_id INTEGER, created_at TEXT, action TEXT, info TEXT)"
        )
        for user_id, action in raw_actions:
            conn.execute(
                "INSERT INTO trace (user_id, created_at, action, info) VALUES (?, ?, ?, ?)",
                (user_id, "0", action, "{}"),
            )
        conn.commit()
    finally:
        conn.close()


class TestSinglePlatformAggregationReadsTraceDb:
    """
    run_twitter_simulation.py/run_reddit_simulation.py never write
    actions.jsonl (see ensemble_runner.py module docstring point 5), so for
    platform=twitter/reddit ensembles the aggregate must be computed from
    the SQLite trace table each script actually populates, not from
    run_state's action counters (which stay 0 for these platforms) or the
    actions.jsonl-based _tally_action_types (which finds nothing).
    """

    def test_reddit_only_aggregate_uses_trace_db_not_run_state_counters(self):
        _make_source_simulation(enable_reddit=True, enable_twitter=False)
        record = EnsembleRunner.start_ensemble(
            "sim_source12345", run_count=2, platform="reddit"
        )
        member_ids = [m.simulation_id for m in record.members]

        # run_state's reddit_actions_count/current_round are left at their
        # defaults (0) here on purpose, exactly as the real
        # run_reddit_simulation.py + --no-wait leaves them, since that
        # script never touches those fields.
        _complete_member(member_ids[0])
        _complete_member(member_ids[1])

        _write_trace_db(member_ids[0], "reddit", [
            (1, "create_post"), (1, "like_post"), (2, "refresh"), (2, "sign_up"),
        ])
        _write_trace_db(member_ids[1], "reddit", [
            (1, "create_post"), (1, "create_post"), (2, "do_nothing"),
        ])

        summary = EnsembleRunner.get_ensemble_summary(record.ensemble_id)

        # The per-member info in the same response must agree with the
        # aggregate -- not show twitter/reddit_actions_count=0 (straight
        # from run_state) right next to an aggregate computed from the
        # trace db, which would make the response internally contradictory.
        member_infos_by_id = {m["simulation_id"]: m for m in summary["members"]}
        assert member_infos_by_id[member_ids[0]]["reddit_actions_count"] == 2
        assert member_infos_by_id[member_ids[1]]["reddit_actions_count"] == 3
        assert member_infos_by_id[member_ids[0]]["twitter_actions_count"] == 0

        aggregate = summary["aggregate"]
        assert aggregate["completed_run_count"] == 2

        # member 0: create_post + like_post = 2 (refresh/sign_up filtered out)
        # member 1: create_post*2 + do_nothing = 3
        reddit_metric = aggregate["metrics"]["reddit_actions_count"]
        assert reddit_metric["count"] == 2
        assert reddit_metric["mean"] == 2.5
        assert reddit_metric["min"] == 2
        assert reddit_metric["max"] == 3

        twitter_metric = aggregate["metrics"]["twitter_actions_count"]
        assert twitter_metric["mean"] == 0  # this is a reddit-only ensemble

        # rounds_reached is honestly unavailable for single-platform members
        # rather than a fabricated 0/total_rounds guess.
        rounds_metric = aggregate["metrics"]["rounds_reached"]
        assert rounds_metric["count"] == 0
        assert rounds_metric["mean"] is None

        freq = aggregate["outcome_frequency"]
        assert freq["CREATE_POST"]["run_occurrence_count"] == 2
        assert freq["CREATE_POST"]["total_count"] == 3  # 1 + 2
        assert freq["LIKE_POST"]["run_occurrence_count"] == 1
        assert freq["LIKE_POST"]["total_count"] == 1
        assert freq["DO_NOTHING"]["run_occurrence_count"] == 1
        assert "REFRESH" not in freq
        assert "SIGN_UP" not in freq

    def test_missing_trace_db_yields_zero_not_an_error(self):
        # A completed member whose db file never got created for any reason
        # must degrade to a zero-count sample, not raise.
        _make_source_simulation(enable_reddit=True, enable_twitter=False)
        record = EnsembleRunner.start_ensemble(
            "sim_source12345", run_count=2, platform="reddit"
        )
        for member in record.members:
            _complete_member(member.simulation_id)

        summary = EnsembleRunner.get_ensemble_summary(record.ensemble_id)
        aggregate = summary["aggregate"]
        assert aggregate["metrics"]["reddit_actions_count"]["mean"] == 0
        assert aggregate["outcome_frequency"] == {}


class TestStopEnsemble:
    def test_stop_only_targets_non_terminal_members_and_skips_start_failures(self, monkeypatch):
        _make_source_simulation()

        call_count = {"n": 0}

        def flaky_popen(*_a, **_k):
            call_count["n"] += 1
            if call_count["n"] == 3:
                raise OSError("simulated launch failure")
            return FakeProcess()

        monkeypatch.setattr(runner_module.subprocess, "Popen", flaky_popen)

        record = EnsembleRunner.start_ensemble("sim_source12345", run_count=3)
        member_ids = [m.simulation_id for m in record.members]

        # member 0: still running. member 1: already completed (must be
        # skipped). member 2: never started at all (start_error set, must be
        # skipped -- calling stop_simulation on it would fail since it has no
        # run_state).
        _complete_member(member_ids[1], reddit_actions=1)

        stop_calls = []

        def fake_stop_simulation(cls, simulation_id):
            stop_calls.append(simulation_id)
            state = SimulationRunner.get_run_state(simulation_id)
            state.runner_status = RunnerStatus.STOPPED
            SimulationRunner._save_run_state(state)
            return state

        monkeypatch.setattr(
            SimulationRunner, "stop_simulation", classmethod(fake_stop_simulation)
        )

        results = EnsembleRunner.stop_ensemble(record.ensemble_id)

        assert stop_calls == [member_ids[0]]
        assert results[member_ids[0]]["success"] is True

    def test_stop_missing_ensemble_raises(self):
        with pytest.raises(ValueError, match="不存在"):
            EnsembleRunner.stop_ensemble("ens_doesnotexist")

    def test_ensemble_lock_returns_the_same_instance_for_the_same_id(self):
        # Same pattern as SimulationRunner._finalization_lock: the launch
        # loop and stop_ensemble must serialize against the *same* lock
        # object for a given ensemble_id, or the mutual exclusion below is
        # meaningless.
        lock1 = EnsembleRunner._ensemble_lock("ens_same0001")
        lock2 = EnsembleRunner._ensemble_lock("ens_same0001")
        assert lock1 is lock2
        lock_other = EnsembleRunner._ensemble_lock("ens_other0001")
        assert lock_other is not lock1

    def test_stop_cannot_set_cancelled_while_a_member_launch_is_in_progress(
        self, monkeypatch
    ):
        # Regression test for the start/stop race: without holding the same
        # ensemble-level lock during "check cancelled -> launch -> persist",
        # a concurrent stop_ensemble could squeeze in between the check and
        # the launch, or have its cancellation write clobbered by the
        # launch loop's own snapshot write. Proves the lock actually
        # provides mutual exclusion, using a real second thread (a fake,
        # same-thread "concurrent" call can't exercise a threading.Lock at
        # all).
        _make_source_simulation()

        # ensemble_id is normally only known after start_ensemble returns,
        # which is exactly what this test blocks on -- so pin uuid4 to know
        # it upfront instead of waiting for the function to return.
        fixed_uuid = uuid.UUID("12345678123456781234567812345678")
        monkeypatch.setattr(ensemble_runner_module.uuid, "uuid4", lambda: fixed_uuid)
        ensemble_id = f"ens_{fixed_uuid.hex[:12]}"

        member_launch_started = threading.Event()
        release_member_launch = threading.Event()
        real_start = SimulationRunner.start_simulation

        def blocking_start_simulation(cls, *args, **kwargs):
            member_launch_started.set()
            release_member_launch.wait(timeout=5)
            return real_start(*args, **kwargs)

        monkeypatch.setattr(
            SimulationRunner, "start_simulation",
            classmethod(blocking_start_simulation),
        )

        start_result_holder = {}

        def run_start_ensemble():
            try:
                start_result_holder["record"] = EnsembleRunner.start_ensemble(
                    "sim_source12345", run_count=2
                )
            except Exception as error:
                start_result_holder["error"] = error

        start_thread = _RealThread(target=run_start_ensemble)
        start_thread.start()

        # Wait until the launch loop is inside the locked section (blocked
        # on release_member_launch, lock still held) before attempting stop.
        started_in_time = member_launch_started.wait(timeout=5)
        if not started_in_time and "error" in start_result_holder:
            raise start_result_holder["error"]
        assert started_in_time

        def run_stop_ensemble():
            # This must block on the ensemble lock until the in-progress
            # member-launch critical section above releases it.
            EnsembleRunner.stop_ensemble(ensemble_id)

        stop_thread = _RealThread(target=run_stop_ensemble)
        stop_thread.start()

        # Give the stop thread every chance to run; it must NOT be able to
        # complete while the launch critical section is still holding the
        # lock (the provisional record already exists by this point, so if
        # stop_ensemble could act without the lock it would return quickly).
        stop_thread.join(timeout=0.3)
        assert stop_thread.is_alive(), (
            "stop_ensemble should still be blocked on the ensemble lock "
            "while the member-launch critical section holds it"
        )
        reloaded_while_blocked = EnsembleRunner.get_ensemble_record(ensemble_id)
        assert reloaded_while_blocked.cancelled is False

        release_member_launch.set()
        start_thread.join(timeout=5)
        stop_thread.join(timeout=5)
        assert not start_thread.is_alive()
        assert not stop_thread.is_alive()

        reloaded = EnsembleRunner.get_ensemble_record(ensemble_id)
        assert reloaded.cancelled is True
        # The one member that was already launching when stop_ensemble was
        # called must not have been clobbered/lost by the cancellation.
        assert reloaded.members[0].simulation_id == start_result_holder["record"].members[0].simulation_id

    def test_summary_finalizes_never_started_members_after_crash_and_cancel(self):
        # Regression test for: a worker crashes mid-launch-loop, leaving
        # some members in their pristine provisional state (no start_error,
        # no run_state). An operator notices the stuck ensemble and calls
        # stop_ensemble, which durably sets cancelled=True but still can't
        # act on members with no run_state. Without the P2 fix, those
        # members stay classified as STARTING forever and the ensemble
        # never reaches a terminal status. Constructed by hand rather than
        # via a real crash, which isn't reproducible in-process.
        source = _make_source_simulation()
        ensemble_id = "ens_crashsim01"
        member_0_id = f"{ensemble_id}_m0"

        SimulationRunner._save_run_state(
            SimulationRunState(simulation_id=member_0_id, runner_status=RunnerStatus.RUNNING)
        )

        record = EnsembleRecord(
            ensemble_id=ensemble_id,
            source_simulation_id="sim_source12345",
            project_id=source.project_id,
            graph_id=source.graph_id,
            platform="reddit",
            max_rounds=None,
            run_count=3,
            members=[
                EnsembleMemberRecord(simulation_id=member_0_id, index=0),
                EnsembleMemberRecord(simulation_id=f"{ensemble_id}_m1", index=1),
                EnsembleMemberRecord(simulation_id=f"{ensemble_id}_m2", index=2),
            ],
            created_at="2024-01-01T00:00:00",
            owner_id=source.owner_id,
            cancelled=True,
        )
        ensemble_runner_module.atomic_write_json(
            EnsembleRunner._ensemble_path(ensemble_id), record.to_dict()
        )

        _complete_member(member_0_id, reddit_actions=5)

        summary = EnsembleRunner.get_ensemble_summary(ensemble_id)
        assert summary["status"] != "running"
        assert summary["member_counts"]["running"] == 0
        assert summary["member_counts"]["completed"] == 1
        assert summary["member_counts"]["failed"] == 2
        for info in summary["members"]:
            if info["simulation_id"] != member_0_id:
                assert info["runner_status"] == RunnerStatus.FAILED.value
                assert "取消" in info["error"]


