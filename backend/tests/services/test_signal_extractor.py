"""
Tests for SignalExtractor — no real API calls, LLMClient fully mocked.
"""

import pytest
from unittest.mock import MagicMock, patch

from app.services.signal_extractor import SignalExtractor, MiroSignal, SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_extractor(chat_json_return=None, chat_json_side_effect=None):
    """Return a SignalExtractor with a mocked LLMClient."""
    mock_client = MagicMock()
    if chat_json_side_effect is not None:
        mock_client.chat_json.side_effect = chat_json_side_effect
    else:
        mock_client.chat_json.return_value = chat_json_return or {}
    return SignalExtractor(llm_client=mock_client), mock_client


_SAMPLE_REPORT = """
## Executive Summary
The simulation shows strong consensus forming around a YES outcome.
Seventy-three percent of agents expressed optimism.

## Key Findings
- Social momentum is strongly positive.
- Counter-narratives remain marginal.

## Conclusion
The dominant dynamic is consensus formation with high confidence.
"""

_SAMPLE_REQUIREMENT = "Will the proposal pass by end of Q2 2026?"

_GOOD_LLM_RESPONSE = {
    "p_yes": 0.73,
    "confidence": "high",
    "action": "buy_yes",
    "regime": "consensus_forming",
    "summary": "Strong agent consensus supports a YES outcome with high confidence.",
    "drivers": ["70%+ agent agreement", "positive social momentum"],
    "invalidators": ["marginal counter-narrative", "low information diversity"],
}


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestExtractHappyPath:

    def test_returns_miro_signal(self):
        extractor, _ = _make_extractor(_GOOD_LLM_RESPONSE)
        result = extractor.extract("r1", "s1", _SAMPLE_REPORT, _SAMPLE_REQUIREMENT)
        assert isinstance(result, MiroSignal)

    def test_fields_match_llm_output(self):
        extractor, _ = _make_extractor(_GOOD_LLM_RESPONSE)
        sig = extractor.extract("r1", "s1", _SAMPLE_REPORT, _SAMPLE_REQUIREMENT)
        assert sig.p_yes == pytest.approx(0.73)
        assert sig.confidence == "high"
        assert sig.action == "buy_yes"
        assert sig.regime == "consensus_forming"
        assert "YES" in sig.summary or "consensus" in sig.summary.lower()
        assert len(sig.drivers) == 2
        assert len(sig.invalidators) == 2

    def test_metadata_fields(self):
        extractor, _ = _make_extractor(_GOOD_LLM_RESPONSE)
        sig = extractor.extract("report_abc", "sim_xyz", _SAMPLE_REPORT, _SAMPLE_REQUIREMENT)
        assert sig.report_id == "report_abc"
        assert sig.simulation_id == "sim_xyz"
        assert sig.schema_version == SCHEMA_VERSION
        assert sig.signal_id  # non-empty UUID
        assert sig.generated_at  # non-empty ISO timestamp

    def test_to_dict_structure(self):
        extractor, _ = _make_extractor(_GOOD_LLM_RESPONSE)
        sig = extractor.extract("r1", "s1", _SAMPLE_REPORT, _SAMPLE_REQUIREMENT)
        d = sig.to_dict()
        assert "thesis" in d
        assert set(d["thesis"].keys()) == {
            "p_yes", "confidence", "action", "regime",
            "summary", "drivers", "invalidators",
        }

    def test_llm_called_with_low_temperature(self):
        extractor, mock_client = _make_extractor(_GOOD_LLM_RESPONSE)
        extractor.extract("r1", "s1", _SAMPLE_REPORT, _SAMPLE_REQUIREMENT)
        call_kwargs = mock_client.chat_json.call_args.kwargs
        assert call_kwargs["temperature"] <= 0.2

    def test_llm_called_with_retries(self):
        extractor, mock_client = _make_extractor(_GOOD_LLM_RESPONSE)
        extractor.extract("r1", "s1", _SAMPLE_REPORT, _SAMPLE_REQUIREMENT)
        call_kwargs = mock_client.chat_json.call_args.kwargs
        assert call_kwargs.get("max_attempts", 1) >= 2

    def test_simulation_requirement_in_messages(self):
        extractor, mock_client = _make_extractor(_GOOD_LLM_RESPONSE)
        req = "Will the referendum pass?"
        extractor.extract("r1", "s1", _SAMPLE_REPORT, req)
        messages = mock_client.chat_json.call_args.kwargs["messages"]
        user_content = next(m["content"] for m in messages if m["role"] == "user")
        assert req in user_content


# ---------------------------------------------------------------------------
# Field validation and normalisation
# ---------------------------------------------------------------------------

