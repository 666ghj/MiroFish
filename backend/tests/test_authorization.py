"""
资源所有权授权测试

覆盖 app.utils.authorization 的核心比较逻辑，以及依赖它的 API 路由：
项目 / 模拟 / 报告的读取、列表过滤、删除等操作在跨用户访问时被拒绝，
同一用户或未启用认证时正常放行，且历史（owner_id 缺失）资源不会被
升级后的认证永久锁死。
"""

import pytest

from app import create_app
from app.config import Config
from app.utils.authorization import (
    ForbiddenError,
    authorize,
    authorize_any,
    check_owner,
    is_owned_by_current_user,
)


# ─────────────────────────── 单元测试：核心比较逻辑 ───────────────────────────

class _Resource:
    def __init__(self, owner_id=None):
        self.owner_id = owner_id


@pytest.fixture
def app():
    return create_app()


def test_check_owner_noop_when_auth_disabled(app, monkeypatch):
    monkeypatch.setattr(Config, "API_KEYS", {})
    with app.test_request_context("/"):
        # No g.current_user_id set at all (auth middleware never ran) — still fine.
        check_owner("someone-else")


def test_check_owner_allows_matching_owner(app):
    with app.test_request_context("/"):
        from flask import g
        g.current_user_id = "alice"
        check_owner("alice")


def test_check_owner_allows_legacy_resource_with_no_owner(app):
    with app.test_request_context("/"):
        from flask import g
        g.current_user_id = "alice"
        check_owner(None)


def test_check_owner_rejects_mismatched_owner(app):
    with app.test_request_context("/"):
        from flask import g
        g.current_user_id = "alice"
        with pytest.raises(ForbiddenError):
            check_owner("bob")


def test_authorize_noop_for_none_resource(app):
    with app.test_request_context("/"):
        from flask import g
        g.current_user_id = "alice"
        authorize(None)  # must not raise


def test_authorize_rejects_other_users_resource(app):
    with app.test_request_context("/"):
        from flask import g
        g.current_user_id = "alice"
        with pytest.raises(ForbiddenError):
            authorize(_Resource(owner_id="bob"))


def test_is_owned_by_current_user(app):
    with app.test_request_context("/"):
        from flask import g
        g.current_user_id = "alice"
        assert is_owned_by_current_user(_Resource(owner_id="alice")) is True
        assert is_owned_by_current_user(_Resource(owner_id="bob")) is False
        assert is_owned_by_current_user(_Resource(owner_id=None)) is True
        assert is_owned_by_current_user(None) is False


def test_authorize_any_requires_at_least_one_owned_resource(app):
    with app.test_request_context("/"):
        from flask import g
        g.current_user_id = "alice"
        authorize_any([_Resource(owner_id="bob"), _Resource(owner_id="alice")])
        with pytest.raises(ForbiddenError):
            authorize_any([_Resource(owner_id="bob"), _Resource(owner_id="carol")])


def test_authorize_any_empty_list_rejected_when_auth_enabled(app):
    with app.test_request_context("/"):
        from flask import g
        g.current_user_id = "alice"
        with pytest.raises(ForbiddenError):
            authorize_any([])


def test_authorize_any_empty_list_allowed_when_auth_disabled(app):
    with app.test_request_context("/"):
        # g.current_user_id left unset -> current_user_id() returns None
        authorize_any([])


# ─────────────────────────── 集成测试：HTTP 路由级隔离 ───────────────────────────

@pytest.fixture
def two_user_client(monkeypatch):
    monkeypatch.setattr(Config, "API_KEYS", {"alice-key": "alice", "bob-key": "bob"})
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def _auth(user_key):
    return {"Authorization": f"Bearer {user_key}-key"}


class TestProjectAuthorization:
    def _make_project(self, tmp_path, monkeypatch, owner_id):
        from app.models.project import ProjectManager

        monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(tmp_path))
        project = ProjectManager.create_project(name="p", owner_id=owner_id)
        return project

    def test_owner_can_read_own_project(self, tmp_path, monkeypatch, two_user_client):
        project = self._make_project(tmp_path, monkeypatch, owner_id="alice")
        resp = two_user_client.get(
            f"/api/graph/project/{project.project_id}", headers=_auth("alice")
        )
        assert resp.status_code == 200

    def test_other_user_cannot_read_project(self, tmp_path, monkeypatch, two_user_client):
        project = self._make_project(tmp_path, monkeypatch, owner_id="alice")
        resp = two_user_client.get(
            f"/api/graph/project/{project.project_id}", headers=_auth("bob")
        )
        assert resp.status_code in (403, 500)

    def test_other_user_cannot_delete_project(self, tmp_path, monkeypatch, two_user_client):
        from app.models.project import ProjectManager

        project = self._make_project(tmp_path, monkeypatch, owner_id="alice")
        resp = two_user_client.delete(
            f"/api/graph/project/{project.project_id}", headers=_auth("bob")
        )
        assert resp.status_code in (403, 500)
        # The project must genuinely still exist on disk.
        assert ProjectManager.get_project(project.project_id) is not None

    def test_owner_can_delete_own_project(self, tmp_path, monkeypatch, two_user_client):
        from app.models.project import ProjectManager

        project = self._make_project(tmp_path, monkeypatch, owner_id="alice")
        resp = two_user_client.delete(
            f"/api/graph/project/{project.project_id}", headers=_auth("alice")
        )
        assert resp.status_code == 200
        assert ProjectManager.get_project(project.project_id) is None

    def test_legacy_project_without_owner_is_visible_to_any_authenticated_user(
        self, tmp_path, monkeypatch, two_user_client
    ):
        project = self._make_project(tmp_path, monkeypatch, owner_id=None)
        resp = two_user_client.get(
            f"/api/graph/project/{project.project_id}", headers=_auth("bob")
        )
        assert resp.status_code == 200

    def test_list_projects_only_returns_own_projects(
        self, tmp_path, monkeypatch, two_user_client
    ):
        from app.models.project import ProjectManager

        monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(tmp_path))
        alice_project = ProjectManager.create_project(name="a", owner_id="alice")
        ProjectManager.create_project(name="b", owner_id="bob")

        resp = two_user_client.get("/api/graph/project/list", headers=_auth("alice"))
        assert resp.status_code == 200
        ids = [p["project_id"] for p in resp.json["data"]]
        assert alice_project.project_id in ids
        assert len(ids) == 1


