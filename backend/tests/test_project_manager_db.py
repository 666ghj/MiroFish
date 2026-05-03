# backend/tests/test_project_manager_db.py
import io
import pytest
import tempfile
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.app.db import Base
import backend.app.db as db_module
from backend.app.storage.local import LocalFSStorage
import backend.app.models.db_models  # ensure all ORM models are registered with Base.metadata


@pytest.fixture(autouse=True)
def isolated_db(tmp_path):
    db_module._engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    db_module._SessionLocal = sessionmaker(bind=db_module._engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(db_module._engine)
    yield
    Base.metadata.drop_all(db_module._engine)
    db_module._engine = None
    db_module._SessionLocal = None


@pytest.fixture
def storage(tmp_path):
    return LocalFSStorage(str(tmp_path))


def test_create_project(storage):
    from backend.app.models.project import ProjectManager
    proj = ProjectManager.create_project("Test Project", storage=storage)
    assert proj["name"] == "Test Project"
    assert proj["status"] == "created"
    assert "id" in proj


def test_get_project(storage):
    from backend.app.models.project import ProjectManager
    created = ProjectManager.create_project("My Project", storage=storage)
    fetched = ProjectManager.get_project(created["id"])
    assert fetched is not None
    assert fetched["name"] == "My Project"


def test_project_not_found(storage):
    from backend.app.models.project import ProjectManager
    result = ProjectManager.get_project("nonexistent-id")
    assert result is None


def test_save_and_get_extracted_text(storage):
    from backend.app.models.project import ProjectManager
    proj = ProjectManager.create_project("Text Project", storage=storage)
    ProjectManager.save_extracted_text(proj["id"], "hello extracted", storage=storage)
    text = ProjectManager.get_extracted_text(proj["id"], storage=storage)
    assert text == "hello extracted"


def test_project_survives_manager_reset(storage):
    """Les dades han d'estar a la BD, no a la memòria."""
    from backend.app.models.project import ProjectManager
    created = ProjectManager.create_project("Persist Me", storage=storage)
    fetched = ProjectManager.get_project(created["id"])
    assert fetched is not None


def test_list_projects(storage):
    from backend.app.models.project import ProjectManager
    ProjectManager.create_project("P1", storage=storage)
    ProjectManager.create_project("P2", storage=storage)
    projects = ProjectManager.list_projects()
    assert len(projects) == 2


def test_delete_project(storage):
    from backend.app.models.project import ProjectManager
    proj = ProjectManager.create_project("Del Me", storage=storage)
    result = ProjectManager.delete_project(proj["id"], storage=storage)
    assert result is True
    assert ProjectManager.get_project(proj["id"]) is None
