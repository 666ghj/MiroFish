"""
Graph API routes
State lives on the server, keyed by project context.
"""

import os
import re
import traceback
import threading
from contextlib import ExitStack, nullcontext
from flask import request, jsonify
from zep_cloud import NotFoundError

from . import graph_bp
from ..config import Config
from ..services.ontology_generator import OntologyGenerator
from ..services.graph_builder import BatchSubmission, GraphBuilderService
from ..services.graph_preflight import run_graph_preflight
from ..services.text_processor import TextProcessor
from ..utils.file_parser import FileParser
from ..utils.logger import get_logger
from ..utils.locale import t
from ..utils.zep_lifecycle import get_graph_readers, graph_lifecycle_lock
from ..models.task import TaskManager, TaskStatus
from ..models.project import ProjectManager, ProjectStatus
from ..services.simulation_manager import SimulationManager
from ..services.simulation_runner import SimulationRunner, RunnerStatus
from ..services.zep_graph_memory_updater import ZepGraphMemoryManager
from ..utils.llm_client import LLMResponseError

# Application logger
logger = get_logger('sosim.api')
_build_locks: dict[str, threading.Lock] = {}
_build_locks_guard = threading.Lock()


class GraphInUseError(RuntimeError):
    pass


def _active_graph_consumers(graph_id: str) -> list[str]:
    active = {
        f"report:{reader_id}"
        for reader_id in get_graph_readers(graph_id)
    }
    for simulation_id in ZepGraphMemoryManager.get_simulation_ids_for_graph(graph_id):
        finalization_lock = SimulationRunner._finalization_lock(simulation_id)
        if not finalization_lock.acquire(blocking=False):
            active.add(simulation_id)
            continue
        try:
            run_state = SimulationRunner.get_run_state(simulation_id)
            if run_state and run_state.runner_status == RunnerStatus.FAILED:
                # reset/delete is the explicit recovery path for an incomplete,
                # non-replayable write. Serialize it against a retry drain.
                ZepGraphMemoryManager.discard_inactive_updater(simulation_id)
                SimulationRunner._graph_memory_enabled.pop(simulation_id, None)
                continue
            active.add(simulation_id)
        finally:
            finalization_lock.release()
    active_runner_statuses = {
        RunnerStatus.STARTING,
        RunnerStatus.RUNNING,
        RunnerStatus.PAUSED,
        RunnerStatus.STOPPING,
    }
    for simulation in SimulationManager().list_simulations():
        if simulation.graph_id != graph_id:
            continue
        run_state = SimulationRunner.get_run_state(simulation.simulation_id)
        if run_state and run_state.runner_status in active_runner_statuses:
            active.add(simulation.simulation_id)
    return sorted(active)


def _delete_cloud_graph_if_present(graph_id: str | None) -> None:
    """Delete a referenced Cloud graph without retrying the mutation."""

    if not graph_id:
        return
    # Keep the consumer check and Cloud mutation in one critical section. The
    # callers that also clear local references hold this re-entrant lock around
    # both operations.
    with graph_lifecycle_lock(graph_id):
        active_simulations = _active_graph_consumers(graph_id)
        if active_simulations:
            raise GraphInUseError(
                f"Graph {graph_id} is in use by active consumer(s): "
                f"{', '.join(active_simulations)}"
            )
        try:
            GraphBuilderService(api_key=Config.ZEP_API_KEY).delete_graph(graph_id)
        except NotFoundError:
            logger.info("Zep Cloud graph already absent: %s", graph_id)


def _clear_project_batch_reference(project) -> None:
    """Drop the pointers to a Zep batch this project can no longer resume."""

    project.zep_batch_id = None
    project.zep_batch_operation_id = None
    project.zep_retry_batches = []


def _clear_project_graph_reference(project) -> None:
    project.graph_id = None
    project.graph_build_task_id = None
    _clear_project_batch_reference(project)
    project.error = None


def _orphan_project_graph_reference(project) -> None:
    """Hand the project's graph over to the orphan list before it is replaced.

    A non-forced retry deliberately leaves the Cloud graph alone - the episodes
    that landed are worth more than a clean slate - but the new build calls
    remember_graph and overwrites project.graph_id the moment it creates one.
    Nothing else recorded the old value, so the abandoned graph stayed in Zep
    with no local reference at all: reset could not reach it and
    DELETE /graph/delete answered "No local project references this graph".
    """

    graph_id = project.graph_id
    if not graph_id:
        return
    if graph_id not in project.orphaned_graph_ids:
        project.orphaned_graph_ids.append(graph_id)
    project.graph_id = None
    logger.warning(
        "Project %s abandoned graph %s on a rebuild that did not delete it; "
        "it is recorded as orphaned and can be removed with "
        "DELETE /api/graph/delete/%s",
        project.project_id,
        graph_id,
        graph_id,
    )


