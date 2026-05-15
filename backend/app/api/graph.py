"""
Graph-related API routes
Uses project context mechanism with server-side persistent state
"""

import os
import json
import tempfile
import traceback
import threading
from flask import request, jsonify, Response

from . import graph_bp
from .. import get_storage
from ..config import Config
from ..services.ontology_generator import OntologyGenerator
from ..services.graph_builder import GraphBuilderService
from ..services.text_processor import TextProcessor
from ..services.project_name_generator import generate_project_name
from ..utils.file_parser import FileParser
from ..utils.logger import get_logger
from ..utils.locale import t, get_locale, set_locale
from ..models.task import TaskManager, TaskStatus
from ..models.project import ProjectManager, ProjectStatus

# Get logger
logger = get_logger('mirofish.api')


def allowed_file(filename: str) -> bool:
    """Check if the file extension is allowed"""
    if not filename or '.' not in filename:
        return False
    ext = os.path.splitext(filename)[1].lower().lstrip('.')
    return ext in Config.ALLOWED_EXTENSIONS


# ============== Project management endpoints ==============

@graph_bp.route('/project/<project_id>', methods=['GET'])
def get_project(project_id: str):
    """
    Get project details
    """
    project = ProjectManager.get_project(project_id)
    
    if not project:
        return jsonify({
            "success": False,
            "error": t('api.projectNotFound', id=project_id)
        }), 404

    return jsonify({
        "success": True,
        "data": project
    })


@graph_bp.route('/project/list', methods=['GET'])
def list_projects():
    """
    List all projects
    """
    limit = request.args.get('limit', 50, type=int)
    projects = ProjectManager.list_projects(limit=limit)
    
    return jsonify({
        "success": True,
        "data": projects,
        "count": len(projects)
    })


@graph_bp.route('/project/<project_id>', methods=['DELETE'])
def delete_project(project_id: str):
    """
    Delete a project
    """
    storage = get_storage()
    success = ProjectManager.delete_project(project_id, storage=storage)
    
    if not success:
        return jsonify({
            "success": False,
            "error": t('api.projectDeleteFailed', id=project_id)
        }), 404

    return jsonify({
        "success": True,
        "message": t('api.projectDeleted', id=project_id)
    })


@graph_bp.route('/project/<project_id>', methods=['PATCH'])
def patch_project(project_id: str):
    """Update mutable project fields (currently: name)."""
    project = ProjectManager.get_project(project_id)
    if not project:
        return jsonify({"success": False, "error": t('api.projectNotFound', id=project_id)}), 404

    body = request.get_json(silent=True) or {}
    name = body.get("name", "").strip()
    if not name:
        return jsonify({"success": False, "error": "name cannot be empty"}), 400

    ProjectManager.save_project({"id": project_id, "name": name})
    updated = ProjectManager.get_project(project_id)
    return jsonify({"success": True, "data": updated})


@graph_bp.route('/project/<project_id>/reset', methods=['POST'])
def reset_project(project_id: str):
    """
    Reset project status (used to rebuild the graph)
    """
    project = ProjectManager.get_project(project_id)

    if not project:
        return jsonify({
            "success": False,
            "error": t('api.projectNotFound', id=project_id)
        }), 404

    new_status = ProjectStatus.ONTOLOGY_GENERATED if project.get("ontology") else ProjectStatus.CREATED
    ProjectManager.save_project({
        "id": project_id,
        "status": new_status,
        "active_task_id": None,
    })
    updated = ProjectManager.get_project(project_id)

    return jsonify({
        "success": True,
        "message": t('api.projectReset', id=project_id),
        "data": updated
    })


# ============== Endpoint 1: Upload files and generate ontology ==============

