"""Resuming a stopped run: the runner, the API and the ensemble."""

import json
import sqlite3
import threading
import time
from types import SimpleNamespace

import pytest
from flask import Flask

import sim_resume  # noqa: F401  (the runner loads the same module from the scripts directory)
from app.api import ensemble_bp, simulation_bp
from app.services import simulation_runner as runner_module
from app.services.simulation_manager import SimulationManager, SimulationState, SimulationStatus
from app.services.simulation_runner import RunnerStatus, SimulationRunState, SimulationRunner

from test_sim_resume import action, finished_rounds, make_db, posts, round_end, round_start, write_log

# the fixture below replaces threading.Thread globally; keep the real class for tests that need a thread
REAL_THREAD = threading.Thread

SIM = "sim_resume"
SEED = 4242


class FakeProcess:
    pid = 777

    def __init__(self):
        self.returncode = None

    def poll(self):
        return self.returncode


class InertThread:
    def __init__(self, **_kwargs):
        pass

    def start(self):
        pass


@pytest.fixture
def world(monkeypatch, tmp_path):
    runs = tmp_path / "runs"
    sim_dir = runs / SIM
    sim_dir.mkdir(parents=True)
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "run_parallel_simulation.py").write_text("pass\n", encoding="utf-8")
    (sim_dir / "simulation_config.json").write_text(
        json.dumps({"time_config": {"total_simulation_hours": 24, "minutes_per_round": 60}}), encoding="utf-8"
    )

    commands = []
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(runs))
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(runs))
    monkeypatch.setattr(SimulationRunner, "SCRIPTS_DIR", str(scripts))
    monkeypatch.setattr(runner_module.subprocess, "Popen", lambda cmd, **kw: (commands.append(list(cmd)), FakeProcess())[1])
    monkeypatch.setattr(runner_module.threading, "Thread", InertThread)
    monkeypatch.setattr(SimulationRunner, "_sync_simulation_status", classmethod(lambda *_a, **_k: None))
    monkeypatch.setattr(runner_module.ZepGraphMemoryManager, "get_updater", classmethod(lambda *_a: None))

    def stopped_run(status=RunnerStatus.STOPPED, seed=SEED, total_rounds=24):
        state = SimulationRunState(
            simulation_id=SIM, runner_status=status, total_rounds=total_rounds, seed=seed,
            started_at="2026-01-01T00:00:00", current_round=3,
        )
        SimulationRunner._run_states.pop(SIM, None)
        SimulationRunner._save_run_state(state)
        SimulationRunner._run_states.pop(SIM, None)

    def platform(name, rounds, *, checkpoint_round=None, unfinished=True):
        records = finished_rounds(rounds)
        if unfinished:
            records += [round_start(rounds + 1, [4, 5]), action(rounds + 1, 4)]
        write_log(sim_dir / name / "actions.jsonl", records)
        db = sim_dir / f"{name}_simulation.db"
        make_db(db, ["kept"])
        if checkpoint_round is not None:
            sim_resume.write_checkpoint(str(db), checkpoint_round)
        make_db(db, ["kept", "written by the unfinished round"])         # the live db is ahead of the checkpoint
        return db

    try:
        yield SimpleNamespace(sim_dir=sim_dir, commands=commands, stopped_run=stopped_run, platform=platform, runs=runs)
    finally:
        for registry in (
            SimulationRunner._run_states, SimulationRunner._processes, SimulationRunner._monitor_threads,
            SimulationRunner._action_queues, SimulationRunner._stdout_files, SimulationRunner._stderr_files,
            SimulationRunner._graph_memory_enabled, SimulationRunner._resume_positions,
        ):
            registry.pop(SIM, None)


# --- can a run be resumed? ----------------------------------------------------------------

def test_a_stopped_run_with_checkpoints_is_resumable_and_exact(world):
    world.stopped_run()
    world.platform("twitter", 5, checkpoint_round=5)
    world.platform("reddit", 4, checkpoint_round=4)

    info = SimulationRunner.resume_info(SIM)

    assert info["resumable"] and info["exact"] is True
    assert info["rounds"] == {"twitter": 5, "reddit": 4} and info["round"] == 4
    assert info["total_rounds"] == 24


