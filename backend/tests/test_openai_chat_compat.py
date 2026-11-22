import json
from types import SimpleNamespace

import pytest

from app.utils.openai_chat_compat import (
    create_chat_completion,
    create_json_chat_completion,
    extract_chat_completion_text,
    is_gpt5_family,
    is_response_format_unsupported,
)


class CompletionRecorder:
    def __init__(self, result=None, error=None):
        self.result = result or object()
        self.error = error
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.result


def client_for(recorder):
    return SimpleNamespace(chat=SimpleNamespace(completions=recorder))


def test_gpt5_uses_completion_token_limit_without_temperature():
    recorder = CompletionRecorder()
    messages = [{"role": "user", "content": "hello"}]

    result = create_chat_completion(
        client_for(recorder),
        model="gpt-5-2025-08-07",
        messages=messages,
        temperature=0.2,
        max_tokens=123,
        response_format={"type": "json_object"},
    )

    assert result is recorder.result
    assert recorder.calls == [
        {
            "model": "gpt-5-2025-08-07",
            "messages": messages,
            "max_completion_tokens": 123,
            "response_format": {"type": "json_object"},
        }
    ]


def test_legacy_model_preserves_original_request_shape():
    recorder = CompletionRecorder()
    messages = [{"role": "user", "content": "hello"}]

    create_chat_completion(
        client_for(recorder),
        model="third-party-chat-model",
        messages=messages,
        temperature=0.7,
        max_tokens=456,
        response_format={"type": "json_object"},
    )

    assert recorder.calls == [
        {
            "model": "third-party-chat-model",
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 456,
            "response_format": {"type": "json_object"},
        }
    ]


def test_provider_error_is_propagated_without_guessing_or_retrying():
    provider_error = RuntimeError("unsupported max_tokens due to a server outage")
    recorder = CompletionRecorder(error=provider_error)

    with pytest.raises(RuntimeError) as captured:
        create_chat_completion(
            client_for(recorder),
            model="legacy-model",
            messages=[],
            max_tokens=10,
        )

    assert captured.value is provider_error
    assert len(recorder.calls) == 1


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("gpt-5", True),
        (" GPT-5.1-mini ", True),
        ("gpt-4.1", False),
        ("my-gpt-5-proxy", False),
        (None, False),
    ],
)
def test_gpt5_family_detection(model, expected):
    assert is_gpt5_family(model) is expected


def test_extracts_text_from_supported_content_shapes():
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=[
                        {"text": {"value": "first"}},
                        {"content": " second"},
                        SimpleNamespace(text=" third"),
                    ]
                )
            )
        ]
    )

    assert extract_chat_completion_text(response) == "first second third"
    assert extract_chat_completion_text(SimpleNamespace(choices=[])) == ""


class StatusError(RuntimeError):
    def __init__(self, *, status_code, body):
        super().__init__(str(body))
        self.status_code = status_code
        self.body = body


class CompletionSequence:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


LM_STUDIO_MESSAGE = "'response_format.type' must be 'json_schema' or 'text'"


@pytest.mark.parametrize(
    "body",
    [
        LM_STUDIO_MESSAGE,  # what the OpenAI SDK exposes for {"error": "<message>"}
        {"error": LM_STUDIO_MESSAGE},
        {"error": {"message": LM_STUDIO_MESSAGE}},
    ],
)
def test_detects_lm_studio_plain_string_response_format_rejection(body):
    assert is_response_format_unsupported(StatusError(status_code=400, body=body))


@pytest.mark.parametrize(
    ("status_code", "body"),
    [
        (400, "The number of tokens to keep from the initial prompt is greater than the context length"),
        (400, {"error": "model must be loaded first"}),
        (500, LM_STUDIO_MESSAGE),
        (400, None),
    ],
)
def test_ignores_unrelated_plain_string_errors(status_code, body):
    assert not is_response_format_unsupported(
        StatusError(status_code=status_code, body=body)
    )


def test_json_completion_falls_back_and_stops_requesting_json_mode():
    rejection = StatusError(status_code=400, body=LM_STUDIO_MESSAGE)
    first, second = object(), object()
    sequence = CompletionSequence(rejection, first, second)
    client = client_for(sequence)

    response, json_mode = create_json_chat_completion(
        client, model="local-model", messages=[], temperature=0.7
    )
    assert response is first
    assert json_mode is False
    assert sequence.calls[0]["response_format"] == {"type": "json_object"}
    assert "response_format" not in sequence.calls[1]
    assert sequence.calls[1]["temperature"] == 0.7

    response, json_mode = create_json_chat_completion(
        client, model="local-model", messages=[], json_mode=json_mode
    )
    assert response is second
    assert json_mode is False
    assert len(sequence.calls) == 3
    assert "response_format" not in sequence.calls[2]


def test_json_completion_keeps_json_mode_when_supported():
    result = object()
    recorder = CompletionRecorder(result=result)

    response, json_mode = create_json_chat_completion(
        client_for(recorder), model="compatible-model", messages=[]
    )

    assert response is result
    assert json_mode is True
    assert recorder.calls[0]["response_format"] == {"type": "json_object"}


def test_json_completion_propagates_unrelated_errors_without_retrying():
    provider_error = StatusError(status_code=400, body="context length exceeded")
    recorder = CompletionRecorder(error=provider_error)

    with pytest.raises(StatusError) as captured:
        create_json_chat_completion(
            client_for(recorder), model="local-model", messages=[]
        )

    assert captured.value is provider_error
    assert len(recorder.calls) == 1


def test_json_completion_handles_real_lm_studio_error_through_openai_sdk():
    httpx = pytest.importorskip("httpx")
    from openai import OpenAI

    sent = []

    def handler(request):
        payload = json.loads(request.content)
        sent.append(payload)
        if "response_format" in payload:
            return httpx.Response(400, json={"error": LM_STUDIO_MESSAGE})
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-1",
                "object": "chat.completion",
                "created": 0,
                "model": payload["model"],
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": '{"ok": true}'},
                    }
                ],
            },
        )

    client = OpenAI(
        base_url="http://lmstudio.test/v1",
        api_key="lm-studio",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    response, json_mode = create_json_chat_completion(
        client, model="google/gemma-4-26b-a4b-qat", messages=[{"role": "user", "content": "JSON"}]
    )

    assert extract_chat_completion_text(response) == '{"ok": true}'
    assert json_mode is False
    assert [("response_format" in p) for p in sent] == [True, False]
