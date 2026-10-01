"""
集成模拟 API 路由测试（app/api/ensemble.py）

只覆盖路由层本身的行为（参数校验、状态码、鉴权接线），聚合/编排逻辑本身
已经在 tests/test_ensemble_runner.py 里直接对 EnsembleRunner 做了覆盖。
"""

import json
import os

import pytest

from app import create_app
from app.services.ensemble_runner import EnsembleRunner
from app.services import simulation_runner as runner_module
from app.services.simulation_runner import SimulationRunner
from app.services.simulation_manager import SimulationManager, SimulationState, SimulationStatus


class FakeProcess:
    pid = 4242

    def poll(self):
        return None


class NoOpThread:
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


def _make_source_simulation(simulation_id="sim_source12345", owner_id=None):
    manager = SimulationManager()
    state = SimulationState(
        simulation_id=simulation_id,
        project_id="proj_test1234",
        graph_id="graph-test-1",
        enable_twitter=False,
        enable_reddit=True,
        status=SimulationStatus.READY,
        profiles_generated=True,
        config_generated=True,
        owner_id=owner_id,
        random_seed=777,
    )
    manager._save_simulation_state(state)

    sim_dir = manager._get_simulation_dir(simulation_id)
    with open(os.path.join(sim_dir, "simulation_config.json"), "w", encoding="utf-8") as f:
        json.dump({"time_config": {"total_simulation_hours": 1, "minutes_per_round": 60}}, f)
    with open(os.path.join(sim_dir, "reddit_profiles.json"), "w", encoding="utf-8") as f:
        json.dump([{"id": 1, "username": "alice"}], f)

    return state


@pytest.fixture
def client():
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


@pytest.fixture
def two_user_client(monkeypatch):
    from app.config import Config

    monkeypatch.setattr(Config, "API_KEYS", {"alice-key": "alice", "bob-key": "bob"})
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def _auth(user_key):
    return {"Authorization": f"Bearer {user_key}-key"}


class TestStartEnsembleRoute:
    def test_start_requires_source_simulation_id(self, client):
        response = client.post("/api/ensemble/start", json={"run_count": 3})
        assert response.status_code == 400

    def test_start_requires_run_count(self, client):
        response = client.post(
            "/api/ensemble/start", json={"source_simulation_id": "sim_source12345"}
        )
        assert response.status_code == 400

    def test_start_rejects_invalid_platform(self, client):
        _make_source_simulation()
        response = client.post(
            "/api/ensemble/start",
            json={
                "source_simulation_id": "sim_source12345",
                "run_count": 3,
                "platform": "myspace",
            },
        )
        assert response.status_code == 400

    def test_start_with_malformed_json_body_returns_400_not_500(self, client):
        # request.get_json() (without silent=True) raises a werkzeug
        # BadRequest/UnsupportedMediaType for a missing/invalid JSON body,
        # which the route's broad except-Exception used to convert into a
        # 500 with a leaked traceback instead of a clean 4xx.
        response = client.post(
            "/api/ensemble/start",
            data="{not valid json",
            content_type="application/json",
        )
        assert response.status_code == 400
        assert response.json["success"] is False

    def test_start_with_no_content_type_returns_400_not_500(self, client):
        response = client.post("/api/ensemble/start")
        assert response.status_code == 400
        assert response.json["success"] is False

    def test_start_rejects_non_object_json_body(self, client):
        # get_json(silent=True) happily decodes valid-but-non-object JSON
        # (a list here) without raising; the "or {}" idiom only rescues a
        # falsy/None result, so a plain .get(...) on a list would otherwise
        # raise AttributeError and surface as a 500.
        response = client.post("/api/ensemble/start", json=[1, 2, 3])
        assert response.status_code == 400
        assert response.json["success"] is False

    def test_start_rejects_fractional_max_rounds(self, client):
        _make_source_simulation()
        response = client.post(
            "/api/ensemble/start",
            json={
                "source_simulation_id": "sim_source12345",
                "run_count": 2,
                "max_rounds": 2.9,
            },
        )
        assert response.status_code == 400

    def test_start_rejects_boolean_max_rounds(self, client):
        # isinstance(True, int) is True in Python, so a naive int(x) check
        # would silently accept this and run int(True) == 1 round.
        _make_source_simulation()
        response = client.post(
            "/api/ensemble/start",
            json={
                "source_simulation_id": "sim_source12345",
                "run_count": 2,
                "max_rounds": True,
            },
        )
        assert response.status_code == 400

    def test_start_happy_path_returns_members(self, client):
        _make_source_simulation()
        response = client.post(
            "/api/ensemble/start",
            json={"source_simulation_id": "sim_source12345", "run_count": 3},
        )
        assert response.status_code == 200
        data = response.json["data"]
        assert data["run_count"] == 3
        assert len(data["members"]) == 3
        assert all(m["start_error"] is None for m in data["members"])

    def test_start_404s_cleanly_when_source_missing(self, client):
        response = client.post(
            "/api/ensemble/start",
            json={"source_simulation_id": "sim_nope1234", "run_count": 3},
        )
        assert response.status_code == 400  # ValueError from the service -> 400
        assert response.json["success"] is False


