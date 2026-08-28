import importlib.util
import sys
import types
from pathlib import Path


def _load_task_module(monkeypatch, upload_folder):
    backend_dir = Path(__file__).resolve().parents[1]
    app_package = types.ModuleType("app")
    app_package.__path__ = [str(backend_dir / "app")]
    models_package = types.ModuleType("app.models")
    models_package.__path__ = [str(backend_dir / "app" / "models")]
    config_module = types.ModuleType("app.config")
    config_module.Config = type("Config", (), {"UPLOAD_FOLDER": str(upload_folder)})
    monkeypatch.setitem(sys.modules, "app", app_package)
    monkeypatch.setitem(sys.modules, "app.models", models_package)
    monkeypatch.setitem(sys.modules, "app.config", config_module)

    store_name = "app.models.task_store"
    store_spec = importlib.util.spec_from_file_location(
        store_name, backend_dir / "app" / "models" / "task_store.py"
    )
    store_module = importlib.util.module_from_spec(store_spec)
    monkeypatch.setitem(sys.modules, store_name, store_module)
    store_spec.loader.exec_module(store_module)

    module_name = "app.models.task"
    module_spec = importlib.util.spec_from_file_location(
        module_name, backend_dir / "app" / "models" / "task.py"
    )
    module = importlib.util.module_from_spec(module_spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    module_spec.loader.exec_module(module)
    return module


def test_tasks_survive_reload_and_running_task_becomes_interrupted(monkeypatch, tmp_path):
    module = _load_task_module(monkeypatch, tmp_path)
    module.TaskManager.configure_store(str(tmp_path / "tasks.db"))
    manager = module.TaskManager()
    running_id = manager.create_task("构建图谱", {"project_id": "proj-1"})
    manager.update_task(running_id, status=module.TaskStatus.PROCESSING, progress=25)
    completed_id = manager.create_task("生成报告", {"report_id": "report-1"})
    manager.complete_task(completed_id, {"ok": True})

    module.TaskManager.reload_from_store()

    assert manager.get_task(running_id).status == module.TaskStatus.INTERRUPTED
    assert manager.get_task(running_id).metadata == {"project_id": "proj-1"}
    assert manager.get_task(completed_id).status == module.TaskStatus.COMPLETED


def test_list_filters_limits_and_cleanup_persists(monkeypatch, tmp_path):
    module = _load_task_module(monkeypatch, tmp_path)
    path = tmp_path / "tasks.db"
    module.TaskManager.configure_store(str(path))
    manager = module.TaskManager()
    first = manager.create_task("A")
    manager.complete_task(first, {})
    second = manager.create_task("B")
    manager.fail_task(second, "bad")

    assert len(manager.list_tasks(status="failed", limit=1)) == 1
    assert manager.list_tasks(status="failed", limit=1)[0]["task_id"] == second

    manager.cleanup_old_tasks(max_age_hours=-1)
    module.TaskManager.reload_from_store()
    assert manager.list_tasks() == []


def test_task_display_fields_can_be_edited_and_persisted(monkeypatch, tmp_path):
    module = _load_task_module(monkeypatch, tmp_path)
    module.TaskManager.configure_store(str(tmp_path / "tasks.db"))
    manager = module.TaskManager()
    task_id = manager.create_task("构建图谱", {"project_id": "proj-1"})
    manager.complete_task(task_id, {})

    assert manager.update_display(task_id, "泡泡玛特建图", "优先观察海外业务") is True

    module.TaskManager.reload_from_store()
    task = manager.get_task(task_id)
    assert task.task_type == "泡泡玛特建图"
    assert task.metadata["note"] == "优先观察海外业务"
    assert task.status == module.TaskStatus.COMPLETED


def test_running_task_cannot_be_deleted_but_terminal_task_can(monkeypatch, tmp_path):
    module = _load_task_module(monkeypatch, tmp_path)
    module.TaskManager.configure_store(str(tmp_path / "tasks.db"))
    manager = module.TaskManager()
    running_id = manager.create_task("运行中")
    manager.update_task(running_id, status=module.TaskStatus.PROCESSING)
    completed_id = manager.create_task("已完成")
    manager.complete_task(completed_id, {})

    assert manager.delete_task(running_id) is False
    assert manager.delete_task(completed_id) is True

    module.TaskManager.reload_from_store()
    assert manager.get_task(running_id) is not None
    assert manager.get_task(completed_id) is None


def test_project_tasks_can_be_deleted_together(monkeypatch, tmp_path):
    module = _load_task_module(monkeypatch, tmp_path)
    module.TaskManager.configure_store(str(tmp_path / "tasks.db"))
    manager = module.TaskManager()
    first = manager.create_task("项目任务", {"project_id": "proj-1"})
    manager.complete_task(first, {})
    second = manager.create_task("其他任务", {"project_id": "proj-2"})
    manager.complete_task(second, {})

    assert manager.delete_project_tasks("proj-1") == 1
    assert manager.get_task(first) is None
    assert manager.get_task(second) is not None
