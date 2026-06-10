"""
Graph API routes.
Uses the project context mechanism so the server persists state between calls.
"""

import os
import traceback
import threading
from flask import request, jsonify

from . import graph_bp
from ..config import Config
from ..services.ontology_generator import OntologyGenerator
from ..services.graph_builder import GraphBuilderService
from ..services.text_processor import TextProcessor
from ..utils.file_parser import FileParser
from ..utils.logger import get_logger
from ..utils.locale import t, get_locale, set_locale
from ..models.task import TaskManager, TaskStatus
from ..models.project import ProjectManager, ProjectStatus

# Get logger
logger = get_logger('mirofish.api')


def allowed_file(filename: str) -> bool:
    """Check whether the file extension is in the allow-list."""
    if not filename or '.' not in filename:
        return False
    ext = os.path.splitext(filename)[1].lower().lstrip('.')
    return ext in Config.ALLOWED_EXTENSIONS


# ============== Project management endpoints ==============

@graph_bp.route('/project/<project_id>', methods=['GET'])
def get_project(project_id: str):
    """
    Retrieve project details.
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
    List all projects.
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
    """
    Delete a project.
    """
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
    """
    Reset project state (used to rebuild the graph).
    """
    project = ProjectManager.get_project(project_id)

    if not project:
        return jsonify({
            "success": False,
            "error": t('api.projectNotFound', id=project_id)
        }), 404

    # Roll back to the "ontology generated" state
    if project.ontology:
        project.status = ProjectStatus.ONTOLOGY_GENERATED
    else:
        project.status = ProjectStatus.CREATED

    project.graph_id = None
    project.graph_build_task_id = None
    project.error = None
    ProjectManager.save_project(project)

    return jsonify({
        "success": True,
        "message": t('api.projectReset', id=project_id),
        "data": project.to_dict()
    })


# ============== Endpoint 1: upload files and generate the ontology ==============

@graph_bp.route('/ontology/generate', methods=['POST'])
def generate_ontology():
    """
    Endpoint 1: upload files, analyse them and produce an ontology definition.

    Request: multipart/form-data.

    Parameters:
        files: uploaded files (PDF/MD/TXT), one or many.
        simulation_requirement: description of the simulation to run (required).
        project_name: project name (optional).
        additional_context: extra notes (optional).

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
    try:
        logger.info("=== Generating ontology definition ===")

        # Read parameters
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

        # Read uploaded files
        uploaded_files = request.files.getlist('files')
        if not uploaded_files or all(not f.filename for f in uploaded_files):
            return jsonify({
                "success": False,
                "error": t('api.requireFileUpload')
            }), 400

        # Create the project
        project = ProjectManager.create_project(name=project_name)
        project.simulation_requirement = simulation_requirement
        logger.info(f"Created project: {project.project_id}")

        # Save files and extract text
        document_texts = []
        all_text = ""

        for file in uploaded_files:
            if file and file.filename and allowed_file(file.filename):
                # Save the file inside the project directory
                file_info = ProjectManager.save_file_to_project(
                    project.project_id,
                    file,
                    file.filename
                )
                project.files.append({
                    "filename": file_info["original_filename"],
                    "size": file_info["size"]
                })

                # Extract text
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

        # Persist the extracted text
        project.total_text_length = len(all_text)
        ProjectManager.save_extracted_text(project.project_id, all_text)
        logger.info(f"Text extraction complete: {len(all_text)} characters")

        # Generate the ontology
        logger.info("Calling LLM to generate ontology definition...")
        generator = OntologyGenerator()
        ontology = generator.generate(
            document_texts=document_texts,
            simulation_requirement=simulation_requirement,
            additional_context=additional_context if additional_context else None
        )

        # Save the ontology onto the project
        entity_count = len(ontology.get("entity_types", []))
        edge_count = len(ontology.get("edge_types", []))
        logger.info(f"Ontology generation complete: {entity_count} entity types, {edge_count} edge types")

        project.ontology = {
            "entity_types": ontology.get("entity_types", []),
            "edge_types": ontology.get("edge_types", [])
        }
        project.analysis_summary = ontology.get("analysis_summary", "")
        project.status = ProjectStatus.ONTOLOGY_GENERATED
        ProjectManager.save_project(project)
        logger.info(f"=== Ontology generation complete === Project ID: {project.project_id}")

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

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== Endpoint 2: build the graph ==============

