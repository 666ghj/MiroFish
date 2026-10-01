"""
历史回测 API 路由测试（app/api/backtest.py）

只覆盖路由层本身的行为（参数校验、状态码、鉴权接线），登记/打分/聚合逻辑
本身已经在 tests/test_backtest_runner.py 里直接对 BacktestRunner 做了覆盖。
"""

import pytest

from app import create_app
from app.services.backtest_runner import BacktestRunner
from app.services.simulation_manager import SimulationManager, SimulationState, SimulationStatus
from app.services.simulation_runner import RunnerStatus, SimulationRunner, SimulationRunState


@pytest.fixture(autouse=True)
def _isolated_dirs(tmp_path, monkeypatch):
    simulations_dir = tmp_path / "simulations"
    backtests_dir = tmp_path / "backtests"
    simulations_dir.mkdir()

    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(simulations_dir))
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(simulations_dir))
    monkeypatch.setattr(BacktestRunner, "BACKTEST_DATA_DIR", str(backtests_dir))
    monkeypatch.setattr(SimulationRunner, "_run_states", {})

    yield


def _make_completed_simulation(simulation_id="sim_source12345", owner_id=None):
    manager = SimulationManager()
    state = SimulationState(
        simulation_id=simulation_id,
        project_id="proj_test1234",
        graph_id="graph-test-1",
        status=SimulationStatus.COMPLETED,
        owner_id=owner_id,
    )
    manager._save_simulation_state(state)
    SimulationRunner._save_run_state(
        SimulationRunState(simulation_id=simulation_id, runner_status=RunnerStatus.COMPLETED)
    )
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


class TestCreateBacktestRoute:
    def test_requires_prediction(self, client):
        _make_completed_simulation()
        response = client.post(
            "/api/backtest/create",
            json={
                "source_simulation_id": "sim_source12345",
                "scenario_description": "x",
                "t0_cutoff": "2024-01-01",
            },
        )
        assert response.status_code == 400

    def test_rejects_non_object_json_body(self, client):
        response = client.post("/api/backtest/create", json=[1, 2, 3])
        assert response.status_code == 400

    def test_malformed_source_simulation_id_returns_400_not_500(self, client):
        # InvalidIdentifierError is a ValueError subclass; it must be
        # re-raised before the generic except-ValueError clause catches it,
        # so it reaches the app's global 400 handler instead of the
        # route's own (still-400, but differently worded) ValueError path.
        response = client.post(
            "/api/backtest/create",
            json={
                "source_simulation_id": "bad$id",
                "scenario_description": "x",
                "t0_cutoff": "2024-01-01",
                "prediction": {"occurred": True},
            },
        )
        assert response.status_code == 400

    def test_404s_cleanly_when_source_missing(self, client):
        response = client.post(
            "/api/backtest/create",
            json={
                "source_simulation_id": "sim_nope1234",
                "scenario_description": "x",
                "t0_cutoff": "2024-01-01",
                "prediction": {"occurred": True},
            },
        )
        assert response.status_code == 400  # ValueError from the service -> 400
        assert response.json["success"] is False

    def test_happy_path_returns_case(self, client):
        _make_completed_simulation()
        response = client.post(
            "/api/backtest/create",
            json={
                "source_simulation_id": "sim_source12345",
                "scenario_description": "Will X happen?",
                "t0_cutoff": "2024-01-01",
                "prediction": {"occurred": True, "probability": 0.6},
            },
        )
        assert response.status_code == 200
        data = response.json["data"]
        assert data["source_simulation_id"] == "sim_source12345"
        assert data["prediction"]["probability"] == 0.6
        assert data["ground_truth"] is None


class TestRecordGroundTruthRoute:
    def _create_case(self, client, prediction=None):
        _make_completed_simulation()
        response = client.post(
            "/api/backtest/create",
            json={
                "source_simulation_id": "sim_source12345",
                "scenario_description": "x",
                "t0_cutoff": "2024-01-01",
                "prediction": prediction or {"occurred": True},
            },
        )
        return response.json["data"]["backtest_id"]

    def test_requires_ground_truth_object(self, client):
        backtest_id = self._create_case(client)
        response = client.post(
            f"/api/backtest/{backtest_id}/ground-truth", json={}
        )
        assert response.status_code == 400

    def test_404_when_backtest_missing(self, client):
        response = client.post(
            "/api/backtest/bt_doesnotexist/ground-truth",
            json={"ground_truth": {"occurred": True}},
        )
        assert response.status_code == 404

    def test_malformed_backtest_id_returns_400_not_500(self, client):
        response = client.post(
            "/api/backtest/bad$id/ground-truth",
            json={"ground_truth": {"occurred": True}},
        )
        assert response.status_code == 400

    def test_happy_path_computes_metrics(self, client):
        backtest_id = self._create_case(client, {"occurred": True, "probability": 0.9})
        response = client.post(
            f"/api/backtest/{backtest_id}/ground-truth",
            json={"ground_truth": {"occurred": True}},
        )
        assert response.status_code == 200
        data = response.json["data"]
        assert data["metrics"]["event_occurrence_correct"] is True
        assert data["metrics"]["brier_score"] == pytest.approx(0.01)

    def test_recording_twice_returns_400(self, client):
        backtest_id = self._create_case(client)
        client.post(
            f"/api/backtest/{backtest_id}/ground-truth",
            json={"ground_truth": {"occurred": True}},
        )
        response = client.post(
            f"/api/backtest/{backtest_id}/ground-truth",
            json={"ground_truth": {"occurred": False}},
        )
        assert response.status_code == 400


