import json
import pytest
from app.services.interviews.base import StakeholderInterviewer, MemoryDigest, PersonaRecord

class _FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
    def chat_json(self, messages, temperature=0.0, max_tokens=None, **kw):
        self.calls.append(messages)
        return self.responses.pop(0)

class _FakeMemory:
    def get_digest(self, agent_id, max_chars=2000):
        return MemoryDigest(text=f"digest-for-{agent_id}", available=True)

def test_in_character_prompt_includes_persona_and_memory():
    llm = _FakeLLM([{"x": 1}])
    mem = _FakeMemory()
    interviewer = StakeholderInterviewer(llm=llm, memory=mem)
    persona = PersonaRecord(agent_id=7, name="A", persona="I am a small-scale Baltic fisher.")
    out = interviewer.ask_in_character(persona, user_prompt="Q?", schema_hint="{...}")
    assert out == {"x": 1}
    sys_msg = llm.calls[0][0]["content"]
    assert "small-scale Baltic fisher" in sys_msg
    assert "digest-for-7" in sys_msg

def test_schema_retry_on_first_failure():
    bad_then_good = [{}, {"responses": {"a": 3}}]
    llm = _FakeLLM(bad_then_good)
    mem = _FakeMemory()
    interviewer = StakeholderInterviewer(llm=llm, memory=mem)
    def validator(d):
        return d if "responses" in d else None
    persona = PersonaRecord(agent_id=1, name="A", persona="p")
    out = interviewer.ask_in_character(persona, user_prompt="Q?", schema_hint="x", validate=validator)
    assert out == {"responses": {"a": 3}}
    assert len(llm.calls) == 2

def test_two_failures_raise():
    llm = _FakeLLM([{}, {}])
    mem = _FakeMemory()
    interviewer = StakeholderInterviewer(llm=llm, memory=mem)
    persona = PersonaRecord(agent_id=1, name="A", persona="p")
    with pytest.raises(ValueError):
        interviewer.ask_in_character(persona, user_prompt="Q?", schema_hint="x",
                                     validate=lambda d: d if "responses" in d else None)
