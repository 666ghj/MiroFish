from types import SimpleNamespace

from app.deepseek_provider import DeepSeekProvider, FallbackUnavailableError


def test_deepseek_provider_forwards_supported_request_fields():
    captured = {}

    class Completions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                model="deepseek-v4-flash",
                choices=[
                    SimpleNamespace(
                        finish_reason="stop",
                        message=SimpleNamespace(content='{"answer":"fallback"}'),
                    )
                ],
                usage=SimpleNamespace(total_tokens=12),
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    provider = DeepSeekProvider(client=client, model="deepseek-v4-flash")
    result = provider.complete(
        {
            "messages": [{"role": "user", "content": "hello"}],
            "temperature": 0.2,
            "max_tokens": 100,
            "response_format": {"type": "json_object"},
        }
    )

    assert captured["model"] == "deepseek-v4-flash"
    assert captured["messages"][0]["content"] == "hello"
    assert captured["response_format"] == {"type": "json_object"}
    assert result.content == '{"answer":"fallback"}'


def test_deepseek_provider_downgrades_json_schema_to_json_object():
    captured = {}

    class Completions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                model="deepseek-v4-flash",
                choices=[
                    SimpleNamespace(
                        finish_reason="stop",
                        message=SimpleNamespace(content='{"status":"ok"}'),
                    )
                ],
                usage=None,
            )

    messages = [{"role": "user", "content": "Return status"}]
    schema = {
        "type": "object",
        "properties": {"status": {"type": "string"}},
        "required": ["status"],
    }
    provider = DeepSeekProvider(
        client=SimpleNamespace(chat=SimpleNamespace(completions=Completions())),
        model="deepseek-v4-flash",
    )

    provider.complete(
        {
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "result", "schema": schema},
            },
        }
    )

    assert captured["response_format"] == {"type": "json_object"}
    assert "JSON Schema" in captured["messages"][-1]["content"]
    assert messages == [{"role": "user", "content": "Return status"}]


def test_insufficient_balance_opens_circuit_after_first_request():
    calls = []

    class InsufficientBalanceError(RuntimeError):
        status_code = 402

    class Completions:
        def create(self, **kwargs):
            calls.append(kwargs)
            raise InsufficientBalanceError("Insufficient Balance")

    provider = DeepSeekProvider(
        client=SimpleNamespace(chat=SimpleNamespace(completions=Completions())),
        model="deepseek-v4-flash",
    )
    request = {"messages": [{"role": "user", "content": "hello"}]}

    for _ in range(2):
        try:
            provider.complete(request)
        except FallbackUnavailableError as error:
            assert error.reason == "insufficient_balance"
        else:
            raise AssertionError("402 should open the DeepSeek circuit")

    assert len(calls) == 1
