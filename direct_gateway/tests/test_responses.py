import json

import pytest
import httpx
from types import SimpleNamespace

from app.messages import build_responses_payload
from app.schema import normalize_output_schema
from app.responses_client import ResponsesClient, parse_responses_sse


def test_build_payload_preserves_conversation_and_separates_instructions():
    request = {"messages": [{"role": "system", "content": "S"}, {"role": "developer", "content": "D"}, {"role": "user", "content": "U"}, {"role": "assistant", "content": "A"}], "response_format": {"type": "text"}}
    payload = build_responses_payload(request, "gpt-test")
    assert payload["instructions"] == "S\n\nD"
    assert [item["role"] for item in payload["input"]] == ["user", "assistant"]
    assert payload["store"] is False and payload["stream"] is True
    assert "temperature" not in payload


def test_json_object_uses_instruction_instead_of_unsupported_format():
    payload = build_responses_payload(
        {"messages": [{"role": "user", "content": "Return data"}], "response_format": {"type": "json_object"}},
        "gpt-test",
    )
    assert "text" not in payload
    assert "valid JSON object" in payload["instructions"]


def test_schema_is_strict_without_mutating_input():
    schema = {"type": "object", "properties": {"name": {"type": "string", "default": "x"}, "nested": {"type": "object", "properties": {"n": {"type": "integer"}}}}}
    result = normalize_output_schema(schema)
    assert result["additionalProperties"] is False
    assert result["required"] == ["name", "nested"]
    assert result["properties"]["nested"]["required"] == ["n"]
    assert "default" not in result["properties"]["name"]
    assert "default" in schema["properties"]["name"]


def test_sse_collects_text_and_usage_but_not_reasoning():
    lines = [": ping", "data: " + json.dumps({"type": "response.reasoning_text.delta", "delta": "secret"}), "data: " + json.dumps({"type": "response.output_text.delta", "delta": "hel"}), "data: " + json.dumps({"type": "response.output_text.delta", "delta": "lo"}), "data: " + json.dumps({"type": "response.completed", "response": {"model": "gpt", "usage": {"input_tokens": 1}}})]
    result = parse_responses_sse(lines)
    assert result.content == "hello" and result.model == "gpt"
    assert "secret" not in result.content


def test_sse_rejects_failed_or_incomplete_response():
    with pytest.raises(RuntimeError, match="provider_failed"):
        parse_responses_sse(["data: " + json.dumps({"type": "response.failed"})])
    with pytest.raises(RuntimeError, match="incomplete"):
        parse_responses_sse(["data: " + json.dumps({"type": "response.output_text.delta", "delta": "x"})])


def test_client_refreshes_once_after_401():
    calls = []
    completed = "\n".join([
        "data: " + json.dumps({"type": "response.output_text.delta", "delta": "OK"}),
        "data: " + json.dumps({"type": "response.completed", "response": {"model": "gpt", "usage": {}}}),
    ])
    def handler(request):
        calls.append(request.headers["Authorization"])
        if len(calls) == 1:
            return httpx.Response(401, json={"error": "expired"})
        return httpx.Response(200, text=completed)
    class Manager:
        def __init__(self): self.refreshes = 0
        def fresh(self): return SimpleNamespace(access_token="new" if self.refreshes else "old"), {"account_id": "acct", "residency": None}
        def force_refresh(self): self.refreshes += 1
    manager = Manager()
    client = ResponsesClient(endpoint="https://example.test/responses", model="gpt", token_manager=manager, http=httpx.Client(transport=httpx.MockTransport(handler)))
    result = client.complete({"messages": [{"role": "user", "content": "hi"}]})
    assert result.content == "OK"
    assert manager.refreshes == 1
    assert len(calls) == 2
