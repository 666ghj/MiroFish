from __future__ import annotations
import json
import statistics
from pathlib import Path
from typing import Optional
import yaml
from app.models.interview import ScenarioRating, ScenarioResponse
from app.services.interviews.base import StakeholderInterviewer, PersonaRecord

class ScenarioSubagent:
    def __init__(self, llm, memory, instrument_path: Path, language: str = "de"):
        with Path(instrument_path).open("r", encoding="utf-8") as f:
            self.instrument = yaml.safe_load(f)
        self.interviewer = StakeholderInterviewer(llm=llm, memory=memory, language=language)
        self.language = language

    def _schema_hint(self) -> str:
        sids = [s["scenario_id"] for s in self.instrument["scenarios"]]
        return json.dumps({
            "ratings": {sid: {
                "desirability": "<int 1-7>",
                "plausibility": "<int 1-7>",
                "impact_on_my_group": "<int 1-7>",
                "fairness": "<int 1-7>",
                "if_woke_up_response": "<string>",
            } for sid in sids}
        }, ensure_ascii=False)

    def _user_prompt(self) -> str:
        head = ("Bewerten Sie jedes der folgenden Szenarien auf vier Dimensionen (1-7) "
                "und beantworten Sie kurz, was Sie tun würden, wenn Sie in dieser Welt aufwachten.") \
               if self.language == "de" else \
               ("Rate each of the following scenarios on four dimensions (1-7) "
                "and briefly answer what you would do if you woke up in this world.")
        blocks = []
        for s in self.instrument["scenarios"]:
            label = s["label_de"] if self.language == "de" else s["label_en"]
            desc = s["description_de"] if self.language == "de" else s["description_en"]
            blocks.append(f"--- {s['scenario_id']}: {label} ---\n{desc}")
        return head + "\n\n" + "\n\n".join(blocks)

    def _validate(self, raw: dict) -> Optional[dict]:
        if not isinstance(raw, dict): return None
        sids = {s["scenario_id"] for s in self.instrument["scenarios"]}
        ratings = raw.get("ratings", {})
        if set(ratings.keys()) != sids: return None
        for v in ratings.values():
            if not isinstance(v, dict): return None
            for k in ("desirability", "plausibility", "impact_on_my_group", "fairness"):
                if not isinstance(v.get(k), int) or not 1 <= v[k] <= 7: return None
            if not isinstance(v.get("if_woke_up_response", ""), str): return None
        return raw

    def administer(self, persona: PersonaRecord) -> ScenarioResponse:
        raw = self.interviewer.ask_in_character(
            persona, user_prompt=self._user_prompt(),
            schema_hint=self._schema_hint(), validate=self._validate,
        )
        ratings = {sid: ScenarioRating(**v) for sid, v in raw["ratings"].items()}
        return ScenarioResponse(agent_id=persona.agent_id, ratings=ratings)

def polarity_matrix(responses: list[ScenarioResponse]) -> dict:
    matrix: dict[str, dict] = {}
    sids: set[str] = set()
    for r in responses: sids.update(r.ratings.keys())
    for sid in sorted(sids):
        vals = [r.ratings[sid] for r in responses if sid in r.ratings]
        if not vals:
            matrix[sid] = {"n": 0}
            continue
        matrix[sid] = {
            "n": len(vals),
            "mean_desirability": statistics.mean(v.desirability for v in vals),
            "mean_plausibility": statistics.mean(v.plausibility for v in vals),
            "mean_impact": statistics.mean(v.impact_on_my_group for v in vals),
            "mean_fairness": statistics.mean(v.fairness for v in vals),
            "sd_desirability": statistics.pstdev([v.desirability for v in vals]) if len(vals) > 1 else 0.0,
            "sd_plausibility": statistics.pstdev([v.plausibility for v in vals]) if len(vals) > 1 else 0.0,
        }
    return matrix
