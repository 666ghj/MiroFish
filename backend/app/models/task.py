"""Task state management — persistent via SQLAlchemy."""
import uuid
import threading
from datetime import datetime, timezone
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
            task.updated_at = datetime.now(timezone.utc)
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
            return [self._to_dict(task_row) for task_row in tasks]

    def cleanup_old_tasks(self, max_age_hours: int = 24) -> None:
        from datetime import timedelta
        from sqlalchemy import delete
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
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
