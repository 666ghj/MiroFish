# backend/tests/conftest.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.app.db import Base
import backend.app.db as db_module


@pytest.fixture(autouse=True)
def reset_graph_factory_singleton():
    """Reset the graph backend singleton before each test."""
    yield
    try:
        import backend.app.graph.factory as fmod
        fmod._backend_instance = None
    except ImportError:
        pass


@pytest.fixture(autouse=True)
def reset_task_manager_singleton():
    """Reset TaskManager singleton between tests."""
    from backend.app.models import task as task_module
    task_module.TaskManager._instance = None
    yield
    task_module.TaskManager._instance = None


@pytest.fixture
def in_memory_db():
    """BD SQLite en memòria per a tests que necessiten BD."""
    db_module._engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    db_module._SessionLocal = sessionmaker(bind=db_module._engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(db_module._engine)
    yield db_module._engine
    Base.metadata.drop_all(db_module._engine)
    db_module._engine = None
    db_module._SessionLocal = None
