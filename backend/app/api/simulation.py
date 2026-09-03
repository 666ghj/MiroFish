"""
Simulation API routes
Step 2: read and filter Zep entities, then prepare and run an OASIS simulation.
"""

import os
import threading
import traceback
from contextlib import nullcontext
from typing import Any, Callable, Dict, Optional, Tuple

from flask import request, jsonify, send_file

from . import simulation_bp
from ..config import Config
from ..services.zep_entity_reader import ZepEntityReader
from ..services.oasis_profile_generator import OasisProfileGenerator
from ..services.simulation_manager import (
    PREPARATION_INTERRUPTED_ERROR,
    SimulationBusyError,
    SimulationManager,
    SimulationState,
    SimulationStatus,
)
from ..services.simulation_runner import (
    SimulationRunner,
    SimulationRunState,
    RunnerStatus,
    SimulationStopPending,
)
from ..services.zep_graph_memory_updater import ZepGraphMemoryManager
from ..utils.logger import get_logger
from ..utils.locale import t
from ..utils.zep_lifecycle import get_graph_readers, graph_lifecycle_lock
from ..models.project import ProjectManager

logger = get_logger('sosim.api.simulation')


def _get_default_platform(simulation_id: str) -> str:
    """
    Return the default platform for a simulation.

    Reads enable_twitter / enable_reddit off the SimulationState and returns the
    platform the simulation actually uses, rather than hardcoding 'reddit'.

    Args:
        simulation_id: Simulation ID

    Returns:
        'twitter' or 'reddit'
    """
    try:
        manager = SimulationManager()
        state = manager._load_simulation_state(simulation_id)
        if state:
            return state.get_default_platform()
    except Exception:
        pass
    return "reddit"


# Prefix prepended to every interview prompt. It keeps the agent from calling
# tools and makes it answer in plain text.
INTERVIEW_PROMPT_PREFIX = (
    "Answer me directly in text, drawing on your persona and all of your past "
    "memories and actions. Do not call any tools. "
)


def optimize_interview_prompt(prompt: str) -> str:
    """
    Prepend the no-tools prefix to an interview prompt.
    
    Args:
        prompt: The original question
        
    Returns:
        The prefixed question
    """
    if not prompt:
        return prompt
    # Adding the prefix twice would repeat the instruction to the model.
    if prompt.startswith(INTERVIEW_PROMPT_PREFIX):
        return prompt
    return f"{INTERVIEW_PROMPT_PREFIX}{prompt}"


# ============== Preparation claims ==============

# Simulations whose preparation thread is running in THIS process, mapped to
# the task that reports its progress. Preparation is a daemon thread with no
# cancellation point, and it writes the agent profiles and the simulation
# config into the same directory a run reads, so a second preparation - or a
# restart - must not race it. The registry is also what tells an in-flight
# preparation apart from one a backend restart stranded in 'preparing', which
# is otherwise indistinguishable from the outside: both read status=preparing.
_active_preparations: Dict[str, Optional[str]] = {}
_active_preparations_guard = threading.Lock()


def _claim_preparation(simulation_id: str) -> bool:
    """Claim a simulation for preparation, or report that one is in flight."""
    with _active_preparations_guard:
        if simulation_id in _active_preparations:
            return False
        _active_preparations[simulation_id] = None
        return True


def _note_preparation_task(simulation_id: str, task_id: str) -> None:
    """Record the task that reports on a claimed preparation."""
    with _active_preparations_guard:
        if simulation_id in _active_preparations:
            _active_preparations[simulation_id] = task_id


def _release_preparation(simulation_id: str) -> None:
    """Release a preparation claim once its thread has finished."""
    with _active_preparations_guard:
        _active_preparations.pop(simulation_id, None)


def _preparation_in_flight(simulation_id: str) -> Tuple[bool, Optional[str]]:
    """Report whether a preparation is running here, and under which task."""
    with _active_preparations_guard:
        if simulation_id not in _active_preparations:
            return False, None
        return True, _active_preparations[simulation_id]


def _rescue_stranded_preparation(
    manager: SimulationManager,
    state: SimulationState,
) -> bool:
    """
    Repair one simulation left in 'preparing' by a backend restart.

    Preparation runs in a daemon thread, so a backend restart kills it without
    raising and neither failure handler runs. Nothing else moves the simulation
    out of 'preparing', every later start is refused with "Simulation not
    ready", and the row becomes a dead end. Rest it at ready when its files are
    complete, and at failed otherwise, so the Simulations menu has somewhere to
    go from.

    Returns:
        True when the simulation is now ready to run
    """
    if manager.is_prepared(state.simulation_id):
        state.status = SimulationStatus.READY
        state.error = None
    else:
        state.status = SimulationStatus.FAILED
        state.error = PREPARATION_INTERRUPTED_ERROR
    manager._save_simulation_state(state)

    logger.warning(
        "Rescued a simulation stranded in 'preparing': simulation_id=%s, status=%s",
        state.simulation_id,
        state.status.value,
    )
    return state.status == SimulationStatus.READY


# ============== Run launching ==============


def _run_needs_finalization(simulation_id: str) -> bool:
    """
    Does a previous run still have to be finalized before /start may relaunch?

    True when the saved state says the run owns a process (RUNNING / PAUSED /
    STOPPING) or, having FAILED, still owes the Zep graph the tail of its
    ingestion. /start answers this from the saved status alone and deliberately
    stays conservative: it relaunches in place rather than reaping first, so a
    saved status that merely *claims* a run is reason enough to demand force.

    Args:
        simulation_id: Simulation ID

    Returns:
        True when the caller must stop the run (or pass force) first
    """
    run_state = SimulationRunner.get_run_state(simulation_id)
    if run_state is None:
        return False
    owns_process = run_state.runner_status in {
        RunnerStatus.RUNNING,
        RunnerStatus.PAUSED,
        RunnerStatus.STOPPING,
    }
    if owns_process:
        return True
    return (
        run_state.runner_status == RunnerStatus.FAILED
        and ZepGraphMemoryManager.get_updater(simulation_id) is not None
    )


def _run_is_live(simulation_id: str) -> bool:
    """
    Is a run genuinely in flight right now?

    The same question the Simulations menu asks before it disables Restart, and
    answered the same way: an active runner status whose run really is being
    held - by the child this backend spawned, by an orphan that outlived a
    backend restart, or by a Zep updater still draining. That is
    simulationFormat.js's isLive(), which is `status in LIVE_STATUSES && !stale`
    and, because describe_activity now reports stale as the exact negation of
    active, is this.

    Asked from the saved status alone instead, this would refuse a STALE row -
    one whose saved state claims a run whose process is gone - and /restart is
    the documented and only way out of that state, so the frontend offers
    Restart there on purpose. The pid lookup is what tells the two apart.

    /restart uses this rather than _run_needs_finalization because it is
    destructive in a way /start is not: it reaps the child and deletes
    run_state.json, simulation.log, both actions.jsonl files and both platform
    databases. The refusal has to live here and not only in the Vue menu - a
    curl, a template regression or any other programmatic caller reaches the
    route directly.

    Args:
        simulation_id: Simulation ID

    Returns:
        True when something is still holding the run
    """
    activity = SimulationRunner.describe_activity(simulation_id)
    live_statuses = {status.value for status in SimulationRunner.ACTIVE_STATUSES}
    return bool(activity["active"]) and activity["runner_status"] in live_statuses


def _launch_under_graph_guard(
    manager: SimulationManager,
    simulation_id: str,
    state: SimulationState,
    enable_graph_memory_update: bool,
    launch: Callable[[Optional[str]], SimulationRunState],
) -> Tuple[Optional[SimulationRunState], Optional[str], Optional[Tuple[Dict[str, Any], int]]]:
    """
    Resolve the graph a run may write to, hold it, and launch the run.

    Shared by /start and /restart so the two cannot drift over which graph a
    run is allowed to claim.

    Args:
        manager: Simulation manager
        simulation_id: Simulation ID
        state: The simulation state the caller already loaded
        enable_graph_memory_update: Push agent activity into the Zep graph
        launch: Called with the resolved graph_id (None when graph memory is
            off) while the per-graph lock is held; returns the new run state

    Returns:
        (run_state, graph_id, error) - exactly one of run_state and error is
        set, and error is a (payload, http_status) pair ready to jsonify
    """
    graph_id = None
    if enable_graph_memory_update:
        # The project is authoritative. A graph ID copied into an older
        # simulation can outlive a project reset/rebuild and must not be
        # used to resurrect writes to a deleted graph.
        project = ProjectManager.get_project(state.project_id)
        graph_id = project.graph_id if project else None
        if not graph_id:
            return None, None, ({
                "success": False,
                "error": t('api.graphIdRequiredForMemory'),
            }, 400)

    graph_guard = (
        graph_lifecycle_lock(graph_id)
        if enable_graph_memory_update
        else nullcontext()
    )
    with graph_guard:
        if enable_graph_memory_update:
            # Re-read both references under the same per-graph lock used
            # by reset/delete. Keep the lock through updater creation in
            # start_simulation so check -> claim is atomic.
            refreshed_state = manager.get_simulation(simulation_id)
            refreshed_project = (
                ProjectManager.get_project(refreshed_state.project_id)
                if refreshed_state
                else None
            )
            current_graph_id = (
                refreshed_project.graph_id if refreshed_project else None
            )
            if current_graph_id != graph_id:
                return None, graph_id, ({
                    "success": False,
                    "error": (
                        "The project graph changed while the simulation "
                        "was starting; retry after refreshing the project"
                    ),
                }, 409)
            if (
                refreshed_state.graph_id
                and refreshed_state.graph_id != current_graph_id
            ):
                return None, graph_id, ({
                    "success": False,
                    "error": (
                        "The simulation references an older graph; "
                        "prepare it again before enabling graph memory"
                    ),
                }, 409)
            active_reports = get_graph_readers(graph_id)
            if active_reports:
                return None, graph_id, ({
                    "success": False,
                    "error": (
                        "A report is currently reading this graph; wait "
                        "for report generation to finish before enabling "
                        "graph memory updates"
                    ),
                    "active_reports": active_reports,
                }, 409)
            logger.info(
                "Enabled graph memory updates: simulation_id=%s, graph_id=%s",
                simulation_id,
                graph_id,
            )

        # Launch the run. With graph writes on, graph_guard is still held
        # until the updater claim and the process resources are published.
        return launch(graph_id), graph_id, None


# ============== Entity reads ==============

