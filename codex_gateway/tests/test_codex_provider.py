import json
import time
from types import SimpleNamespace

from app.codex_provider import (
    CodexProvider,
    CodexExecutionError,
    CodexTurnError,
    InvalidStructuredResponseError,
    QueueFullError,
)


class FakeThread:
    def __init__(self, final_response):
        self.final_response = final_response
        self.run_calls = []

    def run(self, prompt, **kwargs):
        self.run_calls.append((prompt, kwargs))
        return SimpleNamespace(
            id="turn-1",
            status="completed",
            error=None,
            final_response=self.final_response,
            usage=None,
        )


class FakeCodex:
    def __init__(self, final_response):
        self.thread = FakeThread(final_response)
        self.thread_calls = []

    def thread_start(self, **kwargs):
        self.thread_calls.append(kwargs)
        return self.thread


def test_text_completion_uses_ephemeral_read_only_thread():
    codex = FakeCodex("answer")
    provider = CodexProvider(
        codex=codex,
        model="gpt-5.6-terra",
        approval_mode="deny-all-sentinel",
        sandbox="read-only-sentinel",
    )

    result = provider.complete(
        {
            "messages": [{"role": "user", "content": "Question"}],
            "response_format": {"type": "text"},
        }
    )

    assert result.content == "answer"
    assert result.model == "gpt-5.6-terra"
    assert codex.thread_calls[0]["ephemeral"] is True
    assert codex.thread_calls[0]["approval_mode"] == "deny-all-sentinel"
    assert codex.thread_calls[0]["sandbox"] == "read-only-sentinel"
    assert codex.thread.run_calls[0][1]["sandbox"] == "read-only-sentinel"
    assert codex.thread.run_calls[0][1]["output_schema"] is None


def test_json_schema_is_forwarded_to_codex_output_schema():
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }
    codex = FakeCodex('{"name":"Labubu"}')
    provider = CodexProvider(
        codex=codex,
        model="gpt-5.6-terra",
        approval_mode="deny-all-sentinel",
        sandbox="read-only-sentinel",
    )

    result = provider.complete(
        {
            "messages": [{"role": "user", "content": "Return JSON"}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "result", "schema": schema},
            },
        }
    )

    assert json.loads(result.content) == {"name": "Labubu"}
    assert codex.thread.run_calls[0][1]["output_schema"] == {
        **schema,
        "additionalProperties": False,
    }
    assert "additionalProperties" not in schema


def test_nested_json_schema_objects_are_closed_recursively():
    schema = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {"$ref": "#/$defs/Item"},
            }
        },
        "required": ["items"],
        "$defs": {
            "Item": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "default": None,
                    },
                },
                "required": ["name"],
            }
        },
    }
    codex = FakeCodex('{"items":[]}')
    provider = CodexProvider(
        codex=codex,
        model="gpt-5.6-terra",
        approval_mode="deny-all-sentinel",
        sandbox="read-only-sentinel",
    )

    provider.complete(
        {
            "messages": [{"role": "user", "content": "Return JSON"}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "result", "schema": schema},
            },
        }
    )

    normalized = codex.thread.run_calls[0][1]["output_schema"]
    assert normalized["additionalProperties"] is False
    assert normalized["$defs"]["Item"]["additionalProperties"] is False
    assert normalized["$defs"]["Item"]["required"] == ["name", "description"]
    assert "default" not in normalized["$defs"]["Item"]["properties"]["description"]
    assert "additionalProperties" not in schema["$defs"]["Item"]
    assert schema["$defs"]["Item"]["properties"]["description"]["default"] is None


def test_json_object_requires_valid_json():
    provider = CodexProvider(
        codex=FakeCodex("not-json"),
        model="gpt-5.6-terra",
        approval_mode="deny-all-sentinel",
        sandbox="read-only-sentinel",
    )

    try:
        provider.complete(
            {
                "messages": [{"role": "user", "content": "Return JSON"}],
                "response_format": {"type": "json_object"},
            }
        )
    except InvalidStructuredResponseError as error:
        assert "JSON" in str(error)
    else:
        raise AssertionError("invalid JSON should fail")


def test_queue_full_rejects_request_without_starting_thread():
    codex = FakeCodex("answer")
    provider = CodexProvider(
        codex=codex,
        model="gpt-5.6-terra",
        approval_mode="deny-all-sentinel",
        sandbox="read-only-sentinel",
        max_concurrency=1,
        queue_size=0,
    )
    provider._slots.acquire()

    try:
        provider.complete(
            {"messages": [{"role": "user", "content": "Question"}]}
        )
    except QueueFullError:
        pass
    else:
        raise AssertionError("a full queue should reject the request")
    finally:
        provider._slots.release()

    assert codex.thread_calls == []


def test_failed_turn_raises_provider_error_for_fallback():
    codex = FakeCodex("unused")
    codex.thread.run = lambda prompt, **kwargs: SimpleNamespace(
        id="turn-failed",
        status="failed",
        error=SimpleNamespace(message="provider unavailable"),
        final_response=None,
        usage=None,
    )
    provider = CodexProvider(
        codex=codex,
        model="gpt-5.6-terra",
        approval_mode="deny-all-sentinel",
        sandbox="read-only-sentinel",
    )

    try:
        provider.complete({"messages": [{"role": "user", "content": "hi"}]})
    except CodexTurnError:
        pass
    else:
        raise AssertionError("failed Codex turn should raise CodexTurnError")


def test_timeout_interrupts_active_codex_turn():
    interrupted = []

    class SlowHandle:
        def run(self):
            time.sleep(0.1)
            return SimpleNamespace(
                id="late",
                status="completed",
                final_response="late",
                usage=None,
            )

        def interrupt(self):
            interrupted.append(True)

    class SlowThread:
        def turn(self, prompt, **kwargs):
            return SlowHandle()

    codex = SimpleNamespace(thread_start=lambda **kwargs: SlowThread())
    provider = CodexProvider(
        codex=codex,
        model="gpt-5.6-terra",
        approval_mode="deny-all-sentinel",
        sandbox="read-only-sentinel",
        request_timeout_seconds=0.01,
    )

    try:
        provider.complete({"messages": [{"role": "user", "content": "hi"}]})
    except TimeoutError:
        pass
    else:
        raise AssertionError("slow Codex turn should time out")

    assert interrupted == [True]


def test_runtime_failure_is_wrapped_for_fallback():
    class FailingHandle:
        def run(self):
            raise RuntimeError("provider internals")

        def interrupt(self):
            pass

    class FailingThread:
        def turn(self, prompt, **kwargs):
            return FailingHandle()

    provider = CodexProvider(
        codex=SimpleNamespace(thread_start=lambda **kwargs: FailingThread()),
        model="gpt-5.6-terra",
        approval_mode="deny-all-sentinel",
        sandbox="read-only-sentinel",
    )

    try:
        provider.complete({"messages": [{"role": "user", "content": "hi"}]})
    except CodexExecutionError:
        pass
    else:
        raise AssertionError("runtime failure should be wrapped for fallback")
