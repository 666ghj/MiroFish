"""
任务状态管理
用于跟踪长时间运行的任务（如图谱构建）
"""

import logging
import os
import threading
import uuid
from datetime import datetime
from enum import Enum
from typing import Dict, Any, Optional
from dataclasses import dataclass, field

from ..config import Config
from .task_store import TaskStore


logger = logging.getLogger("mirofish.task_manager")


class TaskStatus(str, Enum):
    """任务状态枚举"""
    PENDING = "pending"          # 等待中
    PROCESSING = "processing"    # 处理中
    COMPLETED = "completed"      # 已完成
    FAILED = "failed"            # 失败
    INTERRUPTED = "interrupted"  # 服务重启后中断


@dataclass
class Task:
    """任务数据类"""
    task_id: str
    task_type: str
    status: TaskStatus
    created_at: datetime
    updated_at: datetime
    progress: int = 0              # 总进度百分比 0-100
    message: str = ""              # 状态消息
    result: Optional[Dict] = None  # 任务结果
    error: Optional[str] = None    # 错误信息
    metadata: Dict = field(default_factory=dict)  # 额外元数据
    progress_detail: Dict = field(default_factory=dict)  # 详细进度信息
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
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
    任务管理器
    线程安全的任务状态管理
    """
    
    _instance = None
    _lock = threading.Lock()
    _store = TaskStore(os.path.join(Config.UPLOAD_FOLDER, "tasks", "tasks.db"))
    
    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._tasks: Dict[str, Task] = {}
                    cls._instance._task_lock = threading.Lock()
                    cls._instance._persist_lock = threading.Lock()
                    cls._instance._load_from_store()
        return cls._instance

    @classmethod
    def configure_store(cls, path: Optional[str]) -> None:
        """配置持久化文件；测试可借此隔离数据。"""
        cls._store = TaskStore(
            path or os.path.join(Config.UPLOAD_FOLDER, "tasks", "tasks.db")
        )
        if cls._instance is not None:
            cls._instance._load_from_store()

    @classmethod
    def reload_from_store(cls) -> None:
        """从存储重新加载任务，用于进程启动与测试。"""
        cls()._load_from_store()

    def _load_from_store(self) -> None:
        loaded: Dict[str, Task] = {}
        interrupted = False
        for record in self._store.load():
            try:
                status = TaskStatus(record["status"])
                message = str(record.get("message", ""))
                if status in {TaskStatus.PENDING, TaskStatus.PROCESSING}:
                    status = TaskStatus.INTERRUPTED
                    message = "服务重启，任务已中断"
                    interrupted = True
                task = Task(
                    task_id=str(record["task_id"]),
                    task_type=str(record["task_type"]),
                    status=status,
                    created_at=datetime.fromisoformat(record["created_at"]),
                    updated_at=datetime.fromisoformat(record["updated_at"]),
                    progress=int(record.get("progress", 0)),
                    message=message,
                    result=record.get("result"),
                    error=record.get("error"),
                    metadata=record.get("metadata") if isinstance(record.get("metadata"), dict) else {},
                    progress_detail=record.get("progress_detail") if isinstance(record.get("progress_detail"), dict) else {},
                )
                loaded[task.task_id] = task
            except (KeyError, TypeError, ValueError) as error:
                logger.warning("跳过损坏的任务记录 error_type=%s", type(error).__name__)
        with self._task_lock:
            self._tasks = loaded
        if interrupted:
            self._persist()

    def _persist(self) -> None:
        with self._persist_lock:
            with self._task_lock:
                records = [task.to_dict() for task in self._tasks.values()]
            try:
                self._store.save(records)
            except Exception as error:
                logger.error("保存任务历史失败 error_type=%s", type(error).__name__)
    
    def create_task(self, task_type: str, metadata: Optional[Dict] = None) -> str:
        """
        创建新任务
        
        Args:
            task_type: 任务类型
            metadata: 额外元数据
            
        Returns:
            任务ID
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
        self._persist()
        
        return task_id
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """获取任务"""
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
        更新任务状态
        
        Args:
            task_id: 任务ID
            status: 新状态
            progress: 进度
            message: 消息
            result: 结果
            error: 错误信息
            progress_detail: 详细进度信息
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
        self._persist()
    
    def complete_task(self, task_id: str, result: Dict):
        """标记任务完成"""
        self.update_task(
            task_id,
            status=TaskStatus.COMPLETED,
            progress=100,
            message="任务完成",
            result=result
        )
    
    def fail_task(self, task_id: str, error: str):
        """标记任务失败"""
        self.update_task(
            task_id,
            status=TaskStatus.FAILED,
            message="任务失败",
            error=error
        )
    
    def list_tasks(
        self,
        task_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list:
        """列出任务"""
        with self._task_lock:
            tasks = list(self._tasks.values())
            if task_type:
                tasks = [t for t in tasks if t.task_type == task_type]
            if status:
                tasks = [t for t in tasks if t.status.value == status]
            tasks = sorted(tasks, key=lambda x: x.created_at, reverse=True)
            if limit is not None:
                tasks = tasks[:limit]
            return [t.to_dict() for t in tasks]
    
    def cleanup_old_tasks(self, max_age_hours: int = 24):
        """清理旧任务"""
        from datetime import timedelta
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        
        with self._task_lock:
            old_ids = [
                tid for tid, task in self._tasks.items()
                if task.created_at < cutoff and task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.INTERRUPTED]
            ]
            for tid in old_ids:
                del self._tasks[tid]
        self._persist()
