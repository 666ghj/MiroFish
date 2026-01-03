"""
图谱相关API路由
采用项目上下文机制，服务端持久化状态
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
from ..models.task import TaskManager, TaskStatus
from ..models.project import ProjectManager, ProjectStatus

# 获取日志器
logger = get_logger('mirofish.api')


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
            "error": f"项目不存在: {project_id}"
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
    """
    删除项目
    """
    success = ProjectManager.delete_project(project_id)
    
    if not success:
        return jsonify({
            "success": False,
            "error": f"项目不存在或删除失败: {project_id}"
        }), 404
    
    return jsonify({
        "success": True,
        "message": f"项目已删除: {project_id}"
    })


@graph_bp.route('/project/<project_id>/reset', methods=['POST'])
def reset_project(project_id: str):
    """
    重置项目状态（用于重新构建图谱）
    """
    project = ProjectManager.get_project(project_id)
    
    if not project:
        return jsonify({
            "success": False,
            "error": f"项目不存在: {project_id}"
        }), 404
    
    # 重置到本体已生成状态
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
        "message": f"项目已重置: {project_id}",
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
                "error": "请提供模拟需求描述 (simulation_requirement)"
            }), 400
        
        # 获取上传的文件
        uploaded_files = request.files.getlist('files')
        if not uploaded_files or all(not f.filename for f in uploaded_files):
            return jsonify({
                "success": False,
                "error": "请至少上传一个文档文件"
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
                "error": "没有成功处理任何文档，请检查文件格式"
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
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== 接口2：构建图谱 ==============

@graph_bp.route('/build', methods=['POST'])
def build_graph():
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
            errors.append("ZEP_API_KEY未配置")
        if errors:
            logger.error(f"配置错误: {errors}")
            return jsonify({
                "success": False,
                "error": "配置错误: " + "; ".join(errors)
            }), 500
        
        # 解析请求
        data = request.get_json() or {}
        project_id = data.get('project_id')
        logger.debug(f"请求参数: project_id={project_id}")
        
        if not project_id:
            return jsonify({
                "success": False,
                "error": "请提供 project_id"
            }), 400
        
        # 获取项目
        project = ProjectManager.get_project(project_id)
        if not project:
            return jsonify({
                "success": False,
                "error": f"项目不存在: {project_id}"
            }), 404
        
        # 检查项目状态
        force = data.get('force', False)  # 强制重新构建
        
        if project.status == ProjectStatus.CREATED:
            return jsonify({
                "success": False,
                "error": "项目尚未生成本体，请先调用 /ontology/generate"
            }), 400
        
        if project.status == ProjectStatus.GRAPH_BUILDING and not force:
            return jsonify({
                "success": False,
                "error": "图谱正在构建中，请勿重复提交。如需强制重建，请添加 force: true",
                "task_id": project.graph_build_task_id
            }), 400
        
        # 如果强制重建，重置状态
        if force and project.status in [ProjectStatus.GRAPH_BUILDING, ProjectStatus.FAILED, ProjectStatus.GRAPH_COMPLETED]:
            project.status = ProjectStatus.ONTOLOGY_GENERATED
            project.graph_id = None
            project.graph_build_task_id = None
            project.error = None
        
        # 获取配置
        graph_name = data.get('graph_name', project.name or 'MiroFish Graph')
        chunk_size = data.get('chunk_size', project.chunk_size or Config.DEFAULT_CHUNK_SIZE)
        chunk_overlap = data.get('chunk_overlap', project.chunk_overlap or Config.DEFAULT_CHUNK_OVERLAP)
        
        # 更新项目配置
        project.chunk_size = chunk_size
        project.chunk_overlap = chunk_overlap
        
        # 获取提取的文本
        text = ProjectManager.get_extracted_text(project_id)
        if not text:
            return jsonify({
                "success": False,
                "error": "未找到提取的文本内容"
            }), 400
        
        # 获取本体
        ontology = project.ontology
        if not ontology:
            return jsonify({
                "success": False,
                "error": "未找到本体定义"
            }), 400
        
        # 创建异步任务
        task_manager = TaskManager()
        task_id = task_manager.create_task(
            f"构建图谱: {graph_name}",
            metadata={
                "project_id": project_id,
                "graph_name": graph_name,
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
            }
        )
        logger.info(f"创建图谱构建任务: task_id={task_id}, project_id={project_id}")
        
        # 更新项目状态
        project.status = ProjectStatus.GRAPH_BUILDING
        project.graph_build_task_id = task_id
        ProjectManager.save_project(project)
        
        # 启动后台任务
        def build_task():
            build_logger = get_logger('mirofish.build')
            try:
                build_logger.info(f"[{task_id}] 开始构建图谱...")
                task_manager.update_task(
                    task_id, 
                    status=TaskStatus.PROCESSING,
                    message="初始化图谱构建服务..."
                )
                
                # 创建图谱构建服务
                builder = GraphBuilderService(api_key=Config.ZEP_API_KEY)
                
                # 分块
                task_manager.update_task(
                    task_id,
                    message="文本分块中...",
                    progress=5,
                    metadata={"stage": "chunking_text"}
                )
                chunks = TextProcessor.split_text(
                    text, 
                    chunk_size=chunk_size, 
                    overlap=chunk_overlap
                )
                total_chunks = len(chunks)
                task_manager.update_task(
                    task_id,
                    metadata={
                        "total_chunks": total_chunks,
                        "stage": "chunks_ready",
                    }
                )
                
                # 创建图谱
                task_manager.update_task(
                    task_id,
                    message="创建Zep图谱...",
                    progress=10,
                    metadata={"stage": "creating_graph"}
                )
                graph_id = builder.create_graph(name=graph_name)
                
                # 更新项目的graph_id
                project.graph_id = graph_id
                ProjectManager.save_project(project)
                
                # 记录关键断点信息（用于断点续跑/恢复）
                task_manager.update_task(
                    task_id,
                    metadata={
                        "graph_id": graph_id,
                        "stage": "graph_created",
                    }
                )
                
                # 设置本体
                task_manager.update_task(
                    task_id,
                    message="设置本体定义...",
                    progress=15
                )
                builder.set_ontology(graph_id, ontology)
                task_manager.update_task(
                    task_id,
                    metadata={"stage": "ontology_set"}
                )
                
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
                    message=f"开始添加 {total_chunks} 个文本块...",
                    progress=15
                )
                
                # 批次回调：增量持久化 episode_uuids / sent_chunks，支持重启后继续发送剩余 chunks
                def add_batch_callback(sent_chunks, new_episode_uuids, all_episode_uuids):
                    task_manager.update_task(
                        task_id,
                        metadata={
                            "episode_uuids": all_episode_uuids,
                            "sent_chunks": sent_chunks,
                            "total_chunks": total_chunks,
                            "batch_size": 3,
                            "stage": "episodes_sending",
                        }
                    )

                episode_uuids = builder.add_text_batches(
                    graph_id, 
                    chunks,
                    batch_size=3,
                    progress_callback=add_progress_callback,
                    batch_callback=add_batch_callback,
                )
                
                # 保存 episode_uuids 以便重启后继续等待处理（断点续跑）
                task_manager.update_task(
                    task_id,
                    metadata={
                        "episode_uuids": episode_uuids,
                        "total_chunks": total_chunks,
                        "batch_size": 3,
                        "sent_chunks": total_chunks,
                        "stage": "episodes_sent",
                    }
                )
                
                # 等待Zep处理完成（查询每个episode的processed状态）
                task_manager.update_task(
                    task_id,
                    message="等待Zep处理数据...",
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
                task_manager.update_task(
                    task_id,
                    metadata={"stage": "episodes_processed"}
                )
                
                # 获取图谱数据
                task_manager.update_task(
                    task_id,
                    message="获取图谱数据...",
                    progress=95
                )
                graph_data = builder.get_graph_data(graph_id)
                
                # 更新项目状态
                project.status = ProjectStatus.GRAPH_COMPLETED
                ProjectManager.save_project(project)
                
                node_count = graph_data.get("node_count", 0)
                edge_count = graph_data.get("edge_count", 0)
                build_logger.info(f"[{task_id}] 图谱构建完成: graph_id={graph_id}, 节点={node_count}, 边={edge_count}")
                
                # 完成
                task_manager.update_task(
                    task_id,
                    status=TaskStatus.COMPLETED,
                    message="图谱构建完成",
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
                # 更新项目状态为失败
                build_logger.error(f"[{task_id}] 图谱构建失败: {str(e)}")
                build_logger.debug(traceback.format_exc())
                
                project.status = ProjectStatus.FAILED
                project.error = str(e)
                ProjectManager.save_project(project)
                
                task_manager.update_task(
                    task_id,
                    status=TaskStatus.FAILED,
                    message=f"构建失败: {str(e)}",
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
                "message": "图谱构建任务已启动，请通过 /task/{task_id} 查询进度"
            }
        })
        
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
            "error": f"任务不存在: {task_id}"
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
        "data": [t.to_dict() for t in tasks],
        "count": len(tasks)
    })


@graph_bp.route('/build/resume', methods=['POST'])
def resume_graph_build():
    """
    恢复图谱构建（断点续跑）

    适用场景：后端重启/中断后，前端仍持有 task_id 或 project_id，
    希望继续等待 Zep 处理并完成收尾步骤（获取图谱数据、更新项目状态）。

    请求（JSON）：
        {
            "project_id": "proj_xxxx",   // 可选（建议提供）
            "task_id": "uuid"            // 可选（建议提供）
        }
    """
    try:
        data = request.get_json() or {}
        project_id = data.get("project_id")
        task_id = data.get("task_id")

        project = None
        if project_id:
            project = ProjectManager.get_project(project_id)
            if not project:
                return jsonify({"success": False, "error": f"项目不存在: {project_id}"}), 404
            if not task_id:
                task_id = project.graph_build_task_id

        if not task_id:
            return jsonify({"success": False, "error": "请提供 task_id 或 project_id"}), 400

        task_manager = TaskManager()
        task = task_manager.get_task(task_id)
        if not task:
            return jsonify({"success": False, "error": f"任务不存在: {task_id}"}), 404

        # 尝试从任务元数据补齐 project
        if not project and task.metadata.get("project_id"):
            project = ProjectManager.get_project(task.metadata.get("project_id"))

        graph_id = task.metadata.get("graph_id") or (project.graph_id if project else None)
        if not graph_id:
            return jsonify({"success": False, "error": "缺少 graph_id，无法恢复"}), 400

        episode_uuids = task.metadata.get("episode_uuids") or []

        # 已完成则直接返回
        if task.status == TaskStatus.COMPLETED:
            return jsonify({
                "success": True,
                "data": {
                    "project_id": project.project_id if project else project_id,
                    "task_id": task_id,
                    "graph_id": graph_id,
                    "status": "completed",
                    "message": "图谱构建已完成"
                }
            })

        def resume_task():
            build_logger = get_logger("mirofish.build.resume")
            try:
                # 尝试补齐 project / text / ontology（恢复发送剩余 chunks 时需要）
                effective_project = project
                if not effective_project and task.metadata.get("project_id"):
                    effective_project = ProjectManager.get_project(task.metadata.get("project_id"))

                if not effective_project:
                    raise ValueError("缺少项目上下文，无法恢复图谱构建")

                text = ProjectManager.get_extracted_text(effective_project.project_id)
                if not text:
                    raise ValueError("未找到提取的文本内容，无法恢复图谱构建")

                ontology = effective_project.ontology
                if not ontology:
                    raise ValueError("未找到本体定义，无法恢复图谱构建")

                chunk_size = int(
                    task.metadata.get("chunk_size")
                    or effective_project.chunk_size
                    or Config.DEFAULT_CHUNK_SIZE
                )
                chunk_overlap = int(
                    task.metadata.get("chunk_overlap")
                    or effective_project.chunk_overlap
                    or Config.DEFAULT_CHUNK_OVERLAP
                )
                batch_size = int(task.metadata.get("batch_size") or 3)

                chunks = TextProcessor.split_text(text, chunk_size=chunk_size, overlap=chunk_overlap)
                total_chunks = len(chunks)

                # 允许任务中途崩溃：episode_uuids / sent_chunks 持久化后可继续发送剩余 chunks
                episode_uuids = list(task.metadata.get("episode_uuids") or [])
                sent_chunks = int(task.metadata.get("sent_chunks") or len(episode_uuids) or 0)
                sent_chunks = max(0, min(sent_chunks, total_chunks))

                task_manager.update_task(
                    task_id,
                    status=TaskStatus.PROCESSING,
                    message="恢复构建：加载断点信息...",
                    progress=15,
                    metadata={
                        "stage": "resuming",
                        "graph_id": graph_id,
                        "total_chunks": total_chunks,
                        "sent_chunks": sent_chunks,
                        "batch_size": batch_size,
                    }
                )

                builder = GraphBuilderService(api_key=Config.ZEP_API_KEY)

                # 保险起见：重新设置本体（幂等），避免中断发生在 set_ontology 之前
                try:
                    builder.set_ontology(graph_id, ontology)
                    task_manager.update_task(task_id, metadata={"stage": "ontology_set"})
                except Exception as e:
                    build_logger.warning(f"[{task_id}] 恢复时设置本体失败（将继续尝试后续步骤）: {e}")

                # 1) 如果还有未发送的 chunks，则继续发送
                if total_chunks > 0 and sent_chunks < total_chunks:
                    remaining_chunks = chunks[sent_chunks:]

                    def add_progress_callback(msg, progress_ratio):
                        # progress_ratio 基于 remaining_chunks；映射到 전체 15% - 55%
                        overall_ratio = (sent_chunks + (progress_ratio * len(remaining_chunks))) / total_chunks
                        progress = 15 + int(overall_ratio * 40)
                        task_manager.update_task(
                            task_id,
                            message=f"[恢复] {msg}",
                            progress=progress
                        )

                    base_episode_uuids = list(episode_uuids)

                    def add_batch_callback(sent_in_remaining, new_episode_uuids, all_new_episode_uuids):
                        total_sent = sent_chunks + sent_in_remaining
                        combined = base_episode_uuids + list(all_new_episode_uuids)
                        task_manager.update_task(
                            task_id,
                            metadata={
                                "episode_uuids": combined,
                                "sent_chunks": total_sent,
                                "total_chunks": total_chunks,
                                "batch_size": batch_size,
                                "stage": "episodes_sending",
                            }
                        )

                    task_manager.update_task(
                        task_id,
                        message=f"恢复构建：继续发送文本块 ({sent_chunks}/{total_chunks})...",
                        progress=15 + int((sent_chunks / total_chunks) * 40),
                        metadata={"stage": "episodes_sending"}
                    )

                    new_episode_uuids_final = builder.add_text_batches(
                        graph_id,
                        remaining_chunks,
                        batch_size=batch_size,
                        progress_callback=add_progress_callback,
                        batch_callback=add_batch_callback,
                    )

                    episode_uuids = base_episode_uuids + list(new_episode_uuids_final or [])
                    sent_chunks = total_chunks
                    task_manager.update_task(
                        task_id,
                        metadata={
                            "episode_uuids": episode_uuids,
                            "sent_chunks": sent_chunks,
                            "total_chunks": total_chunks,
                            "batch_size": batch_size,
                            "stage": "episodes_sent",
                        }
                    )

                # 2) 如果保存了 episode_uuids，则继续等待处理；否则直接尝试获取图谱数据
                if episode_uuids:
                    task_manager.update_task(
                        task_id,
                        message="恢复构建：等待Zep处理数据...",
                        progress=55,
                        metadata={"stage": "waiting_episodes"}
                    )

                    def wait_progress_callback(msg, progress_ratio):
                        progress = 55 + int(progress_ratio * 35)  # 55% - 90%
                        task_manager.update_task(
                            task_id,
                            message=f"[恢复] {msg}",
                            progress=progress
                        )

                    builder._wait_for_episodes(episode_uuids, wait_progress_callback)
                    task_manager.update_task(task_id, metadata={"stage": "episodes_processed"})

                task_manager.update_task(
                    task_id,
                    message="恢复构建：获取图谱数据...",
                    progress=95,
                    metadata={"stage": "fetching_graph"}
                )

                graph_data = builder.get_graph_data(graph_id)
                node_count = graph_data.get("node_count", 0)
                edge_count = graph_data.get("edge_count", 0)

                effective_project.graph_id = graph_id
                effective_project.status = ProjectStatus.GRAPH_COMPLETED
                effective_project.error = None
                ProjectManager.save_project(effective_project)

                task_manager.update_task(
                    task_id,
                    status=TaskStatus.COMPLETED,
                    message="图谱构建完成（已恢复）",
                    progress=100,
                    result={
                        "project_id": effective_project.project_id,
                        "graph_id": graph_id,
                        "node_count": node_count,
                        "edge_count": edge_count,
                        "chunk_count": total_chunks,
                    },
                    metadata={"stage": "completed"}
                )

                build_logger.info(
                    f"[{task_id}] 图谱恢复完成: graph_id={graph_id}, 节点={node_count}, 边={edge_count}"
                )

            except Exception as e:
                build_logger.error(f"[{task_id}] 图谱恢复失败: {str(e)}")
                build_logger.debug(traceback.format_exc())

                try:
                    if effective_project:
                        effective_project.status = ProjectStatus.FAILED
                        effective_project.error = f"恢复失败: {str(e)}"
                        ProjectManager.save_project(effective_project)
                except Exception:
                    pass

                task_manager.update_task(
                    task_id,
                    status=TaskStatus.FAILED,
                    message=f"恢复失败: {str(e)}",
                    error=traceback.format_exc(),
                    metadata={"stage": "resume_failed"}
                )

        thread = threading.Thread(target=resume_task, daemon=True)
        thread.start()

        return jsonify({
            "success": True,
            "data": {
                "project_id": project.project_id if project else project_id,
                "task_id": task_id,
                "graph_id": graph_id,
                "status": "processing",
                "message": "图谱构建恢复任务已启动"
            }
        })

    except Exception as e:
        logger.error(f"恢复图谱构建失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


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
                "error": "ZEP_API_KEY未配置"
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
                "error": "ZEP_API_KEY未配置"
            }), 500
        
        builder = GraphBuilderService(api_key=Config.ZEP_API_KEY)
        builder.delete_graph(graph_id)
        
        return jsonify({
            "success": True,
            "message": f"图谱已删除: {graph_id}"
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500