def test_a_run_from_before_checkpoints_is_resumable_but_not_exact(world):
    world.stopped_run()
    world.platform("twitter", 5)
    world.platform("reddit", 5)
    info = SimulationRunner.resume_info(SIM)
    assert info["resumable"] and info["exact"] is False


@pytest.mark.parametrize("status,reason", [
    (RunnerStatus.COMPLETED, "already complete"),
    (RunnerStatus.IDLE, "not been run"),
])
def test_runs_that_have_nothing_to_resume_say_why(world, status, reason):
    world.stopped_run(status=status)
    world.platform("twitter", 3)
    world.platform("reddit", 3)
    info = SimulationRunner.resume_info(SIM)
    assert not info["resumable"] and reason in info["reason"]


def test_a_run_that_is_still_running_cannot_be_resumed(world, monkeypatch):
    world.stopped_run(status=RunnerStatus.RUNNING)
    world.platform("twitter", 3)
    world.platform("reddit", 3)
    monkeypatch.setattr(SimulationRunner, "has_live_process", classmethod(lambda _c, _id: True))
    assert "still running" in SimulationRunner.resume_info(SIM)["reason"]


def test_an_interrupted_run_whose_process_is_gone_is_resumable(world):
    world.stopped_run(status=RunnerStatus.RUNNING)          # the backend died; nothing updated the state
    world.platform("twitter", 3)
    world.platform("reddit", 3)
    assert SimulationRunner.resume_info(SIM)["resumable"]


def test_the_seed_is_needed_to_replay_the_scheduling(world):
    world.stopped_run(seed=None)
    world.platform("twitter", 3)
    world.platform("reddit", 3)
    assert "seed" in SimulationRunner.resume_info(SIM)["reason"]


def test_a_run_without_action_logs_cannot_be_resumed(world):
    world.stopped_run()
    info = SimulationRunner.resume_info(SIM)
    assert not info["resumable"] and "no action log" in info["reason"]


# --- starting a resumed run --------------------------------------------------------------------

def test_resuming_keeps_the_databases_and_logs_and_passes_resume_to_the_script(world):
    world.stopped_run()
    twitter_db = world.platform("twitter", 5, checkpoint_round=5)
    reddit_db = world.platform("reddit", 5, checkpoint_round=5)
    (world.sim_dir / "simulation.log").write_text("earlier output\n", encoding="utf-8")

    state = SimulationRunner.start_simulation(SIM, platform="parallel", resume=True)

    command = world.commands[0]
    assert "--resume" in command
    assert command[command.index("--seed") + 1] == str(SEED)                   # the run's own seed
    assert command[command.index("--max-rounds") + 1] == "24"                  # and its own round limit
    # nothing deleted; the unfinished round's writes are undone by the checkpoint
    assert twitter_db.exists() and reddit_db.exists()
    assert posts(twitter_db) == ["kept"] and posts(reddit_db) == ["kept"]
    # the logs end with round 5 now (the unfinished round 6 is gone)
    for name in ("twitter", "reddit"):
        records = [json.loads(line) for line in (world.sim_dir / name / "actions.jsonl").read_text("utf-8").splitlines()]
        assert records[-1] == round_end(5, 2)
    assert (world.sim_dir / "simulation.log").read_text("utf-8").startswith("earlier output")
    assert "继续模拟" in (world.sim_dir / "simulation.log").read_text("utf-8")
    assert state.resumed_from_round == 5 and state.resume_count == 1 and state.resume_exact is True
    assert state.started_at == "2026-01-01T00:00:00"                               # the run keeps its start time


def test_the_counters_are_rebuilt_from_the_kept_log_without_reaching_zep(world, monkeypatch):
    world.stopped_run()
    world.platform("twitter", 5, checkpoint_round=5)
    world.platform("reddit", 3, checkpoint_round=3)
    sent = []

    class Updater:
        def add_activity_from_dict(self, *args):
            sent.append(args)

    monkeypatch.setattr(runner_module.ZepGraphMemoryManager, "get_updater", classmethod(lambda *_a: None))
    state = SimulationRunner.start_simulation(SIM, platform="parallel", resume=True)

    assert state.twitter_current_round == 5 and state.reddit_current_round == 3
    assert state.twitter_actions_count == 1 + 5 * 2 and state.reddit_actions_count == 1 + 3 * 2
    assert state.activity["twitter"]["state"] == "done"
    assert sent == []
    # the monitor will continue after what was loaded, not from byte 0
    positions = SimulationRunner._resume_positions[SIM]
    assert positions["twitter"] == (world.sim_dir / "twitter" / "actions.jsonl").stat().st_size


