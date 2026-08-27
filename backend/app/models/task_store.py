"""后台任务历史的 SQLite 持久化存储。"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any


logger = logging.getLogger("mirofish.task_store")


class TaskStore:
    """使用 SQLite 事务保存任务记录，并兼容迁移旧 JSON 文件。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        self._migrate_legacy_json()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS task_history (
                    task_id TEXT PRIMARY KEY,
                    task_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    message TEXT NOT NULL DEFAULT '',
                    result_json TEXT,
                    error TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    progress_detail_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_task_history_status ON task_history(status)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_task_history_created_at ON task_history(created_at DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_task_history_type ON task_history(task_type)"
            )

    def _migrate_legacy_json(self) -> None:
        legacy_path = self.path.with_name("tasks.json")
        if not legacy_path.exists():
            return
        with self._connect() as connection:
            if connection.execute("SELECT COUNT(*) FROM task_history").fetchone()[0] > 0:
                logger.warning("检测到旧任务 JSON，但 SQLite 已有数据，跳过迁移")
                return
        try:
            with legacy_path.open("r", encoding="utf-8") as handle:
                records = json.load(handle)
            if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
                raise ValueError("legacy task history must be a list of objects")
        except (OSError, ValueError, json.JSONDecodeError) as error:
            logger.error("迁移旧任务历史失败 error_type=%s", type(error).__name__)
            return
        if records:
            self.save(records)
        migrated_path = legacy_path.with_name("tasks.json.migrated")
        if migrated_path.exists():
            migrated_path.unlink()
        os.replace(legacy_path, migrated_path)

    def load(self) -> list[dict[str, Any]]:
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT * FROM task_history ORDER BY created_at DESC"
                ).fetchall()
        except sqlite3.Error as error:
            logger.error("读取任务历史失败 error_type=%s", type(error).__name__)
            return []
        records = []
        for row in rows:
            try:
                records.append({
                    "task_id": row["task_id"],
                    "task_type": row["task_type"],
                    "status": row["status"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "progress": row["progress"],
                    "message": row["message"],
                    "result": json.loads(row["result_json"]) if row["result_json"] else None,
                    "error": row["error"],
                    "metadata": json.loads(row["metadata_json"]),
                    "progress_detail": json.loads(row["progress_detail_json"]),
                })
            except (TypeError, json.JSONDecodeError) as error:
                logger.warning("跳过损坏的任务记录 error_type=%s", type(error).__name__)
        return records

    def save(self, records: list[dict[str, Any]]) -> None:
        task_ids = [str(record["task_id"]) for record in records]
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.executemany(
                """
                INSERT INTO task_history (
                    task_id, task_type, status, created_at, updated_at, progress,
                    message, result_json, error, metadata_json, progress_detail_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    task_type=excluded.task_type,
                    status=excluded.status,
                    created_at=excluded.created_at,
                    updated_at=excluded.updated_at,
                    progress=excluded.progress,
                    message=excluded.message,
                    result_json=excluded.result_json,
                    error=excluded.error,
                    metadata_json=excluded.metadata_json,
                    progress_detail_json=excluded.progress_detail_json
                """,
                [
                    (
                        str(record["task_id"]), str(record["task_type"]),
                        str(record["status"]), str(record["created_at"]),
                        str(record["updated_at"]), int(record.get("progress", 0)),
                        str(record.get("message", "")),
                        json.dumps(record.get("result"), ensure_ascii=False) if record.get("result") is not None else None,
                        record.get("error"),
                        json.dumps(record.get("metadata") or {}, ensure_ascii=False),
                        json.dumps(record.get("progress_detail") or {}, ensure_ascii=False),
                    )
                    for record in records
                ],
            )
            if task_ids:
                placeholders = ",".join("?" for _ in task_ids)
                connection.execute(
                    f"DELETE FROM task_history WHERE task_id NOT IN ({placeholders})",
                    task_ids,
                )
            else:
                connection.execute("DELETE FROM task_history")
