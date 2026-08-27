from app.redaction import redact_log_value


def test_redaction_removes_credentials_and_prompt_content():
    value = {
        "Authorization": "Bearer secret-token",
        "access_token": "access-secret",
        "refresh_token": "refresh-secret",
        "LLM_API_KEY": "api-secret",
        "messages": [{"role": "user", "content": "private prompt"}],
        "status": 429,
    }

    redacted = redact_log_value(value)
    text = repr(redacted)

    assert "secret" not in text
    assert "private prompt" not in text
    assert redacted["messages"] == [{"role": "user", "content_length": 14}]
    assert redacted["status"] == 429
