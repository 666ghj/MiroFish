"""
Task state tracking.

Tracks long-running work such as a knowledge graph build.
"""

import uuid
import threading
from datetime import datetime
from enum import Enum
from typing import Dict, Any, Optional
from dataclasses import dataclass, field

from ..utils.locale import t


class TaskStatus(str, Enum):
    """The lifecycle of one task."""
    PENDING = "pending"          # Queued, not started
    PROCESSING = "processing"    # In flight
    COMPLETED = "completed"      # Finished successfully
    FAILED = "failed"            # Finished with an error


@dataclass
class Task:
    """One tracked task."""
    task_id: str
    task_type: str
    status: TaskStatus
    created_at: datetime
    updated_at: datetime
    progress: int = 0              # Overall progress, 0-100
    message: str = ""              # Human-readable status
    result: Optional[Dict] = None  # Task result
    error: Optional[str] = None    # Failure reason
    metadata: Dict = field(default_factory=dict)  # Caller-supplied metadata
    progress_detail: Dict = field(default_factory=dict)  # Per-stage progress
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize the task for the API."""
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "progress": self.progress,
            "message": self.message,
            "progress_detail": self.progress_detail,
            "result": self.result,
            "error": self.error,
            "metadata": self.metadata,
        }


class TaskManager:
    """
    Task manager.

    A thread-safe, process-local registry of task state.
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        """Return the process-wide singleton."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._tasks: Dict[str, Task] = {}
                    cls._instance._task_lock = threading.Lock()
        return cls._instance
    
    def create_task(self, task_type: str, metadata: Optional[Dict] = None) -> str:
        """
        Create a task.

        Args:
            task_type: The kind of work being tracked
            metadata: Caller-supplied metadata

        Returns:
            The new task ID
        """
        task_id = str(uuid.uuid4())
        now = datetime.now()
        
        task = Task(
            task_id=task_id,
            task_type=task_type,
            status=TaskStatus.PENDING,
            created_at=now,
            updated_at=now,
            metadata=metadata or {}
        )
        
        with self._task_lock:
            self._tasks[task_id] = task
        
        return task_id
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """Return one task, or None when it is unknown."""
        with self._task_lock:
            return self._tasks.get(task_id)
    
    def update_task(
        self,
        task_id: str,
        status: Optional[TaskStatus] = None,
        progress: Optional[int] = None,
        message: Optional[str] = None,
        result: Optional[Dict] = None,
        error: Optional[str] = None,
        progress_detail: Optional[Dict] = None
    ):
        """
        Update a task in place. Every field is optional.

        Args:
            task_id: The task to update
            status: New status
            progress: New progress percentage
            message: New status message
            result: Task result
            error: Failure reason
            progress_detail: Per-stage progress
        """
        with self._task_lock:
            task = self._tasks.get(task_id)
            if task:
                task.updated_at = datetime.now()
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
    
    def complete_task(self, task_id: str, result: Dict):
        """Mark a task completed and attach its result."""
        self.update_task(
            task_id,
            status=TaskStatus.COMPLETED,
            progress=100,
            message=t('progress.taskComplete'),
            result=result
        )
    
    def fail_task(self, task_id: str, error: str):
        """Mark a task failed and attach the reason."""
        self.update_task(
            task_id,
            status=TaskStatus.FAILED,
            message=t('progress.taskFailed'),
            error=error
        )
    
    def list_tasks(self, task_type: Optional[str] = None) -> list:
        """List tasks, newest first, optionally filtered by type."""
        with self._task_lock:
            tasks = list(self._tasks.values())
            if task_type:
                tasks = [t for t in tasks if t.task_type == task_type]
            return [t.to_dict() for t in sorted(tasks, key=lambda x: x.created_at, reverse=True)]
    
    def cleanup_old_tasks(self, max_age_hours: int = 24):
        """Drop finished tasks older than max_age_hours."""
        from datetime import timedelta
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        
        with self._task_lock:
            old_ids = [
                tid for tid, task in self._tasks.items()
                if task.created_at < cutoff and task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED]
            ]
            for tid in old_ids:
                del self._tasks[tid]

