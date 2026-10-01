"""
模拟检查点（Checkpoint）测试

覆盖 app/services/simulation_checkpoint.py 的构建/保存/加载，以及
_monitor_simulation 在轮次前进时写入检查点、并在失败终态记录"到达轮次 +
明确的续跑限制说明"的端到端行为。
"""

import json
import os

import pytest

from app import create_app
from app.services import simulation_checkpoint
from app.services.simulation_checkpoint import (
    RESUME_LIMITATION_NOTE,
    Checkpoint,
    build_checkpoint_from_state,
    checkpoint_path,
    load_checkpoint,
    save_checkpoint,
)
from app.services import simulation_runner as runner_module
from app.services.simulation_runner import RunnerStatus, SimulationRunState, SimulationRunner


class TestCheckpointDataStructure:
    def test_checkpoint_defaults_are_not_resumable(self):
        cp = Checkpoint(simulation_id="sim_test1234")
        assert cp.resumable is False
        assert cp.resume_limitation == RESUME_LIMITATION_NOTE

    def test_to_dict_shape(self):
        cp = Checkpoint(
            simulation_id="sim_test1234",
            twitter_round=5,
            reddit_round=3,
            total_rounds=10,
            twitter_action_count=42,
            reddit_action_count=17,
            runner_status="running",
        )
        data = cp.to_dict()
        assert data["simulation_id"] == "sim_test1234"
        assert data["twitter_round"] == 5
        assert data["reddit_round"] == 3
        assert data["resumable"] is False
        assert "checkpointed_at" in data


class TestBuildCheckpointFromState:
    def test_reflects_run_state_fields(self):
        state = SimulationRunState(
            simulation_id="sim_test1234",
            runner_status=RunnerStatus.RUNNING,
            total_rounds=100,
            twitter_current_round=30,
            reddit_current_round=28,
            twitter_actions_count=120,
            reddit_actions_count=95,
        )
        cp = build_checkpoint_from_state(state)
        assert cp.simulation_id == "sim_test1234"
        assert cp.twitter_round == 30
        assert cp.reddit_round == 28
        assert cp.total_rounds == 100
        assert cp.twitter_action_count == 120
        assert cp.reddit_action_count == 95
        assert cp.runner_status == "running"

    def test_checkpointed_at_uses_updated_at_not_build_time(self):
        """
        Regression test for Codex's round-9 finding: checkpointed_at must
        reflect when the simulation last actually made progress
        (SimulationRunState.updated_at, only bumped by add_action()), not
        the wall-clock time this function happened to be called at -- so a
        client polling the live-derived checkpoint doesn't see a constantly
        moving timestamp for a simulation that isn't actually progressing.
        """
        fixed_progress_time = "2020-01-01T00:00:00"
        state = SimulationRunState(
            simulation_id="sim_test1234",
            runner_status=RunnerStatus.RUNNING,
            updated_at=fixed_progress_time,
        )
        cp = build_checkpoint_from_state(state)
        assert cp.checkpointed_at == fixed_progress_time

        # Building it again "later" (simulating a second poll with no
        # progress in between) must yield the same timestamp, not "now".
        cp_again = build_checkpoint_from_state(state)
        assert cp_again.checkpointed_at == fixed_progress_time


class TestSaveAndLoadCheckpoint:
    def test_round_trip(self, tmp_path):
        cp = Checkpoint(simulation_id="sim_test1234", twitter_round=7, total_rounds=50)
        save_checkpoint(str(tmp_path), cp)

        assert (tmp_path / "checkpoint.json").exists()
        loaded = load_checkpoint(str(tmp_path))
        assert loaded["simulation_id"] == "sim_test1234"
        assert loaded["twitter_round"] == 7
        assert loaded["resumable"] is False
        assert loaded["resume_limitation"] == RESUME_LIMITATION_NOTE

    def test_missing_checkpoint_returns_none(self, tmp_path):
        assert load_checkpoint(str(tmp_path)) is None

    def test_checkpoint_path(self, tmp_path):
        assert checkpoint_path(str(tmp_path)) == str(tmp_path / "checkpoint.json")

    def test_overwrite_replaces_content(self, tmp_path):
        save_checkpoint(str(tmp_path), Checkpoint(simulation_id="sim_1", twitter_round=1))
        save_checkpoint(str(tmp_path), Checkpoint(simulation_id="sim_1", twitter_round=2))
        loaded = load_checkpoint(str(tmp_path))
        assert loaded["twitter_round"] == 2