class TestGetEnsembleRoute:
    def test_get_returns_live_status(self, client):
        _make_source_simulation()
        start_response = client.post(
            "/api/ensemble/start",
            json={"source_simulation_id": "sim_source12345", "run_count": 2},
        )
        ensemble_id = start_response.json["data"]["ensemble_id"]

        response = client.get(f"/api/ensemble/{ensemble_id}")
        assert response.status_code == 200
        assert response.json["data"]["status"] == "running"
        assert response.json["data"]["aggregate"] is None

    def test_get_404_when_missing(self, client):
        response = client.get("/api/ensemble/ens_doesnotexist")
        assert response.status_code == 404


class TestListEnsemblesRoute:
    def test_list_returns_created_ensembles(self, client):
        _make_source_simulation()
        client.post(
            "/api/ensemble/start",
            json={"source_simulation_id": "sim_source12345", "run_count": 2},
        )

        response = client.get("/api/ensemble/list")
        assert response.status_code == 200
        assert len(response.json["data"]) == 1
        assert response.json["data"][0]["source_simulation_id"] == "sim_source12345"


class TestStopEnsembleRoute:
    def test_stop_requires_ensemble_id(self, client):
        response = client.post("/api/ensemble/stop", json={})
        assert response.status_code == 400

    def test_stop_with_malformed_json_body_returns_400_not_500(self, client):
        response = client.post(
            "/api/ensemble/stop",
            data="{not valid json",
            content_type="application/json",
        )
        assert response.status_code == 400
        assert response.json["success"] is False

    def test_stop_rejects_non_object_json_body(self, client):
        response = client.post("/api/ensemble/stop", json="not-an-object")
        assert response.status_code == 400
        assert response.json["success"] is False

    def test_stop_404_when_missing(self, client):
        response = client.post("/api/ensemble/stop", json={"ensemble_id": "ens_doesnotexist"})
        assert response.status_code == 404

    def test_stop_happy_path(self, client, monkeypatch):
        _make_source_simulation()
        start_response = client.post(
            "/api/ensemble/start",
            json={"source_simulation_id": "sim_source12345", "run_count": 2},
        )
        ensemble_id = start_response.json["data"]["ensemble_id"]

        def fake_stop_simulation(cls, simulation_id):
            state = SimulationRunner.get_run_state(simulation_id)
            from app.services.simulation_runner import RunnerStatus
            state.runner_status = RunnerStatus.STOPPED
            SimulationRunner._save_run_state(state)
            return state

        monkeypatch.setattr(
            SimulationRunner, "stop_simulation", classmethod(fake_stop_simulation)
        )

        response = client.post("/api/ensemble/stop", json={"ensemble_id": ensemble_id})
        assert response.status_code == 200
        assert len(response.json["data"]["results"]) == 2


class TestEnsembleRouteForbiddenErrorReturns403:
    """
    ForbiddenError must reach the app's global @app.errorhandler(ForbiddenError)
    (-> 403) instead of being caught by each route's broad `except Exception`
    (which would turn it into a 500 with a leaked traceback). Uses
    two_user_client so authorize() actually raises instead of the no-API-keys
    fail-open path the other tests in this file rely on.
    """

    def test_start_with_another_users_source_returns_403(self, two_user_client):
        _make_source_simulation(owner_id="alice")
        response = two_user_client.post(
            "/api/ensemble/start",
            json={"source_simulation_id": "sim_source12345", "run_count": 2},
            headers=_auth("bob"),
        )
        assert response.status_code == 403

    def test_get_another_users_ensemble_returns_403(self, two_user_client):
        _make_source_simulation(owner_id="alice")
        start_response = two_user_client.post(
            "/api/ensemble/start",
            json={"source_simulation_id": "sim_source12345", "run_count": 2},
            headers=_auth("alice"),
        )
        ensemble_id = start_response.json["data"]["ensemble_id"]

        response = two_user_client.get(
            f"/api/ensemble/{ensemble_id}", headers=_auth("bob")
        )
        assert response.status_code == 403

    def test_stop_another_users_ensemble_returns_403(self, two_user_client):
        _make_source_simulation(owner_id="alice")
        start_response = two_user_client.post(
            "/api/ensemble/start",
            json={"source_simulation_id": "sim_source12345", "run_count": 2},
            headers=_auth("alice"),
        )
        ensemble_id = start_response.json["data"]["ensemble_id"]

        response = two_user_client.post(
            "/api/ensemble/stop",
            json={"ensemble_id": ensemble_id},
            headers=_auth("bob"),
        )
        assert response.status_code == 403
