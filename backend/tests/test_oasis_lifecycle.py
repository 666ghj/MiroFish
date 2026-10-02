"""#763: OASIS lifecycle —— awaiting-finish / interview unlock / close-env guards.

全部使用 fake/monkeypatch：不跑真实模拟、不调用 LLM、不碰网络。
"""
from types import SimpleNamespace

import pytest

from app import create_app
from app.api import simulation as simulation_api
from app.services.report_agent import ReportManager, ReportStatus
from app.services.simulation_manager import SimulationManager, SimulationStatus
from app.services.simulation_runner import RunnerStatus, SimulationRunner
from app.utils.locale import t


@pytest.fixture()
def client():
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def _patch_env(monkeypatch, alive: bool):
    monkeypatch.setattr(
        SimulationRunner, "check_env_alive",
        classmethod(lambda _cls, _sid: alive),
    )
    monkeypatch.setattr(
        SimulationRunner, "get_env_status_detail",
        classmethod(lambda _cls, _sid: {"twitter_available": alive, "reddit_available": alive}),
    )
    # close 守卫会查报告状态；测试中一律视为无报告，避免触碰真实存储
    monkeypatch.setattr(
        ReportManager, "get_report_by_simulation",
        classmethod(lambda _cls, _sid: None),
    )


def _patch_state(monkeypatch, status, saved=None):
    st = SimpleNamespace(status=status)
    monkeypatch.setattr(
        SimulationManager, "get_simulation",
        classmethod(lambda _cls, _sid: st),
    )
    monkeypatch.setattr(
        SimulationManager, "_save_simulation_state",
        lambda self, s: (saved.append(s.status) if saved is not None else None),
    )
    return st


# 1) 跑完但环境仍存活 → awaiting_finish（不再直接 COMPLETED）
def test_finished_run_with_live_env_becomes_awaiting_finish(monkeypatch):
    _patch_env(monkeypatch, True)
    saved = []
    _patch_state(monkeypatch, SimulationStatus.RUNNING, saved)

    SimulationRunner._sync_simulation_status("sim-763", RunnerStatus.COMPLETED)

    assert saved[-1] == SimulationStatus.AWAITING_FINISH


# 1b) 环境已死 → 维持终态 COMPLETED（回归：不得把死环境也标 awaiting_finish）
def test_finished_run_with_dead_env_stays_completed(monkeypatch):
    _patch_env(monkeypatch, False)
    saved = []
    _patch_state(monkeypatch, SimulationStatus.RUNNING, saved)

    SimulationRunner._sync_simulation_status("sim-763", RunnerStatus.COMPLETED)

    assert saved[-1] == SimulationStatus.COMPLETED


# 2) /env-status 暴露 lifecycle / awaiting_finish
def test_env_status_exposes_awaiting_finish(monkeypatch, client):
    _patch_env(monkeypatch, True)
    _patch_state(monkeypatch, SimulationStatus.AWAITING_FINISH)

    resp = client.post("/api/simulation/env-status", json={"simulation_id": "sim-763"})

    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["env_alive"] is True
    assert data["lifecycle"] == SimulationStatus.AWAITING_FINISH.value
    assert data["awaiting_finish"] is True
    assert data["active_tasks"] == 0


# 3) 环境非活 → 三个 interview 接口都早失败（400 + 本地化文案）
@pytest.mark.parametrize(
    "path,payload",
    [
        ("/api/simulation/interview", {"simulation_id": "sim-763", "agent_id": 1, "prompt": "hi"}),
        ("/api/simulation/interview/batch", {"simulation_id": "sim-763", "interviews": [{"agent_id": 1, "prompt": "hi"}]}),
        ("/api/simulation/interview/all", {"simulation_id": "sim-763", "prompt": "hi"}),
    ],
)
def test_interview_fails_early_when_env_dead(monkeypatch, client, path, payload):
    _patch_env(monkeypatch, False)

    resp = client.post(path, json=payload)

    assert resp.status_code == 400
    assert resp.get_json()["error"] == t("api.envNotRunning")


# 4) 报告检查：环境活着即可 interview；报告完成 + 环境死 → 不解锁
def test_report_check_unlocks_interview_while_env_alive(monkeypatch, client):
    _patch_env(monkeypatch, True)
    _patch_state(monkeypatch, SimulationStatus.AWAITING_FINISH)

    resp = client.get("/api/report/check/sim-763")

    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["interview_unlocked"] is True
    assert data["env_alive"] is True
    assert data["lifecycle"] == SimulationStatus.AWAITING_FINISH.value


