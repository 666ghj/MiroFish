"""
TaskManager 崩溃恢复测试

覆盖任务持久化到磁盘、心跳/进度字段跟踪，以及"进程重启"（新单例、
内存字典清空、只有磁盘文件存活）后未完成任务被正确标记为失败的行为。
这是 graph build / simulation prepare / report generate 三条长任务路径
共用的同一套 TaskManager，因此这里的测试直接覆盖了它们全部的崩溃恢复
行为，而无需分别改动或测试每一条路径。
"""

import json

import pytest

from app.models.task import Task, TaskManager, TaskStatus


@pytest.fixture(autouse=True)
def _isolated_task_manager(tmp_path, monkeypatch):
    """每个测试都拿到一个指向独立临时目录、全新单例的 TaskManager。"""
    monkeypatch.setattr(TaskManager, "TASKS_DIR", str(tmp_path))
    monkeypatch.setattr(TaskManager, "_instance", None)
    yield
    # 测试结束后重置单例，避免污染后续测试（即便某个测试忘了走 fixture）。
    TaskManager._instance = None


def _restart_process():
    """模拟进程重启：丢弃单例与内存缓存，只留下磁盘上的文件。"""
    TaskManager._instance = None
    return TaskManager()


class TestPersistence:
    def test_create_task_persists_to_disk(self, tmp_path):
        manager = TaskManager()
        task_id = manager.create_task("graph_build", metadata={"project_id": "proj_1"})

        path = tmp_path / f"{task_id}.json"
        assert path.exists()
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["status"] == "pending"
        assert data["metadata"] == {"project_id": "proj_1"}

    def test_update_task_persists_changes(self, tmp_path):
        manager = TaskManager()
        task_id = manager.create_task("report_generate")
        manager.update_task(task_id, status=TaskStatus.PROCESSING, progress=50)

        with open(tmp_path / f"{task_id}.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["status"] == "processing"
        assert data["progress"] == 50
        assert data["started_at"] is not None

    def test_heartbeat_updates_on_every_update(self):
        manager = TaskManager()
        task_id = manager.create_task("simulation_prepare")
        first = manager.get_task(task_id).heartbeat_at

        manager.update_task(task_id, progress=10)
        second = manager.get_task(task_id).heartbeat_at

        assert second >= first

    def test_complete_task_marks_terminal_state(self):
        manager = TaskManager()
        task_id = manager.create_task("graph_build")
        manager.complete_task(task_id, result={"graph_id": "graph_1"})

        task = manager.get_task(task_id)
        assert task.status == TaskStatus.COMPLETED
        assert task.progress == 100
        assert task.result == {"graph_id": "graph_1"}

    def test_fail_task_marks_terminal_state_with_error(self):
        manager = TaskManager()
        task_id = manager.create_task("graph_build")
        manager.fail_task(task_id, "boom")

        task = manager.get_task(task_id)
        assert task.status == TaskStatus.FAILED
        assert task.error == "boom"

    def test_cleanup_old_tasks_removes_persisted_file(self, tmp_path):
        from datetime import datetime, timedelta

        manager = TaskManager()
        task_id = manager.create_task("graph_build")
        manager.complete_task(task_id, result={})
        manager._tasks[task_id].created_at = datetime.now() - timedelta(hours=48)
        manager._persist(manager._tasks[task_id])

        manager.cleanup_old_tasks(max_age_hours=24)

        assert manager.get_task(task_id) is None
        assert not (tmp_path / f"{task_id}.json").exists()


class TestCrashRecovery:
    def test_pending_task_recovered_as_failed_after_restart(self):
        manager = TaskManager()
        task_id = manager.create_task("graph_build")
        assert manager.get_task(task_id).status == TaskStatus.PENDING

        restarted = _restart_process()

        recovered = restarted.get_task(task_id)
        assert recovered is not None
        assert recovered.status == TaskStatus.FAILED
        assert "interrupted" in recovered.error.lower()

    def test_processing_task_recovered_as_failed_after_restart(self):
        manager = TaskManager()
        task_id = manager.create_task("report_generate")
        manager.update_task(task_id, status=TaskStatus.PROCESSING, progress=60, message="working")

        restarted = _restart_process()

        recovered = restarted.get_task(task_id)
        assert recovered.status == TaskStatus.FAILED
        assert recovered.progress == 60  # progress made before the crash is preserved

    def test_completed_task_survives_restart_unchanged(self):
        manager = TaskManager()
        task_id = manager.create_task("graph_build")
        manager.complete_task(task_id, result={"graph_id": "graph_1"})

        restarted = _restart_process()

        recovered = restarted.get_task(task_id)
        assert recovered.status == TaskStatus.COMPLETED
        assert recovered.result == {"graph_id": "graph_1"}

    def test_failed_task_survives_restart_unchanged(self):
        manager = TaskManager()
        task_id = manager.create_task("graph_build")
        manager.fail_task(task_id, "original failure")

        restarted = _restart_process()

        recovered = restarted.get_task(task_id)
        assert recovered.status == TaskStatus.FAILED
        assert recovered.error == "original failure"

    def test_multiple_interrupted_tasks_all_recovered(self):
        manager = TaskManager()
        pending_id = manager.create_task("graph_build")
        processing_id = manager.create_task("simulation_prepare")
        manager.update_task(processing_id, status=TaskStatus.PROCESSING)
        done_id = manager.create_task("report_generate")
        manager.complete_task(done_id, result={})

        restarted = _restart_process()

        assert restarted.get_task(pending_id).status == TaskStatus.FAILED
        assert restarted.get_task(processing_id).status == TaskStatus.FAILED
        assert restarted.get_task(done_id).status == TaskStatus.COMPLETED

    def test_list_tasks_reflects_recovery(self):
        manager = TaskManager()
        task_id = manager.create_task("graph_build")
        manager.update_task(task_id, status=TaskStatus.PROCESSING)

        restarted = _restart_process()
        listed = restarted.list_tasks()

        assert len(listed) == 1
        assert listed[0]["status"] == "failed"


def test_task_round_trips_through_to_dict_and_from_dict():
    from datetime import datetime

    original = Task(
        task_id="11111111-1111-1111-1111-111111111111",
        task_type="graph_build",
        status=TaskStatus.PROCESSING,
        created_at=datetime.now(),
        updated_at=datetime.now(),
        progress=33,
        metadata={"k": "v"},
    )
    rebuilt = Task.from_dict(original.to_dict())
    assert rebuilt.task_id == original.task_id
    assert rebuilt.status == original.status
    assert rebuilt.progress == original.progress
    assert rebuilt.metadata == original.metadata
