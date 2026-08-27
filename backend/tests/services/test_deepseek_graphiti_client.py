import asyncio
import importlib.util
import sys
import types
from pathlib import Path


def test_response_model_is_converted_to_json_object_prompt(monkeypatch):
    captured = {}

    class FakeOpenAIGenericClient:
        async def _generate_response(
            self,
            messages,
            response_model=None,
            max_tokens=8192,
            model_size=None,
        ):
            captured["messages"] = messages
            captured["response_model"] = response_model
            return {"name": "星河科技"}

    openai_module = types.ModuleType("graphiti_core.llm_client.openai_generic_client")
    openai_module.OpenAIGenericClient = FakeOpenAIGenericClient
    monkeypatch.setitem(
        sys.modules, "graphiti_core.llm_client.openai_generic_client", openai_module
    )

    class FakeResponseModel:
        @classmethod
        def model_json_schema(cls):
            return {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            }

    class FakeMessage:
        def __init__(self, role, content):
            self.role = role
            self.content = content

    module_path = (
        Path(__file__).resolve().parents[2]
        / "app"
        / "services"
        / "deepseek_graphiti_client.py"
    )
    assert module_path.exists(), "DeepSeek Graphiti compatibility client is missing"

    spec = importlib.util.spec_from_file_location(
        "app.services.deepseek_graphiti_client", module_path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    client = module.DeepSeekGraphitiClient()
    messages = [FakeMessage("system", "Extract entities as JSON")]

    result = asyncio.run(
        client._generate_response(messages, response_model=FakeResponseModel)
    )

    assert result == {"name": "星河科技"}
    assert captured["response_model"] is None
    assert '"required":["name"]' in captured["messages"][-1].content
    assert messages[-1].content == "Extract entities as JSON"
