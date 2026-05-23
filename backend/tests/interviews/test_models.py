import pytest
from pydantic import ValidationError
from app.models.interview import (
    LikertItem, LikertInstrument, LikertResponse,
    InterviewPhase, SubagentKind,
)

def test_likert_item_requires_de_and_en():
    item = LikertItem(item_id="x1", de="Frage", en="Question", scale=5)
    assert item.scale == 5

def test_likert_item_rejects_bad_scale():
    with pytest.raises(ValidationError):
        LikertItem(item_id="x1", de="d", en="e", scale=2)

def test_likert_instrument_unique_item_ids():
    with pytest.raises(ValidationError):
        LikertInstrument(
            name="t",
            items=[LikertItem(item_id="a", de="d", en="e", scale=5),
                   LikertItem(item_id="a", de="d", en="e", scale=5)],
        )

def test_likert_response_validates_scale_range():
    with pytest.raises(ValidationError):
        LikertResponse(agent_id=1, phase=InterviewPhase.T0,
                       responses={"a": 6}, confidence={"a": 0.5})

def test_subagent_kind_enum():
    assert SubagentKind.LONGITUDINAL.value == "longitudinal"