class TestMonitorSimulationWritesCheckpoints:
    """
    端到端验证 _monitor_simulation：轮次前进时写入检查点，失败终态时写入
    最终检查点并在 state.error 中附上明确的"不可续跑，需从 round 0 重开"说明。
    """

    def _write_round_end(self, log_path, round_num, simulated_hours=1):
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "event_type": "round_end",
                        "round": round_num,
                        "simulated_hours": simulated_hours,
                    }
                )
                + "\n"
            )

    def test_checkpoint_written_during_run_and_on_failure(self, tmp_path, monkeypatch):
        simulation_id = "sim_checkpoint1"
        sim_dir = tmp_path / simulation_id
        twitter_log = sim_dir / "twitter" / "actions.jsonl"
        self._write_round_end(twitter_log, round_num=5)

        state = SimulationRunState(
            simulation_id=simulation_id,
            runner_status=RunnerStatus.RUNNING,
            total_rounds=100,
            twitter_running=True,
        )

        monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path))
        monkeypatch.setattr(SimulationRunner, "_run_states", {simulation_id: state})
        monkeypatch.setattr(SimulationRunner, "_processes", {})
        monkeypatch.setattr(SimulationRunner, "_manual_stop_requests", set())
        monkeypatch.setattr(SimulationRunner, "_graph_memory_enabled", {})
        monkeypatch.setattr(runner_module.time, "sleep", lambda _: None)
        monkeypatch.setattr(
            SimulationRunner, "_sync_simulation_status", classmethod(lambda *a, **k: None)
        )

        poll_results = iter([None, 1])  # one loop iteration, then process exits (code 1 = failure)

        class FakeProcess:
            pid = 999
            returncode = 1

            def poll(self):
                return next(poll_results, 1)

        SimulationRunner._processes[simulation_id] = FakeProcess()

        SimulationRunner._monitor_simulation(simulation_id, locale="zh")

        # A checkpoint was written mid-loop, reflecting the round_end event.
        mid_run_checkpoint = load_checkpoint(str(sim_dir))
        assert mid_run_checkpoint is not None
        assert mid_run_checkpoint["twitter_round"] == 5

        # Final state: FAILED, with an honest, non-resumable explanation.
        final_state = SimulationRunner._run_states[simulation_id]
        assert final_state.runner_status == RunnerStatus.FAILED
        assert "round 0" in final_state.error
        assert "重新开始" in final_state.error
        assert "twitter=5" in final_state.error

        final_checkpoint = load_checkpoint(str(sim_dir))
        assert final_checkpoint["runner_status"] == "failed"
        assert final_checkpoint["resumable"] is False
        assert final_checkpoint["resume_limitation"] == RESUME_LIMITATION_NOTE


class TestCheckpointApiEndpoint:
    def test_get_checkpoint_returns_persisted_checkpoint(self, tmp_path, monkeypatch):
        simulation_id = "sim_apitest1234"
        monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path))
        sim_dir = tmp_path / simulation_id
        sim_dir.mkdir()
        save_checkpoint(
            str(sim_dir),
            Checkpoint(simulation_id=simulation_id, twitter_round=12, total_rounds=50),
        )

        app = create_app()
        app.config.update(TESTING=True)
        client = app.test_client()

        response = client.get(f"/api/simulation/{simulation_id}/checkpoint")
        assert response.status_code == 200
        assert response.json["data"]["twitter_round"] == 12
        assert response.json["data"]["resumable"] is False

    def test_get_checkpoint_404_when_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path))

        app = create_app()
        app.config.update(TESTING=True)
        client = app.test_client()

        response = client.get("/api/simulation/sim_nope12345/checkpoint")
        assert response.status_code == 404

    def test_get_checkpoint_prefers_live_run_state_over_stale_persisted_file(
        self, tmp_path, monkeypatch
    ):
        """
        Regression test for Codex's round-8 finding: run_state.json and
        checkpoint.json are written in two separate calls, so a process
        killed between them can leave checkpoint.json behind describing an
        earlier, non-terminal snapshot even though run_state.json (which is
        itself crash-safe) already reflects the true terminal outcome. The
        endpoint must reconcile by preferring the live run_state.json.
        """
        simulation_id = "sim_racewindow12"
        monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path))
        sim_dir = tmp_path / simulation_id
        sim_dir.mkdir()

        # Simulate the crash window: run_state.json already made it to a
        # terminal FAILED status at round 42, but checkpoint.json is stuck
        # at an earlier RUNNING snapshot from before the crash.
        SimulationRunner._save_run_state(
            SimulationRunState(
                simulation_id=simulation_id,
                runner_status=RunnerStatus.FAILED,
                total_rounds=100,
                twitter_current_round=42,
                error="进程退出码: 1",
            )
        )
        save_checkpoint(
            str(sim_dir),
            Checkpoint(
                simulation_id=simulation_id,
                twitter_round=10,
                total_rounds=100,
                runner_status="running",
            ),
        )

        app = create_app()
        app.config.update(TESTING=True)
        client = app.test_client()

        response = client.get(f"/api/simulation/{simulation_id}/checkpoint")
        assert response.status_code == 200
        # Must reflect the authoritative, crash-safe run_state.json -- not
        # the stale checkpoint.json left behind from before the crash.
        assert response.json["data"]["runner_status"] == "failed"
        assert response.json["data"]["twitter_round"] == 42


