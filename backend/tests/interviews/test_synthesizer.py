import json
from pathlib import Path
from app.services.interviews.storage import InterviewStore
from app.models.interview import InterviewPhase, SubagentKind, LikertResponse
from app.services.interview_synthesizer import InterviewSynthesizer

def _seed_minimal(tmp_path: Path) -> InterviewStore:
    store = InterviewStore(root=tmp_path, sim_id="s1")
    rd = store.start_run(InterviewPhase.T0, SubagentKind.LONGITUDINAL)
    for i in range(3):
        store.append_response(rd, LikertResponse(
            agent_id=i, phase=InterviewPhase.T0,
            responses={"stk_1": 3, "gov_1": 3}, confidence={"stk_1": 0.5, "gov_1": 0.5},
        ))
    store.write_aggregate(rd, {"per_item": {}, "n_paired": 0})
    store.mark_latest(rd)
    return store

def test_synthesizer_runs_with_partial_data(tmp_path):
    store = _seed_minimal(tmp_path)
    synth = InterviewSynthesizer(store=store)
    report = synth.run()
    assert "limitations" in report.lower()
    assert "stub mode" in report.lower() or "n_responded" in report.lower()

def test_synthesizer_writes_files(tmp_path):
    store = _seed_minimal(tmp_path)
    synth = InterviewSynthesizer(store=store)
    synth.run()
    files = list((store.base / "synthesis").iterdir())
    names = {f.name for f in files}
    assert "report.md" in names
