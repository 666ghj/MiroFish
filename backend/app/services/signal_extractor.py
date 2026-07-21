"""
Miro Signal Extractor
Distils a completed simulation report into a canonical machine-readable
probability signal that external pipelines (e.g. prediction-market bots)
can consume directly.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from ..utils.llm_client import LLMClient
from ..utils.logger import get_logger

logger = get_logger('mirofish.signal_extractor')

SCHEMA_VERSION = "1.1"

_SYSTEM_PROMPT = """\
You are a structured-signal extractor. You will be given the full markdown text
of a social-simulation analysis report and the original simulation requirement
(the prediction question). Your job is to distil the report into a concise,
machine-readable probability signal.

Rules:
- p_yes must be a float strictly between 0.0 and 1.0 (never exactly 0 or 1).
- confidence must be one of: "high", "medium", "low".
- action must be one of: "buy_yes", "buy_no", "hold".
  Use "buy_yes" when p_yes > 0.55, "buy_no" when p_yes < 0.45, else "hold".
- regime describes the dominant social dynamic observed in the simulation,
  e.g. "consensus_forming", "contested", "uncertain", "momentum_shift",
  "echo_chamber", "fragmented".
- summary is one sentence (≤ 30 words).
- drivers is a list of 2–4 short strings (key factors supporting the thesis).
- invalidators is a list of 2–4 short strings (key risks or counter-factors).
- Do not reproduce large sections of the report. Be concise.
- Respond ONLY with valid JSON matching the schema below — no prose, no fences.

Required JSON schema:
{
  "p_yes": <float 0.0–1.0>,
  "confidence": "high" | "medium" | "low",
  "action": "buy_yes" | "buy_no" | "hold",
  "regime": <string>,
  "summary": <string>,
  "drivers": [<string>, ...],
  "invalidators": [<string>, ...]
}
"""


@dataclass
class MiroSignal:
    """Canonical prediction signal extracted from a simulation report."""

    signal_id: str
    schema_version: str
    report_id: str
    simulation_id: str
    generated_at: str

    # Core thesis fields
    p_yes: float
    confidence: str          # high | medium | low
    action: str              # buy_yes | buy_no | hold
    regime: str
    summary: str
    drivers: List[str] = field(default_factory=list)
    invalidators: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "signal_id": self.signal_id,
            "schema_version": self.schema_version,
            "report_id": self.report_id,
            "simulation_id": self.simulation_id,
            "generated_at": self.generated_at,
            "thesis": {
                "p_yes": self.p_yes,
                "confidence": self.confidence,
                "action": self.action,
                "regime": self.regime,
                "summary": self.summary,
                "drivers": self.drivers,
                "invalidators": self.invalidators,
            },
        }


class SignalExtractor:
    """Extracts a MiroSignal from a completed report's markdown content."""

    _VALID_CONFIDENCE = {"high", "medium", "low"}
    _VALID_ACTIONS = {"buy_yes", "buy_no", "hold"}

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self._client = llm_client or LLMClient()

    def extract(
        self,
        report_id: str,
        simulation_id: str,
        markdown_content: str,
        simulation_requirement: str,
    ) -> MiroSignal:
        """
        Distil *markdown_content* into a MiroSignal.

        Args:
            report_id: The report this signal is derived from.
            simulation_id: Parent simulation ID.
            markdown_content: Full report text (may be long).
            simulation_requirement: The original prediction question / goal.

        Returns:
            MiroSignal with validated fields.

        Raises:
            ValueError: If the LLM fails to produce a valid signal after retries.
        """
        # Trim to avoid token limits while keeping the most analytical content.
        # Reports can exceed 30 k chars; the last third is usually the conclusion.
        body = self._trim_report(markdown_content)

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Simulation requirement (prediction question):\n{simulation_requirement}\n\n"
                    f"Report:\n{body}"
                ),
            },
        ]

        raw = self._client.chat_json(
            messages=messages,
            temperature=0.1,
            max_tokens=512,
            max_attempts=3,
            temperature_step=0.05,
            fallback_parser=self._salvage,
        )

        return self._build_signal(raw, report_id, simulation_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _trim_report(content: str, max_chars: int = 12_000) -> str:
        """Keep the tail of the report (conclusions) if it is very long."""
        if len(content) <= max_chars:
            return content
        return "…[report truncated for signal extraction]\n\n" + content[-max_chars:]

    def _build_signal(
        self, raw: dict, report_id: str, simulation_id: str
    ) -> MiroSignal:
        """Validate and normalise the raw LLM dict into a MiroSignal."""
        # p_yes
        try:
            p_yes = float(raw.get("p_yes", 0.5))
        except (TypeError, ValueError):
            p_yes = 0.5
        p_yes = max(0.01, min(0.99, p_yes))

        # confidence
        confidence = str(raw.get("confidence", "medium")).lower()
        if confidence not in self._VALID_CONFIDENCE:
            confidence = "medium"

        # action — recompute from p_yes if missing or invalid
        action = str(raw.get("action", "")).lower()
        if action not in self._VALID_ACTIONS:
            if p_yes > 0.55:
                action = "buy_yes"
            elif p_yes < 0.45:
                action = "buy_no"
            else:
                action = "hold"

        # regime
        regime = str(raw.get("regime", "uncertain")).strip() or "uncertain"

        # summary
        summary = str(raw.get("summary", "")).strip()

        # list fields
        drivers = [str(d) for d in raw.get("drivers", []) if d]
        invalidators = [str(i) for i in raw.get("invalidators", []) if i]

        return MiroSignal(
            signal_id=str(uuid.uuid4()),
            schema_version=SCHEMA_VERSION,
            report_id=report_id,
            simulation_id=simulation_id,
            generated_at=datetime.now(timezone.utc).isoformat(),
            p_yes=p_yes,
            confidence=confidence,
            action=action,
            regime=regime,
            summary=summary,
            drivers=drivers,
            invalidators=invalidators,
        )

    @staticmethod
    def _salvage(raw_text: str) -> Optional[dict]:
        """
        Last-resort fallback: scan for any float that looks like a probability
        and a YES/NO sentiment to construct a minimal signal dict.
        """
        import re

        prob_match = re.search(r'\b(0\.\d+|1\.0+|0)\b', raw_text)
        if not prob_match:
            return None

        try:
            p = float(prob_match.group())
        except ValueError:
            return None

        text_lower = raw_text.lower()
        if "high" in text_lower:
            confidence = "high"
        elif "low" in text_lower:
            confidence = "low"
        else:
            confidence = "medium"

        return {
            "p_yes": p,
            "confidence": confidence,
            "action": "buy_yes" if p > 0.55 else ("buy_no" if p < 0.45 else "hold"),
            "regime": "uncertain",
            "summary": "Signal salvaged from partial LLM output.",
            "drivers": [],
            "invalidators": [],
        }
