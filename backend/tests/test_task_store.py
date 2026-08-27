import importlib.util
import json
import sqlite3
from pathlib import Path


module_path = Path(__file__).resolve().parents[1] / "app" / "models" / "task_store.py"
module_spec = importlib.util.spec_from_file_location("task_store_under_test", module_path)
module = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(module)
TaskStore = module.TaskStore


def _record(task_id="task-1", status="completed"):
    return {
        "task_id": task_id, "task_type": "构建图谱", "status": status,
        "created_at": "2026-08-27T10:00:00", "updated_at": "2026-08-27T10:01:00",
        "progress": 100, "message": "任务完成", "result": {"graph_id": "graph-1"},
        "error": None, "metadata": {"project_id": "proj-1"},
        "progress_detail": {"batch": 2},
    }


def test_database_is_created_with_wal_and_indexes(tmp_path):
    path = tmp_path / "tasks" / "tasks.db"
    TaskStore(path).save([_record()])
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        indexes = {row[1] for row in connection.execute("PRAGMA index_list(task_history)")}
    assert {"idx_task_history_status", "idx_task_history_created_at", "idx_task_history_type"} <= indexes


def test_save_upserts_and_load_decodes_json_fields(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    store.save([_record(status="processing")])
    store.save([_record(status="completed")])
    records = store.load()
    assert len(records) == 1
    assert records[0]["status"] == "completed"
    assert records[0]["metadata"] == {"project_id": "proj-1"}
    assert records[0]["result"] == {"graph_id": "graph-1"}


def test_save_replaces_removed_records(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    store.save([_record("task-1"), _record("task-2")])
    store.save([_record("task-2")])
    assert [record["task_id"] for record in store.load()] == ["task-2"]


def test_legacy_json_is_imported_once_and_renamed(tmp_path):
    database_path = tmp_path / "tasks.db"
    legacy_path = tmp_path / "tasks.json"
    legacy_path.write_text(json.dumps([_record()]), encoding="utf-8")
    store = TaskStore(database_path)
    assert store.load()[0]["task_id"] == "task-1"
    assert not legacy_path.exists()
    assert (tmp_path / "tasks.json.migrated").exists()


def test_corrupt_legacy_json_is_preserved(tmp_path):
    database_path = tmp_path / "tasks.db"
    legacy_path = tmp_path / "tasks.json"
    legacy_path.write_text("{broken", encoding="utf-8")
    assert TaskStore(database_path).load() == []
    assert legacy_path.read_text(encoding="utf-8") == "{broken"


def test_existing_database_is_not_overwritten_by_legacy_json(tmp_path):
    database_path = tmp_path / "tasks.db"
    store = TaskStore(database_path)
    store.save([_record("database-task")])
    legacy_path = tmp_path / "tasks.json"
    legacy_path.write_text(json.dumps([_record("legacy-task")]), encoding="utf-8")

    reloaded = TaskStore(database_path)

    assert [record["task_id"] for record in reloaded.load()] == ["database-task"]
    assert legacy_path.exists()