def test_without_checkpoints_the_database_is_left_exactly_as_it_is(world):
    world.stopped_run()
    twitter_db = world.platform("twitter", 5)
    world.platform("reddit", 5)

    state = SimulationRunner.start_simulation(SIM, platform="parallel", resume=True)

    assert posts(twitter_db) == ["kept", "written by the unfinished round"]
    assert state.resume_exact is False


def test_resuming_twice_counts_up(world):
    world.stopped_run()
    world.platform("twitter", 3, checkpoint_round=3)
    world.platform("reddit", 3, checkpoint_round=3)
    SimulationRunner.start_simulation(SIM, platform="parallel", resume=True)
    saved = SimulationRunner._run_states.pop(SIM)
    saved.runner_status = RunnerStatus.STOPPED
    SimulationRunner._save_run_state(saved)
    SimulationRunner._run_states.pop(SIM, None)
    SimulationRunner._processes.pop(SIM, None)

    state = SimulationRunner.start_simulation(SIM, platform="parallel", resume=True)

    assert state.resume_count == 2


def test_an_unresumable_run_is_refused_without_touching_anything(world):
    world.stopped_run(status=RunnerStatus.COMPLETED)
    db = world.platform("twitter", 3)
    world.platform("reddit", 3)
    before = (world.sim_dir / "twitter" / "actions.jsonl").read_bytes()

    with pytest.raises(ValueError, match="无法继续"):
        SimulationRunner.start_simulation(SIM, platform="parallel", resume=True)

    assert (world.sim_dir / "twitter" / "actions.jsonl").read_bytes() == before and db.exists()
    assert world.commands == []


def test_a_normal_start_is_unchanged_by_resume_support(world):
    world.stopped_run()
    world.platform("twitter", 5, checkpoint_round=5)
    world.platform("reddit", 5, checkpoint_round=5)

    SimulationRunner.start_simulation(SIM, platform="parallel", seed=11)

    assert "--resume" not in world.commands[0]
    assert world.commands[0][world.commands[0].index("--seed") + 1] == "11"
    assert (world.sim_dir / "twitter" / "actions.jsonl").stat().st_size > 0       # the script, not the runner, starts over
    assert SimulationRunner._resume_positions.get(SIM) is None


def test_cleanup_for_a_start_over_removes_the_checkpoints_too(world):
    world.stopped_run()
    db = world.platform("twitter", 3, checkpoint_round=3)
    assert (db.parent / (db.name + ".ckpt")).exists()
    SimulationRunner.cleanup_simulation_logs(SIM)
    assert not (db.parent / (db.name + ".ckpt")).exists() and not db.exists()


# --- the API -----------------------------------------------------------------------------------

@pytest.fixture
def client(world, monkeypatch):
    SimulationManager()._save_simulation_state(SimulationState(
        simulation_id=SIM, project_id="proj_x", graph_id="g", status=SimulationStatus.STOPPED,
    ))
    app = Flask(__name__)
    app.register_blueprint(simulation_bp, url_prefix="/api/simulation")
    app.register_blueprint(ensemble_bp, url_prefix="/api/simulation")
    return app.test_client()


def test_the_resume_info_endpoint(client, world):
    world.stopped_run()
    world.platform("twitter", 4, checkpoint_round=4)
    world.platform("reddit", 4, checkpoint_round=4)

    data = client.get(f"/api/simulation/{SIM}/resume-info").get_json()["data"]

    assert data["resumable"] and data["round"] == 4 and data["exact"]
    assert client.get("/api/simulation/sim_missing/resume-info").status_code == 404


