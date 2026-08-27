"""模型连接、角色草稿、版本和项目快照的 SQLite 仓库。"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from ..models.model_config import ConfigVersion, ConnectionType, ModelConnection, ModelRole, ProjectModelSnapshot
from .credential_cipher import CredentialCipher


class ModelConfigStore:
    def __init__(self, path: str | Path, cipher: CredentialCipher):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.cipher = cipher
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self):
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS model_connections (
                    connection_id TEXT PRIMARY KEY, name TEXT NOT NULL,
                    connection_type TEXT NOT NULL, base_url TEXT NOT NULL,
                    api_key_encrypted TEXT, api_key_masked TEXT,
                    is_local INTEGER NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS model_role_drafts (
                    role TEXT PRIMARY KEY, config_json TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS model_config_versions (
                    version_id TEXT PRIMARY KEY, assignments_json TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS model_config_state (
                    state_key TEXT PRIMARY KEY, state_value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS project_model_snapshots (
                    project_id TEXT PRIMARY KEY, version_id TEXT NOT NULL,
                    assignments_json TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS model_test_runs (
                    test_id TEXT PRIMARY KEY, connection_id TEXT NOT NULL,
                    test_type TEXT NOT NULL, status TEXT NOT NULL,
                    latency_ms INTEGER, error_code TEXT, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_model_connections_type ON model_connections(connection_type);
                CREATE INDEX IF NOT EXISTS idx_model_test_runs_connection ON model_test_runs(connection_id, created_at DESC);
            """)

    def create_connection(self, name, connection_type, base_url, api_key, is_local):
        connection_type = ConnectionType(connection_type)
        now = datetime.now().isoformat()
        connection_id = f"conn_{uuid.uuid4().hex[:12]}"
        encrypted = self.cipher.encrypt(api_key) if api_key else None
        masked = self.cipher.mask(api_key) if api_key else None
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO model_connections VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
                (connection_id, name, connection_type.value, base_url, encrypted, masked, int(is_local), now, now),
            )
        return self.get_connection(connection_id)

    def _public_connection(self, row):
        return ModelConnection(
            row["connection_id"], row["name"], ConnectionType(row["connection_type"]),
            row["base_url"], row["api_key_masked"], bool(row["is_local"]),
            bool(row["enabled"]), row["created_at"], row["updated_at"],
        )

    def get_connection(self, connection_id):
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM model_connections WHERE connection_id=?", (connection_id,)).fetchone()
        if row is None:
            raise KeyError(connection_id)
        return self._public_connection(row)

    def list_connections(self):
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM model_connections ORDER BY created_at").fetchall()
        return [self._public_connection(row) for row in rows]

    def get_connection_secret(self, connection_id):
        with self._connect() as connection:
            row = connection.execute("SELECT api_key_encrypted FROM model_connections WHERE connection_id=?", (connection_id,)).fetchone()
        if row is None:
            raise KeyError(connection_id)
        return self.cipher.decrypt(row[0]) if row[0] else ""

    def delete_connection(self, connection_id):
        draft = self.get_draft()
        if any(value.get("connection_id") == connection_id for value in draft.values()):
            raise ValueError("连接正在被模型角色使用")
        with self._connect() as connection:
            connection.execute("DELETE FROM model_connections WHERE connection_id=?", (connection_id,))

    def update_connection(self, connection_id, **changes):
        current = self.get_connection(connection_id)
        api_key = changes.pop("api_key", None)
        values = {
            "name": changes.get("name", current.name),
            "base_url": changes.get("base_url", current.base_url),
            "enabled": int(changes.get("enabled", current.enabled)),
            "is_local": int(changes.get("is_local", current.is_local)),
            "updated_at": datetime.now().isoformat(),
        }
        with self._connect() as connection:
            connection.execute("UPDATE model_connections SET name=:name, base_url=:base_url, enabled=:enabled, is_local=:is_local, updated_at=:updated_at WHERE connection_id=:connection_id", {**values, "connection_id": connection_id})
            if api_key:
                connection.execute("UPDATE model_connections SET api_key_encrypted=?, api_key_masked=? WHERE connection_id=?", (self.cipher.encrypt(api_key), self.cipher.mask(api_key), connection_id))
        return self.get_connection(connection_id)

    def get_state(self, key):
        with self._connect() as connection:
            row = connection.execute("SELECT state_value FROM model_config_state WHERE state_key=?", (key,)).fetchone()
        return row[0] if row else None

    def set_state(self, key, value):
        with self._connect() as connection:
            connection.execute("INSERT INTO model_config_state VALUES (?, ?) ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value", (key, value))

    def list_versions(self):
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM model_config_versions ORDER BY created_at DESC").fetchall()
        return [ConfigVersion(row["version_id"], self._decode(row["assignments_json"]), row["created_at"]) for row in rows]

    def record_test(self, connection_id, test_type, status, latency_ms, error_code=None):
        now = datetime.now().isoformat()
        with self._connect() as connection:
            connection.execute("INSERT INTO model_test_runs VALUES (?, ?, ?, ?, ?, ?, ?)", (f"test_{uuid.uuid4().hex[:12]}", connection_id, test_type, status, latency_ms, error_code, now))

    def latest_test(self, connection_id):
        with self._connect() as connection:
            row = connection.execute("SELECT test_type,status,latency_ms,error_code,created_at FROM model_test_runs WHERE connection_id=? ORDER BY created_at DESC LIMIT 1", (connection_id,)).fetchone()
        return dict(row) if row else None

    def save_draft(self, assignments):
        now = datetime.now().isoformat()
        with self._connect() as connection:
            for role, config in assignments.items():
                role = ModelRole(role)
                connection.execute(
                    "INSERT INTO model_role_drafts VALUES (?, ?, ?) ON CONFLICT(role) DO UPDATE SET config_json=excluded.config_json, updated_at=excluded.updated_at",
                    (role.value, json.dumps(config, ensure_ascii=False), now),
                )

    def get_draft(self):
        with self._connect() as connection:
            rows = connection.execute("SELECT role, config_json FROM model_role_drafts").fetchall()
        return {ModelRole(row["role"]): json.loads(row["config_json"]) for row in rows}

    @staticmethod
    def _encode(assignments):
        return json.dumps({ModelRole(role).value: config for role, config in assignments.items()}, ensure_ascii=False)

    @staticmethod
    def _decode(value):
        return {ModelRole(role): config for role, config in json.loads(value).items()}

    def apply_draft(self):
        assignments = self.get_draft()
        if set(assignments) != set(ModelRole):
            raise ValueError("三个模型角色必须全部配置")
        version_id = f"modelcfg_{uuid.uuid4().hex[:12]}"
        now = datetime.now().isoformat()
        encoded = self._encode(assignments)
        with self._connect() as connection:
            connection.execute("INSERT INTO model_config_versions VALUES (?, ?, ?)", (version_id, encoded, now))
            connection.execute("INSERT INTO model_config_state VALUES ('active_version', ?) ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value", (version_id,))
        return ConfigVersion(version_id, assignments, now)

    def get_active_version(self):
        with self._connect() as connection:
            row = connection.execute("SELECT state_value FROM model_config_state WHERE state_key='active_version'").fetchone()
            if row is None:
                return None
            version = connection.execute("SELECT * FROM model_config_versions WHERE version_id=?", (row[0],)).fetchone()
        return ConfigVersion(version["version_id"], self._decode(version["assignments_json"]), version["created_at"])

    def get_or_create_project_snapshot(self, project_id):
        existing = self.get_project_snapshot(project_id)
        if existing:
            return existing
        active = self.get_active_version()
        if active is None:
            raise ValueError("尚未应用模型配置")
        now = datetime.now().isoformat()
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO project_model_snapshots VALUES (?, ?, ?, ?)",
                (project_id, active.version_id, self._encode(active.assignments), now),
            )
        return self.get_project_snapshot(project_id)

    def get_project_snapshot(self, project_id):
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM project_model_snapshots WHERE project_id=?", (project_id,)).fetchone()
        if row is None:
            return None
        return ProjectModelSnapshot(row["project_id"], row["version_id"], self._decode(row["assignments_json"]), row["created_at"])
