from pathlib import Path
import pytest
from app.models.interview import InterviewPhase
from app.services.interviews.base import PersonaRecord, MemoryDigest
from app.services.interviews.longitudinal import LongitudinalSubagent, run_aggregate


class _FakeMem:
    def get_digest(self, agent_id, max_chars=2000):
        return MemoryDigest(text="x", available=True)


class _CannedLLM:
    def __init__(self): self.n = 0
    def chat_json(self, messages, temperature=0.0, max_tokens=None, **kw):
        self.n += 1
        return {
            "responses": {
                "stk_1": 4, "stk_2": 3, "stk_3": 5,
                "gov_1": 3, "gov_2": 4, "gov_3": 2,
                "mkt_1": 5, "mkt_2": 3, "mkt_3": 4,
                "clm_1": 2, "clm_2": 4, "clm_3": 5,
            },
            "confidence": {
                "stk_1": 0.8, "stk_2": 0.7, "stk_3": 0.9,
                "gov_1": 0.6, "gov_2": 0.7, "gov_3": 0.5,
                "mkt_1": 0.7, "mkt_2": 0.6, "mkt_3": 0.8,
                "clm_1": 0.5, "clm_2": 0.7, "clm_3": 0.6,
            },
            "open_comment": "test",
        }


INSTRUMENT = Path(__file__).resolve().parents[2] / "scripts" / "instruments" / "longitudinal_v1.yaml"


def test_longitudinal_administer_one_agent():
    sub = LongitudinalSubagent(llm=_CannedLLM(), memory=_FakeMem(), instrument_path=INSTRUMENT)
    persona = PersonaRecord(agent_id=3, name="A", persona="p")
    resp = sub.administer(persona, phase=InterviewPhase.T0)
    assert resp.agent_id == 3
    assert resp.phase == InterviewPhase.T0
    assert set(resp.responses.keys()) >= {"stk_1", "gov_1", "mkt_1", "clm_1"}


def test_longitudinal_aggregate_delta():
    from app.models.interview import LikertResponse
    t0 = [LikertResponse(agent_id=i, phase=InterviewPhase.T0,
                         responses={"stk_1": 3, "gov_1": 4},
                         confidence={"stk_1": 0.8, "gov_1": 0.8}) for i in range(5)]
    t1 = [LikertResponse(agent_id=i, phase=InterviewPhase.T1,
                         responses={"stk_1": 4, "gov_1": 4},
                         confidence={"stk_1": 0.8, "gov_1": 0.8}) for i in range(5)]
    agg = run_aggregate(t0, t1)
    assert agg["per_item"]["stk_1"]["mean_delta"] == 1.0
    assert agg["per_item"]["gov_1"]["mean_delta"] == 0.0
    assert agg["n_paired"] == 5
