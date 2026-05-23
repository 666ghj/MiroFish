from __future__ import annotations
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, field_validator, model_validator

class InterviewPhase(str, Enum):
    T0 = "T0"
    T1 = "T1"

class SubagentKind(str, Enum):
    LONGITUDINAL = "longitudinal"
    DIVERSITY = "diversity"
    DELPHI = "delphi"
    SCENARIO = "scenario"

class LikertItem(BaseModel):
    item_id: str
    de: str
    en: str
    scale: int = Field(ge=3, le=7)
    family: Optional[str] = None
    reverse_coded: bool = False

    @field_validator("scale")
    @classmethod
    def odd_scale(cls, v: int) -> int:
        if v not in (3, 5, 7):
            raise ValueError("scale must be 3, 5, or 7")
        return v

class LikertInstrument(BaseModel):
    name: str
    version: str = "1.0"
    language_default: str = "de"
    items: list[LikertItem]

    @model_validator(mode="after")
    def unique_item_ids(self) -> "LikertInstrument":
        ids = [i.item_id for i in self.items]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate item_id in instrument")
        return self

class LikertResponse(BaseModel):
    agent_id: int
    phase: InterviewPhase
    responses: dict[str, int]
    confidence: dict[str, float] = Field(default_factory=dict)
    open_comment: Optional[str] = None
    memory_available: bool = True
    failed_items: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def values_in_range(self) -> "LikertResponse":
        for k, v in self.responses.items():
            if not 1 <= v <= 5:
                raise ValueError(f"response {k}={v} out of 1..5 range")
        for k, v in self.confidence.items():
            if not 0.0 <= v <= 1.0:
                raise ValueError(f"confidence {k}={v} out of 0..1 range")
        return self

class QSortStatement(BaseModel):
    statement_id: str
    de: str
    en: str

class QSortInstrument(BaseModel):
    name: str
    version: str = "1.0"
    statements: list[QSortStatement]
    distribution: list[int]  # e.g. [2,3,4,6,4,3,2] for -3..+3

class QSortResponse(BaseModel):
    agent_id: int
    placements: dict[str, int]  # statement_id -> bucket (-3..+3)
    likert_axes: dict[str, int]  # axis_id -> 1..7

class DelphiOpenResponse(BaseModel):
    agent_id: int
    round: int = 1
    answers: dict[str, str]  # question_id -> free text

class DelphiRatingResponse(BaseModel):
    agent_id: int
    round: int
    ratings: dict[str, dict[str, int]]  # theme_id -> {importance, plausibility}
    justification: Optional[str] = None

class ScenarioRating(BaseModel):
    desirability: int = Field(ge=1, le=7)
    plausibility: int = Field(ge=1, le=7)
    impact_on_my_group: int = Field(ge=1, le=7)
    fairness: int = Field(ge=1, le=7)
    if_woke_up_response: str

class ScenarioResponse(BaseModel):
    agent_id: int
    ratings: dict[str, ScenarioRating]  # scenario_id -> rating
