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
