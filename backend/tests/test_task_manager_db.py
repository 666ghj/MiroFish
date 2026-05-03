# backend/tests/test_task_manager_db.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.app.db import Base
import backend.app.db as db_module
from backend.app.models.db_models import TaskModel


@pytest.fixture(autouse=True)
def isolated_db():
    """BD SQLite en memòria per a cada test."""
    db_module._engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    db_module._SessionLocal = sessionmaker(bind=db_module._engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(db_module._engine)
    yield
    Base.metadata.drop_all(db_module._engine)
    db_module._engine = None
    db_module._SessionLocal = None


def test_create_and_get_task():
    from backend.app.models.task import TaskManager
    tm = TaskManager()
    task_id = tm.create_task("graph_build", {"project_id": "proj-1"})
    task = tm.get_task(task_id)
    assert task is not None
    assert task["task_type"] == "graph_build"
    assert task["status"] == "pending"
    assert task["progress"] == 0


def test_update_task_progress():
    from backend.app.models.task import TaskManager
    tm = TaskManager()
    task_id = tm.create_task("ontology_generate")
    tm.update_task(task_id, progress=50, message="Halfway")
    task = tm.get_task(task_id)
    assert task["progress"] == 50
    assert task["message"] == "Halfway"


def test_complete_task():
    from backend.app.models.task import TaskManager
    tm = TaskManager()
    task_id = tm.create_task("graph_build")
    tm.complete_task(task_id, {"graph_id": "g-1"})
    task = tm.get_task(task_id)
    assert task["status"] == "completed"
    assert task["progress"] == 100
    assert task["result"]["graph_id"] == "g-1"


def test_fail_task():
    from backend.app.models.task import TaskManager
    tm = TaskManager()
    task_id = tm.create_task("simulation_prepare")
    tm.fail_task(task_id, "LLM timeout")
    task = tm.get_task(task_id)
    assert task["status"] == "failed"
    assert task["error"] == "LLM timeout"


def test_task_survives_new_manager_instance():
    """La tasca ha d'estar a la BD, no a la memòria."""
    from backend.app.models.task import TaskManager
    tm1 = TaskManager()
    task_id = tm1.create_task("graph_build")
    # Crear una nova instància (simula reinici)
    TaskManager._instance = None
    tm2 = TaskManager()
    task = tm2.get_task(task_id)
    assert task is not None
    assert task["task_id"] == task_id


def test_list_tasks():
    from backend.app.models.task import TaskManager
    tm = TaskManager()
    tm.create_task("graph_build")
    tm.create_task("graph_build")
    tm.create_task("ontology_generate")
    all_tasks = tm.list_tasks()
    assert len(all_tasks) == 3
    graph_tasks = tm.list_tasks(task_type="graph_build")
    assert len(graph_tasks) == 2
