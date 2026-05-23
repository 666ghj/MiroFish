from pathlib import Path
import pytest
from app.models.interview import InterviewPhase, SubagentKind
from app.services.interviews.base import PersonaRecord, MemoryDigest
from app.services.interview_orchestrator import (
    InterviewOrchestrator, PersonaProvider,
)

INST_DIR = Path(__file__).resolve().parents[2] / "scripts" / "instruments"

class _Mem:
    def get_digest(self, agent_id, max_chars=2000):
        return MemoryDigest(text="x", available=True)

class _LLM:
    def chat_json(self, messages, temperature=0.0, max_tokens=None, **kw):
        sys_text = next((m["content"] for m in messages if m["role"] == "system"), "")
        if "longitudinal" in sys_text or "stk_" in (messages[-1].get("content") or ""):
            return {
                "responses": {k: 3 for k in ("stk_1","stk_2","stk_3","gov_1","gov_2","gov_3",
                                             "mkt_1","mkt_2","mkt_3","clm_1","clm_2","clm_3")},
                "confidence": {}, "open_comment": "ok",
            }
        return {}

class _Personas(PersonaProvider):
    def __init__(self, n=3):
        self._items = [PersonaRecord(agent_id=i, name=f"A{i}", persona="p") for i in range(n)]
    def all(self): return list(self._items)

class _NoopZep:
    def write_per_agent(self, *a, **kw): pass
    def write_aggregate(self, *a, **kw): pass

def test_pre_phase_runs_longitudinal_only(tmp_path):
    orch = InterviewOrchestrator(
        llm=_LLM(), memory=_Mem(), personas=_Personas(3),
        instrument_dir=INST_DIR, store_root=tmp_path, sim_id="sim1",
        zep_writer=_NoopZep(), max_workers=2,
    )
    result = orch.run_pre()
    assert result["longitudinal"]["n_responded"] == 3
    assert "diversity" not in result  # only longitudinal in pre-phase

def test_partial_failure_does_not_kill_run(tmp_path):
    class _FlakyLLM:
        def __init__(self): self.n = 0
        def chat_json(self, messages, temperature=0.0, max_tokens=None, **kw):
            self.n += 1
            if self.n % 2 == 0:
                raise RuntimeError("simulated LLM 5xx")
            return {
                "responses": {k: 3 for k in ("stk_1","stk_2","stk_3","gov_1","gov_2","gov_3",
                                             "mkt_1","mkt_2","mkt_3","clm_1","clm_2","clm_3")},
                "confidence": {}, "open_comment": "ok",
            }
    orch = InterviewOrchestrator(
        llm=_FlakyLLM(), memory=_Mem(), personas=_Personas(4),
        instrument_dir=INST_DIR, store_root=tmp_path, sim_id="sim2",
        zep_writer=_NoopZep(), max_workers=1,
    )
    result = orch.run_pre()
    assert result["longitudinal"]["n_responded"] < 4
    assert result["longitudinal"]["n_failed"] > 0


def test_schema_failure_audit_captures_raw_llm_output(tmp_path):
    """When an agent's LLM output fails the schema validator twice, the audit log
    should preserve both raw outputs so we can debug what the model actually said."""
    bad_response = {"wrong": "shape, no responses key"}
    class _BadLLM:
        def chat_json(self, messages, temperature=0.0, max_tokens=None, **kw):
            return bad_response  # always fails Longitudinal validator
    orch = InterviewOrchestrator(
        llm=_BadLLM(), memory=_Mem(), personas=_Personas(1),
        instrument_dir=INST_DIR, store_root=tmp_path, sim_id="sim3",
        zep_writer=_NoopZep(), max_workers=1,
    )
    result = orch.run_pre()
    assert result["longitudinal"]["n_responded"] == 0
    assert result["longitudinal"]["n_failed"] == 1

    import json as _j
    run_dir = Path(result["longitudinal"]["run_dir"])
    audit_path = run_dir / "audit.jsonl"
    lines = audit_path.read_text(encoding="utf-8").splitlines()
    assert lines, "audit.jsonl should not be empty"
    entry = _j.loads(lines[0])
    assert entry["event"] == "schema_validation_failure"
    assert entry["agent_id"] == 0
    detail = entry["detail"]
    assert detail["label"] == "longitudinal_T0"
    assert len(detail["attempts"]) == 2
    assert detail["attempts"][0]["raw"] == bad_response
    assert detail["attempts"][1]["raw"] == bad_response
