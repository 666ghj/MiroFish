"""
任务状态管理
用于跟踪长时间运行的任务（如图谱构建）
"""

import json
import os
import uuid
import threading
from datetime import datetime
from enum import Enum
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field

from ..config import Config


class TaskStatus(str, Enum):
    """任务状态枚举"""
    PENDING = "pending"          # 等待中
    PROCESSING = "processing"    # 处理中
    COMPLETED = "completed"      # 已完成
    FAILED = "failed"            # 失败


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
    history: List[Dict[str, Any]] = field(default_factory=list)  # 进度历史（用于断点续跑/排障）
    
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
            "history": self.history,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Task":
        def parse_dt(value: Any) -> datetime:
            if isinstance(value, datetime):
                return value
            if isinstance(value, str) and value:
                try:
                    return datetime.fromisoformat(value)
                except Exception:
                    pass
            return datetime.now()
        
        status = data.get("status", TaskStatus.PENDING)
        if isinstance(status, str):
            status = TaskStatus(status)
        
        return cls(
            task_id=data.get("task_id", ""),
            task_type=data.get("task_type", ""),
            status=status,
            created_at=parse_dt(data.get("created_at")),
            updated_at=parse_dt(data.get("updated_at")),
            progress=int(data.get("progress", 0) or 0),
            message=data.get("message", "") or "",
            result=data.get("result"),
            error=data.get("error"),
            metadata=data.get("metadata") or {},
            progress_detail=data.get("progress_detail") or {},
            history=data.get("history") or [],
        )


class TaskManager:
    """
    任务管理器
    线程安全的任务状态管理
    """
    
    TASKS_DIR = os.path.join(Config.UPLOAD_FOLDER, "tasks")
    MAX_HISTORY_EVENTS = 200
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._tasks: Dict[str, Task] = {}
                    cls._instance._task_lock = threading.Lock()
                    cls._instance._ensure_tasks_dir()
                    cls._instance._load_tasks_from_disk()
                    cls._instance._mark_processing_tasks_stale()
        return cls._instance
    
    def _ensure_tasks_dir(self):
        os.makedirs(self.TASKS_DIR, exist_ok=True)
    
    def _task_path(self, task_id: str) -> str:
        return os.path.join(self.TASKS_DIR, f"{task_id}.json")
    
    def _atomic_write_json(self, path: str, data: Dict[str, Any]):
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    
    def _save_task_to_disk(self, task: Task):
        self._ensure_tasks_dir()
        self._atomic_write_json(self._task_path(task.task_id), task.to_dict())
    
    def _load_tasks_from_disk(self):
        self._ensure_tasks_dir()
        try:
            for filename in os.listdir(self.TASKS_DIR):
                if not filename.endswith(".json"):
                    continue
                path = os.path.join(self.TASKS_DIR, filename)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    task = Task.from_dict(data)
                    if task.task_id:
                        self._tasks[task.task_id] = task
                except Exception:
                    # 单个任务文件损坏不影响整体启动
                    continue
        except FileNotFoundError:
            return
    
    def _append_history(self, task: Task):
        event = {
            "timestamp": datetime.now().isoformat(),
            "status": task.status.value if isinstance(task.status, TaskStatus) else str(task.status),
            "progress": task.progress,
            "message": task.message,
        }
        
        # 去重（避免大量重复事件）
        if task.history:
            last = task.history[-1]
            if (
                last.get("status") == event["status"]
                and last.get("progress") == event["progress"]
                and last.get("message") == event["message"]
            ):
                return
        
        task.history.append(event)
        if len(task.history) > self.MAX_HISTORY_EVENTS:
            task.history = task.history[-self.MAX_HISTORY_EVENTS :]
    
    def _mark_processing_tasks_stale(self):
        """
        后端重启后，后台线程会中断：将遗留的 processing 任务标记为失败，避免前端永久等待。
        """
        now = datetime.now()
        changed = False
        
        for task in self._tasks.values():
            if task.status == TaskStatus.PROCESSING:
                task.status = TaskStatus.FAILED
                task.updated_at = now
                if not task.message:
                    task.message = "任务在服务重启后中断"
                if not task.error:
                    task.error = "stale_after_restart"
                self._append_history(task)
                try:
                    self._save_task_to_disk(task)
                except Exception:
                    pass
                changed = True
        
        return changed
    
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
            self._append_history(task)
            self._save_task_to_disk(task)
        
        return task_id
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """获取任务"""
        with self._task_lock:
            task = self._tasks.get(task_id)
            if task:
                return task
        
        # 兜底：内存里没有则尝试从磁盘加载（允许跨进程/重启查询）
        path = self._task_path(task_id)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                task = Task.from_dict(data)
                with self._task_lock:
                    self._tasks[task_id] = task
                return task
            except Exception:
                return None
        
        return None
    
    def update_task(
        self,
        task_id: str,
        status: Optional[TaskStatus] = None,
        progress: Optional[int] = None,
        message: Optional[str] = None,
        result: Optional[Dict] = None,
        error: Optional[str] = None,
        progress_detail: Optional[Dict] = None,
        metadata: Optional[Dict] = None
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
                if metadata is not None:
                    task.metadata.update(metadata)
                
                self._append_history(task)
                try:
                    self._save_task_to_disk(task)
                except Exception:
                    pass
    
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
    
    def list_tasks(self, task_type: Optional[str] = None) -> list:
        """列出任务"""
        with self._task_lock:
            tasks = list(self._tasks.values())
            if task_type:
                tasks = [t for t in tasks if t.task_type == task_type]
            return sorted(tasks, key=lambda x: x.created_at, reverse=True)
    
    def cleanup_old_tasks(self, max_age_hours: int = 24):
        """清理旧任务"""
        from datetime import timedelta
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        
        with self._task_lock:
            old_ids = [
                tid for tid, task in self._tasks.items()
                if task.created_at < cutoff and task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED]
            ]
            for tid in old_ids:
                del self._tasks[tid]
                try:
                    os.remove(self._task_path(tid))
                except FileNotFoundError:
                    pass
                except Exception:
                    pass
