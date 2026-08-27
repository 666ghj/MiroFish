"""模型连接的最小安全探测。"""

import time
from openai import OpenAI
from ..models.model_config import ConnectionType, ModelRole


class ModelConnectionTester:
    def __init__(self, store): self.store = store

    def test(self, connection_id):
        connection = self.store.get_connection(connection_id)
        client = OpenAI(api_key=self.store.get_connection_secret(connection_id) or "local", base_url=connection.base_url, timeout=20)
        started = time.monotonic()
        test_type = "embedding" if connection.connection_type == ConnectionType.EMBEDDING else "structured"
        try:
            draft = self.store.get_draft()
            preferred_roles = {
                ConnectionType.EMBEDDING: (ModelRole.EMBEDDING,),
                ConnectionType.LOCAL_OPENAI: (ModelRole.HIGH_THROUGHPUT, ModelRole.HIGH_CAPABILITY),
                ConnectionType.OPENAI_COMPATIBLE: (ModelRole.HIGH_CAPABILITY, ModelRole.HIGH_THROUGHPUT),
                ConnectionType.CODEX_GATEWAY: (ModelRole.HIGH_CAPABILITY,),
                ConnectionType.DIRECT_OAUTH_GATEWAY: (ModelRole.HIGH_CAPABILITY,),
            }[connection.connection_type]
            assignment = next(
                (draft[role] for role in preferred_roles if draft.get(role, {}).get("connection_id") == connection_id),
                None,
            )
            gateway_types = {ConnectionType.CODEX_GATEWAY, ConnectionType.DIRECT_OAUTH_GATEWAY}
            if connection.connection_type in gateway_types and not assignment:
                assignment = {"model": "gateway-default"}
            if not assignment or not assignment.get("model"):
                raise ValueError("请先在角色配置中选择模型后再测试")
            if test_type == "embedding":
                response = client.embeddings.create(model=assignment["model"], input=["MiroFish connection test"])
                if not response.data or not response.data[0].embedding:
                    raise RuntimeError("empty_embedding")
            else:
                response = client.chat.completions.create(model=assignment["model"], messages=[{"role": "user", "content": "Return OK."}], max_tokens=8)
                if not response.choices:
                    raise RuntimeError("empty_response")
            latency = int((time.monotonic() - started) * 1000)
            self.store.record_test(connection_id, test_type, "passed", latency)
            return {"status": "passed", "test_type": test_type, "latency_ms": latency}
        except Exception as error:
            latency = int((time.monotonic() - started) * 1000)
            code = "connection_failed" if not isinstance(error, ValueError) else "model_required"
            self.store.record_test(connection_id, test_type, "failed", latency, code)
            return {"status": "failed", "test_type": test_type, "latency_ms": latency, "error_code": code}
