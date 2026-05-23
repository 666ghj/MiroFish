from __future__ import annotations
import json
import statistics
from pathlib import Path
from typing import Optional
import yaml
from app.models.interview import (
    DelphiOpenResponse, DelphiRatingResponse,
)
from app.services.interviews.base import StakeholderInterviewer, PersonaRecord, coerce_int


class DelphiSubagent:
    def __init__(self, llm, memory, instrument_path: Path, language: str = "de"):
        with Path(instrument_path).open("r", encoding="utf-8") as f:
            self.instrument = yaml.safe_load(f)
        self.interviewer = StakeholderInterviewer(llm=llm, memory=memory, language=language)
        self.llm = llm
        self.language = language

    # --- Round 1: open questions ---
    def _r1_schema(self) -> str:
        return json.dumps({
            "answers": {q["question_id"]: "<string>" for q in self.instrument["questions"]}
        }, ensure_ascii=False)

    def _r1_prompt(self) -> str:
        lines = ["Bitte beantworten Sie offen:" if self.language == "de" else "Please answer openly:"]
        for q in self.instrument["questions"]:
            txt = q["de"] if self.language == "de" else q["en"]
            lines.append(f"[{q['question_id']}] {txt}")
        return "\n".join(lines)

    def _r1_validate(self, raw: dict) -> Optional[dict]:
        if not isinstance(raw, dict): return None
        ans = raw.get("answers")
        if not isinstance(ans, dict): return None
        required = {q["question_id"] for q in self.instrument["questions"]}
        if not required.issubset(ans.keys()): return None
        return raw

    def administer_round1(self, persona: PersonaRecord) -> DelphiOpenResponse:
        raw = self.interviewer.ask_in_character(
            persona, user_prompt=self._r1_prompt(),
            schema_hint=self._r1_schema(), validate=self._r1_validate,
        )
        return DelphiOpenResponse(agent_id=persona.agent_id, round=1,
                                  answers={k: str(v) for k, v in raw["answers"].items()})

    # --- Round 2: rate themes ---
    def _r2_schema(self, theme_ids: list[str]) -> str:
        return json.dumps({
            "ratings": {tid: {"importance": "<int 1-5>", "plausibility": "<int 1-5>"} for tid in theme_ids}
        }, ensure_ascii=False)

    def _r2_prompt(self, themes: list[dict]) -> str:
        head = "Bewerten Sie jedes Thema nach Wichtigkeit (1-5) und Plausibilität (1-5):" if self.language == "de" \
               else "Rate each theme on importance (1-5) and plausibility (1-5):"
        body = [f"- [{t['theme_id']}] {t['label']}" for t in themes]
        return head + "\n" + "\n".join(body)

    def _r2_validate(self, theme_ids: list[str]):
        def v(raw: dict) -> Optional[dict]:
            if not isinstance(raw, dict): return None
            ratings = raw.get("ratings", {})
            if set(ratings.keys()) != set(theme_ids): return None
            for tid, r in ratings.items():
                if not isinstance(r, dict): return None
                coerced: dict[str, int] = {}
                for key in ("importance", "plausibility"):
                    iv = coerce_int(r.get(key))
                    if iv is None or not 1 <= iv <= 5: return None
                    coerced[key] = iv
                ratings[tid] = coerced
            return raw
        return v

    def administer_round2(self, persona: PersonaRecord, themes: list[dict]) -> DelphiRatingResponse:
        theme_ids = [t["theme_id"] for t in themes]
        raw = self.interviewer.ask_in_character(
            persona, user_prompt=self._r2_prompt(themes),
            schema_hint=self._r2_schema(theme_ids), validate=self._r2_validate(theme_ids),
        )
        return DelphiRatingResponse(agent_id=persona.agent_id, round=2,
                                    ratings={k: dict(v) for k, v in raw["ratings"].items()})

    # --- Round 3: revise after seeing group stats ---
    def administer_round3(
        self, persona: PersonaRecord, themes: list[dict], group_stats: dict, own_r2: DelphiRatingResponse
    ) -> DelphiRatingResponse:
        theme_ids = [t["theme_id"] for t in themes]
        head = ("Sie sehen unten die anonymisierten Gruppenwerte (Median, IQR). "
                "Bitte überarbeiten Sie Ihre Bewertungen, wenn Sie möchten, und begründen Sie kurz.") \
               if self.language == "de" else \
               ("Below are the anonymised group values (median, IQR). "
                "Please revise your ratings if you wish and add a short justification.")
        ctx_lines = []
        for t in themes:
            tid = t["theme_id"]
            gs = group_stats.get(tid, {})
            own = own_r2.ratings.get(tid, {})
            ctx_lines.append(
                f"[{tid}] {t['label']} — group importance median={gs.get('imp_median')}, "
                f"IQR={gs.get('imp_iqr')}; plausibility median={gs.get('plaus_median')}, "
                f"IQR={gs.get('plaus_iqr')}. Your R2: imp={own.get('importance')}, plaus={own.get('plausibility')}."
            )
        prompt = head + "\n\n" + "\n".join(ctx_lines)
        schema = json.dumps({
            "ratings": {tid: {"importance": "<int 1-5>", "plausibility": "<int 1-5>"} for tid in theme_ids},
            "justification": "<string>",
        }, ensure_ascii=False)

        def validate(raw):
            if not isinstance(raw, dict): return None
            ratings = raw.get("ratings", {})
            if set(ratings.keys()) != set(theme_ids): return None
            for tid, r in ratings.items():
                if not isinstance(r, dict): return None
                coerced: dict[str, int] = {}
                for key in ("importance", "plausibility"):
                    iv = coerce_int(r.get(key))
                    if iv is None or not 1 <= iv <= 5: return None
                    coerced[key] = iv
                ratings[tid] = coerced
            return raw

        raw = self.interviewer.ask_in_character(persona, user_prompt=prompt,
                                                schema_hint=schema, validate=validate)
        return DelphiRatingResponse(
            agent_id=persona.agent_id, round=3,
            ratings={k: dict(v) for k, v in raw["ratings"].items()},
            justification=raw.get("justification"),
        )