def _delete_orphaned_graphs(project) -> None:
    """Delete the graphs earlier attempts abandoned, keeping what will not go.

    Called from the paths that wipe a project's graph state. An orphan that
    cannot be deleted right now stays on the record rather than being dropped
    silently, so it is still reachable by hand afterwards.
    """

    remaining: list[str] = []
    for graph_id in project.orphaned_graph_ids:
        try:
            _delete_cloud_graph_if_present(graph_id)
        except Exception as error:
            logger.warning(
                "Could not delete orphaned graph %s for project %s: %s",
                graph_id,
                project.project_id,
                error,
            )
            remaining.append(graph_id)
    project.orphaned_graph_ids = remaining


def _project_build_lock(project_id: str) -> threading.Lock:
    with _build_locks_guard:
        return _build_locks.setdefault(project_id, threading.Lock())


def _can_resume_persisted_batch(project) -> bool:
    """Report whether the project's persisted Zep batch can still be resumed."""

    if not (
        project.graph_id
        and project.zep_batch_id
        and project.zep_batch_operation_id
    ):
        return False
    try:
        builder = GraphBuilderService(api_key=Config.ZEP_API_KEY)
        batch_summary = builder.get_batch_summary(project.zep_batch_id)
    except Exception:
        # A batch that can no longer be read is simply not resumable; the
        # caller falls back to a fresh build rather than failing the request.
        logger.warning(
            f"Could not read Zep batch {project.zep_batch_id} for project "
            f"{project.project_id}",
            exc_info=True,
        )
        return False
    return getattr(batch_summary, "status", None) in {
        "queued",
        "processing",
        "succeeded",
        # "partial" belongs here: the batch committed most of its episodes and
        # GraphBuilderService resubmits the items that failed, so resuming is
        # what recovers the ingest instead of re-running the whole build. The
        # resubmissions are journaled on the project, so a resume replays the
        # retry batches it already created rather than ingesting those chunks
        # a second time.
        "partial",
    }


def _project_has_active_build(project) -> bool:
    if project.status != ProjectStatus.GRAPH_BUILDING:
        return False
    if not project.graph_build_task_id:
        return False
    task = TaskManager().get_task(project.graph_build_task_id)
    return bool(
        task
        and task.status in {TaskStatus.PENDING, TaskStatus.PROCESSING}
    )


def allowed_file(filename: str) -> bool:
    """Report whether a file extension is allowed."""
    if not filename or '.' not in filename:
        return False
    ext = os.path.splitext(filename)[1].lower().lstrip('.')
    return ext in Config.ALLOWED_EXTENSIONS


# ============== Project management ==============

@graph_bp.route('/project/<project_id>', methods=['GET'])
def get_project(project_id: str):
    """
    Return one project.
    """
    project = ProjectManager.get_project(project_id)
    
    if not project:
        return jsonify({
            "success": False,
            "error": t('api.projectNotFound', id=project_id)
        }), 404

    return jsonify({
        "success": True,
        "data": project.to_dict()
    })


@graph_bp.route('/project/list', methods=['GET'])
def list_projects():
    """
    List every project.
    """
    limit = request.args.get('limit', 50, type=int)
    projects = ProjectManager.list_projects(limit=limit)
    
    return jsonify({
        "success": True,
        "data": [p.to_dict() for p in projects],
        "count": len(projects)
    })


@graph_bp.route('/project/<project_id>', methods=['DELETE'])
def delete_project(project_id: str):
    with _project_build_lock(project_id):
        return _delete_project_impl(project_id)


def _delete_project_impl(project_id: str):
    """
    Delete a project.
    """
    project = ProjectManager.get_project(project_id)
    if not project:
        return jsonify({
            "success": False,
            "error": t('api.projectNotFound', id=project_id)
        }), 404
    if _project_has_active_build(project):
        return jsonify({
            "success": False,
            "error": t('api.graphBuilding')
        }), 409

    graph_id = project.graph_id
    graph_guard = (
        graph_lifecycle_lock(graph_id) if graph_id else nullcontext()
    )
    with graph_guard:
        try:
            _delete_cloud_graph_if_present(graph_id)
        except GraphInUseError as error:
            return jsonify({"success": False, "error": str(error)}), 409
        # Deleting the project takes the orphan record with it, so this is the
        # last moment anything knows those graphs exist.
        _delete_orphaned_graphs(project)
        if project.orphaned_graph_ids:
            logger.error(
                "Project %s is being deleted while orphaned graph(s) %s could "
                "not be removed; they are now unreferenced in Zep",
                project_id,
                project.orphaned_graph_ids,
            )
        # The local reference remains protected until it is removed, so a new
        # simulation cannot claim the just-deleted graph in between.
        success = ProjectManager.delete_project(project_id)
    
    if not success:
        return jsonify({
            "success": False,
            "error": t('api.projectDeleteFailed', id=project_id)
        }), 404

    return jsonify({
        "success": True,
        "message": t('api.projectDeleted', id=project_id)
    })