class TestPerPlatformCheckpointFreshness:
    """
    Regression test for Codex's finding: comparing only the cross-platform
    aggregate `current_round` misses progress on the platform that is behind
    (its round/action count can change without the aggregate changing), so a
    crash could report stale per-platform progress. Checkpoints must react
    to per-platform round/action changes too.
    """

    def _write_round_end(self, log_path, round_num, simulated_hours=1):
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "event_type": "round_end",
                        "round": round_num,
                        "simulated_hours": simulated_hours,
                    }
                )
                + "\n"
            )

    def test_checkpoint_updates_when_lagging_platform_advances(self, tmp_path, monkeypatch):
        simulation_id = "sim_perplat1234"
        sim_dir = tmp_path / simulation_id
        twitter_log = sim_dir / "twitter" / "actions.jsonl"
        reddit_log = sim_dir / "reddit" / "actions.jsonl"
        # Twitter starts ahead; the aggregate current_round becomes 5 and
        # will NOT change when reddit later advances to round 3 (3 < 5).
        self._write_round_end(twitter_log, round_num=5)

        state = SimulationRunState(
            simulation_id=simulation_id,
            runner_status=RunnerStatus.RUNNING,
            total_rounds=100,
            twitter_running=True,
            reddit_running=True,
        )

        monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path))
        monkeypatch.setattr(SimulationRunner, "_run_states", {simulation_id: state})
        monkeypatch.setattr(SimulationRunner, "_processes", {})
        monkeypatch.setattr(SimulationRunner, "_manual_stop_requests", set())
        monkeypatch.setattr(SimulationRunner, "_graph_memory_enabled", {})
        monkeypatch.setattr(
            SimulationRunner, "_sync_simulation_status", classmethod(lambda *a, **k: None)
        )

        checkpoints_seen = []
        real_save = simulation_checkpoint.save_checkpoint

        def spy_save(sim_dir_arg, cp):
            checkpoints_seen.append((cp.twitter_round, cp.reddit_round))
            real_save(sim_dir_arg, cp)

        monkeypatch.setattr(runner_module.simulation_checkpoint, "save_checkpoint", spy_save)

        sleep_calls = {"n": 0}

        def fake_sleep(_):
            sleep_calls["n"] += 1
            if sleep_calls["n"] == 1:
                # Simulate reddit making progress on the next monitor tick,
                # while the aggregate current_round (5) stays unchanged.
                self._write_round_end(reddit_log, round_num=3)

        monkeypatch.setattr(runner_module.time, "sleep", fake_sleep)

        poll_results = iter([None, None, 0])

        class FakeProcess:
            pid = 1
            returncode = 0

            def poll(self):
                return next(poll_results, 0)

        SimulationRunner._processes[simulation_id] = FakeProcess()

        SimulationRunner._monitor_simulation(simulation_id, locale="zh")

        assert state.current_round == 5  # aggregate never moved past twitter's round
        # But both distinct per-platform snapshots were still checkpointed.
        assert (5, 0) in checkpoints_seen
        assert (5, 3) in checkpoints_seen


