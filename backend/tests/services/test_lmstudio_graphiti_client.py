import asyncio
from types import SimpleNamespace

from app.services.lmstudio_graphiti_client import LMStudioGraphitiClient


class Completions:
    async def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok":true}'))])


def test_lmstudio_structured_requests_disable_reasoning():
    completions = Completions()
    client = LMStudioGraphitiClient.__new__(LMStudioGraphitiClient)
    client.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    client.model = "qwen"
    client.temperature = 0
    client.max_tokens = 1024
    client._clean_input = lambda value: value
    messages = [SimpleNamespace(role="user", content="return json")]
    result = asyncio.run(client._generate_response(messages))
    assert result == {"ok": True}
    assert completions.kwargs["reasoning_effort"] == "none"
