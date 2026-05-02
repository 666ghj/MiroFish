# backend/tests/test_db_models.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.app.db import Base, init_db, get_session
from backend.app.models.db_models import (
    ProjectModel, TaskModel, OntologyModel, GraphModel,
    SimulationModel, ReportModel, UserModel
)


@pytest.fixture
def db_session():
    """Sessió SQLite en memòria per a tests."""
    from sqlalchemy import event
    from backend.app import db as db_module
    db_module._engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})

    @event.listens_for(db_module._engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    db_module._SessionLocal = sessionmaker(bind=db_module._engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(db_module._engine)
    session = db_module._SessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(db_module._engine)
    db_module._engine = None
    db_module._SessionLocal = None


def test_create_project(db_session):
    proj = ProjectModel(id="proj-1", name="Test Project")
    db_session.add(proj)
    db_session.commit()
    result = db_session.get(ProjectModel, "proj-1")
    assert result.name == "Test Project"
    assert result.status == "created"
    assert result.chunk_size == 500


def test_create_task(db_session):
    task = TaskModel(id="task-1", task_type="graph_build", entity_type="project", entity_id="proj-1")
    db_session.add(task)
    db_session.commit()
    result = db_session.get(TaskModel, "task-1")
    assert result.status == "pending"
    assert result.progress == 0


def test_project_cascade_delete(db_session):
    proj = ProjectModel(id="proj-del", name="Del Project")
    db_session.add(proj)
    db_session.flush()
    ont = OntologyModel(id="ont-1", project_id="proj-del", version=1)
    db_session.add(ont)
    db_session.commit()
    db_session.delete(proj)
    db_session.commit()
    assert db_session.get(OntologyModel, "ont-1") is None


def test_task_set_null_on_delete(db_session):
    """SQLite applies FK ON DELETE SET NULL with PRAGMA foreign_keys=ON.
    Test verifies that when a TaskModel is deleted, the ProjectModel's active_task_id
    is set to NULL due to the ON DELETE SET NULL constraint."""
    task = TaskModel(id="task-del", task_type="graph_build")
    db_session.add(task)
    db_session.flush()  # Ensure task is persisted before project references it
    proj = ProjectModel(id="proj-2", name="P2", active_task_id="task-del")
    db_session.add(proj)
    db_session.commit()
    db_session.delete(task)
    db_session.commit()
    # Verify task is deleted
    assert db_session.get(TaskModel, "task-del") is None
    # Verify project still exists
    refreshed = db_session.get(ProjectModel, "proj-2")
    assert refreshed is not None
    # With PRAGMA foreign_keys=ON, active_task_id should be NULL
    assert refreshed.active_task_id is None


def test_graph_linked_to_ontology(db_session):
    proj = ProjectModel(id="proj-g", name="Graph Project")
    ont = OntologyModel(id="ont-g", project_id="proj-g", version=1)
    graph = GraphModel(id="graph-1", project_id="proj-g", ontology_id="ont-g", backend="zep")
    db_session.add_all([proj, ont, graph])
    db_session.commit()
    result = db_session.get(GraphModel, "graph-1")
    assert result.ontology_id == "ont-g"
    assert result.backend == "zep"