@graph_bp.route('/project/<project_id>/reset', methods=['POST'])
def reset_project(project_id: str):
    with _project_build_lock(project_id):
        return _reset_project_impl(project_id)


def _reset_project_impl(project_id: str):
    """
    Reset a project so its graph can be built again.
    """
    project = ProjectManager.get_project(project_id)
    
    if not project:
        return jsonify({
            "success": False,
            "error": t('api.projectNotFound', id=project_id)
        }), 404

    if _project_has_active_build(project):
        return jsonify({
            "success": False,
            "error": t('api.graphBuilding')
        }), 409

    graph_id = project.graph_id
    graph_guard = (
        graph_lifecycle_lock(graph_id) if graph_id else nullcontext()
    )
    with graph_guard:
        try:
            _delete_cloud_graph_if_present(graph_id)
        except GraphInUseError as error:
            return jsonify({"success": False, "error": str(error)}), 409

        # Reset means "start over", so the graphs earlier attempts walked away
        # from go too; whatever refuses to go stays on the record.
        _delete_orphaned_graphs(project)

        # Reset to the state the project had once its ontology existed.
        if project.ontology:
            project.status = ProjectStatus.ONTOLOGY_GENERATED
        else:
            project.status = ProjectStatus.CREATED

        _clear_project_graph_reference(project)
        ProjectManager.save_project(project)
    
    return jsonify({
        "success": True,
        "message": t('api.projectReset', id=project_id),
        "data": project.to_dict()
    })


# ============== Endpoint 1: upload files and generate an ontology ==============

@graph_bp.route('/ontology/generate', methods=['POST'])
def generate_ontology():
    """
    Endpoint 1: upload documents and generate an ontology definition.
    
    Request: multipart/form-data
    
    Parameters:
        files: Uploaded documents (PDF/MD/TXT), one or more
        simulation_requirement: What the simulation should answer (required)
        project_name: Project name (optional)
        additional_context: Extra guidance for the model (optional)
        
    Returns:
        {
            "success": true,
            "data": {
                "project_id": "proj_xxxx",
                "ontology": {
                    "entity_types": [...],
                    "edge_types": [...],
                    "analysis_summary": "..."
                },
                "files": [...],
                "total_text_length": 12345
            }
        }
    """
    project = None
    try:
        logger.info("Generating an ontology definition")
        
        # Read the request parameters
        simulation_requirement = request.form.get('simulation_requirement', '')
        project_name = request.form.get('project_name', 'Unnamed Project')
        additional_context = request.form.get('additional_context', '')
        
        logger.debug(f"Project name: {project_name}")
        logger.debug(f"Simulation requirement: {simulation_requirement[:100]}...")
        
        if not simulation_requirement:
            return jsonify({
                "success": False,
                "error": t('api.requireSimulationRequirement')
            }), 400
        
        # Read the uploaded files
        uploaded_files = request.files.getlist('files')
        if not uploaded_files or all(not f.filename for f in uploaded_files):
            return jsonify({
                "success": False,
                "error": t('api.requireFileUpload')
            }), 400
        
        # Create the project
        project = ProjectManager.create_project(name=project_name)
        project.simulation_requirement = simulation_requirement
        logger.info(f"Created project {project.project_id}")
        
        # Save each file and extract its text
        document_texts = []
        all_text = ""
        
        for file in uploaded_files:
            if file and file.filename and allowed_file(file.filename):
                # Save the file into the project directory
                file_info = ProjectManager.save_file_to_project(
                    project.project_id, 
                    file, 
                    file.filename
                )
                project.files.append({
                    "filename": file_info["original_filename"],
                    "size": file_info["size"]
                })
                
                # Extract the text
                text = FileParser.extract_text(file_info["path"])
                text = TextProcessor.preprocess_text(text)
                document_texts.append(text)
                all_text += f"\n\n=== {file_info['original_filename']} ===\n{text}"
        
        if not document_texts:
            ProjectManager.delete_project(project.project_id)
            return jsonify({
                "success": False,
                "error": t('api.noDocProcessed')
            }), 400
        
        # Save the extracted text
        project.total_text_length = len(all_text)
        ProjectManager.save_extracted_text(project.project_id, all_text)
        logger.info(f"Extracted {len(all_text)} characters of text")
        
        # Generate the ontology
        logger.info("Asking the LLM for an ontology definition")
        generator = OntologyGenerator()
        ontology = generator.generate(
            document_texts=document_texts,
            simulation_requirement=simulation_requirement,
            additional_context=additional_context if additional_context else None
        )
        
        # Save the ontology onto the project
        entity_count = len(ontology.get("entity_types", []))
        edge_count = len(ontology.get("edge_types", []))
        logger.info(f"Generated an ontology with {entity_count} entity types and {edge_count} edge types")
        
        project.ontology = {
            "entity_types": ontology.get("entity_types", []),
            "edge_types": ontology.get("edge_types", [])
        }
        project.analysis_summary = ontology.get("analysis_summary", "")
        project.status = ProjectStatus.ONTOLOGY_GENERATED
        ProjectManager.save_project(project)
        logger.info(f"Generated the ontology for project {project.project_id}")
        
        return jsonify({
            "success": True,
            "data": {
                "project_id": project.project_id,
                "project_name": project.name,
                "ontology": project.ontology,
                "analysis_summary": project.analysis_summary,
                "files": project.files,
                "total_text_length": project.total_text_length
            }
        })
        
    except Exception as error:
        provider_status = getattr(error, "status_code", None)
        request_id = getattr(error, "request_id", None)

        if isinstance(error, LLMResponseError):
            public_error = str(error)
            response_status = 502
            logger.exception("LLM returned an unusable ontology response")
        elif isinstance(provider_status, int):
            public_error = f"LLM provider request failed (HTTP {provider_status})"
            if request_id:
                safe_request_id = re.sub(
                    r"[^a-zA-Z0-9._:-]", "", str(request_id)
                )[:128]
                if safe_request_id:
                    public_error += f" (request_id: {safe_request_id})"
            response_status = 502
            # Provider exception bodies may echo request content. Keep the
            # server log useful without serializing the exception body.
            logger.error(
                "Ontology provider request failed: type=%s status=%s request_id=%s",
                type(error).__name__,
                provider_status,
                request_id or "unknown",
            )
        else:
            public_error = "Ontology generation failed; check the server logs"
            response_status = 500
            logger.exception("Unexpected ontology generation failure")

        response_data = None
        if project is not None:
            project.status = ProjectStatus.FAILED
            project.error = public_error
            try:
                ProjectManager.save_project(project)
            except Exception:
                logger.exception(
                    "Failed to persist ontology failure for project %s",
                    project.project_id,
                )
            response_data = {"project_id": project.project_id}

        payload = {
            "success": False,
            "error": public_error,
        }
        if response_data is not None:
            payload["data"] = response_data
        return jsonify(payload), response_status


