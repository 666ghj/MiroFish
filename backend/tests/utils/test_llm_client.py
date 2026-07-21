"""
Tests for LLMClient utility — no real API calls, all OpenAI interactions mocked.
"""

import json
import pytest
from unittest.mock import MagicMock, patch, call

from app.utils.llm_client import LLMClient


# ---------------------------------------------------------------------------
# Helpers to build fake OpenAI response objects
# ---------------------------------------------------------------------------

def _make_response(content: str, finish_reason: str = "stop"):
    choice = MagicMock()
    choice.message.content = content
    choice.finish_reason = finish_reason
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _make_client(responses):
    """
    Return a patched LLMClient whose underlying OpenAI client returns
    *responses* in order on successive .chat.completions.create() calls.
    """
    with patch("app.utils.llm_client.OpenAI") as MockOpenAI:
        mock_openai_instance = MagicMock()
        mock_openai_instance.chat.completions.create.side_effect = responses
        MockOpenAI.return_value = mock_openai_instance

        client = LLMClient(api_key="test-key", base_url="http://localhost", model="test-model")
        # Expose the underlying mock for assertions
        client._mock_create = mock_openai_instance.chat.completions.create
        return client


# ---------------------------------------------------------------------------
# _clean_response_text
# ---------------------------------------------------------------------------

class TestCleanResponseText:

    def setup_method(self):
        with patch("app.utils.llm_client.OpenAI"):
            self.client = LLMClient(api_key="k", base_url="u", model="m")

    def test_passthrough_plain_json(self):
        raw = '{"a": 1}'
        assert self.client._clean_response_text(raw) == '{"a": 1}'

    def test_strips_think_tags(self):
        raw = '<think>internal reasoning</think>{"a": 1}'
        assert self.client._clean_response_text(raw) == '{"a": 1}'

    def test_strips_multiline_think_tags(self):
        raw = '<think>\nline1\nline2\n</think>\n{"b": 2}'
        assert self.client._clean_response_text(raw) == '{"b": 2}'

    def test_strips_json_markdown_fence(self):
        raw = '```json\n{"c": 3}\n```'
        assert self.client._clean_response_text(raw) == '{"c": 3}'

    def test_strips_plain_markdown_fence(self):
        raw = '```\n{"d": 4}\n```'
        assert self.client._clean_response_text(raw) == '{"d": 4}'

    def test_strips_think_and_fence_combined(self):
        raw = '<think>reasoning</think>\n```json\n{"e": 5}\n```'
        assert self.client._clean_response_text(raw) == '{"e": 5}'

    def test_empty_string(self):
        assert self.client._clean_response_text("") == ""

    def test_no_fence_no_think(self):
        raw = '  {"f": 6}  '
        assert self.client._clean_response_text(raw) == '{"f": 6}'


# ---------------------------------------------------------------------------
# _fix_truncated_json
# ---------------------------------------------------------------------------

class TestFixTruncatedJson:

    def setup_method(self):
        with patch("app.utils.llm_client.OpenAI"):
            self.client = LLMClient(api_key="k", base_url="u", model="m")

    def test_closes_one_brace(self):
        truncated = '{"key": "val'
        fixed = self.client._fix_truncated_json(truncated)
        result = json.loads(fixed)
        assert result["key"] == "val"

    def test_closes_nested_braces(self):
        truncated = '{"outer": {"inner": "x"'
        fixed = self.client._fix_truncated_json(truncated)
        result = json.loads(fixed)
        assert result["outer"]["inner"] == "x"

    def test_closes_open_array(self):
        truncated = '{"list": [1, 2'
        fixed = self.client._fix_truncated_json(truncated)
        result = json.loads(fixed)
        assert result["list"] == [1, 2]

    def test_closes_array_and_brace(self):
        truncated = '{"a": [1, 2, 3'
        fixed = self.client._fix_truncated_json(truncated)
        result = json.loads(fixed)
        assert result["a"] == [1, 2, 3]

    def test_already_valid_unchanged(self):
        valid = '{"x": 1}'
        fixed = self.client._fix_truncated_json(valid)
        assert json.loads(fixed) == {"x": 1}

    def test_trailing_dangling_value_gets_quote(self):
        # ends mid-string without closing quote
        truncated = '{"k": "incomplete'
        fixed = self.client._fix_truncated_json(truncated)
        # Should be parseable after repair
        result = json.loads(fixed)
        assert "k" in result


# ---------------------------------------------------------------------------
# _try_fix_json
# ---------------------------------------------------------------------------

