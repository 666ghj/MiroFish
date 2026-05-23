from __future__ import annotations
import json
import math
from pathlib import Path
from typing import Optional
from app.models.interview import (
    LikertInstrument, LikertResponse, InterviewPhase,
)
from app.services.interviews.base import StakeholderInterviewer, PersonaRecord, coerce_int
from app.services.interviews.instrument_loader import load_likert_instrument


class LongitudinalSubagent:
    def __init__(self, llm, memory, instrument_path: Path, language: str = "de"):
        self.instrument: LikertInstrument = load_likert_instrument(Path(instrument_path))
        self.interviewer = StakeholderInterviewer(llm=llm, memory=memory, language=language)
        self.language = language

    def _schema_hint(self) -> str:
        ids = [i.item_id for i in self.instrument.items]
        return json.dumps({
            "responses": {k: "<int 1-5>" for k in ids},
            "confidence": {k: "<float 0-1>" for k in ids},
            "open_comment": "<string, optional>",
        }, ensure_ascii=False)

    def _user_prompt(self) -> str:
        lines = [
            "Bitte bewerten Sie die folgenden Aussagen auf einer Skala von 1 (lehne stark ab) bis 5 (stimme stark zu)."
            if self.language == "de"
            else "Please rate the following statements on a scale from 1 (strongly disagree) to 5 (strongly agree)."
        ]
        for it in self.instrument.items:
            txt = it.de if self.language == "de" else it.en
            lines.append(f"- [{it.item_id}] {txt}")
        return "\n".join(lines)

    def _validator(self, raw: dict) -> Optional[dict]:
        if not isinstance(raw, dict):
            return None
        resp = raw.get("responses")
        if not isinstance(resp, dict):
            return None
        required = {it.item_id for it in self.instrument.items}
        if not required.issubset(resp.keys()):
            return None
        coerced: dict[str, int] = {}
        for k, v in resp.items():
            iv = coerce_int(v)
            if iv is None or not 1 <= iv <= 5:
                return None
            coerced[k] = iv
        raw["responses"] = coerced
        return raw

    def administer(self, persona: PersonaRecord, phase: InterviewPhase) -> LikertResponse:
        raw = self.interviewer.ask_in_character(
            persona,
            user_prompt=self._user_prompt(),
            schema_hint=self._schema_hint(),
            validate=self._validator,
        )
        return LikertResponse(
            agent_id=persona.agent_id,
            phase=phase,
            responses={k: int(v) for k, v in raw["responses"].items()},
            confidence={k: float(v) for k, v in raw.get("confidence", {}).items()},
            open_comment=raw.get("open_comment"),
        )


def run_aggregate(t0: list[LikertResponse], t1: list[LikertResponse]) -> dict:
    by_t0 = {r.agent_id: r for r in t0}
    by_t1 = {r.agent_id: r for r in t1}
    paired = sorted(set(by_t0) & set(by_t1))
    items: set[str] = set()
    for r in t0 + t1:
        items.update(r.responses.keys())
    per_item: dict[str, dict] = {}
    for it in sorted(items):
        deltas = []
        for aid in paired:
            v0 = by_t0[aid].responses.get(it)
            v1 = by_t1[aid].responses.get(it)
            if v0 is None or v1 is None:
                continue
            deltas.append(v1 - v0)
        if not deltas:
            per_item[it] = {"mean_delta": None, "n": 0}
            continue
        m = sum(deltas) / len(deltas)
        var = sum((d - m) ** 2 for d in deltas) / max(len(deltas) - 1, 1)
        per_item[it] = {
            "mean_delta": m,
            "sd_delta": math.sqrt(var),
            "n": len(deltas),
            "n_positive": sum(1 for d in deltas if d > 0),
            "n_negative": sum(1 for d in deltas if d < 0),
        }
    per_agent: dict[int, dict] = {}
    for aid in paired:
        r0 = by_t0[aid].responses
        r1 = by_t1[aid].responses
        common = set(r0) & set(r1)
        total = sum(abs(r1[k] - r0[k]) for k in common)
        per_agent[aid] = {"total_abs_drift": total, "n_items": len(common)}
    return {
        "n_paired": len(paired),
        "n_t0_only": len(set(by_t0) - set(by_t1)),
        "n_t1_only": len(set(by_t1) - set(by_t0)),
        "per_item": per_item,
        "per_agent": per_agent,
    }
