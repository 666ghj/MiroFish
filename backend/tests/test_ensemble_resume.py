"""Resuming a stopped or interrupted ensemble."""

from types import SimpleNamespace

import pytest
from flask import Flask

from app.api import ensemble_bp, simulation_bp
from app.services import ensemble_runner as er
from app.services.ensemble_runner import EnsembleConflict, EnsembleManager
from app.services.simulation_runner import RunnerStatus, SimulationRunner

from test_ensemble_manager import create, drive, env, rid, status_of, wait_for  # noqa: F401  (env is a fixture)

NOT_RUN = {"resumable": False, "reason": "this simulation has not been run yet", "round": None, "exact": None}
SETUP = {"resumable": False, "reason": "twitter: the run stopped while it was still setting up; start it over",
         "round": None, "exact": None}
SEED_LOST = {"resumable": False, "reason": "the run's seed was not recorded", "round": None, "exact": None}


def resumable(round_num, exact=True):
    return {"resumable": True, "reason": None, "round": round_num, "exact": exact}


@pytest.fixture
def infos(monkeypatch):
    """What ``SimulationRunner.resume_info`` answers per simulation id (default: not run yet)."""
    answers = {}
    monkeypatch.setattr(
        SimulationRunner, "resume_info", classmethod(lambda _cls, simulation_id: answers.get(simulation_id, NOT_RUN))
    )
    cleaned = []
    monkeypatch.setattr(
        SimulationRunner, "cleanup_simulation_logs",
        classmethod(lambda _cls, simulation_id: (cleaned.append(simulation_id), {"success": True})[1]),
    )
    return SimpleNamespaceLike(answers=answers, cleaned=cleaned)


class SimpleNamespaceLike:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def set_states(ensemble_id, status, replicate_states, **extra):
    """Put an ensemble into a given shape: ``replicate_states`` is [(status, error), ...]."""
    ensemble = EnsembleManager._load(ensemble_id)
    for replicate, (replicate_status, error) in zip(ensemble["replicates"], replicate_states):
        replicate.update(status=replicate_status, error=error)
    ensemble.update(status=status, **extra)
    EnsembleManager._save(ensemble)


def started_with(env, simulation_id):
    return [call for call in env.runner.started if call["simulation_id"] == simulation_id]


def test_stopped_runs_continue_and_the_rest_start_where_they_never_started(env, infos):
    ensemble = create(env, n_replicates=3)
    ensemble_id = ensemble["ensemble_id"]
    set_states(ensemble_id, "stopped", [("stopped", None), ("stopped", None), ("stopped", None)])
    infos.answers[rid(ensemble, 1)] = resumable(7)

    EnsembleManager.resume(ensemble_id)
    drive(env, ensemble_id, {})

    assert started_with(env, rid(ensemble, 1))[0]["resume"] is True
    assert started_with(env, rid(ensemble, 2))[0]["resume"] is False         # nothing to keep: a fresh start
    assert started_with(env, rid(ensemble, 3))[0]["resume"] is False
    assert infos.cleaned == [rid(ensemble, 2), rid(ensemble, 3)]               # only those get their old files cleared
    final = EnsembleManager._load(ensemble_id)
    assert final["status"] == "completed" and final["resume_count"] == 1 and final["resumed_at"]
    assert final["replicates"][0]["resumed"] is True and "resume" not in final["replicates"][0]


def test_finished_runs_are_kept_and_interrupted_ones_are_resumed(env, infos):
    ensemble = create(env, n_replicates=3, concurrency=2)
    ensemble_id = ensemble["ensemble_id"]
    set_states(ensemble_id, "failed", [("completed", None), ("failed", er.INTERRUPTED_ERROR), ("stopped", None)],
               error="fewer than 2 replicates completed; nothing to aggregate")
    infos.answers[rid(ensemble, 2)] = resumable(4)
    infos.answers[rid(ensemble, 3)] = resumable(0)

    EnsembleManager.resume(ensemble_id)
    drive(env, ensemble_id, {})

    assert started_with(env, rid(ensemble, 1)) == []                           # the finished run is not touched
    assert started_with(env, rid(ensemble, 2))[0]["resume"] and started_with(env, rid(ensemble, 3))[0]["resume"]
    final = EnsembleManager._load(ensemble_id)
    assert final["status"] == "completed" and final["error"] is None


def test_a_run_that_really_failed_is_not_resumed(env, infos):
    ensemble = create(env, n_replicates=3, concurrency=2)
    ensemble_id = ensemble["ensemble_id"]
    set_states(ensemble_id, "failed", [("completed", None), ("failed", "the simulation failed: boom"), ("stopped", None)])
    infos.answers[rid(ensemble, 3)] = resumable(2)

    EnsembleManager.resume(ensemble_id)
    drive(env, ensemble_id, {})

    assert started_with(env, rid(ensemble, 2)) == []
    final = EnsembleManager._load(ensemble_id)
    assert final["replicates"][1]["status"] == "failed"
    assert final["status"] == "partial"                                        # 2 of 3 completed