class TestStartSimulationResetsStaleCheckpoint:
    def test_start_simulation_clears_previous_run_checkpoint(self, tmp_path, monkeypatch):
        simulation_id = "sim_startreset1"
        sim_dir = tmp_path / "runs" / simulation_id
        scripts_dir = tmp_path / "scripts"
        sim_dir.mkdir(parents=True)
        scripts_dir.mkdir()
        (sim_dir / "simulation_config.json").write_text(
            json.dumps({
                "time_config": {"total_simulation_hours": 1, "minutes_per_round": 60},
            }),
            encoding="utf-8",
        )
        (scripts_dir / "run_twitter_simulation.py").write_text("pass\n", encoding="utf-8")

        # Stale checkpoint left over from a previous (already-finished) run.
        save_checkpoint(
            str(sim_dir),
            Checkpoint(
                simulation_id=simulation_id,
                twitter_round=42,
                total_rounds=50,
                runner_status="completed",
            ),
        )

        class Process:
            pid = 123

            def poll(self):
                return None

        class BrokenThread:
            def __init__(self, **_kwargs):
                pass

            def start(self):
                raise RuntimeError("monitor failed")

        monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path / "runs"))
        monkeypatch.setattr(SimulationRunner, "SCRIPTS_DIR", str(scripts_dir))
        monkeypatch.setattr(runner_module.subprocess, "Popen", lambda *_a, **_k: Process())
        monkeypatch.setattr(runner_module.threading, "Thread", BrokenThread)
        monkeypatch.setattr(
            SimulationRunner,
            "_terminate_process",
            classmethod(lambda _cls, _process, sim_id: None),
        )
        monkeypatch.setattr(
            SimulationRunner, "_sync_simulation_status", classmethod(lambda *a, **k: None)
        )

        try:
            with pytest.raises(RuntimeError, match="monitor failed"):
                SimulationRunner.start_simulation(
                    simulation_id, platform="twitter", enable_graph_memory_update=False
                )

            # The stale previous run's round=42/completed snapshot must be
            # gone. The monitor-thread-start failure is caught by
            # start_simulation's own cleanup path, which now also persists a
            # terminal checkpoint -- so the final state is an honest "failed
            # at round 0", not a checkpoint stuck forever at "starting".
            checkpoint = load_checkpoint(str(sim_dir))
            assert checkpoint["twitter_round"] == 0
            assert checkpoint["runner_status"] == "failed"
        finally:
            SimulationRunner._run_states.pop(simulation_id, None)
            SimulationRunner._processes.pop(simulation_id, None)
            SimulationRunner._action_queues.pop(simulation_id, None)
            SimulationRunner._stdout_files.pop(simulation_id, None)
            SimulationRunner._stderr_files.pop(simulation_id, None)
            SimulationRunner._graph_memory_enabled.pop(simulation_id, None)


class TestCleanupRemovesCheckpoint:
    def test_cleanup_simulation_logs_removes_checkpoint_file(self, tmp_path, monkeypatch):
        simulation_id = "sim_cleanup1234"
        sim_dir = tmp_path / simulation_id
        sim_dir.mkdir()
        save_checkpoint(
            str(sim_dir),
            Checkpoint(simulation_id=simulation_id, twitter_round=10, runner_status="failed"),
        )
        monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path))
        monkeypatch.setattr(SimulationRunner, "_run_states", {})

        assert load_checkpoint(str(sim_dir)) is not None

        result = SimulationRunner.cleanup_simulation_logs(simulation_id)

        assert load_checkpoint(str(sim_dir)) is None
        assert "checkpoint.json" in result["cleaned_files"]


class TestStopSimulationWithoutMonitorThreadSavesCheckpoint:
    """
    Regression test for Codex's finding: stop_simulation has a synchronous
    finalization branch used when there is no monitor thread to hand off to
    (e.g. after a backend restart, where the SimulationRunner process lost
    its in-memory monitor/process handles but run_state.json says the
    simulation was still RUNNING). That branch must also persist a final
    checkpoint, the same as the normal _monitor_simulation finalization path.
    """

    def test_synchronous_stop_persists_final_checkpoint(self, tmp_path, monkeypatch):
        simulation_id = "sim_syncstop1234"
        sim_dir = tmp_path / simulation_id

        state = SimulationRunState(
            simulation_id=simulation_id,
            runner_status=RunnerStatus.RUNNING,
            total_rounds=100,
            twitter_current_round=17,
        )

        monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path))
        monkeypatch.setattr(SimulationRunner, "_run_states", {simulation_id: state})
        # Simulate "no monitor thread survived a backend restart":
        monkeypatch.setattr(SimulationRunner, "_processes", {})
        monkeypatch.setattr(SimulationRunner, "_monitor_threads", {})
        monkeypatch.setattr(SimulationRunner, "_manual_stop_requests", set())
        monkeypatch.setattr(SimulationRunner, "_graph_memory_enabled", {})
        monkeypatch.setattr(
            SimulationRunner, "_sync_simulation_status", classmethod(lambda *a, **k: None)
        )

        result = SimulationRunner.stop_simulation(simulation_id)

        assert result.runner_status == RunnerStatus.STOPPED
        checkpoint = load_checkpoint(str(sim_dir))
        assert checkpoint is not None
        assert checkpoint["runner_status"] == "stopped"
        assert checkpoint["twitter_round"] == 17


