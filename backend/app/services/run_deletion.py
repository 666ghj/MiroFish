"""Delete a simulation together with everything that belongs to it.

"Everything" is: the simulation's own folder, the replicate simulations and ensembles built from it,
the reports written for any of those, and -- because a project folder only exists to feed its
simulations -- the project (uploaded files, ontology, Zep graph) and every other simulation of
that project.

Nothing is touched while anything involved is still working: the checks run first, the Zep graph
(the only step that can fail halfway) goes next, and the local folders last.
"""

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional
import os
import shutil

from ..models.project import ProjectManager
from ..utils.logger import get_logger
from .ensemble_runner import EnsembleManager
from .report_agent import ReportManager
from .simulation_manager import SimulationManager, SimulationStatus
from .simulation_runner import RunnerStatus, SimulationRunner
from .zep_graph_memory_updater import ZepGraphMemoryManager

logger = get_logger("mirofish.run_deletion")

ACTIVE_RUNNER_STATUSES = {
    RunnerStatus.STARTING,
    RunnerStatus.RUNNING,
    RunnerStatus.PAUSED,
    RunnerStatus.STOPPING,
}
ACTIVE_ENSEMBLE_STATUSES = {"running", "aggregating"}


class RunNotFound(LookupError):
    pass


class RunBusy(RuntimeError):
    """Something that would be deleted is still running or being prepared."""


@dataclass
class DeletionPlan:
    simulation_id: str
    project_id: Optional[str]
    graph_id: Optional[str]
    simulation_ids: List[str] = field(default_factory=list)
    ensemble_ids: List[str] = field(default_factory=list)
    report_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "simulation_id": self.simulation_id,
            "project_id": self.project_id,
            "graph_id": self.graph_id,
            "simulations": len(self.simulation_ids),
            "ensembles": len(self.ensemble_ids),
            "reports": len(self.report_ids),
        }


def plan_deletion(simulation_id: str, *, with_project: bool = True) -> DeletionPlan:
    manager = SimulationManager()
    state = manager.get_simulation(simulation_id)
    if state is None:
        raise RunNotFound(simulation_id)

    everything = manager.list_simulations(include_replicates=True)
    project_id = state.project_id if with_project else None
    if project_id:
        simulations = [s for s in everything if s.project_id == project_id]
    else:
        simulations = [
            s for s in everything
            if s.simulation_id == simulation_id or s.simulation_id.startswith(f"{simulation_id}__")
        ]
    simulation_ids = sorted({s.simulation_id for s in simulations} | {simulation_id})

    ensemble_ids = [
        e["ensemble_id"]
        for e in EnsembleManager.list_ensembles()
        if e.get("base_simulation_id") in simulation_ids
    ]
    report_ids = [
        r.report_id
        for r in ReportManager.list_reports(limit=100000)
        if r.simulation_id in simulation_ids or (r.ensemble_id and r.ensemble_id in ensemble_ids)
    ]
    return DeletionPlan(
        simulation_id=simulation_id,
        project_id=project_id,
        graph_id=state.graph_id if project_id else None,
        simulation_ids=simulation_ids,
        ensemble_ids=ensemble_ids,
        report_ids=report_ids,
    )


def _busy_reasons(plan: DeletionPlan, is_preparing: Callable[[str], bool]) -> List[str]:
    reasons = []
    for sim_id in plan.simulation_ids:
        run_state = SimulationRunner.get_run_state(sim_id)
        if run_state and run_state.runner_status in ACTIVE_RUNNER_STATUSES:
            reasons.append(f"{sim_id} is running")
        elif is_preparing(sim_id):
            reasons.append(f"{sim_id} is being prepared")
    for ensemble_id in plan.ensemble_ids:
        try:
            if EnsembleManager._load(ensemble_id).get("status") in ACTIVE_ENSEMBLE_STATUSES:
                reasons.append(f"ensemble {ensemble_id} is running")
        except Exception:
            continue  # an unreadable ensemble cannot be running
    return reasons


def delete_run(
    simulation_id: str,
    *,
    with_project: bool = True,
    delete_graph: Callable[[Optional[str]], None] = lambda graph_id: None,
    is_preparing: Callable[[str], bool] = lambda sim_id: False,
) -> DeletionPlan:
    """Delete the simulation (and, by default, its whole project). Raises RunNotFound / RunBusy."""
    plan = plan_deletion(simulation_id, with_project=with_project)
    reasons = _busy_reasons(plan, is_preparing)
    if reasons:
        raise RunBusy("; ".join(reasons))

    if plan.project_id and plan.graph_id:
        delete_graph(plan.graph_id)  # may raise; nothing local has been removed yet

    for ensemble_id in plan.ensemble_ids:
        shutil.rmtree(EnsembleManager._dir(ensemble_id), ignore_errors=True)
    for report_id in plan.report_ids:
        try:
            ReportManager.delete_report(report_id)
        except Exception as error:
            logger.warning(f"Could not delete report {report_id}: {error}")
    for sim_id in plan.simulation_ids:
        try:
            ZepGraphMemoryManager.discard_inactive_updater(sim_id)
        except Exception:
            pass
        SimulationRunner._graph_memory_enabled.pop(sim_id, None)
        SimulationRunner._run_states.pop(sim_id, None)
        shutil.rmtree(os.path.join(SimulationManager.SIMULATION_DATA_DIR, sim_id), ignore_errors=True)
    if plan.project_id:
        ProjectManager.delete_project(plan.project_id)

    logger.info(
        f"Deleted {plan.simulation_id}: {len(plan.simulation_ids)} simulation(s), "
        f"{len(plan.ensemble_ids)} ensemble(s), {len(plan.report_ids)} report(s), project={plan.project_id}"
    )
    return plan