@graph_bp.route('/ontology/generate', methods=['POST'])
def generate_ontology():
    """
    Endpoint 1: Upload files and generate ontology definition

    Request method: multipart/form-data

    Parameters:
        files: Uploaded files (PDF/MD/TXT), multiple allowed
        simulation_requirement: Simulation requirement description (required)
        project_name: Project name (optional)
        additional_context: Additional context (optional)

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
    project_id = None
    try:
        logger.info("=== Starting ontology generation ===")
        storage = get_storage()

        simulation_requirement = request.form.get('simulation_requirement', '')
        project_name = request.form.get('project_name', 'Unnamed Project')
        additional_context = request.form.get('additional_context', '')

        if not simulation_requirement:
            return jsonify({"success": False, "error": t('api.requireSimulationRequirement')}), 400

        uploaded_files = request.files.getlist('files')
        if not uploaded_files or all(not f.filename for f in uploaded_files):
            return jsonify({"success": False, "error": t('api.requireFileUpload')}), 400

        project = ProjectManager.create_project(name=project_name, storage=storage)
        project_id = project["project_id"]
        logger.info(f"Project created: {project_id}")

        document_texts = []
        all_text = ""

        for file in uploaded_files:
            if file and file.filename and allowed_file(file.filename):
                file_info = ProjectManager.save_file_to_project(
                    project_id, file, file.filename, storage
                )
                raw = storage.download(file_info["storage_path"])
                ext = os.path.splitext(file.filename)[1].lower()
                with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                    tmp.write(raw)
                    tmp_path = tmp.name
                try:
                    text = FileParser.extract_text(tmp_path)
                finally:
                    os.unlink(tmp_path)
                text = TextProcessor.preprocess_text(text)
                document_texts.append(text)
                all_text += f"\n\n=== {file.filename} ===\n{text}"

        if not document_texts:
            ProjectManager.delete_project(project_id, storage=storage)
            return jsonify({"success": False, "error": t('api.noDocProcessed')}), 400

        ProjectManager.save_extracted_text(project_id, all_text, storage)
        logger.info(f"Text extraction complete, total {len(all_text)} characters")

        # Generate project name in background (non-blocking)
        def _name_task():
            try:
                name = generate_project_name(all_text)
                ProjectManager.save_project({"id": project_id, "name": name})
                logger.info(f"Project name generated: {name!r}")
            except Exception as exc:
                logger.warning(f"Background name generation failed: {exc}")

        threading.Thread(target=_name_task, daemon=True).start()

        logger.info("Calling LLM to generate ontology definition...")
        generator = OntologyGenerator()
        ontology = generator.generate(
            document_texts=document_texts,
            simulation_requirement=simulation_requirement,
            additional_context=additional_context if additional_context else None
        )

        entity_types = ontology.get("entity_types", [])
        edge_types = ontology.get("edge_types", [])
        analysis_summary = ontology.get("analysis_summary", "")
        logger.info(f"Ontology generation complete: {len(entity_types)} entity types, {len(edge_types)} relationship types")

        ProjectManager.save_ontology(project_id, entity_types, edge_types)
        ProjectManager.save_project({
            "id": project_id,
            "simulation_requirement": simulation_requirement,
            "analysis_summary": analysis_summary,
            "status": ProjectStatus.ONTOLOGY_GENERATED,
        })
        logger.info(f"=== Ontology generation complete === Project ID: {project_id}")

        return jsonify({
            "success": True,
            "data": {
                "project_id": project_id,
                "project_name": project_name,
                "ontology": {"entity_types": entity_types, "edge_types": edge_types},
                "analysis_summary": analysis_summary,
                "files": [],
                "total_text_length": len(all_text)
            }
        })

    except Exception as e:
        logger.exception("Error in generate_ontology")
        if project_id:
            try:
                ProjectManager.delete_project(project_id, storage=get_storage())
            except Exception:
                pass
        return jsonify({"success": False, "error": str(e), "traceback": traceback.format_exc()}), 500


# ============== Endpoint 1b: Import ontology ==============

@graph_bp.route('/ontology/import', methods=['POST'])
def import_ontology():
    """
    Endpoint 1b: Upload files and import a pre-existing ontology definition

    Request method: multipart/form-data

    Parameters:
        files: Uploaded files (PDF/MD/TXT), multiple allowed
        simulation_requirement: Simulation requirement description (required)
        ontology: JSON string with entity_types and edge_types (required)
        project_name: Project name (optional)

    Returns same structure as generate_ontology.
    """
    project_id = None
    try:
        logger.info("=== Starting ontology import ===")
        storage = get_storage()

        simulation_requirement = request.form.get('simulation_requirement', '')
        project_name = request.form.get('project_name', 'Unnamed Project')
        ontology_json = request.form.get('ontology', '')

        if not simulation_requirement:
            return jsonify({"success": False, "error": t('api.requireSimulationRequirement')}), 400
        if not ontology_json:
            return jsonify({"success": False, "error": t('api.requireOntologyJson')}), 400
        try:
            ontology = json.loads(ontology_json)
        except (ValueError, TypeError):
            return jsonify({"success": False, "error": t('api.invalidOntologyJson')}), 400
        if not isinstance(ontology.get('entity_types'), list) or not isinstance(ontology.get('edge_types'), list):
            return jsonify({"success": False, "error": t('api.invalidOntologyStructure')}), 400

        uploaded_files = request.files.getlist('files')
        if not uploaded_files or all(not f.filename for f in uploaded_files):
            return jsonify({"success": False, "error": t('api.requireFileUpload')}), 400

        project = ProjectManager.create_project(name=project_name, storage=storage)
        project_id = project["project_id"]
        logger.info(f"Project created for import: {project_id}")

        document_texts = []
        all_text = ""

        for file in uploaded_files:
            if file and file.filename and allowed_file(file.filename):
                file_info = ProjectManager.save_file_to_project(
                    project_id, file, file.filename, storage
                )
                raw = storage.download(file_info["storage_path"])
                ext = os.path.splitext(file.filename)[1].lower()
                with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                    tmp.write(raw)
                    tmp_path = tmp.name
                try:
                    text = FileParser.extract_text(tmp_path)
                finally:
                    os.unlink(tmp_path)
                text = TextProcessor.preprocess_text(text)
                document_texts.append(text)
                all_text += f"\n\n=== {file.filename} ===\n{text}"

        if not document_texts:
            ProjectManager.delete_project(project_id, storage=storage)
            return jsonify({"success": False, "error": t('api.noDocProcessed')}), 400

        ProjectManager.save_extracted_text(project_id, all_text, storage)

        # Generate project name in background (non-blocking)
        def _name_task():
            try:
                name = generate_project_name(all_text)
                ProjectManager.save_project({"id": project_id, "name": name})
                logger.info(f"Project name generated: {name!r}")
            except Exception as exc:
                logger.warning(f"Background name generation failed: {exc}")

        threading.Thread(target=_name_task, daemon=True).start()

        entity_types = ontology.get("entity_types", [])
        edge_types = ontology.get("edge_types", [])
        analysis_summary = ontology.get("analysis_summary", "")

        ProjectManager.save_ontology(project_id, entity_types, edge_types)
        ProjectManager.save_project({
            "id": project_id,
            "simulation_requirement": simulation_requirement,
            "analysis_summary": analysis_summary,
            "status": ProjectStatus.ONTOLOGY_GENERATED,
        })
        logger.info(f"=== Ontology import complete === Project ID: {project_id}")

        return jsonify({
            "success": True,
            "data": {
                "project_id": project_id,
                "project_name": project_name,
                "ontology": {"entity_types": entity_types, "edge_types": edge_types},
                "analysis_summary": analysis_summary,
                "files": [],
                "total_text_length": len(all_text)
            }
        })

    except Exception as e:
        if project_id:
            try:
                ProjectManager.delete_project(project_id, storage=get_storage())
            except Exception:
                pass
        return jsonify({"success": False, "error": str(e), "traceback": traceback.format_exc()}), 500


# ============== Endpoint 2: Build graph ==============

@graph_bp.route('/build', methods=['POST'])
def build_graph():
    """
    Endpoint 2: Build graph from project_id

    Request (JSON):
        {
            "project_id": "proj_xxxx",  // required, from endpoint 1
            "graph_name": "Graph name", // optional
            "chunk_size": 500,          // optional, default 500
            "chunk_overlap": 50         // optional, default 50
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
        logger.info(f"GRAPH_BACKEND={Config.GRAPH_BACKEND!r} ZEP_API_KEY={'set' if Config.ZEP_API_KEY else 'unset'} NEO4J_PASSWORD={'set' if Config.NEO4J_PASSWORD else 'unset'}")

        # Check configuration
        errors = Config.get_graph_config_errors()
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
        
        # Get project
        project = ProjectManager.get_project(project_id)
        if not project:
            return jsonify({"success": False, "error": t('api.projectNotFound', id=project_id)}), 404
        storage = get_storage()

        # Check project status
        force = data.get('force', False)

        if project["status"] == ProjectStatus.CREATED:
            return jsonify({"success": False, "error": t('api.ontologyNotGenerated')}), 400

        if project["status"] == ProjectStatus.GRAPH_BUILDING and not force:
            return jsonify({
                "success": False,
                "error": t('api.graphBuilding'),
                "task_id": project.get("active_task_id")
            }), 400

        # If force rebuild, reset status
        if force and project["status"] in [ProjectStatus.GRAPH_BUILDING, ProjectStatus.FAILED, ProjectStatus.GRAPH_COMPLETED]:
            ProjectManager.save_project({"id": project_id, "status": ProjectStatus.ONTOLOGY_GENERATED, "active_task_id": None})
            project = ProjectManager.get_project(project_id)

        # Get configuration
        graph_name = data.get('graph_name', project["name"] or 'MiroFish Graph')
        chunk_size = data.get('chunk_size', project.get("chunk_size") or Config.DEFAULT_CHUNK_SIZE)
        chunk_overlap = data.get('chunk_overlap', project.get("chunk_overlap") or Config.DEFAULT_CHUNK_OVERLAP)
        ProjectManager.save_project({"id": project_id, "chunk_size": chunk_size, "chunk_overlap": chunk_overlap})

        # Get extracted text
        text = ProjectManager.get_extracted_text(project_id, storage)
        if not text:
            return jsonify({"success": False, "error": t('api.textNotFound')}), 400

        # Get ontology
        ontology = project.get("ontology") or ProjectManager.get_ontology(project_id)
        if not ontology:
            return jsonify({"success": False, "error": t('api.ontologyNotFound')}), 400

        # Create async task
        task_manager = TaskManager()
        task_id = task_manager.create_task(f"Build graph: {graph_name}")
        logger.info(f"Graph build task created: task_id={task_id}, project_id={project_id}")

        # Update project status
        ProjectManager.save_project({
            "id": project_id,
            "status": ProjectStatus.GRAPH_BUILDING,
            "active_task_id": task_id,
        })

        # Capture locale before spawning background thread
        current_locale = get_locale()

        # Start background task
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
                
                # Create graph builder service
                builder = GraphBuilderService()

                # Split into chunks
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
                
                # Create graph
                task_manager.update_task(
                    task_id,
                    message=t('progress.creatingZepGraph'),
                    progress=10
                )
                graph_id = builder.create_graph(name=graph_name)
                
                # Persist graph record
                ont_id = None
                try:
                    from ..models.db_models import OntologyModel
                    from sqlalchemy import select as sa_select
                    from ..db import get_session
                    with get_session() as _db:
                        _ont = _db.execute(
                            sa_select(OntologyModel)
                            .where(OntologyModel.project_id == project_id)
                            .order_by(OntologyModel.version.desc())
                        ).scalars().first()
                        ont_id = _ont.id if _ont else None
                except Exception:
                    pass
                ProjectManager.save_graph_record(project_id, graph_id, ontology_id=ont_id)

                # Set ontology
                task_manager.update_task(
                    task_id,
                    message=t('progress.settingOntology'),
                    progress=15
                )
                builder.set_ontology(graph_id, ontology)
                
                # Add text (progress_callback signature: (msg, progress_ratio))
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
                
                batch_size = Config.GRAPHITI_BATCH_SIZE if Config.GRAPH_BACKEND == 'graphiti' else 3
                episode_uuids = builder.add_text_batches(
                    graph_id,
                    chunks,
                    batch_size=batch_size,
                    progress_callback=add_progress_callback
                )
                
                # Wait for Zep processing to complete (poll each episode's processed status)
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
                
                # Fetch graph data
                task_manager.update_task(
                    task_id,
                    message=t('progress.fetchingGraphData'),
                    progress=95
                )
                graph_data = builder.get_graph_data(graph_id)
                
                node_count = graph_data.get("node_count", 0)
                edge_count = graph_data.get("edge_count", 0)

                # Update project status
                ProjectManager.complete_graph_record(project_id, node_count, edge_count)
                ProjectManager.save_project({
                    "id": project_id,
                    "status": ProjectStatus.GRAPH_COMPLETED,
                    "active_task_id": None,
                })
                build_logger.info(f"[{task_id}] Graph build complete: graph_id={graph_id}, nodes={node_count}, edges={edge_count}")

                # Complete
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
                # Update project status to failed
                build_logger.error(f"[{task_id}] Graph build failed: {str(e)}")
                build_logger.debug(traceback.format_exc())
                
                ProjectManager.save_project({
                    "id": project_id,
                    "status": ProjectStatus.FAILED,
                    "active_task_id": None,
                })
                
                task_manager.update_task(
                    task_id,
                    status=TaskStatus.FAILED,
                    message=t('progress.buildFailed', error=str(e)),
                    error=traceback.format_exc()
                )
        
        # Start background thread
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


# ============== Task query endpoints ==============

@graph_bp.route('/task/<task_id>', methods=['GET'])
def get_task(task_id: str):
    """
    Query task status
    """
    task = TaskManager().get_task(task_id)
    
    if not task:
        return jsonify({
            "success": False,
            "error": t('api.taskNotFound', id=task_id)
        }), 404
    
    return jsonify({
        "success": True,
        "data": task
    })


@graph_bp.route('/tasks', methods=['GET'])
def list_tasks():
    """
    List all tasks
    """
    tasks = TaskManager().list_tasks()
    
    return jsonify({
        "success": True,
        "data": tasks,
        "count": len(tasks)
    })


# ============== Graph data endpoints ==============

@graph_bp.route('/data/<graph_id>', methods=['GET'])
def get_graph_data(graph_id: str):
    """
    Get graph data (nodes and edges)
    """
    try:
        builder = GraphBuilderService()
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
    Delete a Zep graph
    """
    try:
        builder = GraphBuilderService()
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


@graph_bp.route('/project/<project_id>/download/source', methods=['GET'])
def download_project_source(project_id: str):
    """Download the original uploaded document for a project."""
    project = ProjectManager.get_project(project_id)
    if not project:
        return jsonify({"success": False, "error": t('api.projectNotFound', id=project_id)}), 404

    files = ProjectManager._get_project_files(project_id)
    if not files:
        return jsonify({"success": False, "error": "No source file found"}), 404

    file_info = files[0]
    storage = get_storage()
    try:
        data = storage.download(file_info["storage_path"])
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

    return Response(
        data,
        status=200,
        headers={
            "Content-Disposition": f'attachment; filename="{file_info["filename"]}"',
            "Content-Type": file_info.get("mime_type", "application/octet-stream"),
        }
    )