class TestStartupFailureBeforeMonitorPersistsCheckpoint:
    """
    Regression test for Codex's round-3 finding: several start_simulation
    failure paths (missing script, Zep updater init failure, Popen/monitor
    launch failure) happen before a monitor thread ever exists to finalize
    a checkpoint. Without an explicit terminal checkpoint in each of those
    paths, GET .../checkpoint would report "starting" forever after a
    startup failure, rather than an honest "failed".
    """

    def test_missing_script_persists_failed_checkpoint(self, tmp_path, monkeypatch):
        simulation_id = "sim_noscript1234"
        sim_dir = tmp_path / "runs" / simulation_id
        scripts_dir = tmp_path / "scripts"  # intentionally left empty: no script file
        sim_dir.mkdir(parents=True)
        scripts_dir.mkdir()
        (sim_dir / "simulation_config.json").write_text(
            json.dumps({
                "time_config": {"total_simulation_hours": 1, "minutes_per_round": 60},
            }),
            encoding="utf-8",
        )

        monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path / "runs"))
        monkeypatch.setattr(SimulationRunner, "SCRIPTS_DIR", str(scripts_dir))
        monkeypatch.setattr(
            SimulationRunner, "_sync_simulation_status", classmethod(lambda *a, **k: None)
        )

        try:
            with pytest.raises(ValueError, match="脚本不存在"):
                SimulationRunner.start_simulation(
                    simulation_id, platform="twitter", enable_graph_memory_update=False
                )

            checkpoint = load_checkpoint(str(sim_dir))
            assert checkpoint is not None
            assert checkpoint["runner_status"] == "failed"
        finally:
            SimulationRunner._run_states.pop(simulation_id, None)
            SimulationRunner._graph_memory_enabled.pop(simulation_id, None)

    def test_missing_graph_id_fails_before_claiming_run_or_touching_checkpoint(
        self, tmp_path, monkeypatch
    ):
        """
        Regression test for Codex's round-4 finding: enable_graph_memory_update=True
        with no graph_id used to raise *after* the checkpoint had already been
        reset to STARTING, leaving it stuck there forever since this path
        never reached any FAILED-transition/checkpoint-save code. It must now
        be validated before the run is claimed at all, so it leaves no trace.
        """
        simulation_id = "sim_nographid12"
        sim_dir = tmp_path / "runs" / simulation_id
        sim_dir.mkdir(parents=True)
        (sim_dir / "simulation_config.json").write_text(
            json.dumps({
                "time_config": {"total_simulation_hours": 1, "minutes_per_round": 60},
            }),
            encoding="utf-8",
        )

        monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path / "runs"))
        monkeypatch.setattr(SimulationRunner, "_run_states", {})

        with pytest.raises(ValueError, match="graph_id"):
            SimulationRunner.start_simulation(
                simulation_id,
                platform="parallel",
                enable_graph_memory_update=True,
                graph_id=None,
            )

        # No run_state.json and no checkpoint.json should have been written --
        # the validation must fail before the run is ever claimed.
        assert simulation_id not in SimulationRunner._run_states
        assert load_checkpoint(str(sim_dir)) is None


