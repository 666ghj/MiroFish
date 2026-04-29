"""Live LLM-usage / cost tracker.

This service counts tokens, requests, and cumulative cost across
LLM calls so the UI can show a live "you've spent $X.YZ on this run"
bar. It is the user-visible safety net against runaway spend that
complements the subprocess watchdog (which catches *technical*
leaks; this catches *runtime* over-spend).

Design
------

* In-process singleton, thread-safe via a single :class:`RLock`.
* Per-simulation totals plus a global "all simulations" total.
* Cost is taken straight from the LLM response when the provider
  returns it (OpenRouter does, in ``usage.cost``); otherwise we
  approximate from a small static price table keyed by model id.
* :meth:`record_usage` is best-effort — never raises. The caller
  is the LLM hot path, and a tracker bug must not break a real
  user's simulation.
* :class:`UsageBudget` enforces optional spend caps. When the cap
  is exceeded the tracker flips an event flag that the runner
  polls and uses to abort the simulation gracefully.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Optional

from ..utils.logger import get_logger

logger = get_logger("mirofish.usage_tracker")


# ---------------------------------------------------------------------------
# Static price table for providers that do NOT return usage.cost.
# Numbers are USD per 1M tokens, taken from OpenRouter's public listing.
# Best-effort and easy to update; absent entries fall back to 0.
# ---------------------------------------------------------------------------
_PRICE_TABLE_USD_PER_M: dict[str, tuple[float, float]] = {
    # OpenRouter Qwen family
    "qwen/qwen-plus":          (0.26, 0.78),
    "qwen/qwen-turbo":         (0.03, 0.13),
    "qwen/qwen-max":           (1.04, 4.16),
    "qwen/qwen3-max":          (0.78, 3.90),
    "qwen/qwen3.6-plus":       (0.33, 1.95),
    "qwen/qwen-plus-2025-07-28": (0.26, 0.78),
    # Common alternatives
    "anthropic/claude-haiku-4.5":   (1.00, 5.00),
    "anthropic/claude-sonnet-4.5":  (3.00, 15.00),
    "google/gemini-2.0-flash-001":  (0.10, 0.40),
    "openai/gpt-4o-mini":           (0.15, 0.60),
    "meta-llama/llama-3.3-70b-instruct": (0.59, 0.79),
}


def _estimate_cost_usd(
    model: str, prompt_tokens: int, completion_tokens: int
) -> float:
    """Rough cost estimate when the provider does not return one."""
    rates = _PRICE_TABLE_USD_PER_M.get(model)
    if rates is None:
        return 0.0
    return (
        prompt_tokens * rates[0] / 1_000_000
        + completion_tokens * rates[1] / 1_000_000
    )


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


@dataclass
class UsageSnapshot:
    """A point-in-time snapshot of usage for one simulation (or global)."""

    simulation_id: Optional[str]
    model: Optional[str] = None
    requests: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    started_at: float = field(default_factory=time.time)
    last_updated_at: float = field(default_factory=time.time)
    cap_usd: Optional[float] = None
    over_cap: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "simulation_id": self.simulation_id,
            "model": self.model,
            "requests": self.requests,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "started_at": self.started_at,
            "last_updated_at": self.last_updated_at,
            "elapsed_seconds": int(self.last_updated_at - self.started_at),
            "cap_usd": self.cap_usd,
            "over_cap": self.over_cap,
        }


# ---------------------------------------------------------------------------
# Tracker
# ---------------------------------------------------------------------------


class UsageTracker:
    """Process-wide singleton that aggregates LLM usage."""

    _instance: Optional["UsageTracker"] = None
    _instance_lock = threading.Lock()

    @classmethod
    def instance(cls) -> "UsageTracker":
        """Return the process-wide tracker (lazy)."""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        self._lock = threading.RLock()
        # Per-simulation snapshots, keyed by simulation_id.
        self._per_sim: dict[str, UsageSnapshot] = {}
        # The "global" snapshot tallies usage that was recorded
        # without a simulation_id (e.g. graph-build-time calls).
        self._global = UsageSnapshot(simulation_id=None)
        # Cap configuration: read once at init from env, can be
        # overridden per-simulation via :meth:`set_cap`.
        try:
            self._default_cap_usd: Optional[float] = float(
                os.environ.get("MAX_SIMULATION_COST_USD", "")
            )
        except (TypeError, ValueError):
            self._default_cap_usd = None
        # Per-simulation event flags that the runner polls to know
        # when to abort.
        self._cap_breached_events: dict[str, threading.Event] = {}

    # ------------------------------------------------------------------
    # Public recording API — safe to call from anywhere
    # ------------------------------------------------------------------

    def record_usage(
        self,
        *,
        simulation_id: Optional[str],
        model: Optional[str],
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cost_usd: Optional[float] = None,
    ) -> None:
        """Record a single LLM call's usage. Never raises."""
        try:
            total = prompt_tokens + completion_tokens
            if cost_usd is None:
                cost_usd = _estimate_cost_usd(
                    model or "", prompt_tokens, completion_tokens
                )
            with self._lock:
                snap = self._snapshot_for(simulation_id)
                snap.requests += 1
                snap.prompt_tokens += prompt_tokens
                snap.completion_tokens += completion_tokens
                snap.total_tokens += total
                snap.cost_usd += float(cost_usd or 0.0)
                snap.last_updated_at = time.time()
                if model and not snap.model:
                    snap.model = model

                # Also tally on the global snapshot so a single
                # endpoint can show "total LLM spend ever".
                if simulation_id is not None:
                    self._global.requests += 1
                    self._global.prompt_tokens += prompt_tokens
                    self._global.completion_tokens += completion_tokens
                    self._global.total_tokens += total
                    self._global.cost_usd += float(cost_usd or 0.0)
                    self._global.last_updated_at = time.time()

                # Cap check.
                effective_cap = (
                    snap.cap_usd if snap.cap_usd is not None else self._default_cap_usd
                )
                if (
                    effective_cap is not None
                    and effective_cap > 0
                    and snap.cost_usd >= effective_cap
                    and not snap.over_cap
                ):
                    snap.over_cap = True
                    if simulation_id:
                        ev = self._cap_breached_events.setdefault(
                            simulation_id, threading.Event()
                        )
                        ev.set()
                    logger.warning(
                        "Cost cap breached for simulation %s: $%.4f >= $%.2f",
                        simulation_id,
                        snap.cost_usd,
                        effective_cap,
                    )
        except Exception as exc:  # noqa: BLE001
            logger.debug("usage record failed (suppressed): %s", exc)

    def record_from_openai_response(
        self,
        response: Any,
        *,
        simulation_id: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        """Convenience: pull token + cost fields off an OpenAI-shaped object."""
        try:
            usage = getattr(response, "usage", None)
            if usage is None:
                return
            prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
            completion = int(getattr(usage, "completion_tokens", 0) or 0)
            # OpenRouter returns "cost" inside usage; the OpenAI SDK
            # exposes it as a model attribute so both forms work.
            cost = getattr(usage, "cost", None)
            if cost is None and hasattr(usage, "model_extra"):
                cost = (usage.model_extra or {}).get("cost")
            self.record_usage(
                simulation_id=simulation_id,
                model=model or getattr(response, "model", None),
                prompt_tokens=prompt,
                completion_tokens=completion,
                cost_usd=float(cost) if cost is not None else None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("record_from_openai_response failed (suppressed): %s", exc)

    # ------------------------------------------------------------------
    # Read API
    # ------------------------------------------------------------------

    def snapshot(self, simulation_id: Optional[str]) -> UsageSnapshot:
        """Return a copy of the current snapshot for ``simulation_id``."""
        with self._lock:
            snap = self._per_sim.get(simulation_id) if simulation_id else self._global
            if snap is None:
                snap = UsageSnapshot(simulation_id=simulation_id)
            # Shallow copy
            return UsageSnapshot(**{**snap.__dict__})

    def global_snapshot(self) -> UsageSnapshot:
        """Return the cross-simulation total snapshot."""
        with self._lock:
            return UsageSnapshot(**{**self._global.__dict__})

    def all_simulations(self) -> list[UsageSnapshot]:
        """Return a copy of every per-simulation snapshot."""
        with self._lock:
            return [UsageSnapshot(**{**s.__dict__}) for s in self._per_sim.values()]

    def cap_breached(self, simulation_id: str) -> bool:
        """Return True if the cap for ``simulation_id`` has been hit."""
        with self._lock:
            snap = self._per_sim.get(simulation_id)
            return bool(snap and snap.over_cap)

    def get_cap_event(self, simulation_id: str) -> threading.Event:
        """Return an :class:`Event` set when the cap is breached.

        The simulation runner can ``wait()`` on this with a timeout
        instead of polling :meth:`cap_breached`.
        """
        with self._lock:
            return self._cap_breached_events.setdefault(
                simulation_id, threading.Event()
            )

    # ------------------------------------------------------------------
    # Cap configuration
    # ------------------------------------------------------------------

    def set_cap(self, simulation_id: str, cap_usd: Optional[float]) -> None:
        """Set / override the cost cap for one simulation."""
        with self._lock:
            snap = self._snapshot_for(simulation_id)
            snap.cap_usd = cap_usd
            snap.over_cap = bool(
                cap_usd is not None and cap_usd > 0 and snap.cost_usd >= cap_usd
            )

    def reset(self, simulation_id: Optional[str] = None) -> None:
        """Drop the snapshot for one simulation, or all if ``None``."""
        with self._lock:
            if simulation_id is None:
                self._per_sim.clear()
                self._global = UsageSnapshot(simulation_id=None)
                self._cap_breached_events.clear()
            else:
                self._per_sim.pop(simulation_id, None)
                self._cap_breached_events.pop(simulation_id, None)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _snapshot_for(self, simulation_id: Optional[str]) -> UsageSnapshot:
        if simulation_id is None:
            return self._global
        snap = self._per_sim.get(simulation_id)
        if snap is None:
            snap = UsageSnapshot(
                simulation_id=simulation_id,
                cap_usd=self._default_cap_usd,
            )
            self._per_sim[simulation_id] = snap
        return snap


# Convenience module-level alias so callers don't have to remember the class.
def get_usage_tracker() -> UsageTracker:
    return UsageTracker.instance()
