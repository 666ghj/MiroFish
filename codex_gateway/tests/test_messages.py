import json

from app.messages import build_codex_input


def test_build_codex_input_preserves_roles_and_instructions():
    converted = build_codex_input(
        [
            {"role": "system", "content": "System policy"},
            {"role": "developer", "content": "Developer policy"},
            {"role": "user", "content": "Question"},
            {"role": "assistant", "content": "Earlier answer"},
            {"role": "tool", "content": "Tool result", "tool_call_id": "call-1"},
        ]
    )

    assert converted.base_instructions == "System policy"
    assert converted.developer_instructions == "Developer policy"
    payload = json.loads(converted.turn_text)
    assert [item["role"] for item in payload["messages"]] == [
        "user",
        "assistant",
        "tool",
    ]
    assert payload["messages"][2]["tool_call_id"] == "call-1"


def test_build_codex_input_rejects_unknown_role():
    try:
        build_codex_input([{"role": "unknown", "content": "bad"}])
    except ValueError as error:
        assert "unknown" in str(error)
    else:
        raise AssertionError("unknown role should be rejected")