class TestStartSimulationClearsStaleActionLogs:
    """
    Regression test for Codex's round-5 finding: this is a pre-existing gap
    that predates the checkpoint feature -- _monitor_simulation always tails
    actions.jsonl from position 0, but nothing cleared that file unless the
    API caller explicitly passed force=True. Restarting a completed/stopped
    simulation without force left the previous run's actions.jsonl in place,
    so the new run's monitor would replay old rounds/actions as if they were
    fresh progress, corrupting both run_state.json and the new checkpoint.
    Fixed at the SimulationRunner level so it holds regardless of how the
    caller invokes start_simulation.
    """

    def test_stale_action_logs_removed_when_claiming_a_new_run(self, tmp_path, monkeypatch):
        simulation_id = "sim_stalelogs123"
        sim_dir = tmp_path / "runs" / simulation_id
        scripts_dir = tmp_path / "scripts"
        sim_dir.mkdir(parents=True)
        scripts_dir.mkdir()
        (sim_dir / "simulation_config.json").write_text(
            json.dumps({
                "time_config": {"total_simulation_hours": 1, "minutes_per_round": 60},
            }),
            encoding="utf-8",
        )
        (scripts_dir / "run_twitter_simulation.py").write_text("pass\n", encoding="utf-8")

        # Leftover action log from a previous, already-finished run.
        stale_log = sim_dir / "twitter" / "actions.jsonl"
        stale_log.parent.mkdir(parents=True)
        stale_log.write_text(
            json.dumps({"event_type": "round_end", "round": 99, "simulated_hours": 99}) + "\n",
            encoding="utf-8",
        )

        class Process:
            pid = 123

            def poll(self):
                return None

        class BrokenThread:
            def __init__(self, **_kwargs):
                pass

            def start(self):
                raise RuntimeError("monitor failed")

        monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path / "runs"))
        monkeypatch.setattr(SimulationRunner, "SCRIPTS_DIR", str(scripts_dir))
        monkeypatch.setattr(runner_module.subprocess, "Popen", lambda *_a, **_k: Process())
        monkeypatch.setattr(runner_module.threading, "Thread", BrokenThread)
        monkeypatch.setattr(
            SimulationRunner,
            "_terminate_process",
            classmethod(lambda _cls, _process, sim_id: None),
        )
        monkeypatch.setattr(
            SimulationRunner, "_sync_simulation_status", classmethod(lambda *a, **k: None)
        )

        try:
            with pytest.raises(RuntimeError, match="monitor failed"):
                SimulationRunner.start_simulation(
                    simulation_id, platform="twitter", enable_graph_memory_update=False
                )

            # The stale log must be gone even though startup failed later --
            # it's cleared at claim time, before any monitor ever runs.
            assert not stale_log.exists()
        finally:
            SimulationRunner._run_states.pop(simulation_id, None)
            SimulationRunner._processes.pop(simulation_id, None)
            SimulationRunner._action_queues.pop(simulation_id, None)
            SimulationRunner._stdout_files.pop(simulation_id, None)
            SimulationRunner._stderr_files.pop(simulation_id, None)
            SimulationRunner._graph_memory_enabled.pop(simulation_id, None)

    def test_start_fails_closed_if_stale_log_cannot_be_removed(self, tmp_path, monkeypatch):
        """
        Regression test for Codex's round-6 finding: if os.remove() itself
        fails while clearing a stale action log (e.g. a read-only
        filesystem), start_simulation must not silently continue and launch
        a monitor that would replay the un-deletable stale log as fresh
        progress. It must fail closed with a FAILED status and a matching
        terminal checkpoint, and never reach subprocess/monitor launch.
        """
        simulation_id = "sim_lockedlogs12"
        sim_dir = tmp_path / "runs" / simulation_id
        scripts_dir = tmp_path / "scripts"
        sim_dir.mkdir(parents=True)
        scripts_dir.mkdir()
        (sim_dir / "simulation_config.json").write_text(
            json.dumps({
                "time_config": {"total_simulation_hours": 1, "minutes_per_round": 60},
            }),
            encoding="utf-8",
        )
        (scripts_dir / "run_twitter_simulation.py").write_text("pass\n", encoding="utf-8")

        stale_log = sim_dir / "twitter" / "actions.jsonl"
        stale_log.parent.mkdir(parents=True)
        stale_log.write_text(
            json.dumps({"event_type": "round_end", "round": 99, "simulated_hours": 99}) + "\n",
            encoding="utf-8",
        )

        monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path / "runs"))
        monkeypatch.setattr(SimulationRunner, "SCRIPTS_DIR", str(scripts_dir))
        monkeypatch.setattr(
            SimulationRunner, "_sync_simulation_status", classmethod(lambda *a, **k: None)
        )

        popen_called = []
        monkeypatch.setattr(
            runner_module.subprocess,
            "Popen",
            lambda *a, **k: popen_called.append(1) or pytest.fail("must not spawn a process"),
        )

        real_remove = os.remove

        def failing_remove(path):
            if path == str(stale_log):
                raise PermissionError("simulated read-only filesystem")
            return real_remove(path)

        monkeypatch.setattr(runner_module.os, "remove", failing_remove)

        try:
            with pytest.raises(RuntimeError, match="清理上一轮动作日志失败"):
                SimulationRunner.start_simulation(
                    simulation_id, platform="twitter", enable_graph_memory_update=False
                )

            assert popen_called == []
            state = SimulationRunner._run_states[simulation_id]
            assert state.runner_status == RunnerStatus.FAILED

            checkpoint = load_checkpoint(str(sim_dir))
            assert checkpoint is not None
            assert checkpoint["runner_status"] == "failed"
        finally:
            SimulationRunner._run_states.pop(simulation_id, None)
            SimulationRunner._graph_memory_enabled.pop(simulation_id, None)


