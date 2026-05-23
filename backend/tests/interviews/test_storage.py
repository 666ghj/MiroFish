import json
from pathlib import Path
from app.models.interview import (
    LikertResponse, InterviewPhase, SubagentKind,
)
from app.services.interviews.storage import InterviewStore

def test_run_directory_layout(tmp_path):
    store = InterviewStore(root=tmp_path, sim_id="sim42")
    run_dir = store.start_run(phase=InterviewPhase.T0, subagent=SubagentKind.LONGITUDINAL)
    assert run_dir.exists()
    assert run_dir.parent.name == "longitudinal"
    assert run_dir.parent.parent.name == "T0"

def test_append_response(tmp_path):
    store = InterviewStore(root=tmp_path, sim_id="sim42")
    run_dir = store.start_run(phase=InterviewPhase.T0, subagent=SubagentKind.LONGITUDINAL)
    r = LikertResponse(agent_id=1, phase=InterviewPhase.T0,
                       responses={"a": 3}, confidence={"a": 0.5})
    store.append_response(run_dir, r)
    contents = (run_dir / "responses.jsonl").read_text()
    assert json.loads(contents.splitlines()[0])["agent_id"] == 1

def test_write_aggregate_and_latest_pointer(tmp_path):
    store = InterviewStore(root=tmp_path, sim_id="sim42")
    run_dir = store.start_run(phase=InterviewPhase.T1, subagent=SubagentKind.SCENARIO)
    store.write_aggregate(run_dir, {"k": 1})
    store.mark_latest(run_dir)
    latest = (run_dir.parent / "latest.json").read_text()
    assert json.loads(latest)["run_dir"].endswith(run_dir.name)

def test_audit_log_append(tmp_path):
    store = InterviewStore(root=tmp_path, sim_id="sim42")
    run_dir = store.start_run(phase=InterviewPhase.T0, subagent=SubagentKind.DELPHI)
    store.audit(run_dir, agent_id=7, event="schema_violation", detail="missing key x")
    audit = (run_dir / "audit.jsonl").read_text()
    assert "schema_violation" in audit
