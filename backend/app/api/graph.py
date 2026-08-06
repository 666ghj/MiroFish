"""
图谱相关API路由
采用项目上下文机制，服务端持久化状态
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
from ..services.text_processor import TextProcessor
from ..utils.file_parser import FileParser
from ..utils.logger import get_logger
from ..utils.locale import t, get_locale, set_locale
from ..utils.zep_lifecycle import get_graph_readers, graph_lifecycle_lock
from ..models.task import TaskManager, TaskStatus
from ..models.project import ProjectManager, ProjectStatus
from ..services.simulation_manager import SimulationManager
from ..services.simulation_runner import SimulationRunner, RunnerStatus
from ..services.zep_graph_memory_updater import ZepGraphMemoryManager
from ..utils.llm_client import LLMResponseError

# 获取日志器
logger = get_logger('mirofish.api')
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


def _clear_project_graph_reference(project) -> None:
    project.graph_id = None
    project.graph_build_task_id = None
    project.zep_batch_id = None
    project.zep_batch_operation_id = None
    project.error = None


def _project_build_lock(project_id: str) -> threading.Lock:
    with _build_locks_guard:
        return _build_locks.setdefault(project_id, threading.Lock())


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
    """检查文件扩展名是否允许"""
    if not filename or '.' not in filename:
        return False
    ext = os.path.splitext(filename)[1].lower().lstrip('.')
    return ext in Config.ALLOWED_EXTENSIONS


# ============== 项目管理接口 ==============

@graph_bp.route('/project/<project_id>', methods=['GET'])
def get_project(project_id: str):
    """
    获取项目详情
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
    列出所有项目
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
    删除项目
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
    重置项目状态（用于重新构建图谱）
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

        # 重置到本体已生成状态
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


# ============== 接口1：上传文件并生成本体 ==============