class TestStartFailsClosedWhenCheckpointResetFails:
    """
    Regression test for Codex's round-7 finding, symmetric to round 6 but
    for the checkpoint reset write itself rather than the stale-log cleanup:
    if save_checkpoint() raises while resetting the checkpoint for a new
    run, start_simulation must not silently continue and launch a monitor
    against run_state.json that says STARTING while checkpoint.json still
    (or now permanently) describes an unrelated previous run.
    """

    def test_start_fails_closed_if_checkpoint_reset_write_fails(self, tmp_path, monkeypatch):
        simulation_id = "sim_ckptfail1234"
        sim_dir = tmp_path / "runs" / simulation_id
        scripts_dir = tmp_path / "scripts"
        sim_dir.mkdir(parents=True)
        scripts_dir.mkdir()
        (sim_dir / "simulation_config.json").write_text(
            json.dumps({
                "time_config": {"total_simulation_hours": 1, "minutes_per_round": 60},
            }),
            encoding="utf-8",
        )
        (scripts_dir / "run_twitter_simulation.py").write_text("pass\n", encoding="utf-8")

        monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path / "runs"))
        monkeypatch.setattr(SimulationRunner, "SCRIPTS_DIR", str(scripts_dir))
        monkeypatch.setattr(
            SimulationRunner, "_sync_simulation_status", classmethod(lambda *a, **k: None)
        )

        popen_called = []
        monkeypatch.setattr(
            runner_module.subprocess,
            "Popen",
            lambda *a, **k: popen_called.append(1) or pytest.fail("must not spawn a process"),
        )
        monkeypatch.setattr(
            runner_module.simulation_checkpoint,
            "save_checkpoint",
            lambda *a, **k: (_ for _ in ()).throw(OSError("simulated disk full")),
        )

        try:
            with pytest.raises(RuntimeError, match="重置检查点失败"):
                SimulationRunner.start_simulation(
                    simulation_id, platform="twitter", enable_graph_memory_update=False
                )

            assert popen_called == []
            state = SimulationRunner._run_states[simulation_id]
            assert state.runner_status == RunnerStatus.FAILED
        finally:
            SimulationRunner._run_states.pop(simulation_id, None)
            SimulationRunner._graph_memory_enabled.pop(simulation_id, None)


class TestActionlessRoundStillUpdatesProgressTimestamp:
    """
    Regression test for Codex's round-10 finding: a round where every agent
    chose DO_NOTHING produces a round_end event but zero action records, so
    add_action() (the only other place updated_at was refreshed) never runs.
    Without also touching updated_at on round_end, a simulation that is
    genuinely still advancing would look "stalled" by checkpointed_at even
    though current_round just moved forward.
    """

    def test_round_end_with_no_actions_still_advances_updated_at(self, tmp_path, monkeypatch):
        monkeypatch.setattr(SimulationRunner, "_graph_memory_enabled", {})

        state = SimulationRunState(
            simulation_id="sim_noaction1234",
            runner_status=RunnerStatus.RUNNING,
            updated_at="2020-01-01T00:00:00",
        )
        log_path = tmp_path / "actions.jsonl"
        log_path.write_text(
            json.dumps({"event_type": "round_end", "round": 3, "simulated_hours": 1}) + "\n",
            encoding="utf-8",
        )

        SimulationRunner._read_action_log(str(log_path), 0, state, "twitter")

        assert state.twitter_current_round == 3
        assert state.updated_at != "2020-01-01T00:00:00"
