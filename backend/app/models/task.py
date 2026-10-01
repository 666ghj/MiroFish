"""
任务状态管理
用于跟踪长时间运行的任务（图谱构建、模拟准备、报告生成等）

崩溃恢复：每次创建/更新任务时都会将其原子性地持久化到磁盘
（backend/uploads/tasks/<task_id>.json）。内存中的 `_tasks` 字典是读写
快速路径；磁盘上的文件才是权威的、能在进程重启后存活的记录。

TaskManager 是进程内单例，第一次被构造时会从磁盘恢复任务：任何仍处于
PENDING / PROCESSING 状态的任务，其执行线程只存在于上一个（已经不存在
的）进程的内存里，不可能真的还在运行，于是立即被标记为 FAILED 并给出
明确原因，而不是让轮询它的客户端永远转圈等待一个不会再更新的任务。
"""

import json
import os
import uuid
import threading
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, Any, Optional
from dataclasses import dataclass, field

from ..config import Config
from ..utils.locale import t
from ..utils.logger import get_logger
from ..utils.id_validation import validate_task_id
from ..utils.state_machine import atomic_write_json

logger = get_logger('mirofish.task')


class TaskStatus(str, Enum):
    """任务状态枚举"""
    PENDING = "pending"          # 等待中
    PROCESSING = "processing"    # 处理中
    COMPLETED = "completed"      # 已完成
    FAILED = "failed"            # 失败


NON_TERMINAL_STATUSES = (TaskStatus.PENDING, TaskStatus.PROCESSING)


@dataclass
class Task:
    """任务数据类"""
    task_id: str
    task_type: str
    status: TaskStatus
    created_at: datetime
    updated_at: datetime
    started_at: Optional[datetime] = None    # 首次进入 PROCESSING 的时间
    heartbeat_at: Optional[datetime] = None  # 最近一次被更新（证明仍在被处理）的时间
    attempt_count: int = 1                   # 第几次尝试（为将来的重试策略预留）
    timeout_seconds: Optional[int] = None    # 预期超时时间（秒），仅用于观测/诊断
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
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "heartbeat_at": self.heartbeat_at.isoformat() if self.heartbeat_at else None,
            "attempt_count": self.attempt_count,
            "timeout_seconds": self.timeout_seconds,
            "progress": self.progress,
            "message": self.message,
            "progress_detail": self.progress_detail,
            "result": self.result,
            "error": self.error,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Task':
        """从持久化的字典重建 Task（用于崩溃恢复 / 重启后加载）"""

        def _parse(value: Optional[str]) -> Optional[datetime]:
            return datetime.fromisoformat(value) if value else None

        return cls(
            task_id=data['task_id'],
            task_type=data.get('task_type', ''),
            status=TaskStatus(data.get('status', 'pending')),
            created_at=_parse(data.get('created_at')) or datetime.now(),
            updated_at=_parse(data.get('updated_at')) or datetime.now(),
            started_at=_parse(data.get('started_at')),
            heartbeat_at=_parse(data.get('heartbeat_at')),
            attempt_count=data.get('attempt_count', 1),
            timeout_seconds=data.get('timeout_seconds'),
            progress=data.get('progress', 0),
            message=data.get('message', ''),
            result=data.get('result'),
            error=data.get('error'),
            metadata=data.get('metadata', {}),
            progress_detail=data.get('progress_detail', {}),
        )


