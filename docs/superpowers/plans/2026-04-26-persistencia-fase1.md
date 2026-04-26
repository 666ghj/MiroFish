# Persistència Fase 1: Infraestructura Base

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Substituir la persistència JSON+memòria per SQLAlchemy 2.x (SQLite dev / PostgreSQL prod) i un `StorageService` abstracte (LocalFS dev / Azure Blob prod), de manera que projectes i tasques sobrevisquin reinicis del servidor.

**Architecture:** S'afegeix una capa de BD via SQLAlchemy sota els `Manager` existents. `ProjectManager` i `TaskManager` es refactoritzen per llegir/escriure a la BD en comptes de JSON i memòria. L'`StorageService` substitueix totes les operacions directes de fitxers. L'app factory (`create_app`) injecta la sessió DB i el storage com a extensions Flask.

**Tech Stack:** SQLAlchemy 2.x, Alembic, `flask-sqlalchemy`, `azure-storage-blob`, `bcrypt` (per a fases posteriors, s'afegeix al `pyproject.toml` ara)

---

## Mapa de fitxers

### Nous fitxers a crear

| Fitxer | Responsabilitat |
|--------|-----------------|
| `backend/app/db.py` | Engine SQLAlchemy, `Base`, `get_db()` session factory, `init_db()` |
| `backend/app/models/db_models.py` | Tots els models SQLAlchemy (Project, ProjectFile, Ontology, Graph, Simulation, Report, Task, SystemConfig, User, InvitationToken, PasswordResetToken) |
| `backend/app/storage/__init__.py` | Exporta `StorageService`, `get_storage()` |
| `backend/app/storage/protocol.py` | `StorageService` Protocol (interfície) |
| `backend/app/storage/local.py` | `LocalFSStorage` (pathlib) |
| `backend/app/storage/azure_blob.py` | `AzureBlobStorage` (azure-storage-blob) |
| `backend/app/storage/factory.py` | `create_storage_service()` — selecció per STORAGE_TYPE |
| `backend/alembic.ini` | Config Alembic |
| `backend/alembic/env.py` | Entorn Alembic (llegeix DATABASE_URL) |
| `backend/alembic/versions/0001_initial_schema.py` | Migració inicial (totes les taules) |
| `backend/tests/test_db_models.py` | Tests dels models SQLAlchemy |
| `backend/tests/test_storage.py` | Tests de LocalFSStorage |
| `backend/tests/test_project_manager_db.py` | Tests de ProjectManager amb BD |
| `backend/tests/test_task_manager_db.py` | Tests de TaskManager amb BD |

### Fitxers a modificar

| Fitxer | Canvi |
|--------|-------|
| `backend/pyproject.toml` | Afegir `sqlalchemy`, `alembic`, `flask-sqlalchemy`, `azure-storage-blob`, `bcrypt`, `flask-jwt-extended` |
| `backend/app/config.py` | Afegir `DATABASE_URL`, `STORAGE_TYPE`, `STORAGE_LOCAL_PATH`, `AZURE_STORAGE_*`, `JWT_SECRET`, `JWT_REFRESH_SECRET` |
| `backend/app/__init__.py` | Inicialitzar DB + Storage a `create_app()`; substituir auth provisional per `flask-jwt-extended` stub |
| `backend/app/models/project.py` | Refactoritzar `ProjectManager` per usar BD + `StorageService` |
| `backend/app/models/task.py` | Refactoritzar `TaskManager` per usar BD |
| `backend/tests/conftest.py` | Afegir fixtures de BD en memòria i storage temporal |

---

## Task 1: Afegir dependències

**Files:**
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Afegir dependències al pyproject.toml**

```toml
# backend/pyproject.toml — secció dependencies, afegir:
    "sqlalchemy>=2.0.0",
    "alembic>=1.13.0",
    "flask-sqlalchemy>=3.1.0",
    "azure-storage-blob>=12.19.0",
    "bcrypt>=4.1.0",
    "flask-jwt-extended>=4.6.0",
```

- [ ] **Step 2: Instal·lar dependències**

```bash
cd /home/ubuntu/dev/MiroFish/.worktrees/persistencia/backend
uv sync
```

Expected: sense errors. `uv sync` actualitza el `.venv`.

- [ ] **Step 3: Verificar importació**

```bash
cd /home/ubuntu/dev/MiroFish/.worktrees/persistencia/backend
.venv/bin/python -c "import sqlalchemy; import alembic; import flask_sqlalchemy; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/pyproject.toml
git commit -m "chore(deps): add SQLAlchemy, Alembic, Azure Blob, bcrypt, flask-jwt-extended"
```

---

## Task 2: Afegir variables de configuració

**Files:**
- Modify: `backend/app/config.py`

- [ ] **Step 1: Escriure test de la nova configuració**

Afegir a `backend/tests/test_db_models.py` (el fitxer el crearem al Task 3, però el test de config el posem a un fitxer nou):

```python
# backend/tests/test_config.py
import os
import pytest


def test_database_url_default():
    """DATABASE_URL per defecte ha de ser SQLite"""
    from backend.app.config import Config
    assert Config.DATABASE_URL.startswith("sqlite")


def test_storage_type_default():
    from backend.app.config import Config
    assert Config.STORAGE_TYPE == "local"


def test_storage_local_path_exists():
    from backend.app.config import Config
    assert Config.STORAGE_LOCAL_PATH is not None
```

- [ ] **Step 2: Executar test per verificar que falla**

```bash
cd /home/ubuntu/dev/MiroFish/.worktrees/persistencia
.venv/bin/pytest backend/tests/test_config.py -v 2>/dev/null || \
backend/.venv/bin/pytest backend/tests/test_config.py -v
```

Expected: `AttributeError: type object 'Config' has no attribute 'DATABASE_URL'`

- [ ] **Step 3: Afegir configuració a config.py**

Afegir al final de la classe `Config` (just abans del mètode `validate`):

```python
    # ── Persistència ──────────────────────────────────────────────
    # Base de dades
    DATABASE_URL = os.environ.get('DATABASE_URL', 'sqlite:///mirofish_dev.db')
    
    # Storage de fitxers
    STORAGE_TYPE = os.environ.get('STORAGE_TYPE', 'local')          # local | azure
    STORAGE_LOCAL_PATH = os.environ.get(
        'STORAGE_LOCAL_PATH',
        os.path.join(os.path.dirname(__file__), '../uploads')
    )
    AZURE_STORAGE_CONNECTION_STRING = os.environ.get('AZURE_STORAGE_CONNECTION_STRING', '')
    AZURE_STORAGE_CONTAINER = os.environ.get('AZURE_STORAGE_CONTAINER', 'mirofish')
    
    # JWT (per a la Fase 2 d'autenticació — definits aquí perquè flask-jwt-extended els necessita en create_app)
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET', 'change-me-in-production')
    JWT_REFRESH_SECRET_KEY = os.environ.get('JWT_REFRESH_SECRET', 'change-me-refresh-in-production')
    JWT_ACCESS_TOKEN_EXPIRES_HOURS = int(os.environ.get('JWT_ACCESS_TOKEN_EXPIRES_HOURS', '8'))
    JWT_REFRESH_TOKEN_EXPIRES_DAYS = int(os.environ.get('JWT_REFRESH_TOKEN_EXPIRES_DAYS', '7'))
```

- [ ] **Step 4: Executar test per verificar que passa**

```bash
backend/.venv/bin/pytest backend/tests/test_config.py -v
```

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/config.py backend/tests/test_config.py
git commit -m "feat(config): add DATABASE_URL, STORAGE_TYPE, AZURE_STORAGE_*, JWT config vars"
```

---

## Task 3: Crear models SQLAlchemy

**Files:**
- Create: `backend/app/models/db_models.py`
- Create: `backend/app/db.py`
- Create: `backend/tests/test_db_models.py`

- [ ] **Step 1: Crear backend/app/db.py**

```python
# backend/app/db.py
"""SQLAlchemy engine, session factory i Base declarativa."""
from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session
from typing import Generator


class Base(DeclarativeBase):
    pass


_engine = None
_SessionLocal = None


def init_db(database_url: str) -> None:
    global _engine, _SessionLocal
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    _engine = create_engine(database_url, connect_args=connect_args, echo=False)
    _SessionLocal = sessionmaker(bind=_engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(_engine)


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Context manager de sessió SQLAlchemy."""
    if _SessionLocal is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    db = _SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
```

- [ ] **Step 2: Crear backend/app/models/db_models.py**

```python
# backend/app/models/db_models.py
"""Models SQLAlchemy per a tota la persistència de MiroFish."""
import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import (
    String, Integer, Text, Boolean, DateTime, JSON,
    ForeignKey, UniqueConstraint
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ..db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.utcnow()


class UserModel(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    password_hash: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    projects: Mapped[list["ProjectModel"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )
    invitation_tokens: Mapped[list["InvitationTokenModel"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    password_reset_tokens: Mapped[list["PasswordResetTokenModel"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class ProjectModel(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="Unnamed Project")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="created")
    analysis_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    simulation_requirement: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    chunk_size: Mapped[int] = mapped_column(Integer, default=500)
    chunk_overlap: Mapped[int] = mapped_column(Integer, default=50)
    active_task_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    owner: Mapped[Optional["UserModel"]] = relationship(back_populates="projects")
    files: Mapped[list["ProjectFileModel"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    ontologies: Mapped[list["OntologyModel"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    graphs: Mapped[list["GraphModel"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    simulations: Mapped[list["SimulationModel"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    reports: Mapped[list["ReportModel"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class ProjectFileModel(Base):
    __tablename__ = "project_files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    size: Mapped[int] = mapped_column(Integer, default=0)
    mime_type: Mapped[str] = mapped_column(String(100), default="application/octet-stream")
    file_type: Mapped[str] = mapped_column(String(30), default="upload")  # upload | extracted_text
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    project: Mapped["ProjectModel"] = relationship(back_populates="files")


class OntologyModel(Base):
    __tablename__ = "ontologies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    entity_types: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    edge_types: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    project: Mapped["ProjectModel"] = relationship(back_populates="ontologies")
    graphs: Mapped[list["GraphModel"]] = relationship(back_populates="ontology")


class GraphModel(Base):
    __tablename__ = "graphs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    ontology_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("ontologies.id", ondelete="SET NULL"), nullable=True
    )
    backend: Mapped[str] = mapped_column(String(20), default="zep")  # zep | graphiti
    external_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="building")  # building | ready | failed
    node_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    edge_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    project: Mapped["ProjectModel"] = relationship(back_populates="graphs")
    ontology: Mapped[Optional["OntologyModel"]] = relationship(back_populates="graphs")
    simulations: Mapped[list["SimulationModel"]] = relationship(back_populates="graph")
    reports: Mapped[list["ReportModel"]] = relationship(back_populates="graph")


class SimulationModel(Base):
    __tablename__ = "simulations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    graph_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("graphs.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(30), default="prepared")
    platform: Mapped[str] = mapped_column(String(20), default="twitter")  # twitter | reddit | both
    config: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    profiles_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    db_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    actions_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rounds_total: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rounds_completed: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    project: Mapped["ProjectModel"] = relationship(back_populates="simulations")
    graph: Mapped[Optional["GraphModel"]] = relationship(back_populates="simulations")
    reports: Mapped[list["ReportModel"]] = relationship(back_populates="simulation")


class ReportModel(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    simulation_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("simulations.id", ondelete="SET NULL"), nullable=True
    )
    graph_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("graphs.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(30), default="generating")
    outline: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    storage_prefix: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    project: Mapped["ProjectModel"] = relationship(back_populates="reports")
    simulation: Mapped[Optional["SimulationModel"]] = relationship(back_populates="reports")
    graph: Mapped[Optional["GraphModel"]] = relationship(back_populates="reports")


class TaskModel(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    task_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    entity_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    progress_detail: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class SystemConfigModel(Base):
    __tablename__ = "system_config"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    value_type: Mapped[str] = mapped_column(String(20), default="string")
    group: Mapped[str] = mapped_column(String(50), default="general")
    label: Mapped[str] = mapped_column(String(255), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)
    updated_by: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class InvitationTokenModel(Base):
    __tablename__ = "invitation_tokens"

    token: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    user: Mapped["UserModel"] = relationship(back_populates="invitation_tokens")


class PasswordResetTokenModel(Base):
    __tablename__ = "password_reset_tokens"

    token: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    user: Mapped["UserModel"] = relationship(back_populates="password_reset_tokens")
```

- [ ] **Step 3: Crear test dels models**

```python
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
    from backend.app import db as db_module
    db_module._engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
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
    task = TaskModel(id="task-del", task_type="graph_build")
    proj = ProjectModel(id="proj-2", name="P2", active_task_id="task-del")
    db_session.add_all([task, proj])
    db_session.commit()
    db_session.delete(task)
    db_session.commit()
    db_session.expire(proj)
    refreshed = db_session.get(ProjectModel, "proj-2")
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
```

- [ ] **Step 4: Executar tests dels models**

```bash
cd /home/ubuntu/dev/MiroFish/.worktrees/persistencia
backend/.venv/bin/pytest backend/tests/test_db_models.py -v
```

Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/db.py backend/app/models/db_models.py backend/tests/test_db_models.py
git commit -m "feat(db): add SQLAlchemy Base, session factory, and all ORM models"
```

---

## Task 4: Configurar Alembic

**Files:**
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/script.py.mako`
- Create: `backend/alembic/versions/0001_initial_schema.py`

- [ ] **Step 1: Inicialitzar Alembic**

```bash
cd /home/ubuntu/dev/MiroFish/.worktrees/persistencia/backend
backend/.venv/bin/alembic init alembic
```

Expected: crea `alembic/` i `alembic.ini`

- [ ] **Step 2: Actualitzar alembic.ini**

Substituir la línia `sqlalchemy.url = ...` a `alembic.ini`:

```ini
# Canviar aquesta línia:
sqlalchemy.url = driver://user:pass@localhost/dbname
# Per:
sqlalchemy.url = sqlite:///mirofish_dev.db
```

I afegir just sota `[alembic]`:
```ini
script_location = alembic
```

- [ ] **Step 3: Actualitzar alembic/env.py**

Substituir el contingut complet d'`alembic/env.py`:

```python
# backend/alembic/env.py
import os
import sys
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

# Afegir el backend al path perquè els imports funcionin
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.db import Base
import app.models.db_models  # noqa: F401 — registra tots els models al Base

config = context.config

# Llegir DATABASE_URL de l'entorn (prioritat sobre alembic.ini)
db_url = os.environ.get('DATABASE_URL', config.get_main_option('sqlalchemy.url'))
config.set_main_option('sqlalchemy.url', db_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 4: Generar migració inicial**

```bash
cd /home/ubuntu/dev/MiroFish/.worktrees/persistencia/backend
backend/.venv/bin/alembic revision --autogenerate -m "initial_schema"
```

Expected: crea `alembic/versions/XXXX_initial_schema.py` amb totes les taules

- [ ] **Step 5: Aplicar migració**

```bash
backend/.venv/bin/alembic upgrade head
```

Expected: `Running upgrade  -> XXXX, initial_schema`

- [ ] **Step 6: Verificar que la BD té les taules**

```bash
backend/.venv/bin/python -c "
import sqlite3
conn = sqlite3.connect('mirofish_dev.db')
tables = conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()
print([t[0] for t in tables])
conn.close()
"
```

Expected: llista que inclou `projects`, `tasks`, `users`, `ontologies`, `graphs`, `simulations`, `reports`, `system_config`

- [ ] **Step 7: Commit**

```bash
git add backend/alembic.ini backend/alembic/ backend/mirofish_dev.db
git commit -m "feat(alembic): add initial schema migration for all SQLAlchemy models"
```

---

## Task 5: Implementar StorageService

**Files:**
- Create: `backend/app/storage/__init__.py`
- Create: `backend/app/storage/protocol.py`
- Create: `backend/app/storage/local.py`
- Create: `backend/app/storage/azure_blob.py`
- Create: `backend/app/storage/factory.py`
- Create: `backend/tests/test_storage.py`

- [ ] **Step 1: Crear el directori i el Protocol**

```python
# backend/app/storage/protocol.py
"""Interfície abstracta per a la capa de storage de fitxers."""
from typing import IO, Iterator, Protocol, runtime_checkable


@runtime_checkable
class StorageService(Protocol):
    def upload(self, path: str, data: bytes | IO, content_type: str = "application/octet-stream") -> None:
        ...

    def download(self, path: str) -> bytes:
        ...

    def download_stream(self, path: str) -> IO:
        ...

    def delete(self, path: str) -> None:
        ...

    def delete_prefix(self, prefix: str) -> None:
        """Esborra tots els fitxers que comencen per prefix."""
        ...

    def exists(self, path: str) -> bool:
        ...

    def list(self, prefix: str = "") -> list[str]:
        """Retorna paths relatius sota el prefix."""
        ...

    def public_url(self, path: str) -> str | None:
        """URL pública si el backend ho suporta, None si no."""
        ...
```

- [ ] **Step 2: Crear LocalFSStorage**

```python
# backend/app/storage/local.py
"""Adapter de storage per a filesystem local."""
import io
import os
import shutil
from pathlib import Path
from .protocol import StorageService


class LocalFSStorage:
    """Implementació de StorageService per a filesystem local."""

    def __init__(self, base_path: str) -> None:
        self._base = Path(base_path).resolve()
        self._base.mkdir(parents=True, exist_ok=True)

    def _safe_path(self, relative: str) -> Path:
        """Resol el path i valida que estigui dins del base per evitar path traversal."""
        resolved = (self._base / relative).resolve()
        if not str(resolved).startswith(str(self._base)):
            raise ValueError(f"Path traversal detectat: {relative!r}")
        return resolved

    def upload(self, path: str, data: bytes | io.IOBase, content_type: str = "application/octet-stream") -> None:
        dest = self._safe_path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            dest.write_bytes(data)
        else:
            with open(dest, "wb") as f:
                shutil.copyfileobj(data, f)

    def download(self, path: str) -> bytes:
        return self._safe_path(path).read_bytes()

    def download_stream(self, path: str) -> io.BytesIO:
        return io.BytesIO(self.download(path))

    def delete(self, path: str) -> None:
        p = self._safe_path(path)
        if p.exists():
            p.unlink()

    def delete_prefix(self, prefix: str) -> None:
        p = self._safe_path(prefix)
        if p.is_dir():
            shutil.rmtree(p)
        elif p.exists():
            p.unlink()

    def exists(self, path: str) -> bool:
        return self._safe_path(path).exists()

    def list(self, prefix: str = "") -> list[str]:
        base = self._safe_path(prefix) if prefix else self._base
        if not base.exists():
            return []
        result = []
        for p in base.rglob("*"):
            if p.is_file():
                result.append(str(p.relative_to(self._base)))
        return result

    def public_url(self, path: str) -> str | None:
        return None
```

- [ ] **Step 3: Crear AzureBlobStorage**

```python
# backend/app/storage/azure_blob.py
"""Adapter de storage per a Azure Blob Storage."""
import io
from .protocol import StorageService


class AzureBlobStorage:
    """Implementació de StorageService per a Azure Blob Storage."""

    def __init__(self, connection_string: str, container_name: str) -> None:
        from azure.storage.blob import BlobServiceClient
        self._client = BlobServiceClient.from_connection_string(connection_string)
        self._container = container_name
        self._ensure_container()

    def _ensure_container(self) -> None:
        container_client = self._client.get_container_client(self._container)
        if not container_client.exists():
            container_client.create_container()

    def _blob_client(self, path: str):
        return self._client.get_blob_client(container=self._container, blob=path)

    def upload(self, path: str, data: bytes | io.IOBase, content_type: str = "application/octet-stream") -> None:
        blob = self._blob_client(path)
        if isinstance(data, bytes):
            blob.upload_blob(data, overwrite=True, content_settings={"content_type": content_type})
        else:
            blob.upload_blob(data, overwrite=True, content_settings={"content_type": content_type})

    def download(self, path: str) -> bytes:
        return self._blob_client(path).download_blob().readall()

    def download_stream(self, path: str) -> io.BytesIO:
        return io.BytesIO(self.download(path))

    def delete(self, path: str) -> None:
        self._blob_client(path).delete_blob(delete_snapshots="include")

    def delete_prefix(self, prefix: str) -> None:
        container = self._client.get_container_client(self._container)
        blobs = container.list_blobs(name_starts_with=prefix)
        for blob in blobs:
            container.delete_blob(blob.name, delete_snapshots="include")

    def exists(self, path: str) -> bool:
        return self._blob_client(path).exists()

    def list(self, prefix: str = "") -> list[str]:
        container = self._client.get_container_client(self._container)
        return [b.name for b in container.list_blobs(name_starts_with=prefix)]

    def public_url(self, path: str) -> str | None:
        return self._blob_client(path).url
```

- [ ] **Step 4: Crear factory**

```python
# backend/app/storage/factory.py
"""Selecciona la implementació de StorageService per STORAGE_TYPE."""
import os
from .protocol import StorageService


def create_storage_service() -> StorageService:
    storage_type = os.environ.get("STORAGE_TYPE", "local")
    match storage_type:
        case "azure":
            from .azure_blob import AzureBlobStorage
            conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
            container = os.environ.get("AZURE_STORAGE_CONTAINER", "mirofish")
            if not conn_str:
                raise RuntimeError("AZURE_STORAGE_CONNECTION_STRING no configurada per STORAGE_TYPE=azure")
            return AzureBlobStorage(conn_str, container)
        case _:
            from .local import LocalFSStorage
            base = os.environ.get("STORAGE_LOCAL_PATH",
                                   os.path.join(os.path.dirname(__file__), "../../../uploads"))
            return LocalFSStorage(base)
```

- [ ] **Step 5: Crear __init__.py del package**

```python
# backend/app/storage/__init__.py
from .protocol import StorageService
from .factory import create_storage_service

__all__ = ["StorageService", "create_storage_service"]
```

- [ ] **Step 6: Escriure tests de LocalFSStorage**

```python
# backend/tests/test_storage.py
import io
import pytest
import tempfile
import os
from backend.app.storage.local import LocalFSStorage


@pytest.fixture
def storage(tmp_path):
    return LocalFSStorage(str(tmp_path))


def test_upload_and_download_bytes(storage):
    storage.upload("foo/bar.txt", b"hello world", "text/plain")
    assert storage.download("foo/bar.txt") == b"hello world"


def test_upload_and_download_stream(storage):
    data = io.BytesIO(b"stream data")
    storage.upload("test/stream.bin", data)
    result = storage.download("test/stream.bin")
    assert result == b"stream data"


def test_exists(storage):
    assert not storage.exists("not/there.txt")
    storage.upload("yes.txt", b"x")
    assert storage.exists("yes.txt")


def test_delete(storage):
    storage.upload("del.txt", b"bye")
    storage.delete("del.txt")
    assert not storage.exists("del.txt")


def test_delete_prefix(storage):
    storage.upload("dir/a.txt", b"a")
    storage.upload("dir/b.txt", b"b")
    storage.delete_prefix("dir")
    assert not storage.exists("dir/a.txt")
    assert not storage.exists("dir/b.txt")


def test_list(storage):
    storage.upload("root/x.txt", b"x")
    storage.upload("root/y.txt", b"y")
    paths = storage.list("root")
    assert len(paths) == 2
    assert all("root" in p for p in paths)


def test_path_traversal_blocked(storage):
    with pytest.raises(ValueError, match="Path traversal"):
        storage._safe_path("../../etc/passwd")


def test_public_url_is_none(storage):
    storage.upload("f.txt", b"x")
    assert storage.public_url("f.txt") is None
```

- [ ] **Step 7: Executar tests de storage**

```bash
cd /home/ubuntu/dev/MiroFish/.worktrees/persistencia
backend/.venv/bin/pytest backend/tests/test_storage.py -v
```

Expected: 8 passed

- [ ] **Step 8: Commit**

```bash
git add backend/app/storage/ backend/tests/test_storage.py
git commit -m "feat(storage): add StorageService protocol, LocalFSStorage, AzureBlobStorage, factory"
```

---

## Task 6: Injectar DB i Storage a Flask

**Files:**
- Modify: `backend/app/__init__.py`

- [ ] **Step 1: Actualitzar create_app per inicialitzar DB i Storage**

Afegir just després de `app = Flask(__name__)` i `app.config.from_object(...)`:

```python
    # Inicialitzar BD
    from .db import init_db
    init_db(app.config['DATABASE_URL'])

    # Inicialitzar Storage
    from .storage import create_storage_service
    app.extensions['storage'] = create_storage_service()
```

I afegir una funció helper al final del fitxer (fora de `create_app`):

```python
def get_storage():
    """Accés al StorageService des de qualsevol context Flask."""
    from flask import current_app
    return current_app.extensions['storage']
```

- [ ] **Step 2: Verificar que l'app arrenca correctament**

```bash
cd /home/ubuntu/dev/MiroFish/.worktrees/persistencia
DATABASE_URL=sqlite:///test_startup.db STORAGE_TYPE=local \
  backend/.venv/bin/python -c "
from backend.app import create_app
app = create_app()
print('App created OK')
print('Storage:', app.extensions.get('storage'))
"
```

Expected: `App created OK` + `Storage: <LocalFSStorage ...>`

- [ ] **Step 3: Netejar fitxer de test**

```bash
rm -f /home/ubuntu/dev/MiroFish/.worktrees/persistencia/backend/test_startup.db
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/__init__.py
git commit -m "feat(app): inject SQLAlchemy DB and StorageService into Flask app factory"
```

---

## Task 7: Refactoritzar TaskManager → BD

**Files:**
- Modify: `backend/app/models/task.py`
- Create: `backend/tests/test_task_manager_db.py`

El `TaskManager` actual és in-memory. El refactoritzem per usar la BD via `get_session()`. Mantenim la mateixa interfície pública (`create_task`, `get_task`, `update_task`, `complete_task`, `fail_task`, `list_tasks`) per no trencar cap cridador.

- [ ] **Step 1: Escriure els tests del nou TaskManager**

```python
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
```

- [ ] **Step 2: Executar tests per verificar que fallen**

```bash
cd /home/ubuntu/dev/MiroFish/.worktrees/persistencia
backend/.venv/bin/pytest backend/tests/test_task_manager_db.py -v
```

Expected: `test_task_survives_new_manager_instance` FAIL (perquè ara és in-memory)

- [ ] **Step 3: Refactoritzar TaskManager**

Substituir el contingut de `backend/app/models/task.py`:

```python
"""Task state management — persistent via SQLAlchemy."""
import uuid
import threading
from datetime import datetime
from enum import Enum
from typing import Dict, Any, Optional, List

from ..db import get_session
from ..models.db_models import TaskModel
from ..utils.locale import t


class TaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskManager:
    """Task manager — thread-safe, persistent via SQLAlchemy."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def create_task(self, task_type: str, metadata: Optional[Dict] = None) -> str:
        task_id = str(uuid.uuid4())
        with get_session() as db:
            task = TaskModel(
                id=task_id,
                task_type=task_type,
                status="pending",
                progress=0,
                progress_detail=metadata or {},
            )
            db.add(task)
            db.commit()
        return task_id

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with get_session() as db:
            task = db.get(TaskModel, task_id)
            if task is None:
                return None
            return self._to_dict(task)

    def update_task(
        self,
        task_id: str,
        status: Optional[str] = None,
        progress: Optional[int] = None,
        message: Optional[str] = None,
        result: Optional[Dict] = None,
        error: Optional[str] = None,
        progress_detail: Optional[Dict] = None,
    ) -> None:
        with get_session() as db:
            task = db.get(TaskModel, task_id)
            if task is None:
                return
            if status is not None:
                task.status = status
            if progress is not None:
                task.progress = progress
            if message is not None:
                task.message = message
            if result is not None:
                task.result = result
            if error is not None:
                task.error = error
            if progress_detail is not None:
                task.progress_detail = progress_detail
            task.updated_at = datetime.utcnow()
            db.commit()

    def complete_task(self, task_id: str, result: Dict) -> None:
        self.update_task(
            task_id,
            status=TaskStatus.COMPLETED,
            progress=100,
            message=t("progress.taskComplete"),
            result=result,
        )

    def fail_task(self, task_id: str, error: str) -> None:
        self.update_task(
            task_id,
            status=TaskStatus.FAILED,
            message=t("progress.taskFailed"),
            error=error,
        )

    def list_tasks(self, task_type: Optional[str] = None) -> List[Dict[str, Any]]:
        from sqlalchemy import select, desc
        with get_session() as db:
            stmt = select(TaskModel).order_by(desc(TaskModel.created_at))
            if task_type:
                stmt = stmt.where(TaskModel.task_type == task_type)
            tasks = db.execute(stmt).scalars().all()
            return [self._to_dict(t) for t in tasks]

    def cleanup_old_tasks(self, max_age_hours: int = 24) -> None:
        from datetime import timedelta
        from sqlalchemy import delete
        cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
        with get_session() as db:
            db.execute(
                delete(TaskModel).where(
                    TaskModel.created_at < cutoff,
                    TaskModel.status.in_(["completed", "failed"]),
                )
            )
            db.commit()

    @staticmethod
    def _to_dict(task: TaskModel) -> Dict[str, Any]:
        return {
            "task_id": task.id,
            "task_type": task.task_type,
            "status": task.status,
            "created_at": task.created_at.isoformat(),
            "updated_at": task.updated_at.isoformat(),
            "progress": task.progress,
            "message": task.message or "",
            "progress_detail": task.progress_detail or {},
            "result": task.result,
            "error": task.error,
            "metadata": task.progress_detail or {},
        }
```

**Nota:** `get_session()` ja és un context manager des del Task 3. Usa `with get_session() as db:` tal com es mostra al codi.

- [ ] **Step 4: Executar tests del TaskManager**

```bash
backend/.venv/bin/pytest backend/tests/test_task_manager_db.py -v
```

Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/task.py backend/app/db.py backend/tests/test_task_manager_db.py
git commit -m "feat(task): refactor TaskManager to persist tasks in SQLAlchemy DB"
```

---

## Task 8: Refactoritzar ProjectManager → BD + Storage

**Files:**
- Modify: `backend/app/models/project.py`
- Create: `backend/tests/test_project_manager_db.py`

Refactoritzem `ProjectManager` per usar la BD per a metadades i `StorageService` per a fitxers. Mantenim la mateixa interfície pública.

- [ ] **Step 1: Escriure tests del nou ProjectManager**

```python
# backend/tests/test_project_manager_db.py
import io
import pytest
import tempfile
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.app.db import Base
import backend.app.db as db_module
from backend.app.storage.local import LocalFSStorage


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
    # Simular reinici: netejar l'estat en memòria si n'hi ha
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
```

- [ ] **Step 2: Executar tests per verificar que fallen**

```bash
backend/.venv/bin/pytest backend/tests/test_project_manager_db.py -v
```

Expected: errors (interfície actual no accepta `storage=` paràmetre)

- [ ] **Step 3: Refactoritzar ProjectManager**

Substituir el contingut de `backend/app/models/project.py`:

```python
"""Project context management — persistent via SQLAlchemy + StorageService."""
import uuid
import io
from datetime import datetime
from typing import Dict, Any, List, Optional
from enum import Enum

from ..db import get_session
from ..models.db_models import ProjectModel, ProjectFileModel


class ProjectStatus(str, Enum):
    CREATED = "created"
    ONTOLOGY_GENERATED = "ontology_generated"
    GRAPH_BUILDING = "graph_building"
    GRAPH_COMPLETED = "graph_completed"
    FAILED = "failed"


class ProjectManager:
    """Gestiona projectes: metadades a BD, fitxers a StorageService."""

    @classmethod
    def create_project(cls, name: str = "Unnamed Project", storage=None) -> Dict[str, Any]:
        project_id = str(uuid.uuid4())
        with get_session() as db:
            proj = ProjectModel(id=project_id, name=name, status="created")
            db.add(proj)
            db.commit()
            db.refresh(proj)
            return cls._to_dict(proj)

    @classmethod
    def get_project(cls, project_id: str) -> Optional[Dict[str, Any]]:
        with get_session() as db:
            proj = db.get(ProjectModel, project_id)
            if proj is None:
                return None
            return cls._to_dict(proj)

    @classmethod
    def save_project(cls, project_data: Dict[str, Any]) -> None:
        """Actualitza els camps d'un projecte existent."""
        project_id = project_data.get("id") or project_data.get("project_id")
        with get_session() as db:
            proj = db.get(ProjectModel, project_id)
            if proj is None:
                return
            updatable = [
                "name", "status", "analysis_summary", "simulation_requirement",
                "chunk_size", "chunk_overlap", "active_task_id",
            ]
            for field in updatable:
                if field in project_data:
                    setattr(proj, field, project_data[field])
            proj.updated_at = datetime.utcnow()
            db.commit()

    @classmethod
    def list_projects(cls, limit: int = 50) -> List[Dict[str, Any]]:
        from sqlalchemy import select, desc
        with get_session() as db:
            stmt = select(ProjectModel).order_by(desc(ProjectModel.created_at)).limit(limit)
            projects = db.execute(stmt).scalars().all()
            return [cls._to_dict(p) for p in projects]

    @classmethod
    def delete_project(cls, project_id: str, storage=None) -> bool:
        with get_session() as db:
            proj = db.get(ProjectModel, project_id)
            if proj is None:
                return False
            # Esborrar fitxers de storage si s'ha passat el servei
            if storage is not None:
                storage.delete_prefix(f"projects/{project_id}")
            db.delete(proj)
            db.commit()
        return True

    @classmethod
    def save_file_to_project(
        cls,
        project_id: str,
        file_storage,  # Flask FileStorage
        original_filename: str,
        storage,
    ) -> Dict[str, Any]:
        import os
        ext = os.path.splitext(original_filename)[1].lower()
        safe_filename = f"{uuid.uuid4().hex[:8]}{ext}"
        storage_path = f"projects/{project_id}/files/{safe_filename}"

        data = file_storage.read()
        storage.upload(storage_path, data)

        mime_type = getattr(file_storage, "content_type", "application/octet-stream") or "application/octet-stream"

        with get_session() as db:
            file_rec = ProjectFileModel(
                id=str(uuid.uuid4()),
                project_id=project_id,
                original_name=original_filename,
                storage_path=storage_path,
                size=len(data),
                mime_type=mime_type,
                file_type="upload",
            )
            db.add(file_rec)
            db.commit()

        return {
            "original_filename": original_filename,
            "saved_filename": safe_filename,
            "storage_path": storage_path,
            "size": len(data),
        }

    @classmethod
    def save_extracted_text(cls, project_id: str, text: str, storage) -> None:
        storage_path = f"projects/{project_id}/extracted_text.txt"
        storage.upload(storage_path, text.encode("utf-8"), "text/plain")

        with get_session() as db:
            from sqlalchemy import select
            stmt = select(ProjectFileModel).where(
                ProjectFileModel.project_id == project_id,
                ProjectFileModel.file_type == "extracted_text",
            )
            existing = db.execute(stmt).scalar_one_or_none()
            if existing:
                existing.storage_path = storage_path
                existing.size = len(text.encode("utf-8"))
            else:
                rec = ProjectFileModel(
                    id=str(uuid.uuid4()),
                    project_id=project_id,
                    original_name="extracted_text.txt",
                    storage_path=storage_path,
                    size=len(text.encode("utf-8")),
                    mime_type="text/plain",
                    file_type="extracted_text",
                )
                db.add(rec)
            db.commit()

    @classmethod
    def get_extracted_text(cls, project_id: str, storage) -> Optional[str]:
        storage_path = f"projects/{project_id}/extracted_text.txt"
        if not storage.exists(storage_path):
            return None
        return storage.download(storage_path).decode("utf-8")

    @staticmethod
    def _to_dict(proj: ProjectModel) -> Dict[str, Any]:
        return {
            "id": proj.id,
            "project_id": proj.id,  # compatibilitat amb codi existent
            "name": proj.name,
            "status": proj.status,
            "analysis_summary": proj.analysis_summary,
            "simulation_requirement": proj.simulation_requirement,
            "chunk_size": proj.chunk_size,
            "chunk_overlap": proj.chunk_overlap,
            "active_task_id": proj.active_task_id,
            "created_at": proj.created_at.isoformat(),
            "updated_at": proj.updated_at.isoformat(),
            # Camps llegits del model antic — ara buits per compatibilitat
            "files": [],
            "total_text_length": 0,
            "ontology": None,
            "graph_id": None,
            "graph_build_task_id": None,
            "error": None,
        }
```

- [ ] **Step 4: Executar tests del ProjectManager**

```bash
backend/.venv/bin/pytest backend/tests/test_project_manager_db.py -v
```

Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/project.py backend/tests/test_project_manager_db.py
git commit -m "feat(project): refactor ProjectManager to persist via SQLAlchemy + StorageService"
```

---

## Task 9: Actualitzar tests existents i verificació final

**Files:**
- Modify: `backend/tests/conftest.py`
- Modify: `backend/tests/test_project_task_recovery.py` (si afectat)

- [ ] **Step 1: Actualitzar conftest.py per afegir fixtures globals**

```python
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
```

- [ ] **Step 2: Executar tota la suite de tests**

```bash
cd /home/ubuntu/dev/MiroFish/.worktrees/persistencia
backend/.venv/bin/pytest backend/tests/ -v --tb=short 2>&1 | tail -30
```

Expected: tots els tests del Task 2-8 passen. El test `test_config_graph_backend_default` pot continuar fallant (falla preexistent no relacionada).

- [ ] **Step 3: Verificar que l'app arrenca i la BD es crea correctament**

```bash
cd /home/ubuntu/dev/MiroFish/.worktrees/persistencia/backend
DATABASE_URL=sqlite:///verify_startup.db \
STORAGE_TYPE=local \
STORAGE_LOCAL_PATH=/tmp/mirofish_test_uploads \
LLM_API_KEY=test-key \
ZEP_API_KEY=test-key \
  .venv/bin/python -c "
from app import create_app
app = create_app()
with app.app_context():
    from app.models.project import ProjectManager
    from app.storage import create_storage_service
    storage = app.extensions['storage']
    proj = ProjectManager.create_project('Startup Test', storage=storage)
    print('Project created:', proj['id'])
    fetched = ProjectManager.get_project(proj['id'])
    print('Project fetched:', fetched['name'])
    print('Verification OK')
"
rm -f verify_startup.db
```

Expected: `Verification OK`

- [ ] **Step 4: Commit final de la Fase 1**

```bash
git add backend/tests/conftest.py
git commit -m "test(conftest): add in_memory_db and task manager singleton reset fixtures"

git tag fase1-infraestructura-base
```

---

## Verificació end-to-end de la Fase 1

```bash
# 1. Tots els tests passen
backend/.venv/bin/pytest backend/tests/ -v

# 2. La BD es crea amb les migracions
backend/.venv/bin/alembic upgrade head

# 3. L'app arrenca correctament
DATABASE_URL=sqlite:///mirofish_dev.db STORAGE_TYPE=local LLM_API_KEY=x ZEP_API_KEY=x \
  backend/.venv/bin/python backend/run.py &
sleep 2
curl -s http://localhost:5001/health | python3 -m json.tool
kill %1
```

Expected final: `{"service": "MiroFish Backend", "status": "ok"}`

---

> **Nota:** Les Fases 2 (Auth+RBAC), 3 (pipeline) i 4 (hardening producció) tindran els seus propis plans, escrits quan comenci cada fase.
