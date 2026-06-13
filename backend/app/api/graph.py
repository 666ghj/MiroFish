"""
API routes liên quan đến Graph
Sử dụng cơ chế project context, trạng thái được persist phía server
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
from ..utils.llm_client import LLMClient
from ..utils.logger import get_logger
from ..models.task import TaskManager, TaskStatus
from ..models.project import ProjectManager, ProjectStatus

# Logger
logger = get_logger('mirofish.api')


def allowed_file(filename: str) -> bool:
    """Kiểm tra phần mở rộng file có được cho phép hay không"""
    if not filename or '.' not in filename:
        return False
    ext = os.path.splitext(filename)[1].lower().lstrip('.')
    return ext in Config.ALLOWED_EXTENSIONS


@graph_bp.route('/project/<project_id>', methods=['GET'])
def get_project(project_id: str):
    """
    Lấy chi tiết project
    """
    project = ProjectManager.get_project(project_id)
    
    if not project:
        return jsonify({
            "success": False,
            "error": f"Project does not exist: {project_id}"
        }), 404
    
    return jsonify({
        "success": True,
        "data": project.to_dict()
    })


@graph_bp.route('/project/list', methods=['GET'])
def list_projects():
    """
    Liệt kê tất cả project
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
    Xóa project
    """
    success = ProjectManager.delete_project(project_id)
    
    if not success:
        return jsonify({
            "success": False,
            "error": f"Project does not exist or delete failed: {project_id}"
        }), 404
    
    return jsonify({
        "success": True,
        "message": f"Project deleted: {project_id}"
    })


@graph_bp.route('/project/<project_id>/reset', methods=['POST'])
def reset_project(project_id: str):
    """
    Reset trạng thái project (dùng để rebuild graph)
    """
    project = ProjectManager.get_project(project_id)
    
    if not project:
        return jsonify({
            "success": False,
            "error": f"Project does not exist: {project_id}"
        }), 404
    
    # Reset về trạng thái ontology_generated nếu đã có ontology, ngược lại về created
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
        "message": f"Project reset successfully: {project_id}",
        "data": project.to_dict()
    })


# ============== API 1: Upload file và generate ontology ==============

@graph_bp.route('/ontology/generate', methods=['POST'])
def generate_ontology():
    """
    API 1: Upload file, phân tích và generate định nghĩa ontology
    
    Request type: multipart/form-data
    
    Parameters:
        files: File upload (PDF/MD/TXT), có thể nhiều file
        simulation_requirement: Mô tả yêu cầu simulation (bắt buộc)
        project_name: Tên project (tùy chọn)
        additional_context: Thông tin bổ sung (tùy chọn)
        
    Response:
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
        logger.info("=== Start generating ontology definition ===")
        
        # Get parameters
        simulation_requirement = request.form.get('simulation_requirement', '')
        project_name = request.form.get('project_name', 'Unnamed Project')
        additional_context = request.form.get('additional_context', '')
        
        logger.debug(f"Project name: {project_name}")
        logger.debug(f"Simulation requirement: {simulation_requirement[:100]}...")
        
        if not simulation_requirement:
            return jsonify({
                "success": False,
                "error": "Please provide simulation requirement description (simulation_requirement)"
            }), 400
        
        # Get uploaded files
        uploaded_files = request.files.getlist('files')
        if not uploaded_files or all(not f.filename for f in uploaded_files):
            return jsonify({
                "success": False,
                "error": "Please upload at least one document file"
            }), 400
        
        # Create project
        project = ProjectManager.create_project(name=project_name)
        project.simulation_requirement = simulation_requirement
        logger.info(f"Project created: {project.project_id}")
        
        # Save and extract text
        document_texts = []
        all_text = ""
        
        for file in uploaded_files:
            if file and file.filename and allowed_file(file.filename):
                # Save file into project directory
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
                "error": "No documents were successfully processed. Please check the file formats."
            }), 400
        
        # Save extracted text to project
        project.total_text_length = len(all_text)
        ProjectManager.save_extracted_text(project.project_id, all_text)
        logger.info(f"Text extraction completed, total {len(all_text)} characters")
        
        # Generate ontology definition using LLM
        logger.info("Calling LLM to generate ontology definition...")
        generator = OntologyGenerator(
            llm_client=LLMClient(
                component="ontology_generator",
                metadata={
                    "project_id": project.project_id,
                    "phase": "ontology_generation",
                },
            )
        )
        ontology = generator.generate(
            document_texts=document_texts,
            simulation_requirement=simulation_requirement,
            additional_context=additional_context if additional_context else None
        )
        
        # Save ontology to project
        entity_count = len(ontology.get("entity_types", []))
        edge_count = len(ontology.get("edge_types", []))
        logger.info(f"Ontology generation completed: {entity_count} entity types, {edge_count} edge types")
        
        project.ontology = {
            "entity_types": ontology.get("entity_types", []),
            "edge_types": ontology.get("edge_types", [])
        }
        project.analysis_summary = ontology.get("analysis_summary", "")
        project.status = ProjectStatus.ONTOLOGY_GENERATED
        ProjectManager.save_project(project)
        logger.info(f"=== Ontology generation completed === Project ID: {project.project_id}")
        
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


