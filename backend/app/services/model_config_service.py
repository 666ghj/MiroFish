"""模型配置的迁移、校验和应用服务。"""

import os
from pathlib import Path
from urllib.parse import urlparse

from ..config import Config
from ..models.model_config import ConnectionType, ModelRole
from .credential_cipher import CredentialCipher
from .model_config_store import ModelConfigStore


class ModelConfigService:
    def __init__(self, store=None, environment=None):
        root = Path(Config.UPLOAD_FOLDER) / "model-config"
        self.store = store or ModelConfigStore(root / "models.db", CredentialCipher(root / "master.key"))
        self.environment = environment or os.environ

    def initialize_from_environment(self):
        if self.store.get_state("environment_imported") == "1":
            return
        specs = [
            (ModelRole.HIGH_CAPABILITY, "高能力模型", ConnectionType.OPENAI_COMPATIBLE, "LLM"),
            (ModelRole.HIGH_THROUGHPUT, "高吞吐模型", ConnectionType.LOCAL_OPENAI, "GRAPHITI_LLM"),
            (ModelRole.EMBEDDING, "Embedding", ConnectionType.EMBEDDING, "GRAPHITI_EMBEDDING"),
        ]
        assignments = {}
        for role, name, connection_type, prefix in specs:
            base_url = self.environment.get(f"{prefix}_BASE_URL") or self.environment.get("OPENAI_BASE_URL", "")
            model = self.environment.get(f"{prefix}_MODEL") or self.environment.get(f"{prefix}_MODEL_NAME") or self.environment.get("LLM_MODEL_NAME", "")
            api_key = self.environment.get(f"{prefix}_API_KEY") or self.environment.get("OPENAI_API_KEY", "")
            connection = self.store.create_connection(name, connection_type, base_url, api_key, role != ModelRole.HIGH_CAPABILITY)
            assignments[role] = {"connection_id": connection.connection_id, "model": model}
        self.store.save_draft(assignments)
        self.store.set_state("environment_imported", "1")

    def validate_draft(self, assignments):
        normalized = {ModelRole(role): config for role, config in assignments.items()}
        if set(normalized) != set(ModelRole):
            raise ValueError("三个模型角色必须全部配置")
        for role, config in normalized.items():
            connection = self.store.get_connection(config.get("connection_id"))
            if not connection.enabled or not config.get("model"):
                raise ValueError(f"模型角色配置不完整: {role.value}")
            parsed = urlparse(connection.base_url)
            if parsed.scheme not in {"http", "https"}:
                raise ValueError("Base URL 必须使用 http 或 https")
            if role == ModelRole.EMBEDDING and connection.connection_type != ConnectionType.EMBEDDING:
                raise ValueError("Embedding 角色必须使用 Embedding 连接")
        return normalized

    def save_draft(self, assignments):
        normalized = self.validate_draft(assignments)
        self.store.save_draft(normalized)
        return normalized

    def apply_draft(self):
        assignments = self.validate_draft(self.store.get_draft())
        untested = []
        for role, config in assignments.items():
            latest = self.store.latest_test(config["connection_id"])
            if not latest or latest["status"] != "passed":
                untested.append(role.value)
        if untested:
            raise ValueError("以下模型角色尚未通过连接测试: " + ", ".join(untested))
        return self.store.apply_draft()
