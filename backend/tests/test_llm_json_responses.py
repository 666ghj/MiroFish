from types import SimpleNamespace

import pytest

from app.utils.llm_client import LLMClient, LLMResponseError


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


class ProviderError(RuntimeError):
    def __init__(self, *, status_code, body):
        super().__init__(body.get("error", {}).get("message", "provider error"))
        self.status_code = status_code
        self.body = body


def _response(content, *, finish_reason="stop", include_choice=True):
    choices = []
    if include_choice:
        choices.append(
            SimpleNamespace(
                finish_reason=finish_reason,
                message=SimpleNamespace(content=content),
            )
        )
    return SimpleNamespace(choices=choices)


def _client_for(sequence):
    client = object.__new__(LLMClient)
    client.model = "compatible-model"
    client.client = SimpleNamespace(
        chat=SimpleNamespace(completions=sequence)
    )
    return client


def test_chat_json_retries_truncated_completion_without_token_cap():
    sequence = CompletionSequence(
        _response('{"items": [', finish_reason="length"),
        _response('{"items": [1, 2]}'),
    )
    client = _client_for(sequence)

    result = client.chat_json(
        messages=[{"role": "user", "content": "Return JSON"}],
        max_tokens=4096,
        max_attempts=2,
    )

    assert result == {"items": [1, 2]}
    assert sequence.calls[0]["max_tokens"] == 4096
    assert "max_tokens" not in sequence.calls[1]


def test_chat_json_omits_token_cap_when_requested():
    sequence = CompletionSequence(_response('{"ok": true}'))
    client = _client_for(sequence)

    assert client.chat_json(
        messages=[{"role": "user", "content": "Return JSON"}],
        max_tokens=None,
    ) == {"ok": True}
    assert "max_tokens" not in sequence.calls[0]


def test_chat_json_retries_empty_content_once():
    sequence = CompletionSequence(
        _response(None),
        _response('{"ok": true}'),
    )
    client = _client_for(sequence)

    result = client.chat_json(
        messages=[{"role": "user", "content": "Return JSON"}],
        max_attempts=2,
    )

    assert result == {"ok": True}
    assert len(sequence.calls) == 2


def test_chat_json_accepts_complete_object_before_trailing_text():
    sequence = CompletionSequence(
        _response('{"ok": true}\nThis object is ready to use.')
    )
    client = _client_for(sequence)

    assert client.chat_json(
        messages=[{"role": "user", "content": "Return JSON"}],
    ) == {"ok": True}


@pytest.mark.parametrize(
    "content",
    [
        '{"status": "draft"}\n{"status": "complete"}',
        '{"status": "draft"}\n```json\n{"status": "complete"}\n```',
        '{"status": "draft"}\nExplanation first.\n{"status": "complete"}',
    ],
)
def test_chat_json_rejects_a_second_json_document(content):
    sequence = CompletionSequence(_response(content))
    client = _client_for(sequence)

    with pytest.raises(LLMResponseError, match="multiple JSON"):
        client.chat_json(
            messages=[{"role": "user", "content": "Return JSON"}],
        )


def test_chat_json_rejects_top_level_array():
    sequence = CompletionSequence(_response('[{"ok": true}]'))
    client = _client_for(sequence)

    with pytest.raises(LLMResponseError, match="JSON object"):
        client.chat_json(
            messages=[{"role": "user", "content": "Return JSON"}],
            max_attempts=1,
        )


def test_chat_json_error_does_not_echo_partial_model_output():
    partial = '{"private_source_text": "SENTINEL-SHOULD-NOT-LEAK"'
    sequence = CompletionSequence(
        _response(partial, finish_reason="length"),
        _response(partial, finish_reason="length"),
    )
    client = _client_for(sequence)

    with pytest.raises(LLMResponseError) as captured:
        client.chat_json(
            messages=[{"role": "user", "content": "Return JSON"}],
            max_attempts=2,
        )

    assert "SENTINEL-SHOULD-NOT-LEAK" not in str(captured.value)
    assert captured.value.finish_reason == "length"


def test_chat_json_falls_back_only_for_explicit_response_format_rejection():
    unsupported = ProviderError(
        status_code=400,
        body={
            "error": {
                "param": "response_format",
                "code": "unsupported_parameter",
                "message": "response_format is not supported by this model",
            }
        },
    )
    sequence = CompletionSequence(unsupported, _response('{"ok": true}'))
    client = _client_for(sequence)

    result = client.chat_json(
        messages=[{"role": "user", "content": "Return JSON"}],
        max_attempts=1,
    )

    assert result == {"ok": True}
    assert sequence.calls[0]["response_format"] == {"type": "json_object"}
    assert "response_format" not in sequence.calls[1]


def test_response_format_fallback_keeps_content_retry_available():
    unsupported = ProviderError(
        status_code=400,
        body={
            "error": {
                "param": "response_format",
                "code": "unsupported_parameter",
                "message": "response_format is not supported by this model",
            }
        },
    )
    sequence = CompletionSequence(
        unsupported,
        _response('{"items": [', finish_reason="length"),
        _response('{"items": [1]}'),
    )
    client = _client_for(sequence)

    result = client.chat_json(
        messages=[{"role": "user", "content": "Return JSON"}],
        max_attempts=2,
    )

    assert result == {"items": [1]}
    assert sequence.calls[0]["response_format"] == {"type": "json_object"}
    assert "response_format" not in sequence.calls[1]
    assert "response_format" not in sequence.calls[2]
    assert "max_tokens" not in sequence.calls[2]


def test_chat_json_defaults_to_one_content_attempt():
    sequence = CompletionSequence(
        _response(None),
        _response('{"ok": true}'),
    )
    client = _client_for(sequence)

    with pytest.raises(LLMResponseError, match="empty JSON"):
        client.chat_json(
            messages=[{"role": "user", "content": "Return JSON"}],
        )

    assert len(sequence.calls) == 1


@pytest.mark.parametrize("status_code", [400, 401, 429, 500])
def test_chat_json_does_not_retry_unrelated_provider_errors(status_code):
    provider_error = ProviderError(
        status_code=status_code,
        body={
            "error": {
                "param": "messages",
                "code": "invalid_request",
                "message": "request failed for an unrelated reason",
            }
        },
    )
    sequence = CompletionSequence(provider_error, _response('{"ok": true}'))
    client = _client_for(sequence)

    with pytest.raises(ProviderError) as captured:
        client.chat_json(
            messages=[{"role": "user", "content": "Return JSON"}],
            max_attempts=2,
        )

    assert captured.value is provider_error
    assert len(sequence.calls) == 1


def test_chat_json_reports_missing_choices_without_retrying_forever():
    sequence = CompletionSequence(
        _response(None, include_choice=False),
        _response(None, include_choice=False),
    )
    client = _client_for(sequence)

    with pytest.raises(LLMResponseError, match="no choices"):
        client.chat_json(
            messages=[{"role": "user", "content": "Return JSON"}],
            max_attempts=2,
        )

    assert len(sequence.calls) == 2