def test_a_run_that_cannot_be_resumed_for_another_reason_is_left_alone(env, infos):
    ensemble = create(env, n_replicates=2)
    ensemble_id = ensemble["ensemble_id"]
    set_states(ensemble_id, "stopped", [("stopped", None), ("stopped", None)])
    infos.answers[rid(ensemble, 1)] = SEED_LOST
    infos.answers[rid(ensemble, 2)] = resumable(3)

    info = EnsembleManager.resume_info(ensemble_id)
    assert [item["action"] for item in info["replicates"]] == ["skip", "resume"]

    EnsembleManager.resume(ensemble_id)
    wait_for(lambda: started_with(env, rid(ensemble, 2)), message="the resumed run to start")
    assert started_with(env, rid(ensemble, 1)) == []
    assert EnsembleManager._load(ensemble_id)["replicates"][0]["status"] == "stopped"


def test_a_run_that_died_during_setup_starts_over(env, infos):
    ensemble = create(env, n_replicates=2)
    ensemble_id = ensemble["ensemble_id"]
    set_states(ensemble_id, "stopped", [("stopped", None), ("stopped", None)])
    infos.answers[rid(ensemble, 1)] = SETUP
    infos.answers[rid(ensemble, 2)] = resumable(5)

    assert [item["action"] for item in EnsembleManager.resume_info(ensemble_id)["replicates"]] == ["restart", "resume"]


def test_the_resume_info_describes_each_run(env, infos):
    ensemble = create(env, n_replicates=2)
    ensemble_id = ensemble["ensemble_id"]
    set_states(ensemble_id, "stopped", [("stopped", None), ("completed", None)])
    infos.answers[rid(ensemble, 1)] = resumable(6, exact=False)

    info = EnsembleManager.resume_info(ensemble_id)

    assert info["resumable"] and info["replicates"] == [
        {"simulation_id": rid(ensemble, 1), "action": "resume", "round": 6, "exact": False, "memory": None, "reason": None}
    ]


@pytest.mark.parametrize("status", ["created", "running", "completed"])
def test_only_stopped_failed_or_partial_ensembles_can_be_resumed(env, infos, status):
    ensemble = create(env, n_replicates=2)
    ensemble_id = ensemble["ensemble_id"]
    set_states(ensemble_id, status, [("completed", None), ("completed", None)])
    with pytest.raises(EnsembleConflict):
        EnsembleManager.resume(ensemble_id)
    assert not EnsembleManager.resume_info(ensemble_id)["resumable"]


def test_an_ensemble_with_nothing_resumable_says_so(env, infos):
    ensemble = create(env, n_replicates=2)
    ensemble_id = ensemble["ensemble_id"]
    set_states(ensemble_id, "failed", [("failed", "boom"), ("failed", "boom")])
    with pytest.raises(EnsembleConflict, match="None of this ensemble's runs"):
        EnsembleManager.resume(ensemble_id)
    assert status_of(ensemble_id) == "failed"


def test_resuming_after_a_backend_restart_repairs_the_orphans_first(env, infos):
    """A 'running' ensemble whose process is gone is reconciled (runs become interrupted), then resumed."""
    ensemble = create(env, n_replicates=2)
    ensemble_id = ensemble["ensemble_id"]
    set_states(ensemble_id, "running", [("running", None), ("pending", None)])
    # the replicate's process is gone but its run state still says RUNNING (nothing updated it)
    env.runner.states[rid(ensemble, 1)] = SimpleNamespace(
        runner_status=RunnerStatus.RUNNING, current_round=3, total_rounds=12, error=None
    )
    infos.answers[rid(ensemble, 1)] = resumable(3)
    infos.answers[rid(ensemble, 2)] = NOT_RUN

    EnsembleManager.resume(ensemble_id)
    wait_for(lambda: started_with(env, rid(ensemble, 1)), message="the interrupted run to be started again")
    drive(env, ensemble_id, {})

    assert started_with(env, rid(ensemble, 1))[0]["resume"] is True
    assert started_with(env, rid(ensemble, 2))[0]["resume"] is False


# --- the API ----------------------------------------------------------------------------------

@pytest.fixture
def client(env):
    app = Flask(__name__)
    app.register_blueprint(simulation_bp, url_prefix="/api/simulation")
    app.register_blueprint(ensemble_bp, url_prefix="/api/simulation")
    return app.test_client()


def test_the_api_resumes_and_reports_what_it_would_do(env, infos, client):
    ensemble = create(env, n_replicates=2)
    ensemble_id = ensemble["ensemble_id"]
    set_states(ensemble_id, "stopped", [("stopped", None), ("stopped", None)])
    infos.answers[rid(ensemble, 1)] = resumable(2)

    info = client.get(f"/api/simulation/ensemble/{ensemble_id}/resume-info").get_json()["data"]
    assert info["resumable"] and info["replicates"][0]["action"] == "resume"

    response = client.post(f"/api/simulation/ensemble/{ensemble_id}/resume")
    assert response.status_code == 200 and response.get_json()["data"]["status"] == "running"
    drive(env, ensemble_id, {})
    assert status_of(ensemble_id) == "completed"


def test_the_api_refuses_a_resume_that_makes_no_sense(env, infos, client):
    ensemble = create(env, n_replicates=2)
    response = client.post(f"/api/simulation/ensemble/{ensemble['ensemble_id']}/resume")      # still 'created'
    assert response.status_code == 409
    assert client.post("/api/simulation/ensemble/ens_missing/resume").status_code == 404