# ============== Endpoint 2: build the graph ==============

@graph_bp.route('/build', methods=['POST'])
def build_graph():
    """Serialize build claims for the same project within this process."""

    data = request.get_json(silent=True) or {}
    project_id = data.get("project_id")
    if not project_id:
        return _build_graph_impl()

    # The preflight is a read-only probe of another service, and it spends its
    # whole budget precisely when that service is the thing that is broken -
    # which is when an operator reaches for /project/<id>/reset or DELETE, and
    # both claim this same per-project lock. Run it before the lock is claimed
    # so those recovery routes stay reachable while it runs; the impl still
    # validates the request and decides what the verdict means.
    preflight = None
    if _preflight_is_worth_running(data, project_id):
        project = ProjectManager.get_project(project_id)
        text = ProjectManager.get_extracted_text(project_id) if project else None
        if project and project.ontology and text:
            preflight = run_graph_preflight(project.ontology, text)

    with _project_build_lock(project_id):
        return _build_graph_impl(preflight=preflight)


def _preflight_is_worth_running(data, project_id) -> bool:
    """Decide whether to spend the preflight budget on this request.

    The probe costs up to GRAPH_BUILD_PREFLIGHT_TIMEOUT seconds, and hoisting
    it above the lock also hoisted it above every short-circuit in
    _build_graph_impl - so a malformed request, or one that only gets a
    "reused" reply, would pay the full probe before being answered. These are
    deliberately cheap, duplicated guards whose only job is to avoid paying
    for a build that is not going to start; _build_graph_impl stays
    authoritative for what the request actually means, and a guard that drifts
    can only cost a skipped probe, never a wrong answer.
    """
    if data.get('skip_preflight', False) is not False:
        return False

    # A malformed request is about to be rejected with a 400.
    for key in ('chunk_size', 'chunk_overlap'):
        if key in data and not isinstance(data[key], int):
            return False

    project = ProjectManager.get_project(project_id)
    if project is None:
        return False

    force = bool(data.get('force', False))

    # Already building, and the task is alive: the reply is "reused".
    if project.status == ProjectStatus.GRAPH_BUILDING and _project_has_active_build(project):
        return False

    # Already built and not being forced: the reply is "reused".
    if project.status == ProjectStatus.GRAPH_COMPLETED and not force:
        return False

    return True