def extract_themes(round1: list[DelphiOpenResponse], llm) -> list[dict]:
    text_blocks = []
    for r in round1:
        for qid, ans in r.answers.items():
            text_blocks.append(f"[agent {r.agent_id} {qid}] {ans}")
    schema = json.dumps({"themes": [{"theme_id": "<string>", "label": "<short string>"}]}, ensure_ascii=False)
    messages = [
        {"role": "system", "content":
            "You extract distinct thematic codes from open-ended German fisheries survey responses. "
            f"Return JSON ONLY matching: {schema}. Use stable theme_ids of form theme_0, theme_1, …"},
        {"role": "user", "content": "Responses:\n" + "\n".join(text_blocks) + "\n\nReturn up to 12 distinct themes."},
    ]
    raw = llm.chat_json(messages=messages, temperature=0.0)
    themes = raw.get("themes", []) if isinstance(raw, dict) else []
    out = []
    for i, t in enumerate(themes):
        if isinstance(t, dict) and "label" in t:
            out.append({"theme_id": t.get("theme_id") or f"theme_{i}", "label": str(t["label"])})
    return out


def _iqr(xs: list[float]) -> float:
    if not xs: return 0.0
    xs = sorted(xs)
    q1 = statistics.quantiles(xs, n=4)[0] if len(xs) >= 4 else xs[0]
    q3 = statistics.quantiles(xs, n=4)[2] if len(xs) >= 4 else xs[-1]
    return q3 - q1


def convergence_metrics(r2: list[DelphiRatingResponse], r3: list[DelphiRatingResponse]) -> dict:
    by_r2 = {r.agent_id: r for r in r2}
    by_r3 = {r.agent_id: r for r in r3}
    themes: set[str] = set()
    for r in r2 + r3:
        themes.update(r.ratings.keys())
    out: dict[str, dict] = {}
    for t in sorted(themes):
        imp_r2 = [by_r2[a].ratings[t]["importance"] for a in by_r2 if t in by_r2[a].ratings]
        imp_r3 = [by_r3[a].ratings[t]["importance"] for a in by_r3 if t in by_r3[a].ratings]
        plaus_r2 = [by_r2[a].ratings[t]["plausibility"] for a in by_r2 if t in by_r2[a].ratings]
        plaus_r3 = [by_r3[a].ratings[t]["plausibility"] for a in by_r3 if t in by_r3[a].ratings]
        out[t] = {
            "imp_median_r2": statistics.median(imp_r2) if imp_r2 else None,
            "imp_median_r3": statistics.median(imp_r3) if imp_r3 else None,
            "imp_iqr_r2": _iqr(imp_r2),
            "imp_iqr_r3": _iqr(imp_r3),
            "delta_iqr_importance": _iqr(imp_r3) - _iqr(imp_r2),
            "plaus_iqr_r2": _iqr(plaus_r2),
            "plaus_iqr_r3": _iqr(plaus_r3),
            "delta_iqr_plausibility": _iqr(plaus_r3) - _iqr(plaus_r2),
        }
    return out


def group_stats_from_r2(r2: list[DelphiRatingResponse]) -> dict:
    themes: set[str] = set()
    for r in r2: themes.update(r.ratings.keys())
    stats: dict[str, dict] = {}
    for t in themes:
        imps = [r.ratings[t]["importance"] for r in r2 if t in r.ratings]
        plauss = [r.ratings[t]["plausibility"] for r in r2 if t in r.ratings]
        stats[t] = {
            "imp_median": statistics.median(imps) if imps else None,
            "imp_iqr": _iqr(imps),
            "plaus_median": statistics.median(plauss) if plauss else None,
            "plaus_iqr": _iqr(plauss),
        }
    return stats
