"""Project context management — persistent via SQLAlchemy + StorageService."""
import uuid
import io
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from enum import Enum

from ..db import get_session
from ..models.db_models import ProjectModel, ProjectFileModel
from ..config import Config


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
            db.expunge(proj)
        return cls._to_dict(proj)

    @classmethod
    def get_project(cls, project_id: str) -> Optional[Dict[str, Any]]:
        with get_session() as db:
            proj = db.get(ProjectModel, project_id)
            if proj is None:
                return None
            db.expunge(proj)
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
            proj.updated_at = datetime.now(timezone.utc)
            db.commit()

    @classmethod
    def list_projects(cls, limit: int = 50) -> List[Dict[str, Any]]:
        from sqlalchemy import select, desc
        with get_session() as db:
            stmt = select(ProjectModel).order_by(desc(ProjectModel.created_at)).limit(limit)
            projects = db.execute(stmt).scalars().all()
            for p in projects:
                db.expunge(p)
        return [cls._to_dict(p) for p in projects]

    @classmethod
    def delete_project(cls, project_id: str, storage=None) -> bool:
        with get_session() as db:
            proj = db.get(ProjectModel, project_id)
            if proj is None:
                return False
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

    @classmethod
    def save_ontology(cls, project_id: str, entity_types: list, edge_types: list) -> str:
        from .db_models import OntologyModel
        from sqlalchemy import select
        with get_session() as db:
            stmt = select(OntologyModel).where(OntologyModel.project_id == project_id).order_by(OntologyModel.version.desc())
            existing = db.execute(stmt).scalars().first()
            if existing:
                existing.entity_types = entity_types
                existing.edge_types = edge_types
                db.commit()
                return existing.id
            else:
                rec = OntologyModel(
                    id=str(uuid.uuid4()),
                    project_id=project_id,
                    version=1,
                    entity_types=entity_types,
                    edge_types=edge_types,
                )
                db.add(rec)
                db.commit()
                return rec.id

    @classmethod
    def get_ontology(cls, project_id: str) -> Optional[Dict[str, Any]]:
        from .db_models import OntologyModel
        from sqlalchemy import select
        with get_session() as db:
            stmt = select(OntologyModel).where(OntologyModel.project_id == project_id).order_by(OntologyModel.version.desc())
            rec = db.execute(stmt).scalars().first()
            if rec is None:
                return None
            return {"entity_types": rec.entity_types or [], "edge_types": rec.edge_types or []}

    @classmethod
    def save_graph_record(cls, project_id: str, external_id: str, ontology_id: Optional[str] = None) -> str:
        from .db_models import GraphModel
        from sqlalchemy import select
        with get_session() as db:
            stmt = select(GraphModel).where(GraphModel.project_id == project_id).order_by(GraphModel.created_at.desc())
            existing = db.execute(stmt).scalars().first()
            if existing:
                existing.external_id = external_id
                existing.status = "building"
                if ontology_id:
                    existing.ontology_id = ontology_id
                db.commit()
                return existing.id
            else:
                rec = GraphModel(
                    id=str(uuid.uuid4()),
                    project_id=project_id,
                    external_id=external_id,
                    ontology_id=ontology_id,
                    status="building",
                    backend=Config.GRAPH_BACKEND,
                )
                db.add(rec)
                db.commit()
                return rec.id

    @classmethod
    def get_latest_graph_external_id(cls, project_id: str) -> Optional[str]:
        from .db_models import GraphModel
        from sqlalchemy import select
        with get_session() as db:
            stmt = select(GraphModel).where(GraphModel.project_id == project_id).order_by(GraphModel.created_at.desc())
            rec = db.execute(stmt).scalars().first()
            return rec.external_id if rec else None

    @classmethod
    def complete_graph_record(cls, project_id: str, node_count: int, edge_count: int) -> None:
        from .db_models import GraphModel
        from sqlalchemy import select
        with get_session() as db:
            stmt = select(GraphModel).where(GraphModel.project_id == project_id).order_by(GraphModel.created_at.desc())
            rec = db.execute(stmt).scalars().first()
            if rec:
                rec.status = "ready"
                rec.node_count = node_count
                rec.edge_count = edge_count
                db.commit()

    @classmethod
    def _to_dict(cls, proj: "ProjectModel") -> Dict[str, Any]:
        from .db_models import GraphModel, OntologyModel
        from sqlalchemy import select
        graph_external_id = None
        ontology = None
        with get_session() as db2:
            graph_rec = db2.execute(
                select(GraphModel).where(GraphModel.project_id == proj.id).order_by(GraphModel.created_at.desc())
            ).scalars().first()
            ont_rec = db2.execute(
                select(OntologyModel).where(OntologyModel.project_id == proj.id).order_by(OntologyModel.version.desc())
            ).scalars().first()
            if graph_rec:
                graph_external_id = graph_rec.external_id
            if ont_rec:
                ontology = {"entity_types": ont_rec.entity_types or [], "edge_types": ont_rec.edge_types or []}
        return {
            "id": proj.id,
            "project_id": proj.id,
            "name": proj.name,
            "status": proj.status,
            "analysis_summary": proj.analysis_summary,
            "simulation_requirement": proj.simulation_requirement,
            "chunk_size": proj.chunk_size,
            "chunk_overlap": proj.chunk_overlap,
            "active_task_id": proj.active_task_id,
            "created_at": proj.created_at.isoformat(),
            "updated_at": proj.updated_at.isoformat(),
            "files": [],
            "total_text_length": 0,
            "ontology": ontology,
            "graph_id": graph_external_id,
            "graph_build_task_id": None,
            "error": None,
        }