def test_report_check_locked_when_report_done_but_env_dead(monkeypatch, client):
    _patch_env(monkeypatch, False)
    monkeypatch.setattr(
        ReportManager, "get_report_by_simulation",
        classmethod(lambda _cls, _sid: SimpleNamespace(status=ReportStatus.COMPLETED, report_id="r-1")),
    )
    _patch_state(monkeypatch, SimulationStatus.COMPLETED)

    resp = client.get("/api/report/check/sim-763")

    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["interview_unlocked"] is False
    assert data["env_alive"] is False


# 5) close-env 守卫：需 confirm；忙时 409；失败不置 COMPLETED；成功才置
def test_close_env_guards(monkeypatch, client):
    _patch_env(monkeypatch, True)
    saved = []
    _patch_state(monkeypatch, SimulationStatus.AWAITING_FINISH, saved)

    # 无 confirm → 400
    r1 = client.post("/api/simulation/close-env", json={"simulation_id": "sim-763"})
    assert r1.status_code == 400
    assert r1.get_json()["error"] == t("api.closeEnvRequiresConfirm")

    # 本仿真 interview 在飞 → 409（计数按 simulation_id 键控）
    with simulation_api._INTERVIEW_INFLIGHT_LOCK:
        simulation_api._INTERVIEW_INFLIGHT["sim-763"] = 1
    try:
        r2 = client.post("/api/simulation/close-env", json={"simulation_id": "sim-763", "confirm": True})
        assert r2.status_code == 409
        assert r2.get_json()["error"] == t("api.envBusy")
    finally:
        with simulation_api._INTERVIEW_INFLIGHT_LOCK:
            simulation_api._INTERVIEW_INFLIGHT.pop("sim-763", None)

    # 服务层失败（超时）→ 502，且状态不被写成 COMPLETED（回归旧 :2858 bug）
    monkeypatch.setattr(
        SimulationRunner, "close_simulation_env",
        classmethod(lambda _cls, **_kw: {"success": False, "timeout": True, "message": "timeout"}),
    )
    r3 = client.post("/api/simulation/close-env", json={"simulation_id": "sim-763", "confirm": True})
    assert r3.status_code == 502
    assert saved == []

    # 成功 → 200 且落 COMPLETED
    monkeypatch.setattr(
        SimulationRunner, "close_simulation_env",
        classmethod(lambda _cls, **_kw: {"success": True, "message": "ok"}),
    )
    r4 = client.post("/api/simulation/close-env", json={"simulation_id": "sim-763", "confirm": True})
    assert r4.status_code == 200
    assert saved[-1] == SimulationStatus.COMPLETED


# 5b) 计数按仿真隔离——他仿真在飞时，本仿真 close-env 不被误拦（#763 并发修正回归）
def test_close_env_not_blocked_by_other_simulation_inflight(monkeypatch, client):
    _patch_env(monkeypatch, True)
    saved = []
    _patch_state(monkeypatch, SimulationStatus.AWAITING_FINISH, saved)
    monkeypatch.setattr(
        SimulationRunner, "close_simulation_env",
        classmethod(lambda _cls, **_kw: {"success": True, "message": "ok"}),
    )
    with simulation_api._INTERVIEW_INFLIGHT_LOCK:
        simulation_api._INTERVIEW_INFLIGHT["sim-other"] = 1
    try:
        resp = client.post("/api/simulation/close-env", json={"simulation_id": "sim-763", "confirm": True})
        assert resp.status_code == 200
        assert saved[-1] == SimulationStatus.COMPLETED
    finally:
        with simulation_api._INTERVIEW_INFLIGHT_LOCK:
            simulation_api._INTERVIEW_INFLIGHT.pop("sim-other", None)


# 5c) _active_task_count 单测：各仿真各回各值（互不串扰）
def test_active_task_count_is_per_simulation(monkeypatch):
    monkeypatch.setattr(
        ReportManager, "get_report_by_simulation",
        classmethod(lambda _cls, _sid: None),
    )
    with simulation_api._INTERVIEW_INFLIGHT_LOCK:
        simulation_api._INTERVIEW_INFLIGHT["sim-A"] = 2
    try:
        assert simulation_api._active_task_count("sim-A") == 2
        assert simulation_api._active_task_count("sim-B") == 0
    finally:
        with simulation_api._INTERVIEW_INFLIGHT_LOCK:
            simulation_api._INTERVIEW_INFLIGHT.pop("sim-A", None)