# ============== API 2: Build graph ==============

# API ROUTE DEFINITION - Flash route handler for graph construction requests
@graph_bp.route('/build', methods=['POST'])
def build_graph():
    """
    API 2: Build graph dựa trên project_id
    
    Request (JSON):
        {
            "project_id": "proj_xxxx",  // bắt buộc, từ API 1
            "graph_name": "Graph name", // tùy chọn
            "chunk_size": 500,          // tùy chọn, mặc định 500
            "chunk_overlap": 50         // tùy chọn, mặc định 50
        }
        
    Response:
        {
            "success": true,
            "data": {
                "project_id": "proj_xxxx",
                "task_id": "task_xxxx",
                "message": "Graph build task started"
            }
        }

    Graph builder workflow 
        - [1] - create_graph()
        - [2] - set_ontology()
        - [3] - split_text()
        - [4] - add_text_batches()
    """
    try:
        logger.info("=== Start building graph ===")
        
        # Kiểm tra cấu hình
        errors = []
        if not Config.NEO4J_URI or not Config.NEO4J_PASSWORD:
            errors.append("NEO4J_URI / NEO4J_PASSWORD not configured")
        if errors:
            logger.error(f"Configuration error: {errors}")
            return jsonify({
                "success": False,
                "error": "Configuration error: " + "; ".join(errors)
            }), 500
        
        # Parse request
        data = request.get_json() or {}
        project_id = data.get('project_id')
        logger.debug(f"Request parameters: project_id={project_id}")
        
        if not project_id:
            return jsonify({
                "success": False,
                "error": "Please provide project_id"
            }), 400
        
        # RETRIEVE PROJECT CONTEXT
        # Fetches project stae including ontology from previous phase 
        project = ProjectManager.get_project(project_id)
        if not project:
            return jsonify({
                "success": False,
                "error": f"Project does not exist: {project_id}"
            }), 404
        
        # Kiểm tra trạng thái project
        force = data.get('force', False)  # force rebuild
        
        if project.status == ProjectStatus.CREATED:
            return jsonify({
                "success": False,
                "error": "Ontology has not been generated. Please call /ontology/generate first"
            }), 400
        
        if project.status == ProjectStatus.GRAPH_BUILDING and not force:
            return jsonify({
                "success": False,
                "error": "Graph is currently building. Do not submit again. Use force: true to rebuild",
                "task_id": project.graph_build_task_id
            }), 400
        
        # Nếu force rebuild thì reset trạng thái
        if force and project.status in [ProjectStatus.GRAPH_BUILDING, ProjectStatus.FAILED, ProjectStatus.GRAPH_COMPLETED]:
            project.status = ProjectStatus.ONTOLOGY_GENERATED
            project.graph_id = None
            project.graph_build_task_id = None
            project.error = None
        
        # Lấy cấu hình
        graph_name = data.get('graph_name', project.name or 'MiroFish Graph')
        chunk_size = data.get('chunk_size', project.chunk_size or Config.DEFAULT_CHUNK_SIZE)
        chunk_overlap = data.get('chunk_overlap', project.chunk_overlap or Config.DEFAULT_CHUNK_OVERLAP)
        
        # Cập nhật cấu hình project
        project.chunk_size = chunk_size
        project.chunk_overlap = chunk_overlap
        
        # Lấy text đã extract
        text = ProjectManager.get_extracted_text(project_id)
        if not text:
            return jsonify({
                "success": False,
                "error": "Extracted text not found"
            }), 400
        
        # Lấy ontology
        ontology = project.ontology
        if not ontology:
            return jsonify({
                "success": False,
                "error": "Ontology definition not found"
            }), 400
        
        # Tạo async task
        task_manager = TaskManager()
        task_id = task_manager.create_task(f"Build graph: {graph_name}")
        logger.info(f"Graph build task created: task_id={task_id}, project_id={project_id}")
        
        # Cập nhật trạng thái project
        project.status = ProjectStatus.GRAPH_BUILDING
        project.graph_build_task_id = task_id
        ProjectManager.save_project(project)
        
        # Khởi động background task
        def build_task():
            build_logger = get_logger('mirofish.build')
            try:
                build_logger.info(f"[{task_id}] Start building graph...")
                task_manager.update_task(
                    task_id, 
                    status=TaskStatus.PROCESSING,
                    message="Initializing graph builder service..."
                )
                
                # INITIALIZE GRAPH BUILDER
                # Graphiti (Neo4j) backend — cấu hình lấy lazy qua get_graphiti()
                builder = GraphBuilderService()
                
                # Chunk text
                task_manager.update_task(
                    task_id,
                    message="Splitting text into chunks...",
                    progress=5
                )
                # [3] - Splits document into overlapping chunks for processing
                chunks = TextProcessor.split_text(
                    text, 
                    chunk_size=chunk_size, 
                    overlap=chunk_overlap
                )
                total_chunks = len(chunks)
                
                # Tạo graph
                task_manager.update_task(
                    task_id,
                    message="Creating Zep graph...",
                    progress=10
                )

                # [1] - Initializes empty graph in Zep Cloud with unique ID
                graph_id = builder.create_graph(name=graph_name)
                
                # Cập nhật graph_id của project
                project.graph_id = graph_id
                ProjectManager.save_project(project)
                
                # Thiết lập ontology
                task_manager.update_task(
                    task_id,
                    message="Setting ontology definition...",
                    progress=15
                )
                # [2] - Defines entity and relationship types for the graph
                builder.set_ontology(graph_id, ontology)
                
                # Callback cập nhật progress khi add text
                def add_progress_callback(msg, progress_ratio):
                    progress = 15 + int(progress_ratio * 40)    # 15% - 55%
                    task_manager.update_task(
                        task_id,
                        message=msg,
                        progress=progress
                    )
                
                task_manager.update_task(
                    task_id,
                    message=f"Adding {total_chunks} text chunks...",
                    progress=15
                )
                
                # [4] - Sends text chunks as episodes to Zep for entity extraction
                episode_uuids = builder.add_text_batches(
                    graph_id,
                    chunks,
                    batch_size=8,
                    progress_callback=add_progress_callback
                )
                
                # Chờ Zep xử lý xong
                task_manager.update_task(
                    task_id,
                    message="Waiting for Zep to process data...",
                    progress=55
                )
                
                # Progress callback updates UI
                def wait_progress_callback(msg, progress_ratio):
                    progress = 55 + int(progress_ratio * 35)    # # 55% - 90%
                    task_manager.update_task(
                        task_id,
                        message=msg,
                        progress=progress
                    )
                
                # WAITING FOR PROCESSING - Initiates polling loop for episode completion
                builder._wait_for_episodes(episode_uuids, wait_progress_callback)
                
                # Lấy graph data
                task_manager.update_task(
                    task_id,
                    message="Fetching graph data...",
                    progress=95
                )
                graph_data = builder.get_graph_data(graph_id)
                
                # Update project status
                project.status = ProjectStatus.GRAPH_COMPLETED
                ProjectManager.save_project(project)
                
                node_count = graph_data.get("node_count", 0)
                edge_count = graph_data.get("edge_count", 0)
                build_logger.info(f"[{task_id}] Graph build completed: graph_id={graph_id}, nodes={node_count}, edges={edge_count}")
                
                # Hoàn thành task
                task_manager.update_task(
                    task_id,
                    status=TaskStatus.COMPLETED,
                    message="Graph build completed",
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
                # Cập nhật trạng thái project là failed
                build_logger.error(f"[{task_id}] Graph build failed: {str(e)}")
                build_logger.debug(traceback.format_exc())
                
                project.status = ProjectStatus.FAILED
                project.error = str(e)
                ProjectManager.save_project(project)
                
                task_manager.update_task(
                    task_id,
                    status=TaskStatus.FAILED,
                    message=f"Build failed: {str(e)}",
                    error=traceback.format_exc()
                )
        
        # START ASYNC TASK
        # Lauches background thread for long-running graph construction
        thread = threading.Thread(target=build_task, daemon=True)
        thread.start()
        
        return jsonify({
            "success": True,
            "data": {
                "project_id": project_id,
                "task_id": task_id,
                "message": "Graph build task started. Check progress via /task/{task_id}"
            }
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== Task query APIs ==============

@graph_bp.route('/task/<task_id>', methods=['GET'])
def get_task(task_id: str):
    """
    Truy vấn trạng thái task
    """
    task = TaskManager().get_task(task_id)
    
    if not task:
        return jsonify({
            "success": False,
            "error": f"Task does not exist: {task_id}"
        }), 404
    
    return jsonify({
        "success": True,
        "data": task.to_dict()
    })


@graph_bp.route('/tasks', methods=['GET'])
def list_tasks():
    """
    Liệt kê tất cả tasks
    """
    tasks = TaskManager().list_tasks()
    
    return jsonify({
        "success": True,
        "data": [t.to_dict() for t in tasks],
        "count": len(tasks)
    })


# ============== Graph data APIs ==============

@graph_bp.route('/data/<graph_id>', methods=['GET'])
def get_graph_data(graph_id: str):
    """
    Lấy dữ liệu graph (nodes và edges)
    """
    try:
        if not Config.NEO4J_URI or not Config.NEO4J_PASSWORD:
            return jsonify({
                "success": False,
                "error": "NEO4J_URI / NEO4J_PASSWORD not configured"
            }), 500

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
    Xóa graph (Graphiti + Neo4j)
    """
    try:
        if not Config.NEO4J_URI or not Config.NEO4J_PASSWORD:
            return jsonify({
                "success": False,
                "error": "NEO4J_URI / NEO4J_PASSWORD not configured"
            }), 500

        builder = GraphBuilderService()
        builder.delete_graph(graph_id)
        
        return jsonify({
            "success": True,
            "message": f"Graph deleted: {graph_id}"
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500