@graph_bp.route('/build', methods=['POST'])
def build_graph():
    """
    Endpoint 2: build the graph for a given project_id.

    Request (JSON):
        {
            "project_id": "proj_xxxx",   // required, returned by endpoint 1
            "graph_name": "graph name",  // optional
            "chunk_size": 500,           // optional, default 500
            "chunk_overlap": 50          // optional, default 50
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
        logger.info("=== Starting graph build ===")

        # Validate config
        errors = []
        if not Config.FALKORDB_HOST:
            errors.append(t('api.zepApiKeyMissing'))
        if errors:
            logger.error(f"Configuration error: {errors}")
            return jsonify({
                "success": False,
                "error": t('api.configError', details="; ".join(errors))
            }), 500

        # Parse request
        data = request.get_json() or {}
        project_id = data.get('project_id')
        logger.debug(f"Request parameters: project_id={project_id}")

        if not project_id:
            return jsonify({
                "success": False,
                "error": t('api.requireProjectId')
            }), 400

        # Look up the project
        project = ProjectManager.get_project(project_id)
        if not project:
            return jsonify({
                "success": False,
                "error": t('api.projectNotFound', id=project_id)
            }), 404

        # Check project state
        force = data.get('force', False)  # force a rebuild

        if project.status == ProjectStatus.CREATED:
            return jsonify({
                "success": False,
                "error": t('api.ontologyNotGenerated')
            }), 400

        if project.status == ProjectStatus.GRAPH_BUILDING and not force:
            return jsonify({
                "success": False,
                "error": t('api.graphBuilding'),
                "task_id": project.graph_build_task_id
            }), 400

        # If forced, roll the project back to the "ontology generated" state
        if force and project.status in [ProjectStatus.GRAPH_BUILDING, ProjectStatus.FAILED, ProjectStatus.GRAPH_COMPLETED]:
            project.status = ProjectStatus.ONTOLOGY_GENERATED
            project.graph_id = None
            project.graph_build_task_id = None
            project.error = None

        # Read configuration
        graph_name = data.get('graph_name', project.name or 'MiroFish Graph')
        chunk_size = data.get('chunk_size', project.chunk_size or Config.DEFAULT_CHUNK_SIZE)
        chunk_overlap = data.get('chunk_overlap', project.chunk_overlap or Config.DEFAULT_CHUNK_OVERLAP)

        # Persist configuration on the project
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

        # Create the async task
        task_manager = TaskManager()
        task_id = task_manager.create_task(f"Build graph: {graph_name}")
        logger.info(f"Created graph build task: task_id={task_id}, project_id={project_id}")

        # Update project state
        project.status = ProjectStatus.GRAPH_BUILDING
        project.graph_build_task_id = task_id
        ProjectManager.save_project(project)

        # Capture locale before spawning background thread
        current_locale = get_locale()

        # Background worker
        def build_task():
            set_locale(current_locale)
            build_logger = get_logger('mirofish.build')
            try:
                build_logger.info(f"[{task_id}] Starting graph build...")
                task_manager.update_task(
                    task_id,
                    status=TaskStatus.PROCESSING,
                    message=t('progress.initGraphService')
                )

                # Create the graph builder service
                builder = GraphBuilderService(api_key=None)

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
                total_chunks = len(chunks)

                # Create the graph
                task_manager.update_task(
                    task_id,
                    message=t('progress.creatingZepGraph'),
                    progress=10
                )
                graph_id = builder.create_graph(name=graph_name)

                # Save the graph_id onto the project
                project.graph_id = graph_id
                ProjectManager.save_project(project)

                # Apply the ontology
                task_manager.update_task(
                    task_id,
                    message=t('progress.settingOntology'),
                    progress=15
                )
                builder.set_ontology(graph_id, ontology)

                # progress_callback signature: (msg, progress_ratio)
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

                episode_uuids = builder.add_text_batches(
                    graph_id,
                    chunks,
                    batch_size=3,
                    progress_callback=add_progress_callback
                )

                # Wait for Zep/Graphiti to finish processing (poll each episode's processed flag)
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

                builder._wait_for_episodes(episode_uuids, wait_progress_callback)

                # Fetch the final graph data
                task_manager.update_task(
                    task_id,
                    message=t('progress.fetchingGraphData'),
                    progress=95
                )
                graph_data = builder.get_graph_data(graph_id)

                # Update project state
                project.status = ProjectStatus.GRAPH_COMPLETED
                ProjectManager.save_project(project)

                node_count = graph_data.get("node_count", 0)
                edge_count = graph_data.get("edge_count", 0)
                build_logger.info(f"[{task_id}] Graph build complete: graph_id={graph_id}, nodes={node_count}, edges={edge_count}")

                # Mark task as complete
                task_manager.update_task(
                    task_id,
                    status=TaskStatus.COMPLETED,
                    message=t('progress.graphBuildComplete'),
                    progress=100,
                    result={
                        "project_id": project_id,
                        "graph_id": graph_id,
                        "node_count": node_count,
                        "edge_count": edge_count,
                        "chunk_count": total_chunks
                    }
                )

            except Exception as e:
                # Mark project as failed
                build_logger.error(f"[{task_id}] Graph build failed: {str(e)}")
                build_logger.debug(traceback.format_exc())

                project.status = ProjectStatus.FAILED
                project.error = str(e)
                ProjectManager.save_project(project)

                task_manager.update_task(
                    task_id,
                    status=TaskStatus.FAILED,
                    message=t('progress.buildFailed', error=str(e)),
                    error=traceback.format_exc()
                )

        # Launch background thread
        thread = threading.Thread(target=build_task, daemon=True)
        thread.start()

        return jsonify({
            "success": True,
            "data": {
                "project_id": project_id,
                "task_id": task_id,
                "message": t('api.graphBuildStarted', taskId=task_id)
            }
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500



# ============== One-shot ingest endpoint ==============

import threading
import traceback

from flask import request, jsonify

from . import graph_bp
from ..config import Config
from ..services.graph_builder import GraphBuilderService
from ..services.ontology_generator import OntologyGenerator
from ..services.text_processor import TextProcessor
from ..utils.logger import get_logger
from ..utils.locale import t, get_locale, set_locale
from ..models.task import TaskManager, TaskStatus
from ..models.project import ProjectManager, ProjectStatus

logger = get_logger("mirofish.api.ingest_text")


@graph_bp.route("/ingest_text", methods=["POST"])
def ingest_text():
    """
    One-shot ingest: text in, project + ontology + async build out.

    Request (JSON):
        {
            "name": "iran-briefing-2026-06-09T11",
            "text": "## IRAN/US/ISRAEL CONFLICT ...",
            "simulation_requirement": "Extract entities and relations...",
            "additional_context": "optional, free-form",
            "graph_name": "optional, defaults to name",
            "chunk_size": 500,
            "chunk_overlap": 50
        }

    Response:
        {
            "success": true,
            "data": {
                "project_id": "proj_xxxx",
                "task_id":    "task_xxxx",
                "message":    "..."
            }
        }

    Poll status with: GET /api/graph/task/<task_id>
    """
    try:
        data = request.get_json(silent=True) or {}

        name = (data.get("name") or "").strip()
        text = (data.get("text") or "").strip()
        simulation_requirement = (data.get("simulation_requirement") or "").strip()
        additional_context = (data.get("additional_context") or "").strip() or None
        graph_name = (data.get("graph_name") or name or "MiroFish Graph").strip()
        chunk_size = int(data.get("chunk_size") or Config.DEFAULT_CHUNK_SIZE)
        chunk_overlap = int(data.get("chunk_overlap") or Config.DEFAULT_CHUNK_OVERLAP)

        if not name:
            return jsonify({"success": False, "error": "name is required"}), 400
        if not text:
            return jsonify({"success": False, "error": "text is required"}), 400
        if not simulation_requirement:
            return jsonify(
                {"success": False, "error": "simulation_requirement is required"}
            ), 400
        if not Config.FALKORDB_HOST:
            return jsonify({"success": False, "error": "FalkorDB not configured"}), 500

        # 1. Create project
        project = ProjectManager.create_project(name=name)
        project.simulation_requirement = simulation_requirement
        project.chunk_size = chunk_size
        project.chunk_overlap = chunk_overlap
        logger.info(f"[ingest_text] created project {project.project_id} ({name})")

        # 2. Save extracted text
        cleaned_text = TextProcessor.preprocess_text(text)
        project.total_text_length = len(cleaned_text)
        ProjectManager.save_extracted_text(project.project_id, cleaned_text)
        logger.info(
            f"[ingest_text] saved text: {len(cleaned_text)} chars "
            f"(project={project.project_id})"
        )

        # 3. Generate ontology synchronously — this is an LLM call, takes ~10–30s
        generator = OntologyGenerator()
        ontology = generator.generate(
            document_texts=[cleaned_text],
            simulation_requirement=simulation_requirement,
            additional_context=additional_context,
        )
        entity_count = len(ontology.get("entity_types", []))
        edge_count = len(ontology.get("edge_types", []))
        project.ontology = {
            "entity_types": ontology.get("entity_types", []),
            "edge_types": ontology.get("edge_types", []),
        }
        project.analysis_summary = ontology.get("analysis_summary", "")
        project.status = ProjectStatus.ONTOLOGY_GENERATED
        ProjectManager.save_project(project)
        logger.info(
            f"[ingest_text] ontology ready: {entity_count} entity types, "
            f"{edge_count} edge types (project={project.project_id})"
        )

        # 4. Kick off async graph build (same path /build uses)
        task_manager = TaskManager()
        task_id = task_manager.create_task(f"Build graph: {graph_name}")
        project.status = ProjectStatus.GRAPH_BUILDING
        project.graph_build_task_id = task_id
        ProjectManager.save_project(project)
        current_locale = get_locale()

        def build_task():
            set_locale(current_locale)
            build_logger = get_logger("mirofish.build.ingest")
            try:
                build_logger.info(
                    f"[{task_id}] start build for project={project.project_id}"
                )
                task_manager.update_task(
                    task_id, status=TaskStatus.PROCESSING, message=t("progress.initGraphService")
                )
                builder = GraphBuilderService(api_key=None)

                # Chunk
                task_manager.update_task(task_id, message=t("progress.textChunking"), progress=5)
                chunks = TextProcessor.split_text(
                    cleaned_text, chunk_size=chunk_size, overlap=chunk_overlap
                )
                total_chunks = len(chunks)

                # Create graph + ontology
                task_manager.update_task(
                    task_id, message=t("progress.creatingZepGraph"), progress=10
                )
                graph_id = builder.create_graph(name=graph_name)
                project.graph_id = graph_id
                ProjectManager.save_project(project)

                task_manager.update_task(
                    task_id, message=t("progress.settingOntology"), progress=15
                )
                builder.set_ontology(graph_id, ontology)

                # Add text batches
                def add_cb(msg, ratio):
                    task_manager.update_task(
                        task_id, message=msg, progress=15 + int(ratio * 40)
                    )

                episode_uuids = builder.add_text_batches(
                    graph_id, chunks, batch_size=3, progress_callback=add_cb
                )

                # Wait for Graphiti to process episodes
                def wait_cb(msg, ratio):
                    task_manager.update_task(
                        task_id, message=msg, progress=55 + int(ratio * 35)
                    )

                builder._wait_for_episodes(episode_uuids, wait_cb)

                # Fetch final graph data
                graph_data = builder.get_graph_data(graph_id)
                project.status = ProjectStatus.GRAPH_COMPLETED
                ProjectManager.save_project(project)

                node_count = graph_data.get("node_count", 0)
                edge_count_out = graph_data.get("edge_count", 0)
                build_logger.info(
                    f"[{task_id}] done: graph_id={graph_id} "
                    f"nodes={node_count} edges={edge_count_out}"
                )

                task_manager.update_task(
                    task_id,
                    status=TaskStatus.COMPLETED,
                    message=t("progress.graphBuildComplete"),
                    progress=100,
                    result={
                        "project_id": project.project_id,
                        "graph_id": graph_id,
                        "node_count": node_count,
                        "edge_count": edge_count_out,
                        "chunk_count": total_chunks,
                    },
                )
            except Exception as e:
                build_logger.error(f"[{task_id}] failed: {e}")
                build_logger.debug(traceback.format_exc())
                project.status = ProjectStatus.FAILED
                project.error = str(e)
                ProjectManager.save_project(project)
                task_manager.update_task(
                    task_id,
                    status=TaskStatus.FAILED,
                    message=t("progress.buildFailed", error=str(e)),
                    error=traceback.format_exc(),
                )

        thread = threading.Thread(target=build_task, daemon=True)
        thread.start()

        return jsonify(
            {
                "success": True,
                "data": {
                    "project_id": project.project_id,
                    "task_id": task_id,
                    "graph_name": graph_name,
                    "ontology_entity_types": entity_count,
                    "ontology_edge_types": edge_count,
                    "text_length": len(cleaned_text),
                    "message": t("api.graphBuildStarted", taskId=task_id),
                },
            }
        )

    except Exception as e:
        logger.error(f"ingest_text failed: {e}")
        logger.debug(traceback.format_exc())
        return jsonify(
            {"success": False, "error": str(e), "traceback": traceback.format_exc()}
        ), 500

# ============== Task query endpoints ==============

@graph_bp.route('/task/<task_id>', methods=['GET'])
def get_task(task_id: str):
    """
    Query a task's state.
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
    List all tasks.
    """
    tasks = TaskManager().list_tasks()

    return jsonify({
        "success": True,
        "data": [t.to_dict() for t in tasks],
        "count": len(tasks)
    })


# ============== Graph data endpoints ==============

@graph_bp.route('/data/<graph_id>', methods=['GET'])
def get_graph_data(graph_id: str):
    """
    Get graph data (nodes and edges).
    """
    try:
        if not Config.FALKORDB_HOST:
            return jsonify({
                "success": False,
                "error": t('api.zepApiKeyMissing')
            }), 500

        builder = GraphBuilderService(api_key=None)
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
    Delete a Zep/Graphiti graph.
    """
    try:
        if not Config.FALKORDB_HOST:
            return jsonify({
                "success": False,
                "error": t('api.zepApiKeyMissing')
            }), 500

        builder = GraphBuilderService(api_key=None)
        builder.delete_graph(graph_id)

        return jsonify({
            "success": True,
            "message": t('api.graphDeleted', id=graph_id)
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500
