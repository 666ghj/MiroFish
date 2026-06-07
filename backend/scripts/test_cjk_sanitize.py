"""
Tests for cjk_sanitize utility.

Verifies:
  1. CJK run detection (basic, dedup, min-length, order)
  2. Boundary-aware replacement (ASCII left/right, fullwidth parens, numbers)
  3. Locale gating (zh skipped, en/id/etc enabled, env override)
  4. Integration: empty, no-CJK, no-API-key, mocked LLM translate, multi-pass
  5. Failure modes: LLM error falls back to original text, idempotent
"""

import os
import sys
from unittest.mock import patch, MagicMock

# Add project path so 'app' package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.utils.cjk_sanitize import (
    sanitize_cjk_in_text,
    is_enabled,
    _extract_cjk_runs,
    _smart_replace,
)


# -------- _extract_cjk_runs --------

def test_extract_cjk_runs_basic():
    text = "Hello 你好世界 world 通胀压力"
    runs = _extract_cjk_runs(text)
    assert "你好世界" in runs
    assert "通胀压力" in runs
    assert len(runs) == 2
    print("PASS: test_extract_cjk_runs_basic")


def test_extract_cjk_runs_dedup():
    text = "你好世界 and 你好世界 again"
    runs = _extract_cjk_runs(text)
    assert runs == ["你好世界"]
    print("PASS: test_extract_cjk_runs_dedup")


def test_extract_cjk_runs_min_length():
    text = "A 你 B"  # single CJK char should NOT match
    runs = _extract_cjk_runs(text)
    assert runs == []
    print("PASS: test_extract_cjk_runs_min_length")


def test_extract_cjk_runs_preserves_order():
    text = "First 你好 then 世界 and 你好 again"
    runs = _extract_cjk_runs(text)
    assert runs == ["你好", "世界"]
    print("PASS: test_extract_cjk_runs_preserves_order")


# -------- _smart_replace (boundary handling) --------

def test_smart_replace_ascii_both_sides():
    out = _smart_replace("data过于依赖issues", "过于依赖", "overly dependent")
    assert out == "data overly dependent issues"
    print("PASS: test_smart_replace_ascii_both_sides")


def test_smart_replace_ascii_left_only():
    out = _smart_replace("Purbaya过于扩张,", "过于扩张", "overly expansionary")
    assert out == "Purbaya overly expansionary,"
    print("PASS: test_smart_replace_ascii_left_only")


def test_smart_replace_ascii_right_only():
    out = _smart_replace("（中央银行）officials", "中央银行", "central bank")
    assert out == "（central bank）officials"
    print("PASS: test_smart_replace_ascii_right_only")


def test_smart_replace_fullwidth_parens_preserved():
    out = _smart_replace("the policy is（财政）expansion", "财政", "fiscal")
    assert "（fiscal）" in out
    print("PASS: test_smart_replace_fullwidth_parens_preserved")


def test_smart_replace_number_boundary():
    out = _smart_replace("2024年通胀率达到高点", "年通胀率达到高点", "annual inflation rate peaked")
    assert out == "2024 annual inflation rate peaked"
    print("PASS: test_smart_replace_number_boundary")


# -------- is_enabled --------

def test_is_enabled_chinese_locale_skipped():
    os.environ.pop("CJK_SANITIZE_ENABLED", None)
    os.environ.pop("CJK_SANITIZE_LANGS", None)
    assert is_enabled("zh") is False
    assert is_enabled("zh-CN") is False
    assert is_enabled("zh-TW") is False
    print("PASS: test_is_enabled_chinese_locale_skipped")


def test_is_enabled_non_chinese_default():
    os.environ.pop("CJK_SANITIZE_ENABLED", None)
    os.environ.pop("CJK_SANITIZE_LANGS", None)
    for loc in ("en", "es", "fr", "pt", "ru", "de", "id"):
        assert is_enabled(loc) is True, f"Expected True for {loc}"
    print("PASS: test_is_enabled_non_chinese_default")


def test_is_enabled_force_on():
    os.environ["CJK_SANITIZE_ENABLED"] = "1"
    try:
        assert is_enabled("zh") is True  # force-on overrides locale check
        print("PASS: test_is_enabled_force_on")
    finally:
        del os.environ["CJK_SANITIZE_ENABLED"]


def test_is_enabled_force_off():
    os.environ["CJK_SANITIZE_ENABLED"] = "0"
    try:
        assert is_enabled("en") is False
        print("PASS: test_is_enabled_force_off")
    finally:
        del os.environ["CJK_SANITIZE_ENABLED"]


def test_is_enabled_custom_langs():
    os.environ.pop("CJK_SANITIZE_ENABLED", None)
    os.environ["CJK_SANITIZE_LANGS"] = "ja,ko"
    try:
        assert is_enabled("en") is False
        assert is_enabled("ja") is True
        assert is_enabled("ko") is True
        print("PASS: test_is_enabled_custom_langs")
    finally:
        del os.environ["CJK_SANITIZE_LANGS"]


# -------- sanitize_cjk_in_text integration --------

