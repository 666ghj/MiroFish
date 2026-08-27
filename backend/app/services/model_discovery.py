"""统一发现并按职责过滤 Provider 支持的模型。"""

from openai import OpenAI

from ..models.model_config import ModelRole


class ModelDiscovery:
    def __init__(self, client_factory=OpenAI):
        self.client_factory = client_factory

    @staticmethod
    def _capability(model_id):
        value = model_id.lower()
        return "embedding" if "embed" in value or "embedding" in value else "chat"

    def list_models(self, connection, api_key, role):
        role = ModelRole(role)
        client = self.client_factory(api_key=api_key or "local", base_url=connection.base_url, timeout=20)
        response = client.models.list()
        expected = "embedding" if role == ModelRole.EMBEDDING else "chat"
        values = []
        for model in response.data:
            model_id = str(model.id)
            capability = self._capability(model_id)
            if capability != expected:
                continue
            if expected == "embedding":
                try:
                    probe = client.embeddings.create(model=model_id, input=["model capability probe"])
                    if not probe.data or not probe.data[0].embedding:
                        continue
                    response_model = getattr(probe, "model", None)
                    if response_model and response_model != model_id:
                        continue
                except Exception:
                    continue
            values.append({"id": model_id, "capability": capability, "available": True, "local": bool(connection.is_local)})
        return sorted(values, key=lambda item: item["id"].lower())