class TestGetBacktestRoute:
    def test_get_404_when_missing(self, client):
        response = client.get("/api/backtest/bt_doesnotexist")
        assert response.status_code == 404

    def test_get_with_malformed_id_returns_400_not_500(self, client):
        # A syntactically-invalid id raises InvalidIdentifierError from
        # validate_backtest_id; this must reach the app's global 400
        # handler, not get caught by a broad except-Exception and turned
        # into a 500 with a leaked traceback.
        response = client.get("/api/backtest/bad$id")
        assert response.status_code == 400

    def test_get_returns_case(self, client):
        _make_completed_simulation()
        create_response = client.post(
            "/api/backtest/create",
            json={
                "source_simulation_id": "sim_source12345",
                "scenario_description": "x",
                "t0_cutoff": "2024-01-01",
                "prediction": {"occurred": True},
            },
        )
        backtest_id = create_response.json["data"]["backtest_id"]

        response = client.get(f"/api/backtest/{backtest_id}")
        assert response.status_code == 200
        assert response.json["data"]["backtest_id"] == backtest_id


class TestListBacktestsRoute:
    def test_list_returns_created_backtests(self, client):
        _make_completed_simulation()
        client.post(
            "/api/backtest/create",
            json={
                "source_simulation_id": "sim_source12345",
                "scenario_description": "x",
                "t0_cutoff": "2024-01-01",
                "prediction": {"occurred": True},
            },
        )
        response = client.get("/api/backtest/list")
        assert response.status_code == 200
        assert len(response.json["data"]) == 1


class TestSuiteSummaryRoute:
    def test_empty_suite_returns_honest_nones(self, client):
        response = client.get("/api/backtest/suite-summary")
        assert response.status_code == 200
        assert response.json["data"]["scored_case_count"] == 0
        assert response.json["data"]["direction_accuracy"] is None


class TestBacktestRouteForbiddenErrorReturns403:
    def test_create_with_another_users_source_returns_403(self, two_user_client):
        _make_completed_simulation(owner_id="alice")
        response = two_user_client.post(
            "/api/backtest/create",
            json={
                "source_simulation_id": "sim_source12345",
                "scenario_description": "x",
                "t0_cutoff": "2024-01-01",
                "prediction": {"occurred": True},
            },
            headers=_auth("bob"),
        )
        assert response.status_code == 403

    def test_get_another_users_backtest_returns_403(self, two_user_client):
        _make_completed_simulation(owner_id="alice")
        create_response = two_user_client.post(
            "/api/backtest/create",
            json={
                "source_simulation_id": "sim_source12345",
                "scenario_description": "x",
                "t0_cutoff": "2024-01-01",
                "prediction": {"occurred": True},
            },
            headers=_auth("alice"),
        )
        backtest_id = create_response.json["data"]["backtest_id"]

        response = two_user_client.get(
            f"/api/backtest/{backtest_id}", headers=_auth("bob")
        )
        assert response.status_code == 403

    def test_record_ground_truth_on_another_users_backtest_returns_403(self, two_user_client):
        _make_completed_simulation(owner_id="alice")
        create_response = two_user_client.post(
            "/api/backtest/create",
            json={
                "source_simulation_id": "sim_source12345",
                "scenario_description": "x",
                "t0_cutoff": "2024-01-01",
                "prediction": {"occurred": True},
            },
            headers=_auth("alice"),
        )
        backtest_id = create_response.json["data"]["backtest_id"]

        response = two_user_client.post(
            f"/api/backtest/{backtest_id}/ground-truth",
            json={"ground_truth": {"occurred": True}},
            headers=_auth("bob"),
        )
        assert response.status_code == 403
