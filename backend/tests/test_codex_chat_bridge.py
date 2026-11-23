import json
from types import SimpleNamespace

import pytest

from scripts import codex_chat_bridge as bridge


def test_rejects_requests_that_facade_cannot_represent():
    messages = [{"role": "user", "content": "Hola"}]
    with pytest.raises(ValueError, match="Streaming"):
        bridge.validate_request({"messages": messages, "stream": True})
    with pytest.raises(ValueError, match="Only function tools"):
        bridge.validate_request({"messages": messages, "tools": [{"type": "function"}]})
    with pytest.raises(ValueError, match="Only text"):
        bridge.validate_request({"messages": [{"role": "user", "content": [{"type": "text"}]}]})


def test_json_mode_prompt_keeps_conversation_and_requests_object():
    request = bridge.validate_request(
        {
            "model": "codex-bridge",
            "messages": [{"role": "system", "content": "Responde en español"}, {"role": "user", "content": "¿Qué pasó?"}],
            "response_format": {"type": "json_object"},
        }
    )
    prompt = bridge.build_prompt(request)
    assert "objeto JSON válido" in prompt
    assert "Responde en español" in prompt
    assert "¿Qué pasó?" in prompt


def test_codex_invocation_uses_saved_login_without_api_keys(monkeypatch):
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["env"] = kwargs["env"]
        seen["input"] = kwargs["input"]
        return SimpleNamespace(returncode=0, stdout="respuesta\n", stderr="")

    monkeypatch.setenv("OPENAI_API_KEY", "other-provider-key")
    monkeypatch.setenv("CODEX_API_KEY", "other-api-key")
    monkeypatch.setenv("ZEP_API_KEY", "zep-key")
    monkeypatch.setenv("MIROFISH_CODEX_BRIDGE_TOKEN", "bridge-token")
    monkeypatch.setattr(bridge.shutil, "which", lambda _: "codex")
    monkeypatch.setattr(bridge.subprocess, "run", fake_run)

    assert bridge.run_codex("Prueba", timeout=30) == "respuesta"
    assert "--ephemeral" in seen["command"]
    assert "--ignore-user-config" in seen["command"]
    assert ["--sandbox", "read-only"] == seen["command"][
        seen["command"].index("--sandbox") : seen["command"].index("--sandbox") + 2
    ]
    assert "OPENAI_API_KEY" not in seen["env"]
    assert "CODEX_API_KEY" not in seen["env"]
    assert "ZEP_API_KEY" not in seen["env"]
    assert "MIROFISH_CODEX_BRIDGE_TOKEN" not in seen["env"]
    assert seen["input"] == "Prueba"


def test_tool_request_passes_output_schema_to_codex(monkeypatch):
    seen = {}

    def fake_run(command, **kwargs):
        schema_path = command[command.index("--output-schema") + 1]
        with open(schema_path, encoding="utf-8") as schema_file:
            seen["schema"] = json.load(schema_file)
        return SimpleNamespace(returncode=0, stdout='{"content":"","tool_calls":[]}', stderr="")

    monkeypatch.setattr(bridge.shutil, "which", lambda _: "codex")
    monkeypatch.setattr(bridge.subprocess, "run", fake_run)
    bridge.run_codex("Prueba", timeout=30, model="gpt-6-luna", output_schema=bridge.TOOL_OUTPUT_SCHEMA)
    assert seen["schema"]["required"] == ["content", "tool_calls"]


def test_login_status_accepts_chatgpt_status_on_stderr(monkeypatch):
    def fake_run(command, **kwargs):
        assert command == ["codex", "login", "status"]
        return SimpleNamespace(
            returncode=0, stdout="", stderr="Logged in using ChatGPT\n"
        )

    monkeypatch.setattr(bridge.subprocess, "run", fake_run)
    bridge.verify_chatgpt_login("codex")


def test_completion_has_openai_chat_shape():
    result = bridge.completion_payload("Hola", "codex-bridge")
    assert result["object"] == "chat.completion"
    assert result["choices"][0]["message"] == {"role": "assistant", "content": "Hola"}
    assert result["choices"][0]["finish_reason"] == "stop"


def test_tool_answer_becomes_openai_function_call():
    tools = [{
        "type": "function",
        "function": {
            "name": "create_post",
            "description": "Publish a post",
            "parameters": {"type": "object", "properties": {"content": {"type": "string"}}},
        },
    }]
    request = bridge.validate_request({
        "model": "codex-bridge",
        "messages": [{"role": "user", "content": "Publica un aviso"}],
        "tools": tools,
    })
    assert "create_post" in bridge.build_prompt(request)
    answer = '{"content":"","tool_calls":[{"name":"create_post","arguments_json":"{\\"content\\":\\"Hola\\"}"}]}'
    payload = bridge.completion_payload(answer, "codex-bridge", tools)
    choice = payload["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["content"] is None
    call = choice["message"]["tool_calls"][0]
    assert call["function"]["name"] == "create_post"
    assert call["function"]["arguments"] == '{"content": "Hola"}'


def test_tool_answer_cannot_select_unavailable_function():
    tools = [{"type": "function", "function": {"name": "create_post", "parameters": {}}}]
    answer = '{"content":"","tool_calls":[{"name":"delete_file","arguments_json":"{}"}]}'
    with pytest.raises(RuntimeError, match="unavailable function"):
        bridge.completion_payload(answer, "codex-bridge", tools)