class TestSimulationAuthorization:
    def _make_simulation(self, tmp_path, monkeypatch, owner_id):
        from app.services.simulation_manager import SimulationManager

        monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(tmp_path))
        manager = SimulationManager()
        state = manager.create_simulation(
            project_id="proj_test", graph_id="graph_test", owner_id=owner_id
        )
        return manager, state

    def test_other_user_cannot_read_simulation(self, tmp_path, monkeypatch, two_user_client):
        _, state = self._make_simulation(tmp_path, monkeypatch, owner_id="alice")
        resp = two_user_client.get(
            f"/api/simulation/{state.simulation_id}", headers=_auth("bob")
        )
        assert resp.status_code in (403, 500)

    def test_owner_can_read_own_simulation(self, tmp_path, monkeypatch, two_user_client):
        _, state = self._make_simulation(tmp_path, monkeypatch, owner_id="alice")
        resp = two_user_client.get(
            f"/api/simulation/{state.simulation_id}", headers=_auth("alice")
        )
        assert resp.status_code == 200

    def test_other_user_cannot_stop_simulation(self, tmp_path, monkeypatch, two_user_client):
        _, state = self._make_simulation(tmp_path, monkeypatch, owner_id="alice")
        resp = two_user_client.post(
            "/api/simulation/stop",
            json={"simulation_id": state.simulation_id},
            headers=_auth("bob"),
        )
        assert resp.status_code in (403, 500)

    def test_list_simulations_only_returns_own(self, tmp_path, monkeypatch, two_user_client):
        from app.services.simulation_manager import SimulationManager

        monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(tmp_path))
        manager = SimulationManager()
        alice_state = manager.create_simulation(
            project_id="proj_a", graph_id="graph_a", owner_id="alice"
        )
        manager.create_simulation(project_id="proj_b", graph_id="graph_b", owner_id="bob")

        resp = two_user_client.get("/api/simulation/list", headers=_auth("alice"))
        assert resp.status_code == 200
        ids = [s["simulation_id"] for s in resp.json["data"]]
        assert alice_state.simulation_id in ids
        assert len(ids) == 1


class TestReportAuthorization:
    def _make_report(self, tmp_path, monkeypatch, owner_id):
        from app.services.report_agent import Report, ReportManager, ReportStatus

        monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path))
        report = Report(
            report_id="report_test1234",
            simulation_id="sim_test",
            graph_id="graph_test",
            simulation_requirement="req",
            status=ReportStatus.COMPLETED,
            markdown_content="# hello",
            owner_id=owner_id,
        )
        ReportManager.save_report(report)
        return report

    def test_other_user_cannot_read_report(self, tmp_path, monkeypatch, two_user_client):
        report = self._make_report(tmp_path, monkeypatch, owner_id="alice")
        resp = two_user_client.get(
            f"/api/report/{report.report_id}", headers=_auth("bob")
        )
        assert resp.status_code in (403, 500)

    def test_owner_can_read_own_report(self, tmp_path, monkeypatch, two_user_client):
        report = self._make_report(tmp_path, monkeypatch, owner_id="alice")
        resp = two_user_client.get(
            f"/api/report/{report.report_id}", headers=_auth("alice")
        )
        assert resp.status_code == 200

    def test_other_user_cannot_delete_report(self, tmp_path, monkeypatch, two_user_client):
        from app.services.report_agent import ReportManager

        report = self._make_report(tmp_path, monkeypatch, owner_id="alice")
        resp = two_user_client.delete(
            f"/api/report/{report.report_id}", headers=_auth("bob")
        )
        assert resp.status_code in (403, 500)
        assert ReportManager.get_report(report.report_id) is not None

    def test_list_reports_only_returns_own(self, tmp_path, monkeypatch, two_user_client):
        from app.services.report_agent import Report, ReportManager, ReportStatus

        monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path))
        alice_report = Report(
            report_id="report_aaaaaaaaaaaa",
            simulation_id="sim_a",
            graph_id="graph_a",
            simulation_requirement="req",
            status=ReportStatus.COMPLETED,
            owner_id="alice",
        )
        bob_report = Report(
            report_id="report_bbbbbbbbbbbb",
            simulation_id="sim_b",
            graph_id="graph_b",
            simulation_requirement="req",
            status=ReportStatus.COMPLETED,
            owner_id="bob",
        )
        ReportManager.save_report(alice_report)
        ReportManager.save_report(bob_report)

        resp = two_user_client.get("/api/report/list", headers=_auth("alice"))
        assert resp.status_code == 200
        ids = [r["report_id"] for r in resp.json["data"]]
        assert alice_report.report_id in ids
        assert bob_report.report_id not in ids
