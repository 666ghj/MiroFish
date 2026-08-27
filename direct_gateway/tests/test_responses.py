import json

import pytest

from app.messages import build_responses_payload
from app.schema import normalize_output_schema
from app.responses_client import parse_responses_sse


def test_build_payload_preserves_conversation_and_separates_instructions():
    request = {"messages": [{"role": "system", "content": "S"}, {"role": "developer", "content": "D"}, {"role": "user", "content": "U"}, {"role": "assistant", "content": "A"}], "response_format": {"type": "text"}}
    payload = build_responses_payload(request, "gpt-test")
    assert payload["instructions"] == "S\n\nD"
    assert [item["role"] for item in payload["input"]] == ["user", "assistant"]
    assert payload["store"] is False and payload["stream"] is True
    assert "temperature" not in payload


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