def _build_graph_impl(preflight=None):
    """
    Endpoint 2: build a knowledge graph for a project.
    
    Request (JSON):
        {
            "project_id": "proj_xxxx",  // required, from endpoint 1
            "graph_name": "Graph name", // optional
            "chunk_size": 500,          // optional, defaults to 500
            "chunk_overlap": 50         // optional, defaults to 50
        }
        
    Returns:
        {
            "success": true,
            "data": {
                "project_id": "proj_xxxx",
                "task_id": "task_xxxx",
                "message": "Graph build task started"
            }
        }
    """
    try:
        logger.info("Building a knowledge graph")
        
        # Check the configuration
        errors = []
        if not Config.ZEP_API_KEY:
            errors.append(t('api.zepApiKeyMissing'))
        if errors:
            logger.error(f"Invalid configuration: {errors}")
            return jsonify({
                "success": False,
                "error": t('api.configError', details="; ".join(errors))
            }), 500
        
        # Parse the request
        data = request.get_json() or {}
        project_id = data.get('project_id')
        logger.debug(f"Request parameters: project_id={project_id}")
        
        if not project_id:
            return jsonify({
                "success": False,
                "error": t('api.requireProjectId')
            }), 400
        
        # Load the project
        project = ProjectManager.get_project(project_id)
        if not project:
            return jsonify({
                "success": False,
                "error": t('api.projectNotFound', id=project_id)
            }), 404

        # Check the project status
        force = data.get('force', False)  # Rebuild even when a graph exists
        if not isinstance(force, bool):
            return jsonify({
                "success": False,
                "error": "force must be a JSON boolean"
            }), 400
        
        if project.status == ProjectStatus.CREATED:
            return jsonify({
                "success": False,
                "error": t('api.ontologyNotGenerated')
            }), 400
        
        resume_existing_batch = False
        if project.status == ProjectStatus.GRAPH_BUILDING:
            if _project_has_active_build(project):
                return jsonify({
                    "success": True,
                    "data": {
                        "project_id": project_id,
                        "task_id": project.graph_build_task_id,
                        "graph_id": project.graph_id,
                        "reused": True,
                        "message": t('api.graphBuilding')
                    }
                })

            if not force:
                resume_existing_batch = _can_resume_persisted_batch(project)

            if not resume_existing_batch:
                project.status = ProjectStatus.FAILED
                project.error = (
                    "Graph build task is no longer present; the persisted Zep "
                    "batch cannot be resumed automatically"
                )
                ProjectManager.save_project(project)
                if not force:
                    return jsonify({
                        "success": False,
                        "error": project.error,
                        "task_id": project.graph_build_task_id,
                        "recoverable": True,
                    }), 409

        if project.status == ProjectStatus.GRAPH_COMPLETED and not force:
            return jsonify({
                "success": True,
                "data": {
                    "project_id": project_id,
                    "task_id": project.graph_build_task_id,
                    "graph_id": project.graph_id,
                    "reused": True,
                    "message": t('progress.graphBuildComplete')
                }
            })
        
        # Read the build configuration
        graph_name = data.get('graph_name', project.name or 'SoSim Graph')
        chunk_size = data.get('chunk_size', project.chunk_size or Config.DEFAULT_CHUNK_SIZE)
        chunk_overlap = data.get('chunk_overlap', project.chunk_overlap or Config.DEFAULT_CHUNK_OVERLAP)
        if not isinstance(chunk_size, int) or chunk_size <= 0:
            return jsonify({"success": False, "error": "chunk_size must be a positive integer"}), 400
        if (
            not isinstance(chunk_overlap, int)
            or chunk_overlap < 0
            or chunk_overlap >= chunk_size
        ):
            return jsonify({
                "success": False,
                "error": "chunk_overlap must satisfy 0 <= chunk_overlap < chunk_size"
            }), 400
        
        # Update the project configuration
        project.chunk_size = chunk_size
        project.chunk_overlap = chunk_overlap
        
        # Read the extracted text
        text = ProjectManager.get_extracted_text(project_id)
        if not text:
            return jsonify({
                "success": False,
                "error": t('api.textNotFound')
            }), 400
        
        # Read the ontology
        ontology = project.ontology
        if not ontology:
            return jsonify({
                "success": False,
                "error": t('api.ontologyNotFound')
            }), 400

        # Prove the extraction endpoint can actually serve this ingest before
        # anything is created. Both production failures were a bad extraction
        # configuration that only surfaced tens of minutes in - once as an
        # APITimeoutError after ~50 minutes, once as a JSONDecodeError on a
        # completion the token budget cut in half - and neither was visible
        # from a request that had already been accepted. This runs before the
        # task exists so a bad configuration costs seconds.
        skip_preflight = data.get('skip_preflight', False)
        if not isinstance(skip_preflight, bool):
            return jsonify({
                "success": False,
                "error": "skip_preflight must be a JSON boolean"
            }), 400
        # A skipped preflight is not a passed one, and a server-side warning is
        # invisible to whoever started the build: say so in the response too.
        preflight_skipped = None
        if skip_preflight:
            preflight_skipped = "skip_preflight was requested"
            logger.warning(
                "Graph build preflight skipped by request for project %s",
                project_id,
            )
        else:
            # Normally already run by the route, outside the per-project build
            # lock; a direct call still gets its own.
            if preflight is None:
                preflight = run_graph_preflight(ontology, text)
            if preflight.skipped:
                preflight_skipped = preflight.detail
                logger.warning("Graph build preflight skipped: %s", preflight.detail)
            elif not preflight.ok:
                logger.error("Graph build preflight failed: %s", preflight.detail)
                return jsonify({
                    "success": False,
                    "error": (
                        f"Graph build preflight failed: {preflight.detail} "
                        "Fix the ingestion service configuration and retry, or "
                        "send skip_preflight=true to build anyway."
                    ),
                    "preflight": preflight.report,
                }), 502
            else:
                logger.info("Graph build preflight passed: %s", preflight.detail)

        # A failed build has usually still committed most of its episodes: each
        # batch item saves independently, so the run that died on one timed-out
        # episode left the other 61 in the graph. Resume that ingest instead of
        # starting over.
        if project.status == ProjectStatus.FAILED and not force:
            resume_existing_batch = _can_resume_persisted_batch(project)

        # Only mutate Cloud state after the complete rebuild request validates,
        # and only when the caller explicitly asked for it: pressing rebuild
        # after a failure used to delete the episodes that had landed and force
        # a full re-ingest. A graph a non-forced retry cannot resume is left in
        # place for reset/delete to remove deliberately.
        if force and project.status in {
            ProjectStatus.FAILED,
            ProjectStatus.GRAPH_COMPLETED,
        }:
            graph_id_to_delete = project.graph_id
            graph_guard = (
                graph_lifecycle_lock(graph_id_to_delete)
                if graph_id_to_delete
                else nullcontext()
            )
            with graph_guard:
                _delete_cloud_graph_if_present(graph_id_to_delete)
                project.status = ProjectStatus.ONTOLOGY_GENERATED
                _clear_project_graph_reference(project)
                ProjectManager.save_project(project)
        elif not resume_existing_batch:
            # This request builds a brand-new graph, so every reference the
            # previous attempt left behind is about to be overwritten.
            stale_reference = bool(
                project.graph_id
                or project.zep_batch_id
                or project.zep_batch_operation_id
                or project.zep_retry_batches
            )
            # Keeping the graph on a non-forced retry is deliberate - the
            # episodes that landed survive a rebuild request - but losing the
            # ID of it is not, so hand it to the orphan list before the new
            # build claims graph_id.
            _orphan_project_graph_reference(project)
            # The batch pointers are not kept either: they name the ingest this
            # run replaces. Left behind, they outlive the graph_id the new
            # build overwrites, and a later resume would attach this project to
            # a batch whose items describe a graph that is no longer the
            # project's own.
            _clear_project_batch_reference(project)
            if stale_reference:
                ProjectManager.save_project(project)

        # Create the background task
        task_manager = TaskManager()
        task_id = task_manager.create_task(f"Building graph: {graph_name}")
        logger.info(f"Created a graph build task: task_id={task_id}, project_id={project_id}")
        
        # Update the project status
        project.status = ProjectStatus.GRAPH_BUILDING
        project.graph_build_task_id = task_id
        ProjectManager.save_project(project)
        
        # Start the background task
        def build_task():
            build_logger = get_logger('sosim.build')
            try:
                build_logger.info(f"[{task_id}] Building the graph")
                task_manager.update_task(
                    task_id, 
                    status=TaskStatus.PROCESSING,
                    message=t('progress.initGraphService')
                )
                
                # Create the graph builder service
                builder = GraphBuilderService(api_key=Config.ZEP_API_KEY)
                
                # Chunk the text
                task_manager.update_task(
                    task_id,
                    message=t('progress.textChunking'),
                    progress=5
                )
                chunks = TextProcessor.split_text(
                    text, 
                    chunk_size=chunk_size, 
                    overlap=chunk_overlap
                )
                builder.validate_batch_chunks(chunks, batch_size=350)
                total_chunks = len(chunks)
                
                if resume_existing_batch:
                    graph_id = project.graph_id
                    operation_id = builder.build_operation_id(graph_id, chunks)
                    if operation_id != project.zep_batch_operation_id:
                        raise RuntimeError(
                            "Persisted Zep batch does not match the current graph input"
                        )
                    submission = BatchSubmission(
                        batch_id=project.zep_batch_id,
                        operation_id=operation_id,
                        episode_uuids=[],
                        item_count=total_chunks,
                    )
                    task_manager.update_task(
                        task_id,
                        message=t('progress.waitingZepProcess'),
                        progress=55,
                    )
                else:
                    # Create the graph
                    task_manager.update_task(
                        task_id,
                        message=t('progress.creatingZepGraph'),
                        progress=10
                    )

                    def remember_graph(graph_id):
                        project.graph_id = graph_id
                        ProjectManager.save_project(project)

                    graph_id = builder.create_graph(
                        name=graph_name,
                        graph_id_callback=remember_graph,
                    )

                    # Set the ontology
                    task_manager.update_task(
                        task_id,
                        message=t('progress.settingOntology'),
                        progress=15
                    )
                    builder.set_ontology(graph_id, ontology)

                    # Add the text (progress_callback takes (msg, progress_ratio))
                    def add_progress_callback(msg, progress_ratio):
                        progress = 15 + int(progress_ratio * 40)  # 15% - 55%
                        task_manager.update_task(
                            task_id,
                            message=msg,
                            progress=progress
                        )

                    task_manager.update_task(
                        task_id,
                        message=t('progress.addingChunks', count=total_chunks),
                        progress=15
                    )

                    def remember_batch(batch_id, operation_id):
                        project.zep_batch_id = batch_id
                        project.zep_batch_operation_id = operation_id
                        ProjectManager.save_project(project)

                    submission = builder.add_text_batches(
                        graph_id,
                        chunks,
                        batch_size=350,
                        progress_callback=add_progress_callback,
                        batch_created_callback=remember_batch,
                    )
                
                # Wait for Zep to finish processing every episode
                task_manager.update_task(
                    task_id,
                    message=t('progress.waitingZepProcess'),
                    progress=55
                )
                
                def wait_progress_callback(msg, progress_ratio):
                    progress = 55 + int(progress_ratio * 35)  # 55% - 90%
                    task_manager.update_task(
                        task_id,
                        message=msg,
                        progress=progress
                    )
                
                def remember_retry_batch(batch_id, operation_id):
                    # Journal every follow-up batch the retries create exactly
                    # the way the main batch is journaled. Without this the
                    # recovery lives only in memory: a crash after the retries
                    # succeeded left zep_batch_id on the still-"partial"
                    # original, and the next resume re-ingested chunks that had
                    # already committed, duplicating their episodes. Keyed on
                    # the operation ID, which is deterministic in the chunk set:
                    # two attempts collide only when the earlier one recovered
                    # nothing, so collapsing them cannot hide a landed episode.
                    for entry in project.zep_retry_batches:
                        if entry.get("operation_id") != operation_id:
                            continue
                        if batch_id and entry.get("batch_id") != batch_id:
                            entry["batch_id"] = batch_id
                            ProjectManager.save_project(project)
                        return
                    project.zep_retry_batches.append(
                        {"operation_id": operation_id, "batch_id": batch_id}
                    )
                    ProjectManager.save_project(project)

                # A single timed-out episode must not throw away the rest of a
                # 50-minute ingest: hand over the chunks so the failed items can
                # be resubmitted, and record whatever is still missing after
                # that instead of failing the build.
                lost_items = []
                builder._wait_for_batch(
                    submission,
                    wait_progress_callback,
                    allow_partial=True,
                    retry_chunks=chunks,
                    lost_items_callback=lost_items.extend,
                    retry_batch_callback=remember_retry_batch,
                    # Snapshot before the callback appends to it: these are the
                    # retry batches a previous run already submitted.
                    known_retry_batches=list(project.zep_retry_batches),
                )
                if lost_items:
                    build_logger.warning(
                        f"[{task_id}] Graph built with {len(lost_items)} of "
                        f"{total_chunks} chunk(s) missing: chunk_indexes="
                        f"{[item.sequence_index for item in lost_items]}"
                    )

                # Read the graph data back
                task_manager.update_task(
                    task_id,
                    message=t('progress.fetchingGraphData'),
                    progress=95
                )
                graph_data = builder.get_graph_data(graph_id)
                
                node_count = graph_data.get("node_count", 0)
                edge_count = graph_data.get("edge_count", 0)
                build_logger.info(f"[{task_id}] Built the graph: graph_id={graph_id}, nodes={node_count}, edges={edge_count}")

                # Publish local project/task terminal state under the same
                # lifecycle lock used by reset/delete/build claims. This
                # prevents a deletion from interleaving between the two saves.
                lost_indexes = [item.sequence_index for item in lost_items]
                with _project_build_lock(project_id):
                    project.status = ProjectStatus.GRAPH_COMPLETED
                    # A graph missing chunks is still usable, but it is not a
                    # clean build. Clearing the error here published a
                    # knowingly incomplete ingest as a full success: the only
                    # trace was a progress line the completion message
                    # overwrote milliseconds later.
                    if lost_indexes:
                        project.error = (
                            f"Graph built without {len(lost_indexes)} of "
                            f"{total_chunks} source chunk(s); missing "
                            f"chunk_indexes={lost_indexes[:20]}"
                            + ("..." if len(lost_indexes) > 20 else "")
                        )
                    else:
                        project.error = None
                    ProjectManager.save_project(project)
                    task_manager.update_task(
                        task_id,
                        status=TaskStatus.COMPLETED,
                        message=(
                            t(
                                'progress.episodesTimeout',
                                completed=total_chunks - len(lost_indexes),
                                total=total_chunks,
                            )
                            if lost_indexes
                            else t('progress.graphBuildComplete')
                        ),
                        progress=100,
                        result={
                            "project_id": project_id,
                            "graph_id": graph_id,
                            "node_count": node_count,
                            "edge_count": edge_count,
                            "chunk_count": total_chunks,
                            "lost_chunk_count": len(lost_indexes),
                            "lost_chunk_indexes": lost_indexes,
                            "zep_batch_id": submission.batch_id,
                        }
                    )
                
            except Exception as e:
                # Mark the project failed
                build_logger.error(f"[{task_id}] Failed to build the graph: {str(e)}")
                build_logger.debug(traceback.format_exc())
                
                with _project_build_lock(project_id):
                    project.status = ProjectStatus.FAILED
                    project.error = str(e)
                    ProjectManager.save_project(project)

                    task_manager.update_task(
                        task_id,
                        status=TaskStatus.FAILED,
                        message=t('progress.buildFailed', error=str(e)),
                        error=traceback.format_exc()
                    )
        
        # Start the background thread
        thread = threading.Thread(target=build_task, daemon=True)
        thread.start()
        
        return jsonify({
            "success": True,
            "data": {
                "project_id": project_id,
                "task_id": task_id,
                "resumed": resume_existing_batch,
                # None when the extraction endpoint actually answered the
                # check; a reason when nothing was verified.
                "preflight_skipped": preflight_skipped,
                "message": t('api.graphBuildStarted', taskId=task_id)
            }
        })
        
    except GraphInUseError as e:
        return jsonify({"success": False, "error": str(e)}), 409
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== Task queries ==============

