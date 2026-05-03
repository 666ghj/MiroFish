# backend/tests/test_project_task_recovery.py
"""
Tests per a la garantia que active_task_id es persisteix i es recupera.
Equivalent als tests originals sobre Project.to_dict/from_dict,
ara adaptats a ProjectManager + BD SQLAlchemy.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.app.db import Base
import backend.app.db as db_module
import backend.app.models.db_models  # registra tots els models ORM


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


def test_project_serializes_active_task_id():
    """active_task_id es pot desar i recuperar del ProjectManager."""
    from backend.app.models.project import ProjectManager
    proj = ProjectManager.create_project("Test")
    ProjectManager.save_project({
        "id": proj["id"],
        "active_task_id": "task-abc-123",
    })
    fetched = ProjectManager.get_project(proj["id"])
    assert fetched["active_task_id"] == "task-abc-123"


def test_project_deserializes_active_task_id():
    """active_task_id es restaura correctament des de la BD."""
    from backend.app.models.project import ProjectManager
    proj = ProjectManager.create_project("Test")
    ProjectManager.save_project({
        "id": proj["id"],
        "active_task_id": "task-abc-456",
    })
    # Simulem que es torna a llegir (com si el servidor hagués reiniciat)
    fetched = ProjectManager.get_project(proj["id"])
    assert fetched["active_task_id"] == "task-abc-456"


def test_project_active_task_id_defaults_none():
    """active_task_id és None per a projectes creats sense task (compatibilitat enrere)."""
    from backend.app.models.project import ProjectManager
    proj = ProjectManager.create_project("Test")
    assert proj["active_task_id"] is None