def test_the_resume_endpoint_starts_the_run_with_resume(client, world):
    world.stopped_run()
    world.platform("twitter", 4, checkpoint_round=4)
    world.platform("reddit", 4, checkpoint_round=4)

    response = client.post("/api/simulation/resume", json={"simulation_id": SIM})

    body = response.get_json()
    assert response.status_code == 200 and body["success"]
    assert body["data"]["resumed_from_round"] == 4 and body["data"]["resume"]["resumable"]
    assert "--resume" in world.commands[0]


def test_the_resume_endpoint_refuses_what_cannot_be_resumed(client, world):
    world.stopped_run(status=RunnerStatus.COMPLETED)
    world.platform("twitter", 4)
    world.platform("reddit", 4)

    response = client.post("/api/simulation/resume", json={"simulation_id": SIM})

    assert response.status_code == 409
    assert "already complete" in response.get_json()["error"]
    assert world.commands == []


def test_the_resume_endpoint_validates_its_input(client, world):
    assert client.post("/api/simulation/resume", json={}).status_code == 400
    assert client.post("/api/simulation/resume", json={"simulation_id": "nope"}).status_code == 404
    assert client.post("/api/simulation/resume", json={"simulation_id": SIM, "enable_graph_memory_update": "yes"}).status_code == 400


# --- state files are written in one step ---------------------------------------------------------

def make_running_state():
    return SimulationRunState(simulation_id=SIM, runner_status=RunnerStatus.RUNNING, total_rounds=40, seed=SEED)


def test_the_run_state_file_is_only_replaced_when_the_new_one_is_complete(world, monkeypatch):
    """Until the final swap the old, complete file stays in place (the old code truncated it first)."""
    from app.utils import atomic_write

    state = make_running_state()
    state.current_round = 1
    SimulationRunner._save_run_state(state)
    state_file = world.sim_dir / "run_state.json"
    seen = []
    real_replace = atomic_write.os.replace

    def checking_replace(source, target):
        seen.append(json.loads(state_file.read_text("utf-8"))["current_round"])      # still the previous round, complete
        assert json.loads(open(source, encoding="utf-8").read())["current_round"] == 2   # the new content is already whole
        return real_replace(source, target)

    monkeypatch.setattr(atomic_write.os, "replace", checking_replace)
    state.current_round = 2
    SimulationRunner._save_run_state(state)

    assert seen == [1]
    assert json.loads(state_file.read_text("utf-8"))["current_round"] == 2
    assert [p.name for p in world.sim_dir.iterdir() if p.suffix == ".tmp"] == []


def test_a_reader_polling_while_the_monitor_saves_never_sees_a_broken_file(world):
    state_file = world.sim_dir / "run_state.json"
    state = make_running_state()
    SimulationRunner._save_run_state(state)
    stop = threading.Event()
    bad = []

    def read():
        while not stop.is_set():
            try:
                json.loads(state_file.read_text(encoding="utf-8"))
            except PermissionError:
                pass                                             # Windows: the rename is in progress
            except (FileNotFoundError, ValueError) as error:
                bad.append(repr(error))
            time.sleep(0.003)

    reader = REAL_THREAD(target=read)
    reader.start()
    try:
        for round_num in range(200):
            state.current_round = round_num
            SimulationRunner._save_run_state(state)
    finally:
        stop.set()
        reader.join()

    assert bad == []
    assert json.loads(state_file.read_text("utf-8"))["current_round"] == 199


def test_a_refused_rename_does_not_lose_the_save(world, monkeypatch):
    """If Windows keeps refusing the rename, the state is still written (in place) and the run goes on."""
    def refuse(*_args, **_kwargs):
        raise PermissionError("[WinError 5] Access is denied")

    monkeypatch.setattr(runner_module, "write_json_atomic", refuse)
    state = make_running_state()
    state.current_round = 7
    SimulationRunner._save_run_state(state)

    assert json.loads((world.sim_dir / "run_state.json").read_text("utf-8"))["current_round"] == 7
    assert SimulationRunner._run_states[SIM] is state


