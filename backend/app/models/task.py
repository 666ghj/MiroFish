"""
任务状态管理
用于跟踪长时间运行的任务（如图谱构建）
"""

import uuid
import threading
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, Any, Optional
from dataclasses import dataclass, field


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
    
    内置自动清理机制：
    - 每次创建新任务时触发清理检查
    - 默认清理24小时前已完成/失败的任务
    - 最大任务数量限制为1000个
    """
    
    _instance = None
    _lock = threading.Lock()
    
    # 配置常量
    MAX_TASKS = 1000  # 最大任务数量
    CLEANUP_INTERVAL_TASKS = 50  # 每创建50个任务检查一次清理
    DEFAULT_MAX_AGE_HOURS = 24  # 默认任务保留时间（小时）
    
    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._tasks: Dict[str, Task] = {}
                    cls._instance._task_lock = threading.Lock()
                    cls._instance._tasks_created_count = 0  # 用于触发定期清理
                    cls._instance._last_cleanup_time = datetime.now()
        return cls._instance
    
    def _maybe_cleanup(self):
        """
        检查是否需要清理旧任务
        
        触发条件：
        1. 任务数量超过最大限制
        2. 每创建 CLEANUP_INTERVAL_TASKS 个任务检查一次
        3. 距离上次清理超过1小时
        """
        current_time = datetime.now()
        should_cleanup = False
        
        # 条件1：任务数量超过最大限制
        if len(self._tasks) >= self.MAX_TASKS:
            should_cleanup = True
        
        # 条件2：定期检查
        if self._tasks_created_count >= self.CLEANUP_INTERVAL_TASKS:
            self._tasks_created_count = 0
            should_cleanup = True
        
        # 条件3：距离上次清理超过1小时
        if (current_time - self._last_cleanup_time).total_seconds() > 3600:
            should_cleanup = True
        
        if should_cleanup:
            self._last_cleanup_time = current_time
            self.cleanup_old_tasks(max_age_hours=self.DEFAULT_MAX_AGE_HOURS)
    
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
            self._tasks_created_count += 1
        
        # 检查是否需要自动清理旧任务（防止内存泄漏）
        self._maybe_cleanup()
        
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
            return [t.to_dict() for t in sorted(tasks, key=lambda x: x.created_at, reverse=True)]
    
    def cleanup_old_tasks(self, max_age_hours: int = 24):
        """
        清理旧任务
        
        清理策略：
        1. 删除超过 max_age_hours 的已完成/失败任务
        2. 如果任务数量仍超过 MAX_TASKS，删除最旧的已完成/失败任务
        
        Args:
            max_age_hours: 任务保留的最大小时数
        """
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        
        with self._task_lock:
            # 第一轮：删除超时的已完成/失败任务
            old_ids = [
                tid for tid, task in self._tasks.items()
                if task.created_at < cutoff and task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED]
            ]
            for tid in old_ids:
                del self._tasks[tid]
            
            # 第二轮：如果任务数量仍超过限制，删除最旧的已完成/失败任务
            if len(self._tasks) >= self.MAX_TASKS:
                finished_tasks = [
                    (tid, task) for tid, task in self._tasks.items()
                    if task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED]
                ]
                # 按创建时间排序，最旧的在前
                finished_tasks.sort(key=lambda x: x[1].created_at)
                
                # 删除一半的已完成任务，保留较新的
                tasks_to_remove = len(finished_tasks) // 2
                for tid, _ in finished_tasks[:tasks_to_remove]:
                    del self._tasks[tid]