class TestFieldValidation:

    def test_p_yes_clamped_below_zero(self):
        extractor, _ = _make_extractor({**_GOOD_LLM_RESPONSE, "p_yes": -0.5})
        sig = extractor.extract("r1", "s1", _SAMPLE_REPORT, _SAMPLE_REQUIREMENT)
        assert sig.p_yes >= 0.01

    def test_p_yes_clamped_above_one(self):
        extractor, _ = _make_extractor({**_GOOD_LLM_RESPONSE, "p_yes": 1.5})
        sig = extractor.extract("r1", "s1", _SAMPLE_REPORT, _SAMPLE_REQUIREMENT)
        assert sig.p_yes <= 0.99

    def test_invalid_confidence_falls_back_to_medium(self):
        extractor, _ = _make_extractor({**_GOOD_LLM_RESPONSE, "confidence": "very_sure"})
        sig = extractor.extract("r1", "s1", _SAMPLE_REPORT, _SAMPLE_REQUIREMENT)
        assert sig.confidence == "medium"

    def test_invalid_action_recomputed_from_p_yes_buy_yes(self):
        extractor, _ = _make_extractor({**_GOOD_LLM_RESPONSE, "p_yes": 0.8, "action": "INVALID"})
        sig = extractor.extract("r1", "s1", _SAMPLE_REPORT, _SAMPLE_REQUIREMENT)
        assert sig.action == "buy_yes"

    def test_invalid_action_recomputed_from_p_yes_buy_no(self):
        extractor, _ = _make_extractor({**_GOOD_LLM_RESPONSE, "p_yes": 0.2, "action": "INVALID"})
        sig = extractor.extract("r1", "s1", _SAMPLE_REPORT, _SAMPLE_REQUIREMENT)
        assert sig.action == "buy_no"

    def test_invalid_action_recomputed_from_p_yes_hold(self):
        extractor, _ = _make_extractor({**_GOOD_LLM_RESPONSE, "p_yes": 0.5, "action": "INVALID"})
        sig = extractor.extract("r1", "s1", _SAMPLE_REPORT, _SAMPLE_REQUIREMENT)
        assert sig.action == "hold"

    def test_missing_regime_defaults_to_uncertain(self):
        resp = {k: v for k, v in _GOOD_LLM_RESPONSE.items() if k != "regime"}
        extractor, _ = _make_extractor(resp)
        sig = extractor.extract("r1", "s1", _SAMPLE_REPORT, _SAMPLE_REQUIREMENT)
        assert sig.regime == "uncertain"

    def test_empty_drivers_list_accepted(self):
        extractor, _ = _make_extractor({**_GOOD_LLM_RESPONSE, "drivers": []})
        sig = extractor.extract("r1", "s1", _SAMPLE_REPORT, _SAMPLE_REQUIREMENT)
        assert sig.drivers == []

    def test_non_list_drivers_handled(self):
        extractor, _ = _make_extractor({**_GOOD_LLM_RESPONSE, "drivers": "some string"})
        sig = extractor.extract("r1", "s1", _SAMPLE_REPORT, _SAMPLE_REQUIREMENT)
        # Should not crash; string is iterable so each char becomes an item — acceptable
        assert isinstance(sig.drivers, list)


# ---------------------------------------------------------------------------
# Report trimming
# ---------------------------------------------------------------------------

class TestReportTrimming:

    def test_short_report_unchanged(self):
        short = "Short report content."
        result = SignalExtractor._trim_report(short, max_chars=100)
        assert result == short

    def test_long_report_trimmed(self):
        long_report = "x" * 20_000
        result = SignalExtractor._trim_report(long_report, max_chars=12_000)
        assert len(result) < 20_000
        assert "truncated" in result

    def test_trimmed_report_keeps_tail(self):
        # The tail (conclusion) is most important for signal extraction
        long_report = "A" * 10_000 + "CONCLUSION"
        result = SignalExtractor._trim_report(long_report, max_chars=100)
        assert "CONCLUSION" in result


# ---------------------------------------------------------------------------
# Fallback (_salvage)
# ---------------------------------------------------------------------------

class TestSalvage:

    def test_salvage_extracts_probability(self):
        result = SignalExtractor._salvage("The probability is 0.68 for YES outcome.")
        assert result is not None
        assert result["p_yes"] == pytest.approx(0.68)

    def test_salvage_returns_none_when_no_probability(self):
        assert SignalExtractor._salvage("no numbers here at all") is None

    def test_salvage_sets_action_buy_yes(self):
        result = SignalExtractor._salvage("probability 0.80")
        assert result["action"] == "buy_yes"

    def test_salvage_sets_action_buy_no(self):
        result = SignalExtractor._salvage("probability 0.20")
        assert result["action"] == "buy_no"

    def test_salvage_sets_action_hold(self):
        result = SignalExtractor._salvage("probability 0.50")
        assert result["action"] == "hold"

    def test_salvage_detects_high_confidence(self):
        result = SignalExtractor._salvage("high confidence, p=0.72")
        assert result["confidence"] == "high"

    def test_salvage_detects_low_confidence(self):
        result = SignalExtractor._salvage("low certainty, p=0.30")
        assert result["confidence"] == "low"


# ---------------------------------------------------------------------------
# LLM failure propagates as ValueError
# ---------------------------------------------------------------------------

class TestLLMFailure:

    def test_raises_value_error_on_llm_failure(self):
        extractor, mock_client = _make_extractor()
        mock_client.chat_json.side_effect = ValueError("LLM返回的JSON格式无效: ...")
        with pytest.raises(ValueError):
            extractor.extract("r1", "s1", _SAMPLE_REPORT, _SAMPLE_REQUIREMENT)