def test_the_simulation_record_is_written_the_same_way(world, monkeypatch):
    import app.services.simulation_manager as manager_module

    manager = SimulationManager()
    state = SimulationState(simulation_id=SIM, project_id="proj_x", graph_id="g", status=SimulationStatus.READY)
    for _ in range(20):
        manager._save_simulation_state(state)
        json.loads((world.sim_dir / "state.json").read_text("utf-8"))
    assert [p.name for p in world.sim_dir.iterdir() if p.suffix == ".tmp"] == []

    monkeypatch.setattr(manager_module, "write_json_atomic", lambda *a, **k: (_ for _ in ()).throw(PermissionError("denied")))
    manager._save_simulation_state(state)                       # falls back to writing in place
    assert json.loads((world.sim_dir / "state.json").read_text("utf-8"))["simulation_id"] == SIM


# --- a run of one platform uses the same script and the same structured log -----------------------

@pytest.mark.parametrize("platform,flag,other", [("twitter", "--twitter-only", "reddit"), ("reddit", "--reddit-only", "twitter")])
def test_a_single_platform_run_uses_the_parallel_script(world, platform, flag, other):
    state = SimulationRunner.start_simulation(SIM, platform=platform)

    command = world.commands[0]
    assert command[1].endswith("run_parallel_simulation.py") and flag in command
    assert not any(part.endswith(("run_twitter_simulation.py", "run_reddit_simulation.py")) for part in command)
    assert state.platform == platform
    assert getattr(state, f"{platform}_running") is True and getattr(state, f"{other}_running") is False
    assert json.loads((world.sim_dir / "run_state.json").read_text("utf-8"))["platform"] == platform   # survives a restart


def test_a_parallel_run_has_no_platform_flag(world):
    state = SimulationRunner.start_simulation(SIM, platform="parallel")
    assert "--twitter-only" not in world.commands[0] and "--reddit-only" not in world.commands[0]
    assert state.platform == "parallel" and state.twitter_running and state.reddit_running


def test_an_older_run_state_without_a_platform_is_a_parallel_run(world):
    world.stopped_run()
    data = json.loads((world.sim_dir / "run_state.json").read_text("utf-8"))
    data.pop("platform", None)
    (world.sim_dir / "run_state.json").write_text(json.dumps(data), encoding="utf-8")
    SimulationRunner._run_states.pop(SIM, None)
    assert SimulationRunner.get_run_state(SIM).platform == "parallel"


def test_a_leftover_log_of_the_other_platform_does_not_keep_a_single_platform_run_open(world):
    """The run finishes when its own platform has; the other platform's old log is not part of it."""
    write_log(world.sim_dir / "reddit" / "actions.jsonl", finished_rounds(3))      # left by an earlier parallel run
    write_log(world.sim_dir / "twitter" / "actions.jsonl", finished_rounds(2))
    state = SimulationRunState(simulation_id=SIM, runner_status=RunnerStatus.RUNNING, platform="twitter")
    state.twitter_completed = True

    assert SimulationRunner._check_all_platforms_completed(state) is True
    assert SimulationRunner._check_all_platforms_completed(
        SimulationRunState(simulation_id=SIM, runner_status=RunnerStatus.RUNNING, platform="parallel", twitter_completed=True)
    ) is False                                                                        # a parallel run still waits for Reddit


def test_a_single_platform_run_resumes_from_its_own_log_only(world):
    world.stopped_run()
    world.platform("twitter", 4, checkpoint_round=4)                                  # no Reddit log at all
    data = json.loads((world.sim_dir / "run_state.json").read_text("utf-8"))
    data["platform"] = "twitter"
    (world.sim_dir / "run_state.json").write_text(json.dumps(data), encoding="utf-8")
    SimulationRunner._run_states.pop(SIM, None)

    info = SimulationRunner.resume_info(SIM)
    assert info["resumable"] and info["rounds"] == {"twitter": 4}

    state = SimulationRunner.start_simulation(SIM, platform="parallel", resume=True)      # the argument is ignored on resume
    assert "--twitter-only" in world.commands[0] and "--resume" in world.commands[0]
    assert state.platform == "twitter" and state.resumed_from_round == 4


def test_a_parallel_run_still_needs_both_logs_to_resume(world):
    world.stopped_run()
    world.platform("twitter", 4, checkpoint_round=4)
    info = SimulationRunner.resume_info(SIM)
    assert not info["resumable"] and "reddit" in info["reason"]
