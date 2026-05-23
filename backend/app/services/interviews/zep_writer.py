from __future__ import annotations
from typing import Any, Optional
from app.models.interview import (
    LikertResponse, QSortResponse, DelphiRatingResponse, ScenarioResponse, SubagentKind,
)

class InterviewZepWriter:
    """Mirrors `ZepGraphMemoryUpdater.add_activity` usage but for interview episodes.

    The real `ZepGraphMemoryUpdater` may expose `add_activity` (preferred) or a lower-level
    text-episode method; this writer adapts to either via duck typing.
    """
    def __init__(self, memory_updater, graph_id: str):
        self.updater = memory_updater
        self.graph_id = graph_id

    def _emit(self, text: str) -> None:
        if hasattr(self.updater, "add_text_episode"):
            self.updater.add_text_episode(self.graph_id, text)
        elif hasattr(self.updater, "add_activity"):
            self.updater.add_activity({"graph_id": self.graph_id, "text": text})
        else:
            raise RuntimeError("memory_updater has neither add_text_episode nor add_activity")

    def _summarize_likert(self, r: LikertResponse) -> str:
        mean_v = sum(r.responses.values()) / max(len(r.responses), 1)
        top = sorted(r.responses.items(), key=lambda kv: -kv[1])[:3]
        bot = sorted(r.responses.items(), key=lambda kv: kv[1])[:3]
        return (f"mean={mean_v:.2f}; agrees with {[k for k,_ in top]}; "
                f"disagrees with {[k for k,_ in bot]}")

    def _summarize_qsort(self, r: QSortResponse) -> str:
        plus = [k for k, v in r.placements.items() if v >= 2]
        minus = [k for k, v in r.placements.items() if v <= -2]
        return f"+strongly:{plus}; -strongly:{minus}"

    def _summarize_scenario(self, r: ScenarioResponse) -> str:
        parts = [f"{sid}: des={rt.desirability} plaus={rt.plausibility}"
                 for sid, rt in r.ratings.items()]
        return "; ".join(parts)

    def write_per_agent(
        self, subagent: SubagentKind, response: Any, agent_name: str,
        phase: Optional[str] = None,
    ) -> None:
        if isinstance(response, LikertResponse):
            phase = phase or response.phase.value
            summary = self._summarize_likert(response)
        elif isinstance(response, QSortResponse):
            phase = phase or "T1"
            summary = self._summarize_qsort(response)
        elif isinstance(response, ScenarioResponse):
            phase = phase or "T1"
            summary = self._summarize_scenario(response)
        elif isinstance(response, DelphiRatingResponse):
            phase = phase or f"T1/R{response.round}"
            summary = f"round={response.round}; {len(response.ratings)} themes rated"
        else:
            phase = phase or "T1"
            summary = str(response)[:200]
        text = f"Agent {agent_name} (interview/{subagent.value}/{phase}): {summary}"
        self._emit(text)

    def write_aggregate(self, subagent: SubagentKind, summary: str) -> None:
        self._emit(f"Interview aggregate ({subagent.value}): {summary}")
