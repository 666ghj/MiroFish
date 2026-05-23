from app.models.interview import (
    LikertResponse, InterviewPhase, SubagentKind,
)
from app.services.interviews.zep_writer import InterviewZepWriter

class _FakeMemoryUpdater:
    def __init__(self):
        self.events = []
    def add_activity(self, activity):
        self.events.append(activity)
    def add_text_episode(self, graph_id, text):
        self.events.append({"graph_id": graph_id, "text": text})

def test_per_agent_episode_text():
    upd = _FakeMemoryUpdater()
    w = InterviewZepWriter(memory_updater=upd, graph_id="g1")
    r = LikertResponse(agent_id=42, phase=InterviewPhase.T1,
                       responses={"stk_1": 4, "gov_1": 3},
                       confidence={"stk_1": 0.8, "gov_1": 0.7})
    w.write_per_agent(SubagentKind.LONGITUDINAL, r, agent_name="Fischer Müller")
    assert any("Fischer Müller" in str(e) for e in upd.events)
    assert any("longitudinal/T1" in str(e) for e in upd.events)

def test_aggregate_episode():
    upd = _FakeMemoryUpdater()
    w = InterviewZepWriter(memory_updater=upd, graph_id="g1")
    w.write_aggregate(SubagentKind.SCENARIO, summary="S1 mean desirability 5.2; S2 mean 2.1")
    assert any("S1 mean" in str(e) for e in upd.events)