@graph_bp.route('/ontology/generate', methods=['POST'])
def generate_ontology():
    """
    接口1：上传文件，分析生成本体定义
    
    请求方式：multipart/form-data
    
    参数：
        files: 上传的文件（PDF/MD/TXT），可多个
        simulation_requirement: 模拟需求描述（必填）
        project_name: 项目名称（可选）
        additional_context: 额外说明（可选）
        
    返回：
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
        logger.info("=== 开始生成本体定义 ===")
        
        # 获取参数
        simulation_requirement = request.form.get('simulation_requirement', '')
        project_name = request.form.get('project_name', 'Unnamed Project')
        additional_context = request.form.get('additional_context', '')
        
        logger.debug(f"项目名称: {project_name}")
        logger.debug(f"模拟需求: {simulation_requirement[:100]}...")
        
        if not simulation_requirement:
            return jsonify({
                "success": False,
                "error": t('api.requireSimulationRequirement')
            }), 400
        
        # 获取上传的文件
        uploaded_files = request.files.getlist('files')
        if not uploaded_files or all(not f.filename for f in uploaded_files):
            return jsonify({
                "success": False,
                "error": t('api.requireFileUpload')
            }), 400
        
        # 创建项目
        project = ProjectManager.create_project(name=project_name)
        project.simulation_requirement = simulation_requirement
        logger.info(f"创建项目: {project.project_id}")
        
        # 保存文件并提取文本
        document_texts = []
        all_text = ""
        
        for file in uploaded_files:
            if file and file.filename and allowed_file(file.filename):
                # 保存文件到项目目录
                file_info = ProjectManager.save_file_to_project(
                    project.project_id, 
                    file, 
                    file.filename
                )
                project.files.append({
                    "filename": file_info["original_filename"],
                    "size": file_info["size"]
                })
                
                # 提取文本
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
        
        # 保存提取的文本
        project.total_text_length = len(all_text)
        ProjectManager.save_extracted_text(project.project_id, all_text)
        logger.info(f"文本提取完成，共 {len(all_text)} 字符")
        
        # 生成本体
        logger.info("调用 LLM 生成本体定义...")
        generator = OntologyGenerator()
        ontology = generator.generate(
            document_texts=document_texts,
            simulation_requirement=simulation_requirement,
            additional_context=additional_context if additional_context else None
        )
        
        # 保存本体到项目
        entity_count = len(ontology.get("entity_types", []))
        edge_count = len(ontology.get("edge_types", []))
        logger.info(f"本体生成完成: {entity_count} 个实体类型, {edge_count} 个关系类型")
        
        project.ontology = {
            "entity_types": ontology.get("entity_types", []),
            "edge_types": ontology.get("edge_types", [])
        }
        project.analysis_summary = ontology.get("analysis_summary", "")
        project.status = ProjectStatus.ONTOLOGY_GENERATED
        ProjectManager.save_project(project)
        logger.info(f"=== 本体生成完成 === 项目ID: {project.project_id}")
        
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


# ============== 接口2：构建图谱 ==============

@graph_bp.route('/build', methods=['POST'])
def build_graph():
    """Serialize build claims for the same project within this process."""

    data = request.get_json(silent=True) or {}
    project_id = data.get("project_id")
    if not project_id:
        return _build_graph_impl()
    with _project_build_lock(project_id):
        return _build_graph_impl()


def _build_graph_impl():
    """
    接口2：根据project_id构建图谱
    
    请求（JSON）：
        {
            "project_id": "proj_xxxx",  // 必填，来自接口1
            "graph_name": "图谱名称",    // 可选
            "chunk_size": 500,          // 可选，默认500
            "chunk_overlap": 50         // 可选，默认50
        }
        
    返回：
        {
            "success": true,
            "data": {
                "project_id": "proj_xxxx",
                "task_id": "task_xxxx",
                "message": "图谱构建任务已启动"
            }
        }
    """
    try:
        logger.info("=== 开始构建图谱 ===")
        
        # 检查配置
        errors = []
        if not Config.ZEP_API_KEY:
            errors.append(t('api.zepApiKeyMissing'))
        if errors:
            logger.error(f"配置错误: {errors}")
            return jsonify({
                "success": False,
                "error": t('api.configError', details="; ".join(errors))
            }), 500
        
        # 解析请求
        data = request.get_json() or {}
        project_id = data.get('project_id')
        logger.debug(f"请求参数: project_id={project_id}")
        
        if not project_id:
            return jsonify({
                "success": False,
                "error": t('api.requireProjectId')
            }), 400
        
        # 获取项目
        project = ProjectManager.get_project(project_id)
        if not project:
            return jsonify({
                "success": False,
                "error": t('api.projectNotFound', id=project_id)
            }), 404

        # 检查项目状态
        force = data.get('force', False)  # 强制重新构建
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

            if (
                not force
                and project.graph_id
                and project.zep_batch_id
                and project.zep_batch_operation_id
            ):
                builder = GraphBuilderService(api_key=Config.ZEP_API_KEY)
                batch_summary = builder.get_batch_summary(project.zep_batch_id)
                if getattr(batch_summary, "status", None) in {
                    "queued",
                    "processing",
                    "succeeded",
                }:
                    resume_existing_batch = True

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
        
        # 获取配置
        graph_name = data.get('graph_name', project.name or 'MiroFish Graph')
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
        
        # 更新项目配置
        project.chunk_size = chunk_size
        project.chunk_overlap = chunk_overlap
        
        # 获取提取的文本
        text = ProjectManager.get_extracted_text(project_id)
        if not text:
            return jsonify({
                "success": False,
                "error": t('api.textNotFound')
            }), 400
        
        # 获取本体
        ontology = project.ontology
        if not ontology:
            return jsonify({
                "success": False,
                "error": t('api.ontologyNotFound')
            }), 400

        # Only mutate Cloud state after the complete rebuild request validates.
        if project.status == ProjectStatus.FAILED or (
            force and project.status == ProjectStatus.GRAPH_COMPLETED
        ):
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
        
        # 创建异步任务
        task_manager = TaskManager()
        task_id = task_manager.create_task(f"构建图谱: {graph_name}")
        logger.info(f"创建图谱构建任务: task_id={task_id}, project_id={project_id}")
        
        # 更新项目状态
        project.status = ProjectStatus.GRAPH_BUILDING
        project.graph_build_task_id = task_id
        ProjectManager.save_project(project)
        
        # Capture locale before spawning background thread
        current_locale = get_locale()

        # 启动后台任务
        def build_task():
            set_locale(current_locale)
            build_logger = get_logger('mirofish.build')
            try:
                build_logger.info(f"[{task_id}] 开始构建图谱...")
                task_manager.update_task(
                    task_id, 
                    status=TaskStatus.PROCESSING,
                    message=t('progress.initGraphService')
                )
                
                # 创建图谱构建服务
                builder = GraphBuilderService(api_key=Config.ZEP_API_KEY)
                
                # 分块
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
                    # 创建图谱
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

                    # 设置本体
                    task_manager.update_task(
                        task_id,
                        message=t('progress.settingOntology'),
                        progress=15
                    )
                    builder.set_ontology(graph_id, ontology)

                    # 添加文本（progress_callback 签名是 (msg, progress_ratio)）
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
                
                # 等待Zep处理完成（查询每个episode的processed状态）
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
                
                builder._wait_for_batch(submission, wait_progress_callback)
                
                # 获取图谱数据
                task_manager.update_task(
                    task_id,
                    message=t('progress.fetchingGraphData'),
                    progress=95
                )
                graph_data = builder.get_graph_data(graph_id)
                
                node_count = graph_data.get("node_count", 0)
                edge_count = graph_data.get("edge_count", 0)
                build_logger.info(f"[{task_id}] 图谱构建完成: graph_id={graph_id}, 节点={node_count}, 边={edge_count}")

                # Publish local project/task terminal state under the same
                # lifecycle lock used by reset/delete/build claims. This
                # prevents a deletion from interleaving between the two saves.
                with _project_build_lock(project_id):
                    project.status = ProjectStatus.GRAPH_COMPLETED
                    project.error = None
                    ProjectManager.save_project(project)
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
                            "chunk_count": total_chunks,
                            "zep_batch_id": submission.batch_id,
                        }
                    )
                
            except Exception as e:
                # 更新项目状态为失败
                build_logger.error(f"[{task_id}] 图谱构建失败: {str(e)}")
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
        
        # 启动后台线程
        thread = threading.Thread(target=build_task, daemon=True)
        thread.start()
        
        return jsonify({
            "success": True,
            "data": {
                "project_id": project_id,
                "task_id": task_id,
                "resumed": resume_existing_batch,
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


# ============== 任务查询接口 ==============

@graph_bp.route('/task/<task_id>', methods=['GET'])
def get_task(task_id: str):
    """
    查询任务状态
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
    列出所有任务
    """
    tasks = TaskManager().list_tasks()
    
    return jsonify({
        "success": True,
        "data": tasks,
        "count": len(tasks)
    })


# ============== 图谱数据接口 ==============

@graph_bp.route('/data/<graph_id>', methods=['GET'])
def get_graph_data(graph_id: str):
    """
    获取图谱数据（节点和边）
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
    删除Zep图谱
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
            if any(_project_has_active_build(project) for project in projects):
                return jsonify({
                    "success": False,
                    "error": t('api.graphBuilding')
                }), 409

            _delete_cloud_graph_if_present(graph_id)

            for project in projects:
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
