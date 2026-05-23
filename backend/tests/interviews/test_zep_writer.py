import pytest

from app.models.interview import (
    LikertResponse, InterviewPhase, SubagentKind,
)
from app.services.interviews.zep_writer import InterviewZepWriter


class _FakeMemoryUpdater:
    """Fake mirroring the real ZepGraphMemoryUpdater contract.

    Post-C4 the writer only uses ``add_text_episode(graph_id, text)`` —
    ``add_activity`` is deliberately omitted to lock in the new behaviour and
    catch any regression that re-introduces the broken dict-based fallback.
    """

    def __init__(self):
        self.events: list[dict] = []

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
    # Each event must carry the configured graph_id.
    assert all(e["graph_id"] == "g1" for e in upd.events)


def test_aggregate_episode():
    upd = _FakeMemoryUpdater()
    w = InterviewZepWriter(memory_updater=upd, graph_id="g1")
    w.write_aggregate(SubagentKind.SCENARIO, summary="S1 mean desirability 5.2; S2 mean 2.1")
    assert any("S1 mean" in str(e) for e in upd.events)


def test_emit_uses_add_text_episode_with_graph_id():
    """C4: ``_emit`` must call ``updater.add_text_episode(graph_id, text)``
    with the constructor's graph_id and the raw text — no dict shape, no
    ``add_activity`` fallback (the real ``add_activity`` rejects dicts).
    """
    upd = _FakeMemoryUpdater()
    w = InterviewZepWriter(memory_updater=upd, graph_id="g_xyz")
    w._emit("hello world")
    assert upd.events == [{"graph_id": "g_xyz", "text": "hello world"}]


def test_emit_raises_when_updater_lacks_add_text_episode():
    """C4: a memory_updater without ``add_text_episode`` must surface a
    RuntimeError rather than silently no-op via a broken ``add_activity``
    fallback.
    """

    class _Broken:
        def add_activity(self, activity):  # pragma: no cover - kept for clarity
            raise AssertionError("must not be called")

    w = InterviewZepWriter(memory_updater=_Broken(), graph_id="g1")
    with pytest.raises(RuntimeError, match="add_text_episode"):
        w._emit("x")


def test_real_updater_exposes_add_text_episode():
    """C4 sanity check: ZepGraphMemoryUpdater (the real class) must expose
    ``add_text_episode`` so the production wiring works without falling
    through to the broken ``add_activity(dict)`` path.
    """
    from app.services.zep_graph_memory_updater import ZepGraphMemoryUpdater

    assert hasattr(ZepGraphMemoryUpdater, "add_text_episode")