class TestTryFixJson:

    def setup_method(self):
        with patch("app.utils.llm_client.OpenAI"):
            self.client = LLMClient(api_key="k", base_url="u", model="m")

    def test_returns_valid_json(self):
        content = '{"name": "Alice", "age": 30}'
        result = self.client._try_fix_json(content)
        assert result == {"name": "Alice", "age": 30}

    def test_extracts_json_from_surrounding_text(self):
        content = 'Here is the result: {"score": 42} end.'
        result = self.client._try_fix_json(content)
        assert result is not None
        assert result["score"] == 42

    def test_fixes_newlines_inside_string_values(self):
        # Literal newline inside a JSON string value is invalid JSON
        content = '{"desc": "line one\nline two"}'
        result = self.client._try_fix_json(content)
        assert result is not None
        assert "desc" in result

    def test_returns_none_for_no_json_object(self):
        assert self.client._try_fix_json("no json here at all") is None

    def test_returns_none_for_empty_string(self):
        assert self.client._try_fix_json("") is None

    def test_recovers_truncated_object(self):
        # Missing closing brace
        content = '{"city": "Beijing", "pop": 21'
        result = self.client._try_fix_json(content)
        assert result is not None
        assert result["city"] == "Beijing"


# ---------------------------------------------------------------------------
# chat_json — retry behavior
# ---------------------------------------------------------------------------

class TestChatJsonRetry:

    # --- succeeds on first attempt ---

    def test_success_first_attempt(self):
        payload = {"status": "ok"}
        client = _make_client([_make_response(json.dumps(payload))])
        result = client.chat_json([{"role": "user", "content": "hi"}])
        assert result == payload
        assert client._mock_create.call_count == 1

    # --- temperature backoff ---

    def test_temperature_decreases_across_retries(self):
        bad = _make_response("not json at all {{{{")
        good = _make_response('{"ok": true}')
        client = _make_client([bad, bad, good])

        result = client.chat_json(
            [{"role": "user", "content": "hi"}],
            temperature=0.9,
            temperature_step=0.3,
            max_attempts=3,
        )
        assert result == {"ok": True}

        calls = client._mock_create.call_args_list
        assert calls[0].kwargs["temperature"] == pytest.approx(0.9)
        assert calls[1].kwargs["temperature"] == pytest.approx(0.6)
        assert calls[2].kwargs["temperature"] == pytest.approx(0.3)

    def test_temperature_never_goes_below_zero(self):
        good = _make_response('{"x": 1}')
        client = _make_client([good])
        client.chat_json(
            [{"role": "user", "content": "hi"}],
            temperature=0.1,
            temperature_step=0.5,
            max_attempts=1,
        )
        calls = client._mock_create.call_args_list
        assert calls[0].kwargs["temperature"] == pytest.approx(0.1)

    # --- fallback_parser ---

    def test_fallback_parser_called_on_bad_json(self):
        bad = _make_response("this is not json")
        client = _make_client([bad])

        fallback = MagicMock(return_value={"rescued": True})
        result = client.chat_json(
            [{"role": "user", "content": "q"}],
            max_attempts=1,
            fallback_parser=fallback,
        )
        assert result == {"rescued": True}
        fallback.assert_called_once()

    def test_fallback_parser_returning_none_does_not_short_circuit(self):
        bad = _make_response("still not json ][")
        good = _make_response('{"second": "attempt"}')
        client = _make_client([bad, good])

        fallback = MagicMock(return_value=None)
        result = client.chat_json(
            [{"role": "user", "content": "q"}],
            max_attempts=2,
            fallback_parser=fallback,
        )
        assert result == {"second": "attempt"}

    # --- raises ValueError after all attempts fail ---

    def test_raises_after_all_attempts_fail(self):
        bad = _make_response("invalid {{{ json")
        client = _make_client([bad, bad, bad])

        with pytest.raises(ValueError, match="LLM返回的JSON格式无效"):
            client.chat_json(
                [{"role": "user", "content": "q"}],
                max_attempts=3,
            )
        assert client._mock_create.call_count == 3

    def test_raises_after_single_attempt(self):
        bad = _make_response("nope")
        client = _make_client([bad])

        with pytest.raises(ValueError):
            client.chat_json([{"role": "user", "content": "q"}], max_attempts=1)

    # --- finish_reason == 'length' triggers truncation repair ---

    def test_truncated_output_is_repaired(self):
        truncated_json = '{"items": [1, 2, 3'
        client = _make_client([_make_response(truncated_json, finish_reason="length")])
        result = client.chat_json([{"role": "user", "content": "q"}])
        assert result["items"] == [1, 2, 3]

    # --- API exception counts as a failed attempt ---

    def test_api_exception_retried(self):
        from openai import APIError
        exc = Exception("network failure")
        good = _make_response('{"recovered": true}')
        client = _make_client([exc, good])

        result = client.chat_json(
            [{"role": "user", "content": "q"}],
            max_attempts=2,
        )
        assert result == {"recovered": True}
        assert client._mock_create.call_count == 2

    def test_api_exception_all_attempts_raises_value_error(self):
        exc = Exception("always fails")
        client = _make_client([exc, exc])

        with pytest.raises(ValueError):
            client.chat_json(
                [{"role": "user", "content": "q"}],
                max_attempts=2,
            )