class TaskManager:
    """
    任务管理器
    线程安全的任务状态管理，附带磁盘持久化与进程重启后的崩溃恢复
    """

    # 任务持久化目录
    TASKS_DIR = os.path.join(Config.UPLOAD_FOLDER, 'tasks')

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """单例模式；首次构造时从磁盘恢复任务状态"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._tasks: Dict[str, Task] = {}
                    instance._task_lock = threading.Lock()
                    cls._instance = instance
                    instance._recover_interrupted_tasks()
        return cls._instance

    # ────────────────────────── 持久化 ──────────────────────────

    def _task_path(self, task_id: str) -> str:
        from ..utils.id_validation import safe_join

        validate_task_id(task_id)
        os.makedirs(self.TASKS_DIR, exist_ok=True)
        return safe_join(self.TASKS_DIR, f"{task_id}.json")

    def _persist(self, task: Task) -> None:
        """原子性地将任务写入磁盘。持久化失败不应中断调用方的业务逻辑，只记录日志。"""
        try:
            atomic_write_json(self._task_path(task.task_id), task.to_dict())
        except Exception:
            logger.exception(f"持久化任务状态失败: task_id={task.task_id}")

    def _load_from_disk(self, task_id: str) -> Optional[Task]:
        path = self._task_path(task_id)
        if not os.path.exists(path):
            return None
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return Task.from_dict(json.load(f))
        except Exception:
            logger.exception(f"加载任务状态失败: task_id={task_id}")
            return None

    def _recover_interrupted_tasks(self) -> None:
        """
        进程启动（本单例首次构造）时调用一次。

        磁盘上任何仍处于 PENDING / PROCESSING 状态的任务，其执行线程只存在于
        已经不存在的上一个进程里——不可能真的还在跑。直接标记为 FAILED，
        给正在轮询它的客户端一个明确的终态答案，而不是让其永远等待一个
        不会再更新的任务。
        """
        if not os.path.isdir(self.TASKS_DIR):
            return

        recovered = 0
        for filename in os.listdir(self.TASKS_DIR):
            if not filename.endswith('.json'):
                continue
            task_id = filename[:-len('.json')]
            try:
                validate_task_id(task_id)
            except Exception:
                continue

            task = self._load_from_disk(task_id)
            if task is None:
                continue

            if task.status in NON_TERMINAL_STATUSES:
                task.status = TaskStatus.FAILED
                task.error = "Task was interrupted by a server restart"
                task.message = t('progress.taskFailed')
                task.updated_at = datetime.now()
                self._persist(task)
                recovered += 1

            self._tasks[task_id] = task

        if recovered:
            logger.warning(f"进程重启恢复：{recovered} 个中断的任务已被标记为失败")

    # ────────────────────────── 公开 API ──────────────────────────
    # 与此前完全一致，调用方（graph/simulation/report 的路由）无需任何改动

    def create_task(
        self,
        task_type: str,
        metadata: Optional[Dict] = None,
        timeout_seconds: Optional[int] = None,
    ) -> str:
        """
        创建新任务

        Args:
            task_type: 任务类型
            metadata: 额外元数据
            timeout_seconds: 预期超时时间（秒），仅用于观测/诊断，不做强制终止

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
            heartbeat_at=now,
            timeout_seconds=timeout_seconds,
            metadata=metadata or {}
        )

        with self._task_lock:
            self._tasks[task_id] = task
            self._persist(task)

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
                now = datetime.now()
                task.updated_at = now
                # 任何一次更新都是任务仍在被积极处理的证据
                task.heartbeat_at = now
                if status is not None:
                    if status == TaskStatus.PROCESSING and task.started_at is None:
                        task.started_at = now
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
                self._persist(task)

    def complete_task(self, task_id: str, result: Dict):
        """标记任务完成"""
        self.update_task(
            task_id,
            status=TaskStatus.COMPLETED,
            progress=100,
            message=t('progress.taskComplete'),
            result=result
        )

    def fail_task(self, task_id: str, error: str):
        """标记任务失败"""
        self.update_task(
            task_id,
            status=TaskStatus.FAILED,
            message=t('progress.taskFailed'),
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
        """清理旧任务（内存记录与磁盘持久化文件一并删除）"""
        cutoff = datetime.now() - timedelta(hours=max_age_hours)

        with self._task_lock:
            old_ids = [
                tid for tid, task in self._tasks.items()
                if task.created_at < cutoff and task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED]
            ]
            for tid in old_ids:
                del self._tasks[tid]
                try:
                    path = self._task_path(tid)
                    if os.path.exists(path):
                        os.remove(path)
                except Exception:
                    logger.exception(f"删除持久化任务文件失败: task_id={tid}")
