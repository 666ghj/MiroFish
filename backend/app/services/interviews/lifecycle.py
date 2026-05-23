"""
Interview lifecycle hook installer (Task 20).

install_hooks(manager) registers two callbacks on a SimulationManager:
  - on_ready  → spawn T0 longitudinal pre-survey in a background thread
  - on_completed → spawn full post-sim batch + synthesis in a background thread

Both hooks are best-effort: failures are logged but never propagate to the
calling thread.
"""

from __future__ import annotations

import threading

from app.utils.logger import get_logger

logger = get_logger(__name__)


def install_hooks(manager) -> None:
    """Attach interview lifecycle callbacks to a SimulationManager.

    on_ready  → spawn T0 longitudinal in a background thread
    on_completed → spawn full post-sim batch in a background thread
    Hooks are best-effort; failures only log.
    """

    def _on_ready(state) -> None:
        sim_id = (
            getattr(state, "simulation_id", None)
            or getattr(state, "sim_id", None)
            or getattr(state, "id", None)
        )
        if not sim_id:
            return
        threading.Thread(target=_run_pre, args=(sim_id,), daemon=True).start()

    def _on_completed(state) -> None:
        sim_id = (
            getattr(state, "simulation_id", None)
            or getattr(state, "sim_id", None)
            or getattr(state, "id", None)
        )
        if not sim_id:
            return
        threading.Thread(target=_run_post, args=(sim_id,), daemon=True).start()

    manager.register_on_ready(_on_ready)
    manager.register_on_completed(_on_completed)


def _run_pre(sim_id: str) -> None:
    try:
        from app.api.interview import _build_orchestrator

        orch = _build_orchestrator(sim_id)
        orch.run_pre()
    except Exception as e:
        logger.warning(f"auto pre-survey failed for {sim_id}: {e!r}")


def _run_post(sim_id: str) -> None:
    try:
        from app.api.interview import _build_orchestrator
        from app.services.interview_synthesizer import InterviewSynthesizer

        orch = _build_orchestrator(sim_id)
        orch.run_post()
        InterviewSynthesizer(store=orch.store).run()
    except Exception as e:
        logger.warning(f"auto post-survey failed for {sim_id}: {e!r}")
