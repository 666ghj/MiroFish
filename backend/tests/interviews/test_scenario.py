from pathlib import Path
from app.services.interviews.base import PersonaRecord, MemoryDigest
from app.services.interviews.scenario import ScenarioSubagent, polarity_matrix

INSTRUMENT = Path(__file__).resolve().parents[2] / "scripts" / "instruments" / "scenario_v1.yaml"

class _Mem:
    def get_digest(self, agent_id, max_chars=2000):
        return MemoryDigest(text="x", available=True)

class _LLM:
    def chat_json(self, messages, temperature=0.0, max_tokens=None, **kw):
        return {"ratings": {sid: {
            "desirability": 4, "plausibility": 3, "impact_on_my_group": 5, "fairness": 3,
            "if_woke_up_response": f"act-on-{sid}",
        } for sid in ("S1", "S2", "S3", "S4")}}

def test_scenario_administer():
    sub = ScenarioSubagent(llm=_LLM(), memory=_Mem(), instrument_path=INSTRUMENT)
    persona = PersonaRecord(agent_id=1, name="A", persona="p")
    resp = sub.administer(persona)
    assert set(resp.ratings.keys()) == {"S1", "S2", "S3", "S4"}
    assert resp.ratings["S1"].desirability == 4

def test_polarity_matrix():
    from app.models.interview import ScenarioResponse, ScenarioRating
    responses = [ScenarioResponse(agent_id=i, ratings={
        "S1": ScenarioRating(desirability=5, plausibility=4, impact_on_my_group=5, fairness=4,
                              if_woke_up_response="x"),
    }) for i in range(3)]
    m = polarity_matrix(responses)
    assert "S1" in m
    assert m["S1"]["mean_desirability"] == 5
    assert m["S1"]["n"] == 3


def test_scenario_accepts_string_likert_values():
    """Scenario ratings should accept stringified ints across all 4 dimensions."""
    from app.services.interviews.base import PersonaRecord, MemoryDigest
    from app.services.interviews.scenario import ScenarioSubagent
    from pathlib import Path as _P

    class _Mem:
        def get_digest(self, agent_id, max_chars=2000):
            return MemoryDigest(text="x", available=True)

    class _StringLLM:
        def chat_json(self, messages, temperature=0.0, max_tokens=None, **kw):
            return {"ratings": {sid: {
                "desirability": "4", "plausibility": "3",
                "impact_on_my_group": "5", "fairness": "3",
                "if_woke_up_response": f"act-{sid}",
            } for sid in ("S1","S2","S3","S4")}}

    inst = _P(__file__).resolve().parents[2] / "scripts" / "instruments" / "scenario_v1.yaml"
    sub = ScenarioSubagent(llm=_StringLLM(), memory=_Mem(), instrument_path=inst)
    persona = PersonaRecord(agent_id=3, name="A", persona="p")
    resp = sub.administer(persona)
    assert resp.ratings["S1"].desirability == 4
    assert isinstance(resp.ratings["S1"].desirability, int)