@graph_bp.route('/task/<task_id>', methods=['GET'])
def get_task(task_id: str):
    """
    Return one task's status.
    """
    task = TaskManager().get_task(task_id)
    
    if not task:
        return jsonify({
            "success": False,
            "error": t('api.taskNotFound', id=task_id)
        }), 404
    
    return jsonify({
        "success": True,
        "data": task.to_dict()
    })


@graph_bp.route('/tasks', methods=['GET'])
def list_tasks():
    """
    List every task.
    """
    tasks = TaskManager().list_tasks()
    
    return jsonify({
        "success": True,
        "data": tasks,
        "count": len(tasks)
    })


# ============== Graph data ==============

@graph_bp.route('/data/<graph_id>', methods=['GET'])
def get_graph_data(graph_id: str):
    """
    Return the graph data: its nodes and edges.
    """
    try:
        if not Config.ZEP_API_KEY:
            return jsonify({
                "success": False,
                "error": t('api.zepApiKeyMissing')
            }), 500
        
        builder = GraphBuilderService(api_key=Config.ZEP_API_KEY)
        graph_data = builder.get_graph_data(graph_id)
        
        return jsonify({
            "success": True,
            "data": graph_data
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@graph_bp.route('/delete/<graph_id>', methods=['DELETE'])
def delete_graph(graph_id: str):
    """
    Delete a Zep graph.
    """
    try:
        if not Config.ZEP_API_KEY:
            return jsonify({
                "success": False,
                "error": t('api.zepApiKeyMissing')
            }), 500
        
        projects = ProjectManager.find_projects_by_graph_id(graph_id)
        if not projects:
            return jsonify({
                "success": False,
                "error": "No local project references this graph"
            }), 404
        project_ids = sorted({project.project_id for project in projects})
        with ExitStack() as stack:
            for project_id in project_ids:
                stack.enter_context(_project_build_lock(project_id))
            stack.enter_context(graph_lifecycle_lock(graph_id))

            # Re-read under all owning project locks so a concurrent build
            # claim cannot appear between validation and Cloud deletion.
            projects = ProjectManager.find_projects_by_graph_id(graph_id)
            # Only a build that is writing to *this* graph blocks the delete.
            # A project whose live build abandoned this graph earlier is
            # exactly the case the orphan record exists to make cleanable.
            if any(
                project.graph_id == graph_id and _project_has_active_build(project)
                for project in projects
            ):
                return jsonify({
                    "success": False,
                    "error": t('api.graphBuilding')
                }), 409

            _delete_cloud_graph_if_present(graph_id)

            for project in projects:
                project.orphaned_graph_ids = [
                    recorded
                    for recorded in project.orphaned_graph_ids
                    if recorded != graph_id
                ]
                if project.graph_id == graph_id:
                    _clear_project_graph_reference(project)
                    project.status = (
                        ProjectStatus.ONTOLOGY_GENERATED
                        if project.ontology
                        else ProjectStatus.CREATED
                    )
                ProjectManager.save_project(project)
        
        return jsonify({
            "success": True,
            "message": t('api.graphDeleted', id=graph_id)
        })
        
    except GraphInUseError as e:
        return jsonify({"success": False, "error": str(e)}), 409
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500
