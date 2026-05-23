import json
import pytest
from pathlib import Path
from app.config import Config
from app.models.interview import SubagentKind, InterviewPhase
from app.services.interviews.adapters import FileSystemPersonaProvider
from app.services.interviews.base import MemoryDigest
from app.services.interviews.zep_writer import InterviewZepWriter
from app.services.interview_orchestrator import InterviewOrchestrator
from app.services.interview_synthesizer import InterviewSynthesizer
from app.utils.llm_client import LLMClient

pytestmark = pytest.mark.integration

INST_DIR = Path(__file__).resolve().parents[2] / "scripts" / "instruments"

class _NullUpdater:
    def __init__(self): self.events = []
    def add_text_episode(self, graph_id, text): self.events.append(text)

class _StaticMem:
    def get_digest(self, agent_id, max_chars=2000):
        return MemoryDigest(text=f"agent {agent_id} memory snippet", available=True)

@pytest.fixture
def seeded_uploads(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_STUB_MODE", "true")
    Config.LLM_STUB_MODE = True
    sim_dir = tmp_path / "simulations" / "intg_sim"
    sim_dir.mkdir(parents=True)
    profiles = [{"user_id": i, "user_name": f"u{i}", "name": f"A{i}",
                 "persona": "stakeholder p", "profession": "fisher"} for i in range(5)]
    (sim_dir / "reddit_profiles.json").write_text(json.dumps(profiles), encoding="utf-8")
    return tmp_path

def _make_orch(tmp_path):
    sim_dir = tmp_path / "simulations" / "intg_sim"
    personas = FileSystemPersonaProvider(
        reddit_path=sim_dir / "reddit_profiles.json", twitter_path=None,
    )
    llm = LLMClient(api_key="x", base_url="x", model="x")
    updater = _NullUpdater()
    writer = InterviewZepWriter(memory_updater=updater, graph_id="g")
    return InterviewOrchestrator(
        llm=llm, memory=_StaticMem(), personas=personas,
        instrument_dir=INST_DIR, store_root=tmp_path, sim_id="intg_sim",
        zep_writer=writer, max_workers=2, language="de",
    )

def test_pipeline_runs_pre_then_post_then_synthesis(seeded_uploads):
    tmp = seeded_uploads
    orch = _make_orch(tmp)

    pre = orch.run_pre()
    assert pre["longitudinal"]["n_responded"] >= 1

    post = orch.run_post()
    assert "longitudinal" in post
    assert "diversity" in post
    assert "scenario" in post
    assert "delphi" in post

    synth = InterviewSynthesizer(store=orch.store)
    report = synth.run()
    assert "Stakeholder Interview Synthesis" in report
    assert "Limitations" in report

    csv_path = orch.store.base / "synthesis" / "exports" / "all_responses.csv"
    assert csv_path.exists()
    lines = csv_path.read_text().splitlines()
    assert lines[0].startswith("agent_id,") or "agent_id" in lines[0]

def test_idempotent_rerun_creates_new_run_id(seeded_uploads):
    tmp = seeded_uploads
    orch = _make_orch(tmp)
    orch.run_pre()
    first = orch.run_post()
    second = orch.rerun(SubagentKind.SCENARIO)
    first_scn = first["scenario"]["run_dir"]
    second_scn = second["scenario"]["run_dir"]
    assert first_scn != second_scn
