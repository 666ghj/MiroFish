"""按模型职责解析当前版本或项目快照。"""

from pathlib import Path

from ..config import Config
from ..models.model_config import ModelRole
from .credential_cipher import CredentialCipher
from .model_config_store import ModelConfigStore


class ModelRouter:
    def __init__(self, store=None):
        upload_folder = getattr(Config, "UPLOAD_FOLDER", None)
        if store is not None:
            self.store = store
        elif upload_folder:
            root = Path(upload_folder) / "model-config"
            self.store = ModelConfigStore(root / "models.db", CredentialCipher(root / "master.key"))
        else:
            self.store = None

    def resolve(self, role: ModelRole, project_id=None):
        source = None
        if self.store is not None:
            source = self.store.get_or_create_project_snapshot(project_id) if project_id else self.store.get_active_version()
        if source and role in source.assignments:
            assignment = dict(source.assignments[role])
            connection = self.store.get_connection(assignment["connection_id"])
            assignment.update({"api_key": self.store.get_connection_secret(connection.connection_id), "base_url": connection.base_url, "connection_type": connection.connection_type.value})
            return assignment
        if role == ModelRole.HIGH_THROUGHPUT:
            env = __import__('os').environ
            return {"api_key": env.get('GRAPHITI_LLM_API_KEY') or env.get('OPENAI_API_KEY') or getattr(Config, 'LLM_API_KEY', None), "base_url": env.get('GRAPHITI_LLM_BASE_URL') or env.get('OPENAI_BASE_URL') or getattr(Config, 'LLM_BASE_URL', None), "model": env.get('GRAPHITI_LLM_MODEL') or env.get('LLM_MODEL_NAME') or getattr(Config, 'LLM_MODEL_NAME', None)}
        if role == ModelRole.EMBEDDING:
            env = __import__('os').environ
            return {"api_key": env.get('GRAPHITI_EMBEDDING_API_KEY') or env.get('OPENAI_API_KEY') or getattr(Config, 'LLM_API_KEY', None), "base_url": env.get('GRAPHITI_EMBEDDING_BASE_URL') or env.get('OPENAI_BASE_URL') or getattr(Config, 'LLM_BASE_URL', None), "model": env.get('GRAPHITI_EMBEDDING_MODEL')}
        return {"api_key": Config.LLM_API_KEY, "base_url": Config.LLM_BASE_URL, "model": Config.LLM_MODEL_NAME}

    def build_simulation_environment(self, project_id=None):
        config = self.resolve(ModelRole.HIGH_THROUGHPUT, project_id)
        return {"LLM_API_KEY": config.get("api_key", ""), "LLM_BASE_URL": config.get("base_url", ""), "LLM_MODEL_NAME": config.get("model", "")}