@simulation_bp.route('/entities/<graph_id>', methods=['GET'])
def get_graph_entities(graph_id: str):
    """
    Return every entity in a graph, already filtered.
    
    Only nodes matching a predefined entity type are returned - nodes whose labels are more than just Entity.
    
    Query parameters:
        entity_types: Comma-separated entity types to filter by (optional)
        enrich: Include the related edges (defaults to true)
    """
    try:
        if not Config.ZEP_API_KEY:
            return jsonify({
                "success": False,
                "error": t('api.zepApiKeyMissing')
            }), 500
        
        entity_types_str = request.args.get('entity_types', '')
        entity_types = [t.strip() for t in entity_types_str.split(',') if t.strip()] if entity_types_str else None
        enrich = request.args.get('enrich', 'true').lower() == 'true'
        
        logger.info(f"Reading graph entities: graph_id={graph_id}, entity_types={entity_types}, enrich={enrich}")
        
        reader = ZepEntityReader()
        result = reader.filter_defined_entities(
            graph_id=graph_id,
            defined_entity_types=entity_types,
            enrich_with_edges=enrich
        )
        
        return jsonify({
            "success": True,
            "data": result.to_dict()
        })
        
    except Exception as e:
        logger.error(f"Failed to read the graph entities: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/entities/<graph_id>/<entity_uuid>', methods=['GET'])
def get_entity_detail(graph_id: str, entity_uuid: str):
    """Return one entity in full."""
    try:
        if not Config.ZEP_API_KEY:
            return jsonify({
                "success": False,
                "error": t('api.zepApiKeyMissing')
            }), 500
        
        reader = ZepEntityReader()
        entity = reader.get_entity_with_context(graph_id, entity_uuid)
        
        if not entity:
            return jsonify({
                "success": False,
                "error": t('api.entityNotFound', id=entity_uuid)
            }), 404
        
        return jsonify({
            "success": True,
            "data": entity.to_dict()
        })
        
    except Exception as e:
        logger.error(f"Failed to read the entity detail: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/entities/<graph_id>/by-type/<entity_type>', methods=['GET'])
def get_entities_by_type(graph_id: str, entity_type: str):
    """Return every entity of one type."""
    try:
        if not Config.ZEP_API_KEY:
            return jsonify({
                "success": False,
                "error": t('api.zepApiKeyMissing')
            }), 500
        
        enrich = request.args.get('enrich', 'true').lower() == 'true'
        
        reader = ZepEntityReader()
        entities = reader.get_entities_by_type(
            graph_id=graph_id,
            entity_type=entity_type,
            enrich_with_edges=enrich
        )
        
        return jsonify({
            "success": True,
            "data": {
                "entity_type": entity_type,
                "count": len(entities),
                "entities": [e.to_dict() for e in entities]
            }
        })
        
    except Exception as e:
        logger.error(f"Failed to read the entities: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== Simulation management ==============

@simulation_bp.route('/create', methods=['POST'])
def create_simulation():
    """
    Create a simulation.
    
    max_rounds and the other run parameters are generated by the LLM, so there is nothing to set by hand.
    
    Request (JSON):
        {
            "project_id": "proj_xxxx",      // required
            "graph_id": "sosim_xxxx",       // optional, taken from the project when omitted
            "enable_twitter": true,          // optional, defaults to true
            "enable_reddit": true            // optional, defaults to true
        }
    
    Returns:
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "project_id": "proj_xxxx",
                "graph_id": "sosim_xxxx",
                "status": "created",
                "enable_twitter": true,
                "enable_reddit": true,
                "created_at": "2025-12-01T10:00:00"
            }
        }
    """
    try:
        data = request.get_json() or {}
        
        project_id = data.get('project_id')
        if not project_id:
            return jsonify({
                "success": False,
                "error": t('api.requireProjectId')
            }), 400
        
        project = ProjectManager.get_project(project_id)
        if not project:
            return jsonify({
                "success": False,
                "error": t('api.projectNotFound', id=project_id)
            }), 404
        
        graph_id = data.get('graph_id') or project.graph_id
        if not graph_id:
            return jsonify({
                "success": False,
                "error": t('api.graphNotBuilt')
            }), 400
        
        manager = SimulationManager()
        state = manager.create_simulation(
            project_id=project_id,
            graph_id=graph_id,
            enable_twitter=data.get('enable_twitter', True),
            enable_reddit=data.get('enable_reddit', True),
        )
        
        return jsonify({
            "success": True,
            "data": state.to_dict()
        })
        
    except Exception as e:
        logger.error(f"Failed to create the simulation: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


def _check_simulation_prepared(simulation_id: str) -> tuple:
    """
    Report whether a simulation has finished preparing.
    
    Conditions:
    1. state.json exists and its status is "ready"
    2. The required files exist: reddit_profiles.json, twitter_profiles.csv, simulation_config.json
    
    The run scripts (run_*.py) stay in backend/scripts/ and are not copied into the simulation directory.
    
    Args:
        simulation_id: Simulation ID
        
    Returns:
        (is_prepared: bool, info: dict)
    """
    import os
    from ..config import Config
    
    simulation_dir = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, simulation_id)
    
    # The directory itself must exist
    if not os.path.exists(simulation_dir):
        return False, {"reason": "Simulation directory not found"}
    
    # Required files; the run scripts are not among them, they live in backend/scripts/
    required_files = [
        "state.json",
        "simulation_config.json",
        "reddit_profiles.json",
        "twitter_profiles.csv"
    ]
    
    # Which of them exist
    existing_files = []
    missing_files = []
    for f in required_files:
        file_path = os.path.join(simulation_dir, f)
        if os.path.exists(file_path):
            existing_files.append(f)
        else:
            missing_files.append(f)
    
    if missing_files:
        return False, {
            "reason": "Required files are missing",
            "missing_files": missing_files,
            "existing_files": existing_files
        }
    
    # Read the status out of state.json
    state_file = os.path.join(simulation_dir, "state.json")
    try:
        import json
        with open(state_file, 'r', encoding='utf-8') as f:
            state_data = json.load(f)
        
        status = state_data.get("status", "")
        config_generated = state_data.get("config_generated", False)
        
        # Detail for the log
        logger.debug(f"Checking preparation state: {simulation_id}, status={status}, config_generated={config_generated}")
        
        # config_generated=True plus the files on disk means preparation finished.
        # Every one of these statuses implies preparation is already done:
        # - ready: prepared, ready to run
        # - preparing: finished when config_generated is True
        # - running: running, so preparation finished long ago
        # - completed: finished running, so preparation finished long ago
        # - stopped: stopped, so preparation finished long ago
        # - failed: the run failed, but preparation itself succeeded
        prepared_statuses = ["ready", "preparing", "running", "completed", "stopped", "failed"]
        if status in prepared_statuses and config_generated:
            # Count what was generated
            profiles_file = os.path.join(simulation_dir, "reddit_profiles.json")
            config_file = os.path.join(simulation_dir, "simulation_config.json")
            
            profiles_count = 0
            if os.path.exists(profiles_file):
                with open(profiles_file, 'r', encoding='utf-8') as f:
                    profiles_data = json.load(f)
                    profiles_count = len(profiles_data) if isinstance(profiles_data, list) else 0
            
            # Preparing but complete on disk: promote the status to ready
            if status == "preparing":
                try:
                    state_data["status"] = "ready"
                    from datetime import datetime
                    state_data["updated_at"] = datetime.now().isoformat()
                    with open(state_file, 'w', encoding='utf-8') as f:
                        json.dump(state_data, f, ensure_ascii=False, indent=2)
                    logger.info(f"Promoted simulation status: {simulation_id} preparing -> ready")
                    status = "ready"
                except Exception as e:
                    logger.warning(f"Failed to promote the simulation status: {e}")
            
            logger.info(f"Simulation {simulation_id} is prepared (status={status}, config_generated={config_generated})")
            return True, {
                "status": status,
                "entities_count": state_data.get("entities_count", 0),
                "profiles_count": profiles_count,
                "entity_types": state_data.get("entity_types", []),
                "config_generated": config_generated,
                "created_at": state_data.get("created_at"),
                "updated_at": state_data.get("updated_at"),
                "existing_files": existing_files
            }
        else:
            logger.warning(f"Simulation {simulation_id} is not prepared (status={status}, config_generated={config_generated})")
            return False, {
                "reason": f"Status is not a prepared one, or config_generated is false: status={status}, config_generated={config_generated}",
                "status": status,
                "config_generated": config_generated
            }
            
    except Exception as e:
        return False, {"reason": f"Failed to read the state file: {str(e)}"}


@simulation_bp.route('/prepare', methods=['POST'])
def prepare_simulation():
    """
    Prepare a simulation environment as a background task, with the LLM generating every parameter.
    
    Preparation takes minutes, so this returns a task_id immediately.
    Poll GET /api/simulation/prepare/status for progress.
    
    Behaviour:
    - Detects work that is already prepared and does not regenerate it
    - Returns the existing result when the simulation is already prepared
    - Regenerates everything when force_regenerate=true
    - Refuses with HTTP 409 and pending=true while a preparation for the same
      simulation is already running in this process, force_regenerate included.
      Two preparation threads interleave their writes to the same profile and
      config files and the loser silently overwrites the winner.

    Steps:
    1. Check for preparation that already finished
    2. Read and filter the entities out of the Zep graph
    3. Generate an OASIS agent profile per entity, with retries
    4. Ask the LLM for the simulation configuration, with retries
    5. Write the configuration file and the preset scripts
    
    Request (JSON):
        {
            "simulation_id": "sim_xxxx",                  // required
            "entity_types": ["Student", "PublicFigure"],  // optional, entity types to use
            "use_llm_for_profiles": true,                 // optional, generate profiles with the LLM
            "parallel_profile_count": 5,                  // optional, profiles generated in parallel, defaults to 5
            "force_regenerate": false                     // optional, defaults to false
        }
    
    Returns:
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "task_id": "task_xxxx",           // present for a new task
                "status": "preparing|ready",
                "message": "Preparation task started|Preparation already complete",
                "already_prepared": true|false
            }
        }
    """
    from ..models.task import TaskManager, TaskStatus
    
    try:
        data = request.get_json() or {}
        
        simulation_id = data.get('simulation_id')
        if not simulation_id:
            return jsonify({
                "success": False,
                "error": t('api.requireSimulationId')
            }), 400
        
        manager = SimulationManager()
        state = manager.get_simulation(simulation_id)
        
        if not state:
            return jsonify({
                "success": False,
                "error": t('api.simulationNotFound', id=simulation_id)
            }), 404
        
        # Regenerate everything when the caller asks for it
        force_regenerate = data.get('force_regenerate', False)
        logger.info(f"Handling /prepare: simulation_id={simulation_id}, force_regenerate={force_regenerate}")

        # Refuse a second preparation, force_regenerate included. Two threads
        # writing the same profile and config files interleave their output,
        # and the loser silently overwrites the winner. The authoritative claim
        # is taken below; this is the early, cheap refusal.
        in_flight, in_flight_task_id = _preparation_in_flight(simulation_id)
        if in_flight:
            return jsonify({
                "success": False,
                "pending": True,
                "task_id": in_flight_task_id,
                "error": (
                    f"Preparation is already running for {simulation_id}. "
                    f"Wait for it to finish, or restart the simulation."
                ),
            }), 409

        # Skip the work when the simulation is already prepared
        if not force_regenerate:
            logger.debug(f"Checking whether simulation {simulation_id} is prepared")
            is_prepared, prepare_info = _check_simulation_prepared(simulation_id)
            logger.debug(f"Check result: is_prepared={is_prepared}, prepare_info={prepare_info}")
            if is_prepared:
                logger.info(f"Simulation {simulation_id} is already prepared; skipping regeneration")
                return jsonify({
                    "success": True,
                    "data": {
                        "simulation_id": simulation_id,
                        "status": "ready",
                        "message": t('api.alreadyPrepared'),
                        "already_prepared": True,
                        "prepare_info": prepare_info
                    }
                })
            else:
                logger.info(f"Simulation {simulation_id} is not prepared; starting the preparation task")
        
        # Everything preparation needs comes off the project
        project = ProjectManager.get_project(state.project_id)
        if not project:
            return jsonify({
                "success": False,
                "error": t('api.projectNotFound', id=state.project_id)
            }), 404
        
        # The simulation requirement
        simulation_requirement = project.simulation_requirement or ""
        if not simulation_requirement:
            return jsonify({
                "success": False,
                "error": t('api.projectMissingRequirement')
            }), 400
        
        # The extracted document text
        document_text = ProjectManager.get_extracted_text(state.project_id) or ""
        
        entity_types_list = data.get('entity_types')
        use_llm_for_profiles = data.get('use_llm_for_profiles', True)
        parallel_profile_count = data.get('parallel_profile_count', 5)
        
        # ========== Count the entities synchronously, before the task starts ==========
        # This way the frontend knows the expected agent total as soon as /prepare returns.
        try:
            logger.info(f"Counting entities: graph_id={state.graph_id}")
            reader = ZepEntityReader()
            # A fast read: the edges are not needed, only the count
            filtered_preview = reader.filter_defined_entities(
                graph_id=state.graph_id,
                defined_entity_types=entity_types_list,
                enrich_with_edges=False  # Skipping the edges keeps this fast
            )
            # Persist the count so the frontend can read it immediately
            state.entities_count = filtered_preview.filtered_count
            state.entity_types = list(filtered_preview.entity_types)
            logger.info(f"Expecting {filtered_preview.filtered_count} entities, types: {filtered_preview.entity_types}")
        except Exception as e:
            logger.warning(f"Failed to count the entities; the background task will retry: {e}")
            # A failure here is not fatal; the background task reads them again
        
        # Claim the simulation. Losing this race means another request started
        # preparing between the check above and here, so nothing was started
        # and there is nothing to release.
        if not _claim_preparation(simulation_id):
            _, in_flight_task_id = _preparation_in_flight(simulation_id)
            return jsonify({
                "success": False,
                "pending": True,
                "task_id": in_flight_task_id,
                "error": (
                    f"Preparation is already running for {simulation_id}. "
                    f"Wait for it to finish, or restart the simulation."
                ),
            }), 409

        # Create the background task
        task_manager = TaskManager()
        task_id = task_manager.create_task(
            task_type="simulation_prepare",
            metadata={
                "simulation_id": simulation_id,
                "project_id": state.project_id
            }
        )
        _note_preparation_task(simulation_id, task_id)

        # Update the simulation state, including the entity count read above
        state.status = SimulationStatus.PREPARING
        manager._save_simulation_state(state)

        # The background task
        def run_prepare():
            try:
                task_manager.update_task(
                    task_id,
                    status=TaskStatus.PROCESSING,
                    progress=0,
                    message=t('progress.startPreparingEnv')
                )
                
                # Prepare the simulation, reporting progress as it goes
                # Per-stage progress detail
                stage_details = {}
                
                def progress_callback(stage, progress, message, **kwargs):
                    # Overall progress across every stage
                    stage_weights = {
                        "reading": (0, 20),           # 0-20%
                        "generating_profiles": (20, 70),  # 20-70%
                        "generating_config": (70, 90),    # 70-90%
                        "copying_scripts": (90, 100)       # 90-100%
                    }
                    
                    start, end = stage_weights.get(stage, (0, 100))
                    current_progress = int(start + (end - start) * progress / 100)
                    
                    # Human-readable stage names
                    stage_names = {
                        "reading": t('progress.readingGraphEntities'),
                        "generating_profiles": t('progress.generatingProfiles'),
                        "generating_config": t('progress.generatingSimConfig'),
                        "copying_scripts": t('progress.preparingScripts')
                    }
                    
                    stage_index = list(stage_weights.keys()).index(stage) + 1 if stage in stage_weights else 1
                    total_stages = len(stage_weights)
                    
                    # Update this stage's detail
                    stage_details[stage] = {
                        "stage_name": stage_names.get(stage, stage),
                        "stage_progress": progress,
                        "current": kwargs.get("current", 0),
                        "total": kwargs.get("total", 0),
                        "item_name": kwargs.get("item_name", "")
                    }
                    
                    # Assemble the detailed progress payload
                    detail = stage_details[stage]
                    progress_detail_data = {
                        "current_stage": stage,
                        "current_stage_name": stage_names.get(stage, stage),
                        "stage_index": stage_index,
                        "total_stages": total_stages,
                        "stage_progress": progress,
                        "current_item": detail["current"],
                        "total_items": detail["total"],
                        "item_description": message
                    }
                    
                    # Assemble the short message
                    if detail["total"] > 0:
                        detailed_message = (
                            f"[{stage_index}/{total_stages}] {stage_names.get(stage, stage)}: "
                            f"{detail['current']}/{detail['total']} - {message}"
                        )
                    else:
                        detailed_message = f"[{stage_index}/{total_stages}] {stage_names.get(stage, stage)}: {message}"
                    
                    task_manager.update_task(
                        task_id,
                        progress=current_progress,
                        message=detailed_message,
                        progress_detail=progress_detail_data
                    )
                
                result_state = manager.prepare_simulation(
                    simulation_id=simulation_id,
                    simulation_requirement=simulation_requirement,
                    document_text=document_text,
                    defined_entity_types=entity_types_list,
                    use_llm_for_profiles=use_llm_for_profiles,
                    progress_callback=progress_callback,
                    parallel_profile_count=parallel_profile_count
                )

                if result_state.status == SimulationStatus.FAILED:
                    task_manager.fail_task(
                        task_id,
                        result_state.error or "Failed to prepare the simulation."
                    )
                else:
                    task_manager.complete_task(
                        task_id,
                        result=result_state.to_simple_dict()
                    )
                
            except Exception as e:
                logger.error(f"Failed to prepare the simulation: {str(e)}")
                task_manager.fail_task(task_id, str(e))
                
                # Mark the simulation failed
                state = manager.get_simulation(simulation_id)
                if state:
                    state.status = SimulationStatus.FAILED
                    state.error = str(e)
                    manager._save_simulation_state(state)
            finally:
                _release_preparation(simulation_id)

        # Start the background thread
        try:
            thread = threading.Thread(target=run_prepare, daemon=True)
            thread.start()
        except Exception:
            # The thread never ran, so its finally clause never will either.
            _release_preparation(simulation_id)
            raise

        return jsonify({
            "success": True,
            "data": {
                "simulation_id": simulation_id,
                "task_id": task_id,
                "status": "preparing",
                "message": t('api.prepareStarted'),
                "already_prepared": False,
                "expected_entities_count": state.entities_count,  # Expected agent total
                "entity_types": state.entity_types  # Entity types found
            }
        })
        
    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 404
        
    except Exception as e:
        logger.error(f"Failed to start the preparation task: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/prepare/status', methods=['POST'])
def get_prepare_status():
    """
    Return the progress of a preparation task.
    
    Two ways to ask:
    1. By task_id, for the progress of a task in flight
    2. By simulation_id, to check whether preparation already finished
    
    Request (JSON):
        {
            "task_id": "task_xxxx",          // optional, returned by /prepare
            "simulation_id": "sim_xxxx"      // optional, to check for finished preparation
        }
    
    Returns:
        {
            "success": true,
            "data": {
                "task_id": "task_xxxx",
                "status": "processing|completed|ready",
                "progress": 45,
                "message": "...",
                "already_prepared": true|false,
                "prepare_info": {...}            // detail, when preparation is complete
            }
        }
    """
    from ..models.task import TaskManager
    
    try:
        data = request.get_json() or {}
        
        task_id = data.get('task_id')
        simulation_id = data.get('simulation_id')
        
        # With a simulation_id, check for finished preparation first
        if simulation_id:
            is_prepared, prepare_info = _check_simulation_prepared(simulation_id)
            if is_prepared:
                return jsonify({
                    "success": True,
                    "data": {
                        "simulation_id": simulation_id,
                        "status": "ready",
                        "progress": 100,
                        "message": t('api.alreadyPrepared'),
                        "already_prepared": True,
                        "prepare_info": prepare_info
                    }
                })
        
        # Without a task_id there is nothing left to report
        if not task_id:
            if simulation_id:
                # A simulation_id, but preparation has not finished
                return jsonify({
                    "success": True,
                    "data": {
                        "simulation_id": simulation_id,
                        "status": "not_started",
                        "progress": 0,
                        "message": t('api.notStartedPrepare'),
                        "already_prepared": False
                    }
                })
            return jsonify({
                "success": False,
                "error": t('api.requireTaskOrSimId')
            }), 400
        
        task_manager = TaskManager()
        task = task_manager.get_task(task_id)
        
        if not task:
            # No such task, but a simulation_id may still show finished preparation
            if simulation_id:
                is_prepared, prepare_info = _check_simulation_prepared(simulation_id)
                if is_prepared:
                    return jsonify({
                        "success": True,
                        "data": {
                            "simulation_id": simulation_id,
                            "task_id": task_id,
                            "status": "ready",
                            "progress": 100,
                            "message": t('api.taskCompletedPrepared'),
                            "already_prepared": True,
                            "prepare_info": prepare_info
                        }
                    })
            
            return jsonify({
                "success": False,
                "error": t('api.taskNotFound', id=task_id)
            }), 404
        
        task_dict = task.to_dict()
        task_dict["already_prepared"] = False
        
        return jsonify({
            "success": True,
            "data": task_dict
        })
        
    except Exception as e:
        logger.error(f"Failed to read the task status: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@simulation_bp.route('/<simulation_id>', methods=['GET'])
def get_simulation(simulation_id: str):
    """Return the simulation state."""
    try:
        manager = SimulationManager()
        state = manager.get_simulation(simulation_id)
        
        if not state:
            return jsonify({
                "success": False,
                "error": t('api.simulationNotFound', id=simulation_id)
            }), 404
        
        result = state.to_dict()
        
        # A prepared simulation carries the instructions for running it by hand
        if state.status == SimulationStatus.READY:
            result["run_instructions"] = manager.get_run_instructions(simulation_id)
        
        return jsonify({
            "success": True,
            "data": result
        })
        
    except Exception as e:
        logger.error(f"Failed to read the simulation state: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/list', methods=['GET'])
def list_simulations():
    """
    List every simulation.
    
    Query parameters:
        project_id: Filter by project ID (optional)
    """
    try:
        project_id = request.args.get('project_id')
        
        manager = SimulationManager()
        simulations = manager.list_simulations(project_id=project_id)
        
        return jsonify({
            "success": True,
            "data": [s.to_dict() for s in simulations],
            "count": len(simulations)
        })
        
    except Exception as e:
        logger.error(f"Failed to list the simulations: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


def _get_report_id_for_simulation(simulation_id: str) -> str:
    """
    Return the newest report_id for a simulation.
    
    Walks the reports directory for reports matching the simulation, and returns
    the newest of them by created_at.
    
    Args:
        simulation_id: Simulation ID
        
    Returns:
        A report_id, or None
    """
    import json
    from datetime import datetime
    
    # The reports directory is backend/uploads/reports.
    # __file__ is app/api/simulation.py, so backend/ is two levels up.
    reports_dir = os.path.join(os.path.dirname(__file__), '../../uploads/reports')
    if not os.path.exists(reports_dir):
        return None
    
    matching_reports = []
    
    try:
        for report_folder in os.listdir(reports_dir):
            report_path = os.path.join(reports_dir, report_folder)
            if not os.path.isdir(report_path):
                continue
            
            meta_file = os.path.join(report_path, "meta.json")
            if not os.path.exists(meta_file):
                continue
            
            try:
                with open(meta_file, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                
                if meta.get("simulation_id") == simulation_id:
                    matching_reports.append({
                        "report_id": meta.get("report_id"),
                        "created_at": meta.get("created_at", ""),
                        "status": meta.get("status", "")
                    })
            except Exception:
                continue
        
        if not matching_reports:
            return None
        
        # Newest first
        matching_reports.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return matching_reports[0].get("report_id")
        
    except Exception as e:
        logger.warning(f"Failed to find a report for simulation {simulation_id}: {e}")
        return None


@simulation_bp.route('/history', methods=['GET'])
def get_simulation_history():
    """
    Return the simulation history, enriched with project detail.
    
    Backs the history list on the home page and the Simulations menu: every
    simulation with its project name, requirement and progress.

    Rows come back newest first, by created_at.

    Query parameters:
        limit: Maximum number of simulations to return (defaults to 20)
        project_id: Only simulations belonging to this project (optional)

    Returns:
        {
            "success": true,
            "data": [
                {
                    "simulation_id": "sim_xxxx",
                    "project_id": "proj_xxxx",
                    "project_name": "Campus opinion analysis",
                    "simulation_requirement": "If the university announces...",
                    "status": "completed",
                    "runner_status": "completed",
                    "stale": false,
                    "process_pid": null,
                    "entities_count": 68,
                    "profiles_count": 68,
                    "entity_types": ["Student", "Professor", ...],
                    "created_at": "2024-12-10",
                    "updated_at": "2024-12-10",
                    "total_rounds": 120,
                    "current_round": 120,
                    "report_id": "report_xxxx",
                    "version": "v1.0.2"
                },
                ...
            ],
            "count": 7
        }
    """
    try:
        limit = request.args.get('limit', 20, type=int)
        project_id = request.args.get('project_id')

        manager = SimulationManager()
        # list_simulations already sorts newest first; sort again here so the
        # ordering this endpoint promises does not depend on that.
        simulations = sorted(
            manager.list_simulations(project_id=project_id),
            key=lambda s: s.created_at,
            reverse=True,
        )[:limit]

        # One lookup per project, not one per simulation: a project usually
        # owns several simulations and ProjectManager reads from disk.
        projects: Dict[str, Any] = {}

        # Enrich each simulation from its own files
        enriched_simulations = []
        for sim in simulations:
            sim_dict = sim.to_dict()
            
            # The simulation requirement comes out of simulation_config.json
            config = manager.get_simulation_config(sim.simulation_id)
            if config:
                sim_dict["simulation_requirement"] = config.get("simulation_requirement", "")
                time_config = config.get("time_config", {})
                sim_dict["total_simulation_hours"] = time_config.get("total_simulation_hours", 0)
                # Recommended rounds, used as a fallback
                recommended_rounds = int(
                    time_config.get("total_simulation_hours", 0) * 60 / 
                    max(time_config.get("minutes_per_round", 60), 1)
                )
            else:
                sim_dict["simulation_requirement"] = ""
                sim_dict["total_simulation_hours"] = 0
                recommended_rounds = 0
            
            # run_state.json carries the round count the user actually set
            run_state = SimulationRunner.get_run_state(sim.simulation_id)
            if run_state:
                sim_dict["current_round"] = run_state.current_round
                sim_dict["runner_status"] = run_state.runner_status.value
                # Prefer the user's total_rounds, falling back to the recommendation
                sim_dict["total_rounds"] = run_state.total_rounds if run_state.total_rounds > 0 else recommended_rounds
            else:
                sim_dict["current_round"] = 0
                sim_dict["runner_status"] = "idle"
                sim_dict["total_rounds"] = recommended_rounds

            # Whether anything is actually running behind the saved status. A
            # row claiming to run with no process left is stale, and the menu
            # marks it so rather than showing a progress bar that never moves.
            activity = SimulationRunner.describe_activity(sim.simulation_id)
            sim_dict["active"] = activity["active"]
            sim_dict["stale"] = activity["stale"]
            sim_dict["process_pid"] = activity["pid"]
            sim_dict["adopted"] = activity["adopted"]

            # The project this simulation belongs to
            if sim.project_id not in projects:
                projects[sim.project_id] = ProjectManager.get_project(sim.project_id)
            project = projects[sim.project_id]
            sim_dict["project_name"] = project.name if project else None
            if project and getattr(project, 'files', None):
                sim_dict["files"] = [
                    {"filename": f.get("filename", "Unnamed file")}
                    for f in project.files[:3]
                ]
            else:
                sim_dict["files"] = []

            # The newest report generated for this simulation
            sim_dict["report_id"] = _get_report_id_for_simulation(sim.simulation_id)
            
            # Schema version of this row
            sim_dict["version"] = "v1.0.2"
            
            # Date, for the list column
            try:
                created_date = sim_dict.get("created_at", "")[:10]
                sim_dict["created_date"] = created_date
            except:
                sim_dict["created_date"] = ""
            
            enriched_simulations.append(sim_dict)
        
        return jsonify({
            "success": True,
            "data": enriched_simulations,
            "count": len(enriched_simulations)
        })
        
    except Exception as e:
        logger.error(f"Failed to read the simulation history: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/profiles', methods=['GET'])
def get_simulation_profiles(simulation_id: str):
    """
    Return a simulation's agent profiles.
    
    Query parameters:
        platform: Platform (reddit/twitter, defaults to the simulation's own)
    """
    try:
        platform = request.args.get('platform') or _get_default_platform(simulation_id)

        manager = SimulationManager()
        profiles = manager.get_profiles(simulation_id, platform=platform)
        
        return jsonify({
            "success": True,
            "data": {
                "platform": platform,
                "count": len(profiles),
                "profiles": profiles
            }
        })
        
    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 404
        
    except Exception as e:
        logger.error(f"Failed to read the agent profiles: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/profiles/realtime', methods=['GET'])
def get_simulation_profiles_realtime(simulation_id: str):
    """
    Return a simulation's agent profiles while they are still being generated.
    
    How this differs from /profiles:
    - Reads the files directly, bypassing SimulationManager
    - Suited to watching generation in progress
    - Returns extra metadata, such as the file mtime and whether work is ongoing
    
    Query parameters:
        platform: Platform (reddit/twitter, defaults to the simulation's own)
    
    Returns:
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "platform": "reddit",
                "count": 15,
                "total_expected": 93,  // expected total, when known
                "is_generating": true,
                "file_exists": true,
                "file_modified_at": "2025-12-04T18:20:00",
                "profiles": [...]
            }
        }
    """
    import json
    import csv
    from datetime import datetime
    
    try:
        platform = request.args.get('platform') or _get_default_platform(simulation_id)

        # The simulation directory
        sim_dir = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, simulation_id)
        
        if not os.path.exists(sim_dir):
            return jsonify({
                "success": False,
                "error": t('api.simulationNotFound', id=simulation_id)
            }), 404
        
        # The profile file for this platform
        if platform == "reddit":
            profiles_file = os.path.join(sim_dir, "reddit_profiles.json")
        else:
            profiles_file = os.path.join(sim_dir, "twitter_profiles.csv")
        
        # Read it when it exists
        file_exists = os.path.exists(profiles_file)
        profiles = []
        file_modified_at = None
        
        if file_exists:
            # File modification time
            file_stat = os.stat(profiles_file)
            file_modified_at = datetime.fromtimestamp(file_stat.st_mtime).isoformat()
            
            try:
                if platform == "reddit":
                    with open(profiles_file, 'r', encoding='utf-8') as f:
                        profiles = json.load(f)
                else:
                    with open(profiles_file, 'r', encoding='utf-8') as f:
                        reader = csv.DictReader(f)
                        profiles = list(reader)
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"Failed to read the profiles file, which may still be written: {e}")
                profiles = []
        
        # state.json says whether generation is still running
        is_generating = False
        total_expected = None
        status = None
        error = None
        
        state_file = os.path.join(sim_dir, "state.json")
        if os.path.exists(state_file):
            try:
                with open(state_file, 'r', encoding='utf-8') as f:
                    state_data = json.load(f)
                    status = state_data.get("status", "")
                    is_generating = status == "preparing"
                    total_expected = state_data.get("entities_count")
                    error = state_data.get("error")
            except Exception:
                pass
        
        return jsonify({
            "success": True,
            "data": {
                "simulation_id": simulation_id,
                "platform": platform,
                "count": len(profiles),
                "total_expected": total_expected,
                "is_generating": is_generating,
                "status": status,
                "error": error,
                "file_exists": file_exists,
                "file_modified_at": file_modified_at,
                "profiles": profiles
            }
        })
        
    except Exception as e:
        logger.error(f"Failed to read the live agent profiles: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/config/realtime', methods=['GET'])
def get_simulation_config_realtime(simulation_id: str):
    """
    Return the simulation configuration while it is still being generated.
    
    How this differs from /config:
    - Reads the file directly, bypassing SimulationManager
    - Suited to watching generation in progress
    - Returns extra metadata, such as the file mtime and whether work is ongoing
    - Returns partial information before the configuration is complete
    
    Returns:
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "file_exists": true,
                "file_modified_at": "2025-12-04T18:20:00",
                "is_generating": true,
                "generation_stage": "generating_config",  // the stage in flight
                "config": {...}  // the configuration, when it exists
            }
        }
    """
    import json
    from datetime import datetime
    
    try:
        # The simulation directory
        sim_dir = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, simulation_id)
        
        if not os.path.exists(sim_dir):
            return jsonify({
                "success": False,
                "error": t('api.simulationNotFound', id=simulation_id)
            }), 404
        
        # The configuration file
        config_file = os.path.join(sim_dir, "simulation_config.json")
        
        # Read it when it exists
        file_exists = os.path.exists(config_file)
        config = None
        file_modified_at = None
        
        if file_exists:
            # File modification time
            file_stat = os.stat(config_file)
            file_modified_at = datetime.fromtimestamp(file_stat.st_mtime).isoformat()
            
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"Failed to read the config file, which may still be written: {e}")
                config = None
        
        # state.json says whether generation is still running
        is_generating = False
        generation_stage = None
        status = None
        error = None
        profiles_generated = False
        config_generated = False
        
        state_file = os.path.join(sim_dir, "state.json")
        if os.path.exists(state_file):
            try:
                with open(state_file, 'r', encoding='utf-8') as f:
                    state_data = json.load(f)
                    status = state_data.get("status", "")
                    error = state_data.get("error")
                    is_generating = status == "preparing"
                    profiles_generated = state_data.get("profiles_generated", False)
                    config_generated = state_data.get("config_generated", False)
                    
                    # Work out the stage in flight
                    if is_generating:
                        if profiles_generated:
                            generation_stage = "generating_config"
                        else:
                            generation_stage = "generating_profiles"
                    elif status == "ready":
                        generation_stage = "completed"
                    elif status == "failed":
                        generation_stage = "failed"
            except Exception:
                pass
        
        # Assemble the response
        response_data = {
            "simulation_id": simulation_id,
            "file_exists": file_exists,
            "file_modified_at": file_modified_at,
            "is_generating": is_generating,
            "status": status,
            "error": error,
            "generation_stage": generation_stage,
            "profiles_generated": profiles_generated,
            "config_generated": config_generated,
            "config": config
        }
        
        # Summarise the configuration when it exists
        if config:
            response_data["summary"] = {
                "total_agents": len(config.get("agent_configs", [])),
                "simulation_hours": config.get("time_config", {}).get("total_simulation_hours"),
                "initial_posts_count": len(config.get("event_config", {}).get("initial_posts", [])),
                "hot_topics_count": len(config.get("event_config", {}).get("hot_topics", [])),
                "has_twitter_config": "twitter_config" in config,
                "has_reddit_config": "reddit_config" in config,
                "generated_at": config.get("generated_at"),
                "llm_model": config.get("llm_model")
            }
        
        return jsonify({
            "success": True,
            "data": response_data
        })
        
    except Exception as e:
        logger.error(f"Failed to read the live simulation config: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/config', methods=['GET'])
def get_simulation_config(simulation_id: str):
    """
    Return the full simulation configuration the LLM generated.
    
    It contains:
        - time_config: duration, rounds, and the peak and quiet hours
        - agent_configs: per-agent activity, posting frequency and stance
        - event_config: the initial posts and the hot topics
        - platform_configs: per-platform settings
        - generation_reasoning: why the LLM chose this configuration
    """
    try:
        manager = SimulationManager()
        config = manager.get_simulation_config(simulation_id)
        
        if not config:
            return jsonify({
                "success": False,
                "error": t('api.configNotFound')
            }), 404
        
        return jsonify({
            "success": True,
            "data": config
        })
        
    except Exception as e:
        logger.error(f"Failed to read the simulation config: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/config/download', methods=['GET'])
def download_simulation_config(simulation_id: str):
    """Download the simulation configuration file."""
    try:
        manager = SimulationManager()
        # ensure=False: a download for an unknown or deleted id must not leave
        # an empty directory behind that then shows up as a phantom row.
        sim_dir = manager._get_simulation_dir(simulation_id, ensure=False)
        config_path = os.path.join(sim_dir, "simulation_config.json")
        
        if not os.path.exists(config_path):
            return jsonify({
                "success": False,
                "error": t('api.configFileNotFound')
            }), 404
        
        return send_file(
            config_path,
            as_attachment=True,
            download_name="simulation_config.json"
        )
        
    except Exception as e:
        logger.error(f"Failed to download the simulation config: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/script/<script_name>/download', methods=['GET'])
def download_simulation_script(script_name: str):
    """
    Download one of the shared simulation run scripts from backend/scripts/.
    
    script_name is one of:
        - run_twitter_simulation.py
        - run_reddit_simulation.py
        - run_parallel_simulation.py
        - action_logger.py
    """
    try:
        # The scripts live in backend/scripts/
        scripts_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../scripts'))
        
        # Only the known scripts may be downloaded
        allowed_scripts = [
            "run_twitter_simulation.py",
            "run_reddit_simulation.py", 
            "run_parallel_simulation.py",
            "action_logger.py"
        ]
        
        if script_name not in allowed_scripts:
            return jsonify({
                "success": False,
                "error": t('api.unknownScript', name=script_name, allowed=allowed_scripts)
            }), 400
        
        script_path = os.path.join(scripts_dir, script_name)
        
        if not os.path.exists(script_path):
            return jsonify({
                "success": False,
                "error": t('api.scriptFileNotFound', name=script_name)
            }), 404
        
        return send_file(
            script_path,
            as_attachment=True,
            download_name=script_name
        )
        
    except Exception as e:
        logger.error(f"Failed to download the script: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== Profile generation, usable on its own ==============

@simulation_bp.route('/generate-profiles', methods=['POST'])
def generate_profiles():
    """
    Generate OASIS agent profiles straight from a graph, without a simulation.
    
    Request (JSON):
        {
            "graph_id": "sosim_xxxx",         // required
            "entity_types": ["Student"],      // optional
            "use_llm": true,                  // optional
            "platform": "reddit"              // optional
        }
    """
    try:
        data = request.get_json() or {}
        
        graph_id = data.get('graph_id')
        if not graph_id:
            return jsonify({
                "success": False,
                "error": t('api.requireGraphId')
            }), 400
        
        entity_types = data.get('entity_types')
        use_llm = data.get('use_llm', True)
        platform = data.get('platform', 'reddit')
        
        reader = ZepEntityReader()
        filtered = reader.filter_defined_entities(
            graph_id=graph_id,
            defined_entity_types=entity_types,
            enrich_with_edges=True
        )
        
        if filtered.filtered_count == 0:
            return jsonify({
                "success": False,
                "error": t('api.noMatchingEntities')
            }), 400
        
        generator = OasisProfileGenerator()
        profiles = generator.generate_profiles_from_entities(
            entities=filtered.entities,
            use_llm=use_llm
        )
        
        if platform == "reddit":
            profiles_data = [p.to_reddit_format() for p in profiles]
        elif platform == "twitter":
            profiles_data = [p.to_twitter_format() for p in profiles]
        else:
            profiles_data = [p.to_dict() for p in profiles]
        
        return jsonify({
            "success": True,
            "data": {
                "platform": platform,
                "entity_types": list(filtered.entity_types),
                "count": len(profiles_data),
                "profiles": profiles_data
            }
        })
        
    except Exception as e:
        logger.error(f"Failed to generate the agent profiles: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== Run control ==============

@simulation_bp.route('/start', methods=['POST'])
def start_simulation():
    """
    Start a simulation run.

    Request (JSON):
        {
            "simulation_id": "sim_xxxx",          // required
            "platform": "parallel",                // optional: twitter / reddit / parallel (default)
            "max_rounds": 100,                     // optional: cap on rounds, to truncate an over-long simulation
            "enable_graph_memory_update": false,   // optional: push agent activity into the Zep graph
            "force": false                         // optional: stop a live run and clear its logs first
        }

    About force:
        - When set, a running or completed simulation is stopped and its logs cleared first
        - The cleanup runs for every status, READY included, not only for a
          simulation caught mid-run: force_restarted=true in the response means
          the logs really were cleared
        - Cleared: run_state.json, actions.jsonl, simulation.log and the like
        - Kept: simulation_config.json and the profile files
        - Use it whenever a simulation has to run again from the start

    About enable_graph_memory_update:
        - When set, every agent action - posts, comments, likes - is written into the Zep graph as it happens
        - This lets the graph "remember" the run, for later analysis or chat
        - The simulation's project must have a valid graph_id
        - Writes are batched, to keep the API call count down

    Returns:
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "runner_status": "running",
                "process_pid": 12345,
                "twitter_running": true,
                "reddit_running": true,
                "started_at": "2025-12-01T10:00:00",
                "graph_memory_update_enabled": true,
                "force_restarted": true
            }
        }
    """
    try:
        data = request.get_json() or {}

        simulation_id = data.get('simulation_id')
        if not simulation_id:
            return jsonify({
                "success": False,
                "error": t('api.requireSimulationId')
            }), 400

        platform = data.get('platform', 'parallel')
        max_rounds = data.get('max_rounds')  # Optional: cap on rounds
        enable_graph_memory_update = data.get('enable_graph_memory_update', False)  # Optional: write to the Zep graph
        force = data.get('force', False)  # Optional: stop and clear before starting
        if not isinstance(enable_graph_memory_update, bool):
            return jsonify({
                "success": False,
                "error": "enable_graph_memory_update must be a JSON boolean",
            }), 400
        if not isinstance(force, bool):
            return jsonify({
                "success": False,
                "error": "force must be a JSON boolean",
            }), 400

        # Validate max_rounds
        if max_rounds is not None:
            try:
                max_rounds = int(max_rounds)
                if max_rounds <= 0:
                    return jsonify({
                        "success": False,
                        "error": t('api.maxRoundsPositive')
                    }), 400
            except (ValueError, TypeError):
                return jsonify({
                    "success": False,
                    "error": t('api.maxRoundsInvalid')
                }), 400

        if platform not in ['twitter', 'reddit', 'parallel']:
            return jsonify({
                "success": False,
                "error": t('api.invalidPlatform', platform=platform)
            }), 400

        # The simulation has to be prepared
        manager = SimulationManager()
        state = manager.get_simulation(simulation_id)

        if not state:
            return jsonify({
                "success": False,
                "error": t('api.simulationNotFound', id=simulation_id)
            }), 404

        force_restarted = False

        # A prepared simulation may start again whatever status it rests in.
        # Only the "is it prepared at all" question depends on the status; the
        # finalization guard and the force cleanup below deliberately do not.
        # READY is the common case - it is what a finished run rests at, and
        # what the Simulations menu starts into - so nesting the cleanup under
        # "status is not READY" made force=true a no-op for almost every
        # simulation: it was accepted, reported back as force_restarted, and
        # left twitter/actions.jsonl and reddit/actions.jsonl in place. The new
        # monitor then reads those logs from byte 0 while the child appends,
        # which replays the entire previous run into the counters, trips the
        # completion flags off the old simulation_end events, and pushes every
        # old action to Zep a second time.
        if state.status != SimulationStatus.READY:
            # Preparation may have finished under an older status
            is_prepared, _prepare_info = _check_simulation_prepared(simulation_id)
            if not is_prepared:
                # Preparation never finished
                return jsonify({
                    "success": False,
                    "error": t('api.simNotReady', status=state.status.value)
                }), 400

        # From here on the status no longer gates anything: force means force.
        if _run_needs_finalization(simulation_id):
            if not force:
                return jsonify({
                    "success": False,
                    "error": t('api.simRunningForceHint')
                }), 400
            logger.info(f"Force start: finalizing the previous run of {simulation_id}")
            try:
                stopped = SimulationRunner.stop_simulation(simulation_id)
            except SimulationStopPending as error:
                return jsonify({
                    "success": False,
                    "pending": True,
                    "error": str(error),
                }), 409
            except Exception as error:
                return jsonify({
                    "success": False,
                    "error": (
                        "Cannot restart until the previous simulation "
                        f"finalizes safely: {error}"
                    ),
                }), 409
            if stopped.runner_status != RunnerStatus.STOPPED:
                return jsonify({
                    "success": False,
                    "error": "Previous simulation did not reach STOPPED",
                }), 409

        # Force always clears the previous run's logs, whatever status the
        # simulation rests in. Nothing is running by now, so the delete is
        # safe, and cleanup_simulation_logs is a no-op that reports success
        # when there is no previous run to clean.
        if force:
            # Settle "can we actually start?" BEFORE deleting anything. The
            # cleanup below is irreversible - run_state.json, simulation.log,
            # both actions.jsonl files and both platform databases - while
            # SimulationRunner.start_simulation refuses a simulation this
            # process still holds, and the two guards do not cover the same
            # cases: a run resting at STARTING, or one whose Zep updater is
            # still draining under a non-active status, walks past the
            # finalization check above and is refused by the runner. Cleaning
            # first left exactly that user with neither their previous run's
            # data nor a new run.
            blocker = SimulationRunner.describe_start_blocker(simulation_id)
            if blocker is not None:
                return jsonify({
                    "success": False,
                    "error": (
                        f"{blocker} Nothing was deleted. Stop it via /stop, "
                        "then retry."
                    ),
                }), 409
            logger.info(f"Force start: clearing the logs of {simulation_id}")
            cleanup_result = SimulationRunner.cleanup_simulation_logs(simulation_id)
            if not cleanup_result.get("success"):
                return jsonify({
                    "success": False,
                    "error": (
                        "Failed to clean previous simulation logs: "
                        f"{cleanup_result.get('errors')}"
                    ),
                }), 500
            force_restarted = True

        # Nothing is running any more, so rest the simulation at ready
        if state.status != SimulationStatus.READY:
            logger.info(f"Simulation {simulation_id} is prepared; resetting its status to ready (was {state.status.value})")
            state.status = SimulationStatus.READY
            manager._save_simulation_state(state)


        # Claim the graph the memory updates are written to, then start the run
        run_state, graph_id, error = _launch_under_graph_guard(
            manager,
            simulation_id,
            state,
            enable_graph_memory_update,
            lambda resolved_graph_id: SimulationRunner.start_simulation(
                simulation_id=simulation_id,
                platform=platform,
                max_rounds=max_rounds,
                enable_graph_memory_update=enable_graph_memory_update,
                graph_id=resolved_graph_id,
            ),
        )
        if error is not None:
            payload, status_code = error
            return jsonify(payload), status_code

        response_data = run_state.to_dict()
        if max_rounds:
            response_data['max_rounds_applied'] = max_rounds
        response_data['graph_memory_update_enabled'] = enable_graph_memory_update
        response_data['force_restarted'] = force_restarted
        if enable_graph_memory_update:
            response_data['graph_id'] = graph_id
        
        return jsonify({
            "success": True,
            "data": response_data
        })
        
    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400
        
    except Exception as e:
        logger.error(f"Failed to start the simulation: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/stop', methods=['POST'])
def stop_simulation():
    """
    Stop a simulation.
    
    Request (JSON):
        {
            "simulation_id": "sim_xxxx"  // required
        }
    
    Returns:
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "runner_status": "stopped",
                "completed_at": "2025-12-01T12:00:00"
            }
        }
    """
    try:
        data = request.get_json() or {}
        
        simulation_id = data.get('simulation_id')
        if not simulation_id:
            return jsonify({
                "success": False,
                "error": t('api.requireSimulationId')
            }), 400
        
        run_state = SimulationRunner.stop_simulation(simulation_id)
        
        # Update the simulation state
        manager = SimulationManager()
        state = manager.get_simulation(simulation_id)
        if state:
            state.status = SimulationStatus.STOPPED
            state.error = None
            manager._save_simulation_state(state)
        
        return jsonify({
            "success": True,
            "data": run_state.to_dict()
        })

    except SimulationStopPending as e:
        return jsonify({
            "success": False,
            "pending": True,
            "error": str(e),
        }), 202

    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400
        
    except Exception as e:
        logger.error(f"Failed to stop the simulation: {str(e)}")
        simulation_id = (request.get_json(silent=True) or {}).get('simulation_id')
        if simulation_id:
            manager = SimulationManager()
            state = manager.get_simulation(simulation_id)
            if state:
                state.status = SimulationStatus.FAILED
                state.error = str(e)
                manager._save_simulation_state(state)
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/restart', methods=['POST'])
def restart_simulation():
    """
    Restart a simulation from a clean slate.

    This is what the Simulations menu's Restart calls. It always quiesces the
    previous run and clears its output before relaunching: the child appends to
    twitter/actions.jsonl and reddit/actions.jsonl while a new monitor reads
    them from byte 0, so a restart that skips the cleanup replays the whole
    previous run - it re-counts every action, trips the completion flags off
    the old simulation_end events, and pushes every old action to Zep a second
    time. A completed simulation restarted through POST /start without
    force=true does exactly that, which is why Restart is its own route.

    It also rescues a simulation stranded in 'preparing'. Preparation runs in a
    daemon thread, so a backend restart kills it without raising and no failure
    handler runs; the row then sits in 'preparing' forever and every start is
    refused with "Simulation not ready". Restart rests such a simulation at
    ready when its files are complete, and at failed otherwise.

    Re-entry: restart does NOT supersede a preparation that is genuinely in
    flight in this process. It refuses with HTTP 409 and pending=true. There is
    no cancellation point in the preparation thread, so superseding it would
    leave two writers racing over the same profile and config files. The same
    guard is on POST /prepare.

    A LIVE run is refused with HTTP 409 unless force=true, exactly as POST
    /start refuses one. The restart is destructive - it reaps the child and
    deletes run_state.json, simulation.log, both actions.jsonl files and both
    platform databases - so it cannot be left to the frontend's disabled menu
    item: a curl, a template regression or any other programmatic caller
    reaches this route directly.

    Request (JSON):
        {
            "simulation_id": "sim_xxxx",          // required
            "platform": "parallel",                // optional: twitter / reddit / parallel (default)
            "max_rounds": 100,                     // optional: cap on rounds
            "enable_graph_memory_update": false,   // optional: push agent activity into the Zep graph
            "force": false                         // optional: restart a live run instead of refusing
        }

    Returns:
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "runner_status": "starting",
                "process_pid": 12345,
                "restarted": true,
                "forced": false,
                "rescued_from_preparing": false,
                "graph_memory_update_enabled": false
            }
        }
    """
    try:
        data = request.get_json() or {}

        simulation_id = data.get('simulation_id')
        if not simulation_id:
            return jsonify({
                "success": False,
                "error": t('api.requireSimulationId')
            }), 400

        platform = data.get('platform', 'parallel')
        max_rounds = data.get('max_rounds')
        enable_graph_memory_update = data.get('enable_graph_memory_update', False)
        force = data.get('force', False)  # Optional: restart a live run
        if not isinstance(enable_graph_memory_update, bool):
            return jsonify({
                "success": False,
                "error": "enable_graph_memory_update must be a JSON boolean",
            }), 400
        if not isinstance(force, bool):
            return jsonify({
                "success": False,
                "error": "force must be a JSON boolean",
            }), 400

        if max_rounds is not None:
            try:
                max_rounds = int(max_rounds)
                if max_rounds <= 0:
                    return jsonify({
                        "success": False,
                        "error": t('api.maxRoundsPositive')
                    }), 400
            except (ValueError, TypeError):
                return jsonify({
                    "success": False,
                    "error": t('api.maxRoundsInvalid')
                }), 400

        if platform not in ['twitter', 'reddit', 'parallel']:
            return jsonify({
                "success": False,
                "error": t('api.invalidPlatform', platform=platform)
            }), 400

        manager = SimulationManager()
        state = manager.get_simulation(simulation_id)
        if not state:
            return jsonify({
                "success": False,
                "error": t('api.simulationNotFound', id=simulation_id)
            }), 404

        # A live run is refused here, not only in the menu. Everything this
        # route does past this point is destructive - reap the child, delete
        # run_state.json, simulation.log, both actions.jsonl files and both
        # platform databases - and the Vue menu's :disabled Restart item does
        # not protect a caller who reaches the route by curl or by a template
        # that posts to it. Same force escape hatch and same message as POST
        # /start, so a run the one route refuses cannot be destroyed through
        # the other.
        #
        # _run_is_live, not /start's _run_needs_finalization: a stale row - one
        # whose saved state claims a run whose process is gone - must stay
        # restartable, because this route is the documented way out of that
        # state and the menu offers it there on purpose.
        if _run_is_live(simulation_id):
            if not force:
                return jsonify({
                    "success": False,
                    "live": True,
                    "error": t('api.simRunningForceHint'),
                }), 409
            logger.info(
                "Force restart: %s is still live and will be reaped first",
                simulation_id,
            )

        # A preparation running here owns the directory the restart would clear
        in_flight, in_flight_task_id = _preparation_in_flight(simulation_id)
        if in_flight:
            return jsonify({
                "success": False,
                "pending": True,
                "task_id": in_flight_task_id,
                "error": (
                    f"Simulation {simulation_id} is still being prepared. "
                    f"Wait for preparation to finish before restarting it."
                ),
            }), 409

        # 'preparing' with no preparation behind it is an orphan of a backend
        # restart, and the only escape from it in the UI is this route.
        rescued_from_preparing = False
        if state.status == SimulationStatus.PREPARING:
            rescued_from_preparing = True
            if not _rescue_stranded_preparation(manager, state):
                return jsonify({
                    "success": False,
                    "error": state.error or PREPARATION_INTERRUPTED_ERROR,
                    "data": {
                        "simulation_id": simulation_id,
                        "status": state.status.value,
                        "rescued_from_preparing": True,
                    },
                }), 409

        if state.status != SimulationStatus.READY:
            is_prepared, _prepare_info = _check_simulation_prepared(simulation_id)
            if not is_prepared:
                return jsonify({
                    "success": False,
                    "error": t('api.simNotReady', status=state.status.value)
                }), 400
            state.status = SimulationStatus.READY
            state.error = None
            manager._save_simulation_state(state)

        # The cleanup this route promises lives one layer down, in
        # SimulationRunner.restart_simulation, and it has to: it reaps the
        # previous child, joins the previous monitor, releases the in-memory
        # resources and drains a retained Zep updater, and only then calls
        # cleanup_simulation_logs and starts the new run. Clearing the logs
        # here instead would delete twitter/actions.jsonl and
        # reddit/actions.jsonl out from under a child that is still appending,
        # so this route must keep delegating rather than clean up itself.
        # SimulationRunner.restart_simulation calling cleanup_simulation_logs
        # unconditionally is a load-bearing part of this route's contract.
        run_state, graph_id, error = _launch_under_graph_guard(
            manager,
            simulation_id,
            state,
            enable_graph_memory_update,
            lambda resolved_graph_id: SimulationRunner.restart_simulation(
                simulation_id=simulation_id,
                platform=platform,
                max_rounds=max_rounds,
                enable_graph_memory_update=enable_graph_memory_update,
                graph_id=resolved_graph_id,
            ),
        )
        if error is not None:
            payload, status_code = error
            return jsonify(payload), status_code

        logger.info(
            "Restarted simulation %s, platform=%s, rescued_from_preparing=%s, "
            "force=%s",
            simulation_id,
            platform,
            rescued_from_preparing,
            force,
        )

        response_data = run_state.to_dict()
        response_data['restarted'] = True
        response_data['forced'] = force
        response_data['rescued_from_preparing'] = rescued_from_preparing
        response_data['graph_memory_update_enabled'] = enable_graph_memory_update
        if max_rounds:
            response_data['max_rounds_applied'] = max_rounds
        if enable_graph_memory_update:
            response_data['graph_id'] = graph_id

        return jsonify({
            "success": True,
            "data": response_data
        })

    except SimulationStopPending as e:
        # The previous monitor is still publishing its terminal state. Retrying
        # shortly succeeds; overwriting it would drop the run's last rounds.
        return jsonify({
            "success": False,
            "pending": True,
            "error": str(e),
        }), 409

    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400

    except Exception as e:
        logger.error(f"Failed to restart the simulation: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/logs', methods=['GET'])
def get_simulation_logs(simulation_id: str):
    """
    Read a bounded window of one of a simulation's logs.

    Backs the menu's View Logs. A long run writes hundreds of megabytes of
    actions.jsonl, so the file is never read whole: with no offset the window
    is the tail of the file, and with one it is the next window from there.
    A viewer polls forward by passing back the next_offset of the previous
    response.

    Query parameters:
        source: main (simulation.log), twitter, reddit or backend. Defaults to
            main. The backend log is the whole application log filtered to
            lines mentioning this simulation, which is the only trace a
            simulation leaves before it has a simulation.log of its own.
        offset: Byte offset to read forward from. Omit for the tail.
        max_lines: Maximum lines to return (defaults to 500)
        max_bytes: Size of the window in bytes, capped by the runner

    Returns:
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "source": "main",
                "path": "simulation.log",
                "exists": true,
                "size": 918273,
                "offset": 655360,
                "next_offset": 918273,
                "eof": true,
                "truncated": true,
                "restarted": false,
                "lines": ["..."],
                "runner_status": "running",
                "live": true
            }
        }

    live says whether more output is still expected, so the viewer can stop
    polling on a terminal run instead of re-reading a file that never changes.
    """
    try:
        source = request.args.get('source', 'main')
        offset = request.args.get('offset', type=int)
        max_lines = request.args.get('max_lines', 500, type=int)
        max_bytes = request.args.get('max_bytes', type=int)

        if source not in SimulationRunner.LOG_SOURCES:
            return jsonify({
                "success": False,
                "error": (
                    f"Unknown log source: {source}. "
                    f"Options: {', '.join(SimulationRunner.LOG_SOURCES)}."
                ),
            }), 400

        manager = SimulationManager()
        run_state = SimulationRunner.get_run_state(simulation_id)
        if manager.get_simulation(simulation_id) is None and run_state is None:
            return jsonify({
                "success": False,
                "error": t('api.simulationNotFound', id=simulation_id)
            }), 404

        result = SimulationRunner.tail_log(
            simulation_id=simulation_id,
            source=source,
            max_lines=max_lines,
            max_bytes=max_bytes,
            offset=offset,
        )

        runner_status = (
            run_state.runner_status if run_state else RunnerStatus.IDLE
        )
        result["runner_status"] = runner_status.value
        result["live"] = runner_status in SimulationRunner.ACTIVE_STATUSES

        return jsonify({
            "success": True,
            "data": result
        })

    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400

    except Exception as e:
        logger.error(f"Failed to read the simulation log: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>', methods=['DELETE'])
def delete_simulation(simulation_id: str):
    """
    Delete a simulation, its on-disk artifacts and its reports.

    Backs the menu's Delete. An active simulation is refused rather than having
    its child process orphaned; force reaps the run first, which is what the
    menu offers on a row the user already knows is stale.

    A preparation or a report still in flight is always refused, force
    included. Both read and write the simulation directory as they go, and a
    preparation would recreate half of it straight after the delete, leaving a
    phantom row behind.

    Query parameters:
        force: Reap an active run instead of refusing the delete (defaults to
            false). Also accepted in a JSON body.

    Returns:
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "deleted": true,
                "previous_status": "completed",
                "reaped_pid": null,
                "deleted_reports": ["report_xxxx"]
            }
        }
    """
    from ..services.report_agent import ReportManager, ReportStatus

    try:
        body = request.get_json(silent=True) or {}
        force = body.get('force')
        if force is None:
            force = request.args.get('force', 'false').lower() == 'true'
        if not isinstance(force, bool):
            return jsonify({
                "success": False,
                "error": "force must be a JSON boolean",
            }), 400

        # A preparation writes the simulation state back after every stage, so
        # a delete underneath it recreates the directory it just removed.
        in_flight, in_flight_task_id = _preparation_in_flight(simulation_id)
        if in_flight:
            return jsonify({
                "success": False,
                "pending": True,
                "task_id": in_flight_task_id,
                "error": (
                    f"Simulation {simulation_id} is still being prepared. "
                    f"Wait for preparation to finish before deleting it."
                ),
            }), 409

        # A report in flight outlives the request that started it, so this is
        # checked before anything is removed.
        unfinished_statuses = {
            ReportStatus.PENDING,
            ReportStatus.PLANNING,
            ReportStatus.GENERATING,
        }
        reports = ReportManager.list_reports(simulation_id=simulation_id, limit=100)
        generating = [
            report.report_id
            for report in reports
            if report.status in unfinished_statuses
        ]
        if generating:
            return jsonify({
                "success": False,
                "error": (
                    f"A report is still being generated for {simulation_id}. "
                    f"Wait for it to finish before deleting the simulation."
                ),
                "active_reports": generating,
            }), 409

        manager = SimulationManager()
        result = manager.delete_simulation(simulation_id, force=force)

        # The simulation's output is gone, so its reports describe nothing.
        deleted_reports = []
        for report in reports:
            try:
                if ReportManager.delete_report(report.report_id):
                    deleted_reports.append(report.report_id)
            except Exception as error:
                # The simulation itself is already gone; a report that resists
                # deletion is worth a log line, not a failed response.
                logger.warning(
                    "Failed to delete report %s of simulation %s: %s",
                    report.report_id,
                    simulation_id,
                    error,
                )
        result["deleted_reports"] = deleted_reports

        return jsonify({
            "success": True,
            "data": result
        })

    except SimulationBusyError as e:
        activity = SimulationRunner.describe_activity(simulation_id)
        return jsonify({
            "success": False,
            "busy": True,
            "error": str(e),
            "activity": activity,
        }), 409

    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 404

    except Exception as e:
        logger.error(f"Failed to delete the simulation: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== Live status ==============

@simulation_bp.route('/<simulation_id>/run-status', methods=['GET'])
def get_run_status(simulation_id: str):
    """
    Return a simulation's live run status, for frontend polling.
    
    Returns:
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "runner_status": "running",
                "current_round": 5,
                "total_rounds": 144,
                "progress_percent": 3.5,
                "simulated_hours": 2,
                "total_simulation_hours": 72,
                "twitter_running": true,
                "reddit_running": true,
                "twitter_actions_count": 150,
                "reddit_actions_count": 200,
                "total_actions_count": 350,
                "started_at": "2025-12-01T10:00:00",
                "updated_at": "2025-12-01T10:30:00"
            }
        }
    """
    try:
        run_state = SimulationRunner.get_run_state(simulation_id)
        
        if not run_state:
            return jsonify({
                "success": True,
                "data": {
                    "simulation_id": simulation_id,
                    "runner_status": "idle",
                    "current_round": 0,
                    "total_rounds": 0,
                    "progress_percent": 0,
                    "twitter_actions_count": 0,
                    "reddit_actions_count": 0,
                    "total_actions_count": 0,
                }
            })
        
        return jsonify({
            "success": True,
            "data": run_state.to_dict()
        })
        
    except Exception as e:
        logger.error(f"Failed to read the run status: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/run-status/detail', methods=['GET'])
def get_run_status_detail(simulation_id: str):
    """
    Return a simulation's run status together with every action.
    
    Backs the live activity feed in the frontend.
    
    Query parameters:
        platform: Filter by platform (twitter/reddit, optional)
    
    Returns:
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "runner_status": "running",
                "current_round": 5,
                ...
                "all_actions": [
                    {
                        "round_num": 5,
                        "timestamp": "2025-12-01T10:30:00",
                        "platform": "twitter",
                        "agent_id": 3,
                        "agent_name": "Agent Name",
                        "action_type": "CREATE_POST",
                        "action_args": {"content": "..."},
                        "result": null,
                        "success": true
                    },
                    ...
                ],
                "twitter_actions": [...],  # every Twitter action
                "reddit_actions": [...]    # every Reddit action
            }
        }
    """
    try:
        run_state = SimulationRunner.get_run_state(simulation_id)
        platform_filter = request.args.get('platform')
        
        if not run_state:
            return jsonify({
                "success": True,
                "data": {
                    "simulation_id": simulation_id,
                    "runner_status": "idle",
                    "all_actions": [],
                    "twitter_actions": [],
                    "reddit_actions": []
                }
            })
        
        # The complete action list
        all_actions = SimulationRunner.get_all_actions(
            simulation_id=simulation_id,
            platform=platform_filter
        )
        
        # The same actions, split by platform
        twitter_actions = SimulationRunner.get_all_actions(
            simulation_id=simulation_id,
            platform="twitter"
        ) if not platform_filter or platform_filter == "twitter" else []
        
        reddit_actions = SimulationRunner.get_all_actions(
            simulation_id=simulation_id,
            platform="reddit"
        ) if not platform_filter or platform_filter == "reddit" else []
        
        # The current round's actions; recent_actions shows only the newest round
        current_round = run_state.current_round
        recent_actions = SimulationRunner.get_all_actions(
            simulation_id=simulation_id,
            platform=platform_filter,
            round_num=current_round
        ) if current_round > 0 else []
        
        # The base status fields
        result = run_state.to_dict()
        result["all_actions"] = [a.to_dict() for a in all_actions]
        result["twitter_actions"] = [a.to_dict() for a in twitter_actions]
        result["reddit_actions"] = [a.to_dict() for a in reddit_actions]
        result["rounds_count"] = len(run_state.rounds)
        # recent_actions carries only the newest round, across both platforms
        result["recent_actions"] = [a.to_dict() for a in recent_actions]
        
        return jsonify({
            "success": True,
            "data": result
        })
        
    except Exception as e:
        logger.error(f"Failed to read the detailed run status: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/actions', methods=['GET'])
def get_simulation_actions(simulation_id: str):
    """
    Return the agent action history of a simulation.
    
    Query parameters:
        limit: Number of actions to return (defaults to 100)
        offset: Offset into the list (defaults to 0)
        platform: Filter by platform (twitter/reddit)
        agent_id: Filter by agent ID
        round_num: Filter by round
    
    Returns:
        {
            "success": true,
            "data": {
                "count": 100,
                "actions": [...]
            }
        }
    """
    try:
        limit = request.args.get('limit', 100, type=int)
        offset = request.args.get('offset', 0, type=int)
        platform = request.args.get('platform')
        agent_id = request.args.get('agent_id', type=int)
        round_num = request.args.get('round_num', type=int)
        
        actions = SimulationRunner.get_actions(
            simulation_id=simulation_id,
            limit=limit,
            offset=offset,
            platform=platform,
            agent_id=agent_id,
            round_num=round_num
        )
        
        return jsonify({
            "success": True,
            "data": {
                "count": len(actions),
                "actions": [a.to_dict() for a in actions]
            }
        })
        
    except Exception as e:
        logger.error(f"Failed to read the action history: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/timeline', methods=['GET'])
def get_simulation_timeline(simulation_id: str):
    """
    Return the simulation timeline, summarised per round.
    
    Backs the progress bar and the timeline view in the frontend.
    
    Query parameters:
        start_round: First round (defaults to 0)
        end_round: Last round (defaults to every round)
    
    Returns one summary per round.
    """
    try:
        start_round = request.args.get('start_round', 0, type=int)
        end_round = request.args.get('end_round', type=int)
        
        timeline = SimulationRunner.get_timeline(
            simulation_id=simulation_id,
            start_round=start_round,
            end_round=end_round
        )
        
        return jsonify({
            "success": True,
            "data": {
                "rounds_count": len(timeline),
                "timeline": timeline
            }
        })
        
    except Exception as e:
        logger.error(f"Failed to read the timeline: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/agent-stats', methods=['GET'])
def get_agent_stats(simulation_id: str):
    """
    Return per-agent statistics.
    
    Backs the agent activity ranking and the action distribution in the frontend.
    """
    try:
        stats = SimulationRunner.get_agent_stats(simulation_id)
        
        return jsonify({
            "success": True,
            "data": {
                "agents_count": len(stats),
                "stats": stats
            }
        })
        
    except Exception as e:
        logger.error(f"Failed to read the agent statistics: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== Database queries ==============

@simulation_bp.route('/<simulation_id>/posts', methods=['GET'])
def get_simulation_posts(simulation_id: str):
    """
    Return the posts made during a simulation.
    
    Query parameters:
        platform: Platform (twitter/reddit)
        limit: Number of posts to return (defaults to 50)
        offset: Offset into the list
    
    Reads the posts out of the platform's SQLite database.
    """
    try:
        platform = request.args.get('platform') or _get_default_platform(simulation_id)
        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)

        sim_dir = os.path.join(
            os.path.dirname(__file__),
            f'../../uploads/simulations/{simulation_id}'
        )

        db_file = f"{platform}_simulation.db"
        db_path = os.path.join(sim_dir, db_file)
        
        if not os.path.exists(db_path):
            return jsonify({
                "success": True,
                "data": {
                    "platform": platform,
                    "count": 0,
                    "posts": [],
                    "message": t('api.dbNotExist')
                }
            })
        
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT * FROM post 
                ORDER BY created_at DESC 
                LIMIT ? OFFSET ?
            """, (limit, offset))
            
            posts = [dict(row) for row in cursor.fetchall()]
            
            cursor.execute("SELECT COUNT(*) FROM post")
            total = cursor.fetchone()[0]
            
        except sqlite3.OperationalError:
            posts = []
            total = 0
        
        conn.close()
        
        return jsonify({
            "success": True,
            "data": {
                "platform": platform,
                "total": total,
                "count": len(posts),
                "posts": posts
            }
        })
        
    except Exception as e:
        logger.error(f"Failed to read the posts: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/comments', methods=['GET'])
def get_simulation_comments(simulation_id: str):
    """
    Return the comments made during a simulation.

    Query parameters:
        platform: Platform (twitter/reddit, defaults to the simulation's own)
        post_id: Filter by post ID (optional)
        limit: Number of comments to return
        offset: Offset into the list
    """
    try:
        platform = request.args.get('platform') or _get_default_platform(simulation_id)
        post_id = request.args.get('post_id')
        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)

        sim_dir = os.path.join(
            os.path.dirname(__file__),
            f'../../uploads/simulations/{simulation_id}'
        )
        
        db_path = os.path.join(sim_dir, f"{platform}_simulation.db")
        
        if not os.path.exists(db_path):
            return jsonify({
                "success": True,
                "data": {
                    "count": 0,
                    "comments": []
                }
            })
        
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        try:
            if post_id:
                cursor.execute("""
                    SELECT * FROM comment 
                    WHERE post_id = ?
                    ORDER BY created_at DESC 
                    LIMIT ? OFFSET ?
                """, (post_id, limit, offset))
            else:
                cursor.execute("""
                    SELECT * FROM comment 
                    ORDER BY created_at DESC 
                    LIMIT ? OFFSET ?
                """, (limit, offset))
            
            comments = [dict(row) for row in cursor.fetchall()]
            
        except sqlite3.OperationalError:
            comments = []
        
        conn.close()
        
        return jsonify({
            "success": True,
            "data": {
                "count": len(comments),
                "comments": comments
            }
        })
        
    except Exception as e:
        logger.error(f"Failed to read the comments: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== Interviews ==============

@simulation_bp.route('/interview', methods=['POST'])
def interview_agent():
    """
    Interview one agent.

    The simulation environment must be running: an agent answers only once the run has entered command-wait mode.

    Request (JSON):
        {
            "simulation_id": "sim_xxxx",       // required
            "agent_id": 0,                     // required
            "prompt": "What do you make of this?",  // required, the interview question
            "platform": "twitter",             // optional, the platform to ask on
                                               // omitted: a dual-platform simulation is asked on both
            "timeout": 60                      // optional, seconds, defaults to 60
        }

    Returns, with no platform given, in dual-platform mode:
        {
            "success": true,
            "data": {
                "agent_id": 0,
                "prompt": "What do you make of this?",
                "result": {
                    "agent_id": 0,
                    "prompt": "...",
                    "platforms": {
                        "twitter": {"agent_id": 0, "response": "...", "platform": "twitter"},
                        "reddit": {"agent_id": 0, "response": "...", "platform": "reddit"}
                    }
                },
                "timestamp": "2025-12-08T10:00:01"
            }
        }

    Returns, with a platform given:
        {
            "success": true,
            "data": {
                "agent_id": 0,
                "prompt": "What do you make of this?",
                "result": {
                    "agent_id": 0,
                    "response": "I think...",
                    "platform": "twitter",
                    "timestamp": "2025-12-08T10:00:00"
                },
                "timestamp": "2025-12-08T10:00:01"
            }
        }
    """
    try:
        data = request.get_json() or {}
        
        simulation_id = data.get('simulation_id')
        agent_id = data.get('agent_id')
        prompt = data.get('prompt')
        platform = data.get('platform')  # Optional: twitter/reddit/None
        timeout = data.get('timeout', 60)
        
        if not simulation_id:
            return jsonify({
                "success": False,
                "error": t('api.requireSimulationId')
            }), 400
        
        if agent_id is None:
            return jsonify({
                "success": False,
                "error": t('api.requireAgentId')
            }), 400
        
        if not prompt:
            return jsonify({
                "success": False,
                "error": t('api.requirePrompt')
            }), 400
        
        # Validate the platform
        if platform and platform not in ("twitter", "reddit"):
            return jsonify({
                "success": False,
                "error": t('api.invalidInterviewPlatform')
            }), 400
        
        # The environment has to be alive
        if not SimulationRunner.check_env_alive(simulation_id):
            return jsonify({
                "success": False,
                "error": t('api.envNotRunning')
            }), 400
        
        # Prefix the prompt so the agent answers in text instead of calling tools
        optimized_prompt = optimize_interview_prompt(prompt)
        
        result = SimulationRunner.interview_agent(
            simulation_id=simulation_id,
            agent_id=agent_id,
            prompt=optimized_prompt,
            platform=platform,
            timeout=timeout
        )

        return jsonify({
            "success": result.get("success", False),
            "data": result
        })
        
    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400
        
    except TimeoutError as e:
        return jsonify({
            "success": False,
            "error": t('api.interviewTimeout', error=str(e))
        }), 504
        
    except Exception as e:
        logger.error(f"Failed to interview the agent: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/interview/batch', methods=['POST'])
def interview_agents_batch():
    """
    Interview several agents in one request.

    The simulation environment must be running.

    Request (JSON):
        {
            "simulation_id": "sim_xxxx",       // required
            "interviews": [                    // required, the interviews to run
                {
                    "agent_id": 0,
                    "prompt": "What do you make of A?",
                    "platform": "twitter"      // optional, the platform for this agent
                },
                {
                    "agent_id": 1,
                    "prompt": "What do you make of B?"  // no platform: the default is used
                }
            ],
            "platform": "reddit",              // optional, default platform, overridden per item
                                               // omitted: a dual-platform simulation is asked on both
            "timeout": 120                     // optional, seconds, defaults to 120
        }

    Returns:
        {
            "success": true,
            "data": {
                "interviews_count": 2,
                "result": {
                    "interviews_count": 4,
                    "results": {
                        "twitter_0": {"agent_id": 0, "response": "...", "platform": "twitter"},
                        "reddit_0": {"agent_id": 0, "response": "...", "platform": "reddit"},
                        "twitter_1": {"agent_id": 1, "response": "...", "platform": "twitter"},
                        "reddit_1": {"agent_id": 1, "response": "...", "platform": "reddit"}
                    }
                },
                "timestamp": "2025-12-08T10:00:01"
            }
        }
    """
    try:
        data = request.get_json() or {}

        simulation_id = data.get('simulation_id')
        interviews = data.get('interviews')
        platform = data.get('platform')  # Optional: twitter/reddit/None
        timeout = data.get('timeout', 120)

        if not simulation_id:
            return jsonify({
                "success": False,
                "error": t('api.requireSimulationId')
            }), 400

        if not interviews or not isinstance(interviews, list):
            return jsonify({
                "success": False,
                "error": t('api.requireInterviews')
            }), 400

        # Validate the platform
        if platform and platform not in ("twitter", "reddit"):
            return jsonify({
                "success": False,
                "error": t('api.invalidInterviewPlatform')
            }), 400

        # Validate every interview item
        for i, interview in enumerate(interviews):
            if 'agent_id' not in interview:
                return jsonify({
                    "success": False,
                    "error": t('api.interviewListMissingAgentId', index=i+1)
                }), 400
            if 'prompt' not in interview:
                return jsonify({
                    "success": False,
                    "error": t('api.interviewListMissingPrompt', index=i+1)
                }), 400
            # Validate this item's platform, when it has one
            item_platform = interview.get('platform')
            if item_platform and item_platform not in ("twitter", "reddit"):
                return jsonify({
                    "success": False,
                    "error": t('api.interviewListInvalidPlatform', index=i+1)
                }), 400

        # The environment has to be alive
        if not SimulationRunner.check_env_alive(simulation_id):
            return jsonify({
                "success": False,
                "error": t('api.envNotRunning')
            }), 400

        # Prefix each prompt so the agent answers in text instead of calling tools
        optimized_interviews = []
        for interview in interviews:
            optimized_interview = interview.copy()
            optimized_interview['prompt'] = optimize_interview_prompt(interview.get('prompt', ''))
            optimized_interviews.append(optimized_interview)

        result = SimulationRunner.interview_agents_batch(
            simulation_id=simulation_id,
            interviews=optimized_interviews,
            platform=platform,
            timeout=timeout
        )

        return jsonify({
            "success": result.get("success", False),
            "data": result
        })

    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400

    except TimeoutError as e:
        return jsonify({
            "success": False,
            "error": t('api.batchInterviewTimeout', error=str(e))
        }), 504

    except Exception as e:
        logger.error(f"Failed to run the batch interview: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/interview/all', methods=['POST'])
def interview_all_agents():
    """
    Interview every agent with the same question.

    The simulation environment must be running.

    Request (JSON):
        {
            "simulation_id": "sim_xxxx",            // required
            "prompt": "What do you make of all this?",  // required, asked of every agent
            "platform": "reddit",                   // optional, the platform to ask on
                                                    // omitted: a dual-platform simulation is asked on both
            "timeout": 180                          // optional, seconds, defaults to 180
        }

    Returns:
        {
            "success": true,
            "data": {
                "interviews_count": 50,
                "result": {
                    "interviews_count": 100,
                    "results": {
                        "twitter_0": {"agent_id": 0, "response": "...", "platform": "twitter"},
                        "reddit_0": {"agent_id": 0, "response": "...", "platform": "reddit"},
                        ...
                    }
                },
                "timestamp": "2025-12-08T10:00:01"
            }
        }
    """
    try:
        data = request.get_json() or {}

        simulation_id = data.get('simulation_id')
        prompt = data.get('prompt')
        platform = data.get('platform')  # Optional: twitter/reddit/None
        timeout = data.get('timeout', 180)

        if not simulation_id:
            return jsonify({
                "success": False,
                "error": t('api.requireSimulationId')
            }), 400

        if not prompt:
            return jsonify({
                "success": False,
                "error": t('api.requirePrompt')
            }), 400

        # Validate the platform
        if platform and platform not in ("twitter", "reddit"):
            return jsonify({
                "success": False,
                "error": t('api.invalidInterviewPlatform')
            }), 400

        # The environment has to be alive
        if not SimulationRunner.check_env_alive(simulation_id):
            return jsonify({
                "success": False,
                "error": t('api.envNotRunning')
            }), 400

        # Prefix the prompt so the agent answers in text instead of calling tools
        optimized_prompt = optimize_interview_prompt(prompt)

        result = SimulationRunner.interview_all_agents(
            simulation_id=simulation_id,
            prompt=optimized_prompt,
            platform=platform,
            timeout=timeout
        )

        return jsonify({
            "success": result.get("success", False),
            "data": result
        })

    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400

    except TimeoutError as e:
        return jsonify({
            "success": False,
            "error": t('api.globalInterviewTimeout', error=str(e))
        }), 504

    except Exception as e:
        logger.error(f"Failed to run the global interview: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/interview/history', methods=['POST'])
def get_interview_history():
    """
    Return the interview history.

    Reads every interview recorded in the simulation databases.

    Request (JSON):
        {
            "simulation_id": "sim_xxxx",  // required
            "platform": "reddit",          // optional, platform (reddit/twitter)
                                           // omitted: both platforms are returned
            "agent_id": 0,                 // optional, only this agent
            "limit": 100                   // optional, defaults to 100
        }

    Returns:
        {
            "success": true,
            "data": {
                "count": 10,
                "history": [
                    {
                        "agent_id": 0,
                        "response": "I think...",
                        "prompt": "What do you make of this?",
                        "timestamp": "2025-12-08T10:00:00",
                        "platform": "reddit"
                    },
                    ...
                ]
            }
        }
    """
    try:
        data = request.get_json() or {}
        
        simulation_id = data.get('simulation_id')
        platform = data.get('platform')  # Omitted: both platforms are returned
        agent_id = data.get('agent_id')
        limit = data.get('limit', 100)
        
        if not simulation_id:
            return jsonify({
                "success": False,
                "error": t('api.requireSimulationId')
            }), 400

        history = SimulationRunner.get_interview_history(
            simulation_id=simulation_id,
            platform=platform,
            agent_id=agent_id,
            limit=limit
        )

        return jsonify({
            "success": True,
            "data": {
                "count": len(history),
                "history": history
            }
        })

    except Exception as e:
        logger.error(f"Failed to read the interview history: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/env-status', methods=['POST'])
def get_env_status():
    """
    Return the state of the simulation environment.

    Reports whether the environment is alive and can accept interview commands.

    Request (JSON):
        {
            "simulation_id": "sim_xxxx"  // required
        }

    Returns:
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "env_alive": true,
                "twitter_available": true,
                "reddit_available": true,
                "message": "Environment is running and ready for Interview commands"
            }
        }
    """
    try:
        data = request.get_json() or {}
        
        simulation_id = data.get('simulation_id')
        
        if not simulation_id:
            return jsonify({
                "success": False,
                "error": t('api.requireSimulationId')
            }), 400

        env_alive = SimulationRunner.check_env_alive(simulation_id)
        
        # The per-platform detail
        env_status = SimulationRunner.get_env_status_detail(simulation_id)

        if env_alive:
            message = t('api.envRunning')
        else:
            message = t('api.envNotRunningShort')

        return jsonify({
            "success": True,
            "data": {
                "simulation_id": simulation_id,
                "env_alive": env_alive,
                "twitter_available": env_status.get("twitter_available", False),
                "reddit_available": env_status.get("reddit_available", False),
                "message": message
            }
        })

    except Exception as e:
        logger.error(f"Failed to read the environment status: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/close-env', methods=['POST'])
def close_simulation_env():
    """
    Close the simulation environment.
    
    Tells the simulation to leave command-wait mode and shut down gracefully.
    
    This is not /stop: /stop kills the process, while this endpoint lets the
    simulation close its environment and exit on its own.
    
    Request (JSON):
        {
            "simulation_id": "sim_xxxx",  // required
            "timeout": 30                  // optional, seconds, defaults to 30
        }
    
    Returns:
        {
            "success": true,
            "data": {
                "message": "Environment close command sent",
                "result": {...},
                "timestamp": "2025-12-08T10:00:01"
            }
        }
    """
    try:
        data = request.get_json() or {}
        
        simulation_id = data.get('simulation_id')
        timeout = data.get('timeout', 30)
        
        if not simulation_id:
            return jsonify({
                "success": False,
                "error": t('api.requireSimulationId')
            }), 400
        
        result = SimulationRunner.close_simulation_env(
            simulation_id=simulation_id,
            timeout=timeout
        )
        
        # Update the simulation state
        manager = SimulationManager()
        state = manager.get_simulation(simulation_id)
        if state:
            state.status = SimulationStatus.COMPLETED
            manager._save_simulation_state(state)
        
        return jsonify({
            "success": result.get("success", False),
            "data": result
        })
        
    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400
        
    except Exception as e:
        logger.error(f"Failed to close the environment: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500
