from pathlib import Path
from app.services.interviews.base import PersonaRecord, MemoryDigest
from app.services.interviews.delphi import (
    DelphiSubagent, extract_themes, convergence_metrics,
)

INSTRUMENT = Path(__file__).resolve().parents[2] / "scripts" / "instruments" / "delphi_v1.yaml"

class _Mem:
    def get_digest(self, agent_id, max_chars=2000):
        return MemoryDigest(text="x", available=True)

class _R1LLM:
    def chat_json(self, messages, temperature=0.0, max_tokens=None, **kw):
        return {"answers": {
            "q1": "Klimawandel, Quoten, Generationswechsel",
            "q2": "MSC, Aquakultur",
            "q3": "Russland, EU-Politik",
            "q4": "Verbraucherpreise",
        }}

class _R2LLM:
    def chat_json(self, messages, temperature=0.0, max_tokens=None, **kw):
        return {"ratings": {f"theme_{i}": {"importance": 4, "plausibility": 3} for i in range(5)}}

class _ExtractLLM:
    def chat_json(self, messages, temperature=0.0, max_tokens=None, **kw):
        return {"themes": [
            {"theme_id": "theme_0", "label": "Klimawandel"},
            {"theme_id": "theme_1", "label": "Quoten"},
            {"theme_id": "theme_2", "label": "MSC"},
            {"theme_id": "theme_3", "label": "EU-Politik"},
            {"theme_id": "theme_4", "label": "Generationswechsel"},
        ]}

def test_delphi_round1_open():
    sub = DelphiSubagent(llm=_R1LLM(), memory=_Mem(), instrument_path=INSTRUMENT)
    persona = PersonaRecord(agent_id=2, name="A", persona="p")
    resp = sub.administer_round1(persona)
    assert resp.round == 1
    assert len(resp.answers) == 4

def test_extract_themes_aggregates():
    from app.models.interview import DelphiOpenResponse
    r1 = [DelphiOpenResponse(agent_id=i, answers={"q1": "Klimawandel", "q2": "MSC"}) for i in range(3)]
    themes = extract_themes(r1, llm=_ExtractLLM())
    assert len(themes) == 5
    assert all("theme_id" in t for t in themes)

def test_convergence_metrics():
    from app.models.interview import DelphiRatingResponse
    r2 = [DelphiRatingResponse(agent_id=i, round=2,
            ratings={"t1": {"importance": 3, "plausibility": 3}}) for i in range(5)]
    r3 = [DelphiRatingResponse(agent_id=i, round=3,
            ratings={"t1": {"importance": 4, "plausibility": 4}}) for i in range(5)]
    conv = convergence_metrics(r2, r3)
    assert "t1" in conv
    assert conv["t1"]["delta_iqr_importance"] is not None


def test_delphi_r2_accepts_string_ratings():
    """Delphi R2/R3 ratings should accept stringified importance/plausibility ints."""
    from app.services.interviews.base import PersonaRecord, MemoryDigest
    from app.services.interviews.delphi import DelphiSubagent
    from pathlib import Path as _P

    class _Mem:
        def get_digest(self, agent_id, max_chars=2000):
            return MemoryDigest(text="x", available=True)

    class _StringLLM:
        def chat_json(self, messages, temperature=0.0, max_tokens=None, **kw):
            return {"ratings": {
                "t1": {"importance": "4", "plausibility": "3"},
                "t2": {"importance": "5", "plausibility": "2"},
            }}

    inst = _P(__file__).resolve().parents[2] / "scripts" / "instruments" / "delphi_v1.yaml"
    sub = DelphiSubagent(llm=_StringLLM(), memory=_Mem(), instrument_path=inst)
    persona = PersonaRecord(agent_id=1, name="A", persona="p")
    themes = [{"theme_id": "t1", "label": "T1"}, {"theme_id": "t2", "label": "T2"}]
    resp = sub.administer_round2(persona, themes)
    assert resp.ratings["t1"]["importance"] == 4
    assert isinstance(resp.ratings["t1"]["importance"], int)