def test_sanitize_empty_text():
    assert sanitize_cjk_in_text("") == ""
    print("PASS: test_sanitize_empty_text")


def test_sanitize_no_cjk_passthrough():
    text = "This is a pure English report with no leaks."
    assert sanitize_cjk_in_text(text, locale="en") == text
    print("PASS: test_sanitize_no_cjk_passthrough")


def test_sanitize_chinese_locale_no_op():
    text = "你好世界 should not be translated in Chinese reports"
    assert sanitize_cjk_in_text(text, locale="zh") == text
    print("PASS: test_sanitize_chinese_locale_no_op")


def test_sanitize_no_api_key_no_op():
    text = "BI said: Purbaya过于扩张"
    result = sanitize_cjk_in_text(
        text, locale="en", api_key=None, base_url="http://test", model="test"
    )
    assert result == text  # no LLM = no change
    print("PASS: test_sanitize_no_api_key_no_op")


def _make_mock_response(json_bytes: bytes):
    """Build a context-manager-friendly mock for urllib.request.urlopen."""
    resp = MagicMock()
    resp.read.return_value = json_bytes
    resp.__enter__ = lambda self: self
    resp.__exit__ = lambda self, *args: None
    return resp


def test_sanitize_translates_cjk_runs():
    mock = _make_mock_response(
        b'{"choices": [{"message": {"content": "[\\"overly inclined toward fiscal expansion\\"]"}}]}'
    )
    with patch("urllib.request.urlopen", return_value=mock):
        text = "BI said: Purbaya过于倾向财政扩张, this is concerning."
        result = sanitize_cjk_in_text(
            text, locale="en", api_key="fake", base_url="http://test", model="test"
        )
    assert "过于倾向财政扩张" not in result
    assert "overly inclined toward fiscal expansion" in result
    print("PASS: test_sanitize_translates_cjk_runs")


def test_sanitize_multi_pass_catches_leftover():
    """LLM translates pass-1 snippets but leaves CJK in one translation. Pass 2
    picks up the leftover CJK that emerged in the output."""
    call_count = [0]
    # Build JSON with embedded CJK as bytes (b'...' can't contain non-ASCII)
    pass1_content = '["Hello world", "partial \u505c\u5de5 remaining"]'
    pass2_content = '["work stoppage"]'
    pass1_body = (
        b'{"choices": [{"message": {"content": "'
        + pass1_content.replace("\\", "\\\\").replace('"', '\\"').encode("utf-8")
        + b'"}}]}'
    )
    pass2_body = (
        b'{"choices": [{"message": {"content": "'
        + pass2_content.replace("\\", "\\\\").replace('"', '\\"').encode("utf-8")
        + b'"}}]}'
    )

    def fake_urlopen(req, timeout):
        call_count[0] += 1
        if call_count[0] == 1:
            return _make_mock_response(pass1_body)
        return _make_mock_response(pass2_body)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        text = "你好世界 then 停工 happened"
        result = sanitize_cjk_in_text(
            text, locale="en", api_key="fake", base_url="http://test", model="test"
        )
    assert "你好世界" not in result
    assert "停工" not in result
    assert "Hello world" in result
    assert "work stoppage" in result
    assert call_count[0] == 2
    print("PASS: test_sanitize_multi_pass_catches_leftover")


def test_sanitize_idempotent_when_clean():
    text = "Pure English with no CJK characters at all."
    assert sanitize_cjk_in_text(text, locale="en") == text
    # Re-run with API key: still no change, 0 LLM calls
    with patch("urllib.request.urlopen") as mock_url:
        result = sanitize_cjk_in_text(
            text, locale="en", api_key="fake", base_url="http://test", model="test"
        )
    assert result == text
    assert mock_url.call_count == 0
    print("PASS: test_sanitize_idempotent_when_clean")


def test_sanitize_llm_failure_returns_original():
    with patch("urllib.request.urlopen", side_effect=Exception("network down")):
        text = "BI said: Purbaya过于扩张"
        result = sanitize_cjk_in_text(
            text, locale="en", api_key="fake", base_url="http://test", model="test"
        )
    assert result == text  # falls back gracefully
    print("PASS: test_sanitize_llm_failure_returns_original")


def test_sanitize_id_locale_enabled():
    """Indonesian locale should also enable sanitization by default."""
    mock = _make_mock_response(
        b'{"choices": [{"message": {"content": "[\\"overly expansive\\"]"}}]}'
    )
    with patch("urllib.request.urlopen", return_value=mock):
        text = "BI: Purbaya过于扩张"
        result = sanitize_cjk_in_text(
            text, locale="id", api_key="fake", base_url="http://test", model="test"
        )
    assert "overly expansive" in result
    print("PASS: test_sanitize_id_locale_enabled")


# -------- runner --------

def run_all():
    tests = [
        v for k, v in globals().items()
        if k.startswith("test_") and callable(v)
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"FAIL: {t.__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    print(f"\n{'=' * 60}")
    print(f"CJK sanitize: {passed} passed, {failed} failed")
    print(f"{'=' * 60}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run_all())
