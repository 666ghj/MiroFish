"""History order and deleting a run together with its project."""
import json
import os
import time
from types import SimpleNamespace

import pytest
from flask import Flask

from app.api import ensemble_bp, simulation_bp
from app.models.project import ProjectManager
from app.services.ensemble_runner import EnsembleManager
from app.services.report_agent import ReportManager
from app.services.simulation_manager import SimulationManager, SimulationState, SimulationStatus
from app.services.simulation_runner import RunnerStatus

from test_ensemble_manager import BASE_ID, QUESTIONS, env  # noqa: F401  (env is a fixture)


@pytest.fixture
def world(env, monkeypatch, tmp_path):
    projects = tmp_path / "projects"
    projects.mkdir()
    monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(projects))
    for name in ("proj_1", "proj_2"):
        (projects / name).mkdir()
        (projects / name / "project.json").write_text(
            json.dumps({"project_id": name, "name": name, "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00"}),
            encoding="utf-8",
        )

    deleted_reports = []
    reports = [
        SimpleNamespace(report_id="rep_base", simulation_id=BASE_ID, ensemble_id=None),
        SimpleNamespace(report_id="rep_other", simulation_id="sim_other", ensemble_id=None),
    ]
    monkeypatch.setattr(ReportManager, "list_reports", classmethod(lambda c, simulation_id=None, limit=50: list(reports)))
    monkeypatch.setattr(ReportManager, "delete_report", classmethod(lambda c, report_id: deleted_reports.append(report_id) or True))

    graph_calls = []
    from app.api import graph as graph_api
    monkeypatch.setattr(graph_api, "_delete_cloud_graph_if_present", lambda graph_id: graph_calls.append(graph_id))

    app = Flask(__name__)
    app.register_blueprint(simulation_bp, url_prefix="/api/simulation")
    app.register_blueprint(ensemble_bp, url_prefix="/api/simulation")
    return SimpleNamespace(env=env, projects=projects, client=app.test_client(),
                           deleted_reports=deleted_reports, graph_calls=graph_calls, reports=reports)


def add_sim(env, simulation_id, project_id):
    env.manager._save_simulation_state(SimulationState(
        simulation_id=simulation_id, project_id=project_id, graph_id=f"graph_{project_id}",
        status=SimulationStatus.COMPLETED, entities_count=2, profiles_count=2,
    ))
    return env.sims / simulation_id


def test_history_lists_the_most_recently_touched_run_first(world):
    old = add_sim(world.env, "sim_old", "proj_2")
    mid = add_sim(world.env, "sim_mid", "proj_2")
    (mid / "run_state.json").write_text("{}", encoding="utf-8")
    now = time.time()
    os.utime(mid / "run_state.json", (now + 3600, now + 3600))   # a run that worked an hour from now

    ids = [s["simulation_id"] for s in world.client.get("/api/simulation/history").get_json()["data"]]
    assert ids.index("sim_mid") < ids.index("sim_old")
    assert ids.index("sim_mid") < ids.index(BASE_ID)


def test_deleting_a_run_removes_its_project_replicates_ensembles_and_reports(world):
    env = world.env
    add_sim(env, "sim_sibling", "proj_1")            # same project: goes too
    add_sim(env, "sim_other", "proj_2")              # another project: stays
    EnsembleManager.create(BASE_ID, n_replicates=2, max_rounds=3, outcome_questions=QUESTIONS, base_seed=5)
    replicate_dirs = [p for p in env.sims.iterdir() if p.name.startswith(f"{BASE_ID}__")]
    ensemble_dirs = list(env.ensembles.iterdir()) if env.ensembles.exists() else []

    response = world.client.delete(f"/api/simulation/{BASE_ID}")

    assert response.status_code == 200, response.get_json()
    assert response.get_json()["data"]["project_id"] == "proj_1"
    assert not (env.sims / BASE_ID).exists() and not (env.sims / "sim_sibling").exists()
    assert (env.sims / "sim_other").exists()
    assert not any(p.exists() for p in replicate_dirs + ensemble_dirs)
    assert not (world.projects / "proj_1").exists() and (world.projects / "proj_2").exists()
    assert world.deleted_reports == ["rep_base"]
    assert world.graph_calls == ["graph_1"]


def test_with_project_false_keeps_the_project_and_its_other_runs(world):
    add_sim(world.env, "sim_sibling", "proj_1")
    response = world.client.delete(f"/api/simulation/{BASE_ID}?with_project=false")
    assert response.status_code == 200
    assert not (world.env.sims / BASE_ID).exists()
    assert (world.env.sims / "sim_sibling").exists() and (world.projects / "proj_1").exists()
    assert world.graph_calls == []


def test_nothing_is_deleted_while_a_run_of_the_project_is_running(world):
    add_sim(world.env, "sim_sibling", "proj_1")
    world.env.runner.start("sim_sibling")

    response = world.client.delete(f"/api/simulation/{BASE_ID}")

    assert response.status_code == 409
    assert "sim_sibling is running" in response.get_json()["error"]
    assert (world.env.sims / BASE_ID).exists() and (world.projects / "proj_1").exists()
    assert world.graph_calls == [] and world.deleted_reports == []


def test_a_failing_graph_deletion_leaves_everything_in_place(world, monkeypatch):
    from app.api import graph as graph_api

    def refuse(graph_id):
        raise graph_api.GraphInUseError("graph is in use")

    monkeypatch.setattr(graph_api, "_delete_cloud_graph_if_present", refuse)
    response = world.client.delete(f"/api/simulation/{BASE_ID}")
    assert response.status_code == 409
    assert (world.env.sims / BASE_ID).exists() and (world.projects / "proj_1").exists()


def test_deleting_an_unknown_run_is_a_404(world):
    assert world.client.delete("/api/simulation/sim_missing").status_code == 404
