"""
API route liên quan đến mô phỏng.
Step2: Đọc và lọc thực thể Zep, chuẩn bị và chạy mô phỏng OASIS (tự động hoàn toàn).
"""

import os
import traceback
from flask import request, jsonify, send_file

from . import simulation_bp
from ..config import Config
from ..services.zep_entity_reader import ZepEntityReader
from ..services.oasis_profile_generator import OasisProfileGenerator
from ..services.simulation_manager import SimulationManager, SimulationStatus
from ..services.simulation_runner import SimulationRunner, RunnerStatus
from ..utils.logger import get_logger
from ..models.project import ProjectManager

logger = get_logger('mirofish.api.simulation')


# Tiền tố tối ưu cho Interview prompt
# Thêm tiền tố này để tránh Agent gọi công cụ, trả lời trực tiếp bằng văn bản
# INTERVIEW_PROMPT_PREFIX = "Based on your persona, all past memories and actions, reply directly in plain text without calling any tools:"

INTERVIEW_PROMPT_PREFIX = "Dựa trên nhân vật, tất cả ký ức và hành động trong quá khứ của bạn, hãy trả lời trực tiếp bằng văn bản thuần túy mà không gọi bất kỳ công cụ nào:"

def optimize_interview_prompt(prompt: str) -> str:
    """
    Tối ưu câu hỏi Interview, thêm tiền tố để tránh Agent gọi công cụ.
    
    Args:
        prompt: Câu hỏi gốc
        
    Returns:
        Câu hỏi đã tối ưu
    """
    if not prompt:
        return prompt
    # Tránh thêm tiền tố lặp lại
    if prompt.startswith(INTERVIEW_PROMPT_PREFIX):
        return prompt
    return f"{INTERVIEW_PROMPT_PREFIX}{prompt}"


# ============== API đọc thực thể ==============

@simulation_bp.route('/entities/<graph_id>', methods=['GET'])
def get_graph_entities(graph_id: str):
    """
    Lấy toàn bộ thực thể trong đồ thị (đã lọc).
    
    Chỉ trả về các node phù hợp với loại thực thể đã định nghĩa trước.
    (Label không chỉ là node Entity)
    
    Tham số query:
        entity_types: Danh sách loại thực thể phân tách bằng dấu phẩy (tùy chọn, dùng để lọc thêm)
        enrich: Có lấy thông tin cạnh liên quan hay không (mặc định true)
    """
    try:
        if not Config.ZEP_API_KEY:
            return jsonify({
                "success": False,
                "error": "ZEP_API_KEY is not configured"
            }), 500
        
        entity_types_str = request.args.get('entity_types', '')
        entity_types = [t.strip() for t in entity_types_str.split(',') if t.strip()] if entity_types_str else None
        enrich = request.args.get('enrich', 'true').lower() == 'true'
        
        logger.info(f"Fetching graph entities: graph_id={graph_id}, entity_types={entity_types}, enrich={enrich}")
        
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
        logger.error(f"Failed to fetch graph entities: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/entities/<graph_id>/<entity_uuid>', methods=['GET'])
def get_entity_detail(graph_id: str, entity_uuid: str):
    """Lấy thông tin chi tiết của một thực thể."""
    try:
        if not Config.ZEP_API_KEY:
            return jsonify({
                "success": False,
                "error": "ZEP_API_KEY is not configured"
            }), 500
        
        reader = ZepEntityReader()
        entity = reader.get_entity_with_context(graph_id, entity_uuid)
        
        if not entity:
            return jsonify({
                "success": False,
                "error": f"Entity does not exist: {entity_uuid}"
            }), 404
        
        return jsonify({
            "success": True,
            "data": entity.to_dict()
        })
        
    except Exception as e:
        logger.error(f"Failed to fetch entity details: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/entities/<graph_id>/by-type/<entity_type>', methods=['GET'])
def get_entities_by_type(graph_id: str, entity_type: str):
    """Lấy toàn bộ thực thể theo loại chỉ định."""
    try:
        if not Config.ZEP_API_KEY:
            return jsonify({
                "success": False,
                "error": "ZEP_API_KEY is not configured"
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
        logger.error(f"Failed to fetch entities: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== API quản lý mô phỏng ==============

@simulation_bp.route('/create', methods=['POST'])
def create_simulation():
    """
    Tạo mô phỏng mới.
    
    Lưu ý: Các tham số như max_rounds được LLM tạo thông minh, không cần đặt thủ công.
    
    Yêu cầu (JSON):
        {
            "project_id": "proj_xxxx",      // bắt buộc
            "graph_id": "mirofish_xxxx",    // tùy chọn, nếu không cung cấp sẽ lấy từ project
            "enable_twitter": true,          // tùy chọn, mặc định true
            "enable_reddit": true            // tùy chọn, mặc định true
        }
    
    Trả về:
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "project_id": "proj_xxxx",
                "graph_id": "mirofish_xxxx",
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
                "error": "Please provide project_id"
            }), 400
        
        project = ProjectManager.get_project(project_id)
        if not project:
            return jsonify({
                "success": False,
                "error": f"Project does not exist: {project_id}"
            }), 404
        
        graph_id = data.get('graph_id') or project.graph_id
        if not graph_id:
            return jsonify({
                "success": False,
                "error": "Project graph has not been built yet. Please call /api/graph/build first"
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
        logger.error(f"Failed to create simulation: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


def _check_simulation_prepared(simulation_id: str) -> tuple:
    """
    Kiểm tra mô phỏng đã được chuẩn bị xong chưa.
    
    Điều kiện kiểm tra:
    1. `state.json` tồn tại và `status` là "ready"
    2. Các file cần thiết tồn tại: reddit_profiles.json, twitter_profiles.csv, simulation_config.json
    
    Lưu ý: Script chạy (run_*.py) được giữ ở thư mục backend/scripts/ và không còn sao chép vào thư mục mô phỏng.
    
    Args:
        simulation_id: simulation ID
        
    Returns:
        (is_prepared: bool, info: dict)
    """
    import os
    from ..config import Config
    
    simulation_dir = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, simulation_id)
    
    # Kiểm tra thư mục có tồn tại hay không
    if not os.path.exists(simulation_dir):
        return False, {"reason": "Simulation directory does not exist"}
    
    # Danh sách file cần thiết (không bao gồm script, script nằm ở backend/scripts/)
    required_files = [
        "state.json",
        "simulation_config.json",
        "reddit_profiles.json",
        "twitter_profiles.csv"
    ]
    
    # Kiểm tra file có tồn tại hay không
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
            "reason": "Missing required files",
            "missing_files": missing_files,
            "existing_files": existing_files
        }
    
    # Kiểm tra trạng thái trong state.json
    state_file = os.path.join(simulation_dir, "state.json")
    try:
        import json
        with open(state_file, 'r', encoding='utf-8') as f:
            state_data = json.load(f)
        
        status = state_data.get("status", "")
        config_generated = state_data.get("config_generated", False)
        
        # Log chi tiết
        logger.debug(f"Checking simulation readiness: {simulation_id}, status={status}, config_generated={config_generated}")
        
        # Nếu config_generated=True và file tồn tại thì xem như đã chuẩn bị xong
        # Các trạng thái dưới đây đều cho thấy quá trình chuẩn bị đã hoàn tất:
        # - ready: chuẩn bị xong, có thể chạy
        # - preparing: nếu config_generated=True thì xem như đã hoàn tất
        # - running: đang chạy, nghĩa là đã chuẩn bị xong từ trước
        # - completed: đã chạy xong, nghĩa là đã chuẩn bị xong từ trước
        # - stopped: đã dừng, nghĩa là đã chuẩn bị xong từ trước
        # - failed: chạy thất bại (nhưng phần chuẩn bị đã hoàn tất)
        prepared_statuses = ["ready", "preparing", "running", "completed", "stopped", "failed", "paused"]
        
        if status in prepared_statuses and config_generated:
            # Lấy thông tin thống kê file
            profiles_file = os.path.join(simulation_dir, "reddit_profiles.json")
            config_file = os.path.join(simulation_dir, "simulation_config.json")
            
            profiles_count = 0
            if os.path.exists(profiles_file):
                with open(profiles_file, 'r', encoding='utf-8') as f:
                    profiles_data = json.load(f)
                    profiles_count = len(profiles_data) if isinstance(profiles_data, list) else 0
            
            # Nếu trạng thái là preparing nhưng file đã hoàn tất, tự động cập nhật thành ready
            if status == "preparing":
                try:
                    state_data["status"] = "ready"
                    from datetime import datetime
                    state_data["updated_at"] = datetime.now().isoformat()
                    with open(state_file, 'w', encoding='utf-8') as f:
                        json.dump(state_data, f, ensure_ascii=False, indent=2)
                        logger.info(f"Auto-updated simulation status: {simulation_id} preparing -> ready")
                    status = "ready"
                except Exception as e:
                    logger.warning(f"Failed to auto-update status: {e}")
            
            logger.info(f"Simulation {simulation_id} check result: prepared (status={status}, config_generated={config_generated})")
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
            logger.warning(f"Simulation {simulation_id} check result: not prepared (status={status}, config_generated={config_generated})")
            return False, {
                "reason": f"Status is not in prepared list or config_generated is false: status={status}, config_generated={config_generated}",
                "status": status,
                "config_generated": config_generated
            }
            
    except Exception as e:
        return False, {"reason": f"Failed to read state file: {str(e)}"}


@simulation_bp.route('/prepare', methods=['POST'])
def prepare_simulation():
    """
    Chuẩn bị môi trường mô phỏng (tác vụ bất đồng bộ, LLM tạo toàn bộ tham số).
    
    Đây là thao tác tốn thời gian, API sẽ trả về task_id ngay lập tức.
    Dùng GET /api/simulation/prepare/status để kiểm tra tiến độ.
    
    Đặc điểm:
    - Tự động phát hiện phần chuẩn bị đã hoàn tất để tránh sinh lại.
    - Nếu đã chuẩn bị xong thì trả về kết quả sẵn có.
    - Hỗ trợ buộc sinh lại (force_regenerate=true).
    
    Các bước:
    1. Kiểm tra xem đã có phần chuẩn bị hoàn tất hay chưa.
    2. Đọc và lọc thực thể từ đồ thị Zep.
    3. Sinh OASIS Agent Profile cho từng thực thể (có cơ chế retry).
    4. LLM sinh cấu hình mô phỏng một cách thông minh (có cơ chế retry).
    5. Lưu file cấu hình và script thiết lập sẵn.
    
    Yêu cầu (JSON):
        {
            "simulation_id": "sim_xxxx",                   // bắt buộc, simulation ID
            "entity_types": ["Student", "PublicFigure"],  // tùy chọn, chỉ định loại thực thể
            "use_llm_for_profiles": true,                 // tùy chọn, có dùng LLM để sinh persona hay không
            "parallel_profile_count": 5,                  // tùy chọn, số lượng sinh persona song song, mặc định 5
            "force_regenerate": false                     // tùy chọn, buộc sinh lại, mặc định false
        }
    
    Trả về:
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "task_id": "task_xxxx",           // trả về khi là tác vụ mới
                "status": "preparing|ready",
                "message": "Preparation task has started|Preparation already exists",
                "already_prepared": true|false    // đã chuẩn bị xong hay chưa
            }
        }
    """
    import threading
    import os
    from ..models.task import TaskManager, TaskStatus
    from ..config import Config
    
    try:
        data = request.get_json() or {}
        
        simulation_id = data.get('simulation_id')
        if not simulation_id:
            return jsonify({
                "success": False,
                "error": "Please provide simulation_id"
            }), 400
        
        manager = SimulationManager()
        state = manager.get_simulation(simulation_id)
        
        if not state:
            return jsonify({
                "success": False,
                "error": f"Simulation does not exist: {simulation_id}"
            }), 404
        
        # Kiểm tra có buộc sinh lại hay không
        force_regenerate = data.get('force_regenerate', False)
        logger.info(f"Start handling /prepare request: simulation_id={simulation_id}, force_regenerate={force_regenerate}")
        
        # Kiểm tra đã chuẩn bị xong hay chưa (tránh sinh lại)
        if not force_regenerate:
            logger.debug(f"Checking whether simulation {simulation_id} is already prepared...")
            is_prepared, prepare_info = _check_simulation_prepared(simulation_id)
            logger.debug(f"Check result: is_prepared={is_prepared}, prepare_info={prepare_info}")
            if is_prepared:
                logger.info(f"Simulation {simulation_id} is already prepared, skipping regeneration")
                return jsonify({
                    "success": True,
                    "data": {
                        "simulation_id": simulation_id,
                        "status": "ready",
                        "message": "Preparation already exists, no regeneration needed",
                        "already_prepared": True,
                        "prepare_info": prepare_info
                    }
                })
            else:
                logger.info(f"Simulation {simulation_id} is not prepared, will start preparation task")
        
        # Lấy thông tin cần thiết từ dự án
        project = ProjectManager.get_project(state.project_id)
        if not project:
            return jsonify({
                "success": False,
                "error": f"Project does not exist: {state.project_id}"
            }), 404
        
        # Lấy yêu cầu mô phỏng
        simulation_requirement = project.simulation_requirement or ""
        if not simulation_requirement:
            return jsonify({
                "success": False,
                "error": "Project is missing simulation requirement description (simulation_requirement)"
            }), 400
        
        # Lấy văn bản tài liệu
        document_text = ProjectManager.get_extracted_text(state.project_id) or ""
        
        entity_types_list = data.get('entity_types')
        use_llm_for_profiles = data.get('use_llm_for_profiles', True)
        parallel_profile_count = data.get('parallel_profile_count', 20)
        
        # ========== Đồng bộ lấy số lượng thực thể (trước khi chạy tác vụ nền) ==========
        # Nhờ đó frontend có thể lấy ngay tổng số Agent dự kiến sau khi gọi prepare
        try:
            logger.info(f"Synchronously fetching entity count: graph_id={state.graph_id}")
            reader = ZepEntityReader()
            # Đọc nhanh thực thể (không cần thông tin cạnh, chỉ đếm số lượng)
            filtered_preview = reader.filter_defined_entities(
                graph_id=state.graph_id,
                defined_entity_types=entity_types_list,
                enrich_with_edges=False  # Do not fetch edge info to speed up
            )
            # Lưu số lượng thực thể vào trạng thái (để frontend lấy ngay)
            state.entities_count = filtered_preview.filtered_count
            state.entity_types = list(filtered_preview.entity_types)
            logger.info(f"Expected entity count: {filtered_preview.filtered_count}, types: {filtered_preview.entity_types}")
        except Exception as e:
            logger.warning(f"Failed to synchronously fetch entity count (will retry in background task): {e}")
            # Lỗi này không ảnh hưởng luồng tiếp theo, tác vụ nền sẽ lấy lại
        
        # Tạo tác vụ bất đồng bộ
        task_manager = TaskManager()
        task_id = task_manager.create_task(
            task_type="simulation_prepare",
            metadata={
                "simulation_id": simulation_id,
                "project_id": state.project_id
            }
        )
        
        # Cập nhật trạng thái mô phỏng (bao gồm số lượng thực thể đã lấy trước)
        state.status = SimulationStatus.PREPARING
        manager._save_simulation_state(state)
        
        # Định nghĩa tác vụ nền
        def run_prepare():
            try:
                task_manager.update_task(
                    task_id,
                    status=TaskStatus.PROCESSING,
                    progress=0,
                    message="Start preparing simulation environment..."
                )
                
                # Chuẩn bị mô phỏng (có callback tiến độ)
                # Lưu chi tiết tiến độ theo giai đoạn
                stage_details = {}
                
                def progress_callback(stage, progress, message, **kwargs):
                    # Tính tổng tiến độ
                    stage_weights = {
                        "reading": (0, 20),           # 0-20%
                        "generating_profiles": (20, 70),  # 20-70%
                        "generating_config": (70, 90),    # 70-90%
                        "copying_scripts": (90, 100)       # 90-100%
                    }
                    
                    start, end = stage_weights.get(stage, (0, 100))
                    current_progress = int(start + (end - start) * progress / 100)
                    
                    # Tạo thông tin tiến độ chi tiết
                    stage_names = {
                        "reading": "Reading graph entities",
                        "generating_profiles": "Generating agent personas",
                        "generating_config": "Generating simulation config",
                        "copying_scripts": "Preparing simulation scripts"
                    }
                    
                    stage_index = list(stage_weights.keys()).index(stage) + 1 if stage in stage_weights else 1
                    total_stages = len(stage_weights)
                    
                    # Cập nhật chi tiết giai đoạn
                    stage_details[stage] = {
                        "stage_name": stage_names.get(stage, stage),
                        "stage_progress": progress,
                        "current": kwargs.get("current", 0),
                        "total": kwargs.get("total", 0),
                        "item_name": kwargs.get("item_name", "")
                    }
                    
                    # Tạo thông tin tiến độ chi tiết
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
                    
                    # Tạo thông báo ngắn gọn
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
                
                # Task completed
                task_manager.complete_task(
                    task_id,
                    result=result_state.to_simple_dict()
                )
                
            except Exception as e:
                logger.error(f"Failed to prepare simulation: {str(e)}")
                task_manager.fail_task(task_id, str(e))
                
                # Cập nhật trạng thái mô phỏng thành failed
                state = manager.get_simulation(simulation_id)
                if state:
                    state.status = SimulationStatus.FAILED
                    state.error = str(e)
                    manager._save_simulation_state(state)
        
        # Khởi chạy luồng nền
        thread = threading.Thread(target=run_prepare, daemon=True)
        thread.start()
        
        return jsonify({
            "success": True,
            "data": {
                "simulation_id": simulation_id,
                "task_id": task_id,
                "status": "preparing",
                "message": "Preparation task has started. Please check progress via /api/simulation/prepare/status",
                "already_prepared": False,
                "expected_entities_count": state.entities_count,  # Expected total Agent count
                "entity_types": state.entity_types  # Entity type list
            }
        })
        
    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 404
        
    except Exception as e:
        logger.error(f"Failed to start preparation task: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/prepare/status', methods=['POST'])
def get_prepare_status():
    """
    Query preparation task progress.
    
    Supports two query modes:
    1. Query ongoing task progress by task_id.
    2. Check whether completed preparation already exists by simulation_id.
    
    Yêu cầu (JSON):
        {
            "task_id": "task_xxxx",          // tùy chọn, task_id trả về từ prepare
            "simulation_id": "sim_xxxx"      // tùy chọn, simulation ID (để kiểm tra phần chuẩn bị đã hoàn tất)
        }
    
    Trả về:
        {
            "success": true,
            "data": {
                "task_id": "task_xxxx",
                "status": "processing|completed|ready",
                "progress": 45,
                "message": "...",
                "already_prepared": true|false,  // đã có phần chuẩn bị hoàn tất hay chưa
                "prepare_info": {...}            // thông tin chi tiết khi đã chuẩn bị hoàn tất
            }
        }
    """
    from ..models.task import TaskManager
    
    try:
        data = request.get_json() or {}
        
        task_id = data.get('task_id')
        simulation_id = data.get('simulation_id')
        
        # Nếu có simulation_id, kiểm tra trước xem đã chuẩn bị hoàn tất chưa
        if simulation_id:
            is_prepared, prepare_info = _check_simulation_prepared(simulation_id)
            if is_prepared:
                return jsonify({
                    "success": True,
                    "data": {
                        "simulation_id": simulation_id,
                        "status": "ready",
                        "progress": 100,
                        "message": "Preparation already completed",
                        "already_prepared": True,
                        "prepare_info": prepare_info
                    }
                })
        
        # Nếu không có task_id thì trả về lỗi
        if not task_id:
            if simulation_id:
                # Có simulation_id nhưng chưa chuẩn bị xong
                return jsonify({
                    "success": True,
                    "data": {
                        "simulation_id": simulation_id,
                        "status": "not_started",
                        "progress": 0,
                        "message": "Preparation has not started yet. Please call /api/simulation/prepare to start",
                        "already_prepared": False
                    }
                })
            return jsonify({
                "success": False,
                "error": "Please provide task_id or simulation_id"
            }), 400
        
        task_manager = TaskManager()
        task = task_manager.get_task(task_id)
        
        if not task:
            # Task không tồn tại, nhưng nếu có simulation_id thì kiểm tra đã chuẩn bị xong chưa
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
                            "message": "Task completed (preparation already exists)",
                            "already_prepared": True,
                            "prepare_info": prepare_info
                        }
                    })
            
            return jsonify({
                "success": False,
                "error": f"Task does not exist: {task_id}"
            }), 404
        
        task_dict = task.to_dict()
        task_dict["already_prepared"] = False
        
        return jsonify({
            "success": True,
            "data": task_dict
        })
        
    except Exception as e:
        logger.error(f"Failed to query task status: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@simulation_bp.route('/<simulation_id>', methods=['GET'])
def get_simulation(simulation_id: str):
    """Lấy trạng thái mô phỏng."""
    try:
        manager = SimulationManager()
        state = manager.get_simulation(simulation_id)
        
        if not state:
            return jsonify({
                "success": False,
                "error": f"Simulation does not exist: {simulation_id}"
            }), 404
        
        result = state.to_dict()
        
        # Nếu mô phỏng đã sẵn sàng, đính kèm hướng dẫn chạy
        if state.status == SimulationStatus.READY:
            result["run_instructions"] = manager.get_run_instructions(simulation_id)
        
        return jsonify({
            "success": True,
            "data": result
        })
        
    except Exception as e:
        logger.error(f"Failed to get simulation status: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/list', methods=['GET'])
def list_simulations():
    """
    Liệt kê toàn bộ mô phỏng.
    
    Tham số query:
        project_id: Lọc theo project ID (tùy chọn)
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
        logger.error(f"Failed to list simulations: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


def _get_report_id_for_simulation(simulation_id: str) -> str:
    """
    Lấy report_id mới nhất tương ứng với simulation.
    
    Duyệt thư mục reports để tìm report khớp simulation_id.
    Nếu có nhiều report thì trả về report mới nhất (sắp xếp theo created_at).
    
    Args:
        simulation_id: simulation ID
        
    Returns:
        report_id hoặc None
    """
    import json
    from datetime import datetime
    
    # Đường dẫn thư mục reports: backend/uploads/reports
    # __file__ là app/api/simulation.py, cần đi lên hai cấp để tới backend/
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
        
        # Sắp xếp giảm dần theo thời gian tạo và trả về bản mới nhất
        matching_reports.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return matching_reports[0].get("report_id")
        
    except Exception as e:
        logger.warning(f"Failed to find report for simulation {simulation_id}: {e}")
        return None


@simulation_bp.route('/history', methods=['GET'])
def get_simulation_history():
    """
    Lấy danh sách lịch sử mô phỏng (kèm chi tiết dự án).
    
    Dùng cho hiển thị lịch sử dự án ở trang chủ, trả về danh sách mô phỏng với thông tin đầy đủ như tên dự án, mô tả.
    
    Tham số query:
        limit: Giới hạn số lượng trả về (mặc định 20)
    
    Trả về:
        {
            "success": true,
            "data": [
                {
                    "simulation_id": "sim_xxxx",
                    "project_id": "proj_xxxx",
                    "project_name": "Phân tích dư luận WU",
                    "simulation_requirement": "Nếu Đại học Vũ Hán đăng tải...",
                    "status": "completed",
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
        
        manager = SimulationManager()
        simulations = manager.list_simulations()[:limit]
        
        # Bổ sung dữ liệu mô phỏng, chỉ đọc từ file Simulation
        enriched_simulations = []
        for sim in simulations:
            sim_dict = sim.to_dict()
            
            # Lấy thông tin cấu hình mô phỏng (đọc simulation_requirement từ simulation_config.json)
            config = manager.get_simulation_config(sim.simulation_id)
            if config:
                sim_dict["simulation_requirement"] = config.get("simulation_requirement", "")
                time_config = config.get("time_config", {})
                sim_dict["total_simulation_hours"] = time_config.get("total_simulation_hours", 0)
                # Số vòng khuyến nghị (giá trị dự phòng)
                recommended_rounds = int(
                    time_config.get("total_simulation_hours", 0) * 60 / 
                    max(time_config.get("minutes_per_round", 60), 1)
                )
            else:
                sim_dict["simulation_requirement"] = ""
                sim_dict["total_simulation_hours"] = 0
                recommended_rounds = 0
            
            # Lấy trạng thái chạy (đọc số vòng thực tế do người dùng thiết lập từ run_state.json)
            run_state = SimulationRunner.get_run_state(sim.simulation_id)
            if run_state:
                sim_dict["current_round"] = run_state.current_round
                sim_dict["runner_status"] = run_state.runner_status.value
                # Dùng total_rounds do người dùng thiết lập, nếu không có thì dùng số vòng khuyến nghị
                sim_dict["total_rounds"] = run_state.total_rounds if run_state.total_rounds > 0 else recommended_rounds
            else:
                sim_dict["current_round"] = 0
                sim_dict["runner_status"] = "idle"
                sim_dict["total_rounds"] = recommended_rounds
            
            # Lấy danh sách file của dự án liên kết (tối đa 3 file)
            project = ProjectManager.get_project(sim.project_id)
            if project and hasattr(project, 'files') and project.files:
                sim_dict["files"] = [
                    {"filename": f.get("filename", "Unknown file")} 
                    for f in project.files[:3]
                ]
            else:
                sim_dict["files"] = []
            
            # Lấy report_id liên kết (tìm report mới nhất của simulation này)
            sim_dict["report_id"] = _get_report_id_for_simulation(sim.simulation_id)
            
            # Thêm số phiên bản
            sim_dict["version"] = "v1.0.2"
            
            # Định dạng ngày
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
        logger.error(f"Failed to get simulation history: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/profiles', methods=['GET'])
def get_simulation_profiles(simulation_id: str):
    """
    Lấy Agent Profile của mô phỏng.
    
    Tham số query:
        platform: Loại nền tảng (reddit/twitter, mặc định reddit)
    """
    try:
        platform = request.args.get('platform', 'reddit')
        
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
        logger.error(f"Failed to get profile: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/profiles/realtime', methods=['GET'])
def get_simulation_profiles_realtime(simulation_id: str):
    """
    Lấy Agent Profile theo thời gian thực (dùng để theo dõi tiến độ trong quá trình sinh).
    
    Khác biệt so với endpoint /profiles:
    - Đọc trực tiếp từ file, không đi qua SimulationManager.
    - Phù hợp cho việc xem realtime trong quá trình sinh.
    - Trả về thêm metadata (như thời điểm sửa file, có đang sinh hay không).
    
    Tham số query:
        platform: Loại nền tảng (reddit/twitter, mặc định reddit)
    
    Trả về:
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "platform": "reddit",
                "count": 15,
                "total_expected": 93,  // tổng số dự kiến (nếu có)
                "is_generating": true,  // có đang sinh hay không
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
        platform = request.args.get('platform', 'reddit')
        
        # Lấy thư mục mô phỏng
        sim_dir = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, simulation_id)
        
        if not os.path.exists(sim_dir):
            return jsonify({
                "success": False,
                "error": f"Simulation does not exist: {simulation_id}"
            }), 404
        
        # Xác định đường dẫn file
        if platform == "reddit":
            profiles_file = os.path.join(sim_dir, "reddit_profiles.json")
        else:
            profiles_file = os.path.join(sim_dir, "twitter_profiles.csv")
        
        # Kiểm tra file có tồn tại hay không
        file_exists = os.path.exists(profiles_file)
        profiles = []
        file_modified_at = None
        
        if file_exists:
            # Lấy thời gian sửa file
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
                logger.warning(f"Failed to read profiles file (it may still be being written): {e}")
                profiles = []
        
            # Kiểm tra có đang sinh hay không (dựa vào state.json)
        is_generating = False
        total_expected = None
        
        state_file = os.path.join(sim_dir, "state.json")
        if os.path.exists(state_file):
            try:
                with open(state_file, 'r', encoding='utf-8') as f:
                    state_data = json.load(f)
                    status = state_data.get("status", "")
                    is_generating = status == "preparing"
                    total_expected = state_data.get("entities_count")
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
                "file_exists": file_exists,
                "file_modified_at": file_modified_at,
                "profiles": profiles
            }
        })
        
    except Exception as e:
        logger.error(f"Failed to get profile in real time: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/config/realtime', methods=['GET'])
def get_simulation_config_realtime(simulation_id: str):
    """
    Lấy cấu hình mô phỏng theo thời gian thực (dùng để theo dõi tiến độ trong quá trình sinh).
    
    Khác biệt so với endpoint /config:
    - Đọc trực tiếp từ file, không đi qua SimulationManager.
    - Phù hợp cho việc xem realtime trong quá trình sinh.
    - Trả về thêm metadata (như thời điểm sửa file, có đang sinh hay không).
    - Ngay cả khi cấu hình chưa sinh xong vẫn có thể trả về thông tin một phần.
    
    Trả về:
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "file_exists": true,
                "file_modified_at": "2025-12-04T18:20:00",
                "is_generating": true,  // có đang sinh hay không
                "generation_stage": "generating_config",  // giai đoạn sinh hiện tại
                "config": {...}  // nội dung cấu hình (nếu có)
            }
        }
    """
    import json
    from datetime import datetime
    
    try:
        # Lấy thư mục mô phỏng
        sim_dir = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, simulation_id)
        
        if not os.path.exists(sim_dir):
            return jsonify({
                "success": False,
                "error": f"Simulation does not exist: {simulation_id}"
            }), 404
        
        # Đường dẫn file cấu hình
        config_file = os.path.join(sim_dir, "simulation_config.json")
        
        # Kiểm tra file có tồn tại hay không
        file_exists = os.path.exists(config_file)
        config = None
        file_modified_at = None
        
        if file_exists:
            # Lấy thời gian sửa file
            file_stat = os.stat(config_file)
            file_modified_at = datetime.fromtimestamp(file_stat.st_mtime).isoformat()
            
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"Failed to read config file (it may still be being written): {e}")
                config = None
        
            # Kiểm tra có đang sinh hay không (dựa vào state.json)
        is_generating = False
        generation_stage = None
        config_generated = False
        
        state_file = os.path.join(sim_dir, "state.json")
        if os.path.exists(state_file):
            try:
                with open(state_file, 'r', encoding='utf-8') as f:
                    state_data = json.load(f)
                    status = state_data.get("status", "")
                    is_generating = status == "preparing"
                    config_generated = state_data.get("config_generated", False)
                    
                    # Xác định giai đoạn hiện tại
                    if is_generating:
                        if state_data.get("profiles_generated", False):
                            generation_stage = "generating_config"
                        else:
                            generation_stage = "generating_profiles"
                    elif status == "ready":
                        generation_stage = "completed"
            except Exception:
                pass
        
        # Tạo dữ liệu trả về
        response_data = {
            "simulation_id": simulation_id,
            "file_exists": file_exists,
            "file_modified_at": file_modified_at,
            "is_generating": is_generating,
            "generation_stage": generation_stage,
            "config_generated": config_generated,
            "config": config
        }
        
        # Nếu cấu hình tồn tại, trích xuất một số thống kê quan trọng
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
        logger.error(f"Failed to get config in real time: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/config', methods=['GET'])
def get_simulation_config(simulation_id: str):
    """
    Lấy cấu hình mô phỏng (cấu hình đầy đủ do LLM sinh).
    
    Bao gồm:
        - time_config: Cấu hình thời gian (thời lượng mô phỏng, số vòng, khung giờ cao điểm/thấp điểm)
        - agent_configs: Cấu hình hoạt động của từng Agent (mức độ hoạt động, tần suất phát biểu, lập trường...)
        - event_config: Cấu hình sự kiện (bài đăng khởi tạo, chủ đề nóng)
        - platform_configs: Cấu hình nền tảng
        - generation_reasoning: Giải thích suy luận cấu hình của LLM
    """
    try:
        manager = SimulationManager()
        config = manager.get_simulation_config(simulation_id)
        
        if not config:
            return jsonify({
                "success": False,
                "error": "Simulation config does not exist. Please call /prepare first"
            }), 404
        
        return jsonify({
            "success": True,
            "data": config
        })
        
    except Exception as e:
        logger.error(f"Failed to get config: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/config/download', methods=['GET'])
def download_simulation_config(simulation_id: str):
    """Tải file cấu hình mô phỏng."""
    try:
        manager = SimulationManager()
        sim_dir = manager._get_simulation_dir(simulation_id)
        config_path = os.path.join(sim_dir, "simulation_config.json")
        
        if not os.path.exists(config_path):
            return jsonify({
                "success": False,
                "error": "Config file does not exist. Please call /prepare first"
            }), 404
        
        return send_file(
            config_path,
            as_attachment=True,
            download_name="simulation_config.json"
        )
        
    except Exception as e:
        logger.error(f"Failed to download config: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/script/<script_name>/download', methods=['GET'])
def download_simulation_script(script_name: str):
    """
    Tải file script chạy mô phỏng (script dùng chung, nằm trong backend/scripts/).
    
    script_name có thể là:
        - run_twitter_simulation.py
        - run_reddit_simulation.py
        - run_parallel_simulation.py
        - action_logger.py
    """
    try:
        # Script nằm trong thư mục backend/scripts/
        scripts_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../scripts'))
        
        # Kiểm tra tên script
        allowed_scripts = [
            "run_twitter_simulation.py",
            "run_reddit_simulation.py", 
            "run_parallel_simulation.py",
            "action_logger.py"
        ]
        
        if script_name not in allowed_scripts:
            return jsonify({
                "success": False,
                "error": f"Unknown script: {script_name}. Allowed: {allowed_scripts}"
            }), 400
        
        script_path = os.path.join(scripts_dir, script_name)
        
        if not os.path.exists(script_path):
            return jsonify({
                "success": False,
                "error": f"Script file does not exist: {script_name}"
            }), 404
        
        return send_file(
            script_path,
            as_attachment=True,
            download_name=script_name
        )
        
    except Exception as e:
        logger.error(f"Failed to download script: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== API sinh Profile (dùng độc lập) ==============

@simulation_bp.route('/generate-profiles', methods=['POST'])
def generate_profiles():
    """
    Sinh trực tiếp OASIS Agent Profile từ đồ thị (không tạo mô phỏng).
    
    Yêu cầu (JSON):
        {
            "graph_id": "mirofish_xxxx",     // bắt buộc
            "entity_types": ["Student"],      // tùy chọn
            "use_llm": true,                  // tùy chọn
            "platform": "reddit"              // tùy chọn
        }
    """
    try:
        data = request.get_json() or {}
        
        graph_id = data.get('graph_id')
        if not graph_id:
            return jsonify({
                "success": False,
                "error": "Please provide graph_id"
            }), 400
        
        entity_types = data.get('entity_types')
        use_llm = data.get('use_llm', True)
        platform = data.get('platform', 'reddit')
        project_id = data.get('project_id')
        
        reader = ZepEntityReader()
        filtered = reader.filter_defined_entities(
            graph_id=graph_id,
            defined_entity_types=entity_types,
            enrich_with_edges=True
        )
        
        if filtered.filtered_count == 0:
            return jsonify({
                "success": False,
                "error": "No matching entities found"
            }), 400
        
        generator = OasisProfileGenerator()
        profiles = generator.generate_profiles_from_entities(
            entities=filtered.entities,
            use_llm=use_llm,
            project_id=project_id,
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
        logger.error(f"Failed to generate profile: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== API điều khiển chạy mô phỏng ==============

@simulation_bp.route('/start', methods=['POST'])
def start_simulation():
    """
    Bắt đầu chạy mô phỏng.

    Yêu cầu (JSON):
        {
            "simulation_id": "sim_xxxx",          // bắt buộc, simulation ID
            "platform": "parallel",                // tùy chọn: twitter / reddit / parallel (mặc định)
            "max_rounds": 100,                     // tùy chọn: số vòng mô phỏng tối đa, dùng để cắt bớt mô phỏng quá dài
            "enable_graph_memory_update": false,   // tùy chọn: có cập nhật động hoạt động Agent vào bộ nhớ đồ thị Zep hay không
            "force": false                         // tùy chọn: buộc chạy lại (sẽ dừng mô phỏng đang chạy và dọn log)
        }

    Về tham số force:
        - Khi bật, nếu mô phỏng đang chạy hoặc đã hoàn tất thì sẽ dừng trước và dọn log chạy.
        - Nội dung dọn bao gồm: run_state.json, actions.jsonl, simulation.log...
        - Không dọn file cấu hình (simulation_config.json) và file profile.
        - Phù hợp cho tình huống cần chạy lại mô phỏng.

    Về enable_graph_memory_update:
        - Khi bật, toàn bộ hoạt động của Agent trong mô phỏng (đăng bài, bình luận, thả like...) sẽ được cập nhật realtime vào đồ thị Zep.
        - Điều này giúp đồ thị "ghi nhớ" quá trình mô phỏng để phục vụ phân tích hoặc hội thoại AI về sau.
        - Dự án liên kết với mô phỏng cần có graph_id hợp lệ.
        - Dùng cơ chế cập nhật theo lô để giảm số lần gọi API.

    Trả về:
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "runner_status": "running",
                "process_pid": 12345,
                "twitter_running": true,
                "reddit_running": true,
                "started_at": "2025-12-01T10:00:00",
                "graph_memory_update_enabled": true,  // có bật cập nhật bộ nhớ đồ thị hay không
                "force_restarted": true               // có phải là chạy lại bắt buộc hay không
            }
        }
    """
    try:
        data = request.get_json() or {}

        simulation_id = data.get('simulation_id')
        if not simulation_id:
            return jsonify({
                "success": False,
                "error": "Please provide simulation_id"
            }), 400

        platform = data.get('platform', 'parallel')
        max_rounds = data.get('max_rounds')  # Tùy chọn: số vòng mô phỏng tối đa
        enable_graph_memory_update = data.get('enable_graph_memory_update', False)  # Tùy chọn: có bật cập nhật bộ nhớ đồ thị hay không
        force = data.get('force', False)  # Tùy chọn: buộc chạy lại

        # Kiểm tra tham số max_rounds
        if max_rounds is not None:
            try:
                max_rounds = int(max_rounds)
                if max_rounds <= 0:
                    return jsonify({
                        "success": False,
                        "error": "max_rounds must be a positive integer"
                    }), 400
            except (ValueError, TypeError):
                return jsonify({
                    "success": False,
                    "error": "max_rounds must be a valid integer"
                }), 400

        if platform not in ['twitter', 'reddit', 'parallel']:
            return jsonify({
                "success": False,
                "error": f"Invalid platform type: {platform}. Allowed: twitter/reddit/parallel"
            }), 400

        # Kiểm tra mô phỏng đã sẵn sàng hay chưa
        manager = SimulationManager()
        state = manager.get_simulation(simulation_id)

        if not state:
            return jsonify({
                "success": False,
                "error": f"Simulation does not exist: {simulation_id}"
            }), 404

        force_restarted = False
        
        # Xử lý trạng thái thông minh: nếu chuẩn bị đã hoàn tất thì cho phép khởi động lại
        if state.status != SimulationStatus.READY:
            # Kiểm tra phần chuẩn bị đã hoàn tất chưa
            is_prepared, prepare_info = _check_simulation_prepared(simulation_id)

            if is_prepared:
                # Chuẩn bị đã hoàn tất, kiểm tra có tiến trình đang chạy hay không
                if state.status == SimulationStatus.RUNNING:
                    # Kiểm tra tiến trình mô phỏng có thực sự đang chạy không
                    run_state = SimulationRunner.get_run_state(simulation_id)
                    if run_state and run_state.runner_status.value == "running":
                        # Tiến trình thực sự đang chạy
                        if force:
                            # Chế độ force: dừng mô phỏng đang chạy
                            logger.info(f"Force mode: stopping running simulation {simulation_id}")
                            try:
                                SimulationRunner.stop_simulation(simulation_id)
                            except Exception as e:
                                logger.warning(f"Warning while stopping simulation: {str(e)}")
                        else:
                            return jsonify({
                                "success": False,
                                "error": "Simulation is running. Please call /stop first, or use force=true to restart"
                            }), 400

                # Nếu là chế độ force thì dọn log chạy
                if force:
                    logger.info(f"Force mode: cleaning simulation logs {simulation_id}")
                    cleanup_result = SimulationRunner.cleanup_simulation_logs(simulation_id)
                    if not cleanup_result.get("success"):
                        logger.warning(f"Warning while cleaning logs: {cleanup_result.get('errors')}")
                    force_restarted = True

                # Tiến trình không tồn tại hoặc đã kết thúc, đặt lại trạng thái về ready
                logger.info(f"Simulation {simulation_id} is prepared, resetting status to ready (previous: {state.status.value})")
                state.status = SimulationStatus.READY
                manager._save_simulation_state(state)
            else:
                # Chuẩn bị chưa hoàn tất
                return jsonify({
                    "success": False,
                    "error": f"Simulation is not ready. Current status: {state.status.value}. Please call /prepare first"
                }), 400
        
        # Lấy graph ID (dùng cho cập nhật bộ nhớ đồ thị)
        graph_id = None
        if enable_graph_memory_update:
            # Lấy graph_id từ trạng thái mô phỏng hoặc từ dự án
            graph_id = state.graph_id
            if not graph_id:
                # Thử lấy từ dự án
                project = ProjectManager.get_project(state.project_id)
                if project:
                    graph_id = project.graph_id
            
            if not graph_id:
                return jsonify({
                    "success": False,
                    "error": "Enabling graph memory update requires a valid graph_id. Please ensure the project graph is built"
                }), 400
            
            logger.info(f"Graph memory update enabled: simulation_id={simulation_id}, graph_id={graph_id}")
        
        # Khởi chạy mô phỏng
        run_state = SimulationRunner.start_simulation(
            simulation_id=simulation_id,
            platform=platform,
            max_rounds=max_rounds,
            enable_graph_memory_update=enable_graph_memory_update,
            graph_id=graph_id
        )
        
        # Cập nhật trạng thái mô phỏng
        state.status = SimulationStatus.RUNNING
        manager._save_simulation_state(state)
        
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
        logger.error(f"Failed to start simulation: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/stop', methods=['POST'])
def stop_simulation():
    """
    Dừng mô phỏng.
    
    Yêu cầu (JSON):
        {
            "simulation_id": "sim_xxxx"  // bắt buộc, simulation ID
        }
    
    Trả về:
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
                "error": "Please provide simulation_id"
            }), 400
        
        run_state = SimulationRunner.stop_simulation(simulation_id)
        
        # Cập nhật trạng thái mô phỏng
        manager = SimulationManager()
        state = manager.get_simulation(simulation_id)
        if state:
            state.status = SimulationStatus.PAUSED
            manager._save_simulation_state(state)
        
        return jsonify({
            "success": True,
            "data": run_state.to_dict()
        })
        
    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400
        
    except Exception as e:
        logger.error(f"Failed to stop simulation: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== API giám sát trạng thái thời gian thực ==============

@simulation_bp.route('/<simulation_id>/run-status', methods=['GET'])
def get_run_status(simulation_id: str):
    """
    Lấy trạng thái chạy mô phỏng theo thời gian thực (dùng cho frontend polling).
    
    Trả về:
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
        logger.error(f"Failed to get run status: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/run-status/detail', methods=['GET'])
def get_run_status_detail(simulation_id: str):
    """
    Lấy trạng thái chạy mô phỏng chi tiết (bao gồm toàn bộ hành động).
    
    Dùng cho frontend hiển thị diễn biến thời gian thực.
    
    Tham số query:
        platform: Lọc theo nền tảng (twitter/reddit, tùy chọn)
    
    Trả về:
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
                "twitter_actions": [...],  # toàn bộ hành động trên Twitter
                "reddit_actions": [...]    # toàn bộ hành động trên Reddit
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
        
        # Lấy danh sách hành động đầy đủ
        all_actions = SimulationRunner.get_all_actions(
            simulation_id=simulation_id,
            platform=platform_filter
        )
        
        # Lấy hành động theo từng nền tảng
        twitter_actions = SimulationRunner.get_all_actions(
            simulation_id=simulation_id,
            platform="twitter"
        ) if not platform_filter or platform_filter == "twitter" else []
        
        reddit_actions = SimulationRunner.get_all_actions(
            simulation_id=simulation_id,
            platform="reddit"
        ) if not platform_filter or platform_filter == "reddit" else []
        
        # Lấy hành động của vòng hiện tại (recent_actions chỉ hiển thị vòng mới nhất)
        current_round = run_state.current_round
        recent_actions = SimulationRunner.get_all_actions(
            simulation_id=simulation_id,
            platform=platform_filter,
            round_num=current_round
        ) if current_round > 0 else []
        
        # Lấy thông tin trạng thái cơ bản
        result = run_state.to_dict()
        result["all_actions"] = [a.to_dict() for a in all_actions]
        result["twitter_actions"] = [a.to_dict() for a in twitter_actions]
        result["reddit_actions"] = [a.to_dict() for a in reddit_actions]
        result["rounds_count"] = len(run_state.rounds)
        # recent_actions chỉ hiển thị nội dung của vòng mới nhất trên hai nền tảng
        result["recent_actions"] = [a.to_dict() for a in recent_actions]
        
        return jsonify({
            "success": True,
            "data": result
        })
        
    except Exception as e:
        logger.error(f"Failed to get detailed run status: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/actions', methods=['GET'])
def get_simulation_actions(simulation_id: str):
    """
    Lấy lịch sử hành động Agent trong mô phỏng.
    
    Tham số query:
        limit: Số lượng trả về (mặc định 100)
        offset: Độ lệch (mặc định 0)
        platform: Lọc nền tảng (twitter/reddit)
        agent_id: Lọc theo Agent ID
        round_num: Lọc theo vòng
    
    Trả về:
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
        logger.error(f"Failed to get action history: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/timeline', methods=['GET'])
def get_simulation_timeline(simulation_id: str):
    """
    Lấy timeline mô phỏng (tổng hợp theo vòng).
    
    Dùng cho frontend hiển thị thanh tiến độ và timeline.
    
    Tham số query:
        start_round: Vòng bắt đầu (mặc định 0)
        end_round: Vòng kết thúc (mặc định toàn bộ)
    
    Trả về thông tin tổng hợp theo từng vòng.
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
        logger.error(f"Failed to get timeline: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/agent-stats', methods=['GET'])
def get_agent_stats(simulation_id: str):
    """
    Lấy thống kê của từng Agent.
    
    Dùng cho frontend hiển thị bảng xếp hạng mức độ hoạt động và phân bố hành động của Agent.
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
        logger.error(f"Failed to get agent statistics: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== API truy vấn cơ sở dữ liệu ==============

@simulation_bp.route('/<simulation_id>/posts', methods=['GET'])
def get_simulation_posts(simulation_id: str):
    """
    Lấy bài đăng trong mô phỏng.
    
    Tham số query:
        platform: Loại nền tảng (twitter/reddit)
        limit: Số lượng trả về (mặc định 50)
        offset: Độ lệch
    
    Trả về danh sách bài đăng (đọc từ cơ sở dữ liệu SQLite).
    """
    try:
        platform = request.args.get('platform', 'reddit')
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
                    "message": "Database does not exist. The simulation may not have run yet"
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
        logger.error(f"Failed to get posts: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/comments', methods=['GET'])
def get_simulation_comments(simulation_id: str):
    """
    Lấy bình luận trong mô phỏng (chỉ Reddit).
    
    Tham số query:
        post_id: Lọc theo post ID (tùy chọn)
        limit: Số lượng trả về
        offset: Độ lệch
    """
    try:
        post_id = request.args.get('post_id')
        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)
        
        sim_dir = os.path.join(
            os.path.dirname(__file__),
            f'../../uploads/simulations/{simulation_id}'
        )
        
        db_path = os.path.join(sim_dir, "reddit_simulation.db")
        
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
        logger.error(f"Failed to get comments: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== Interview API ==============

@simulation_bp.route('/interview', methods=['POST'])
def interview_agent():
    """
    Phỏng vấn một Agent.

    Lưu ý: chức năng này yêu cầu môi trường mô phỏng đang chạy
    (sau khi hoàn tất vòng mô phỏng, hệ thống vào chế độ chờ lệnh).

    Yêu cầu (JSON):
        {
            "simulation_id": "sim_xxxx",       // Bắt buộc, simulation ID
            "agent_id": 0,                     // Bắt buộc, Agent ID
            "prompt": "Bạn nghĩ gì về vấn đề này?",  // Bắt buộc, câu hỏi phỏng vấn
            "platform": "twitter",             // Tùy chọn, chỉ định nền tảng (twitter/reddit)
                                               // Nếu không chỉ định: mô phỏng 2 nền tảng sẽ phỏng vấn cả hai
            "timeout": 60                      // Tùy chọn, timeout (giây), mặc định 60
        }

    Trả về (không chỉ định `platform`, chế độ hai nền tảng):
        {
            "success": true,
            "data": {
                "agent_id": 0,
                "prompt": "Bạn nghĩ gì về vấn đề này?",
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

    Trả về (có chỉ định `platform`):
        {
            "success": true,
            "data": {
                "agent_id": 0,
                "prompt": "Bạn nghĩ gì về vấn đề này?",
                "result": {
                    "agent_id": 0,
                    "response": "Tôi nghĩ...",
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
        platform = data.get('platform')  # Tùy chọn: twitter/reddit/None
        timeout = data.get('timeout', 60)
        
        if not simulation_id:
            return jsonify({
                "success": False,
                "error": "Please provide simulation_id"
            }), 400
        
        if agent_id is None:
            return jsonify({
                "success": False,
                "error": "Please provide agent_id"
            }), 400
        
        if not prompt:
            return jsonify({
                "success": False,
                "error": "Please provide prompt (interview question)"
            }), 400
        
        # Validate platform parameter
        if platform and platform not in ("twitter", "reddit"):
            return jsonify({
                "success": False,
                "error": "platform must be 'twitter' or 'reddit'"
            }), 400
        
        # Check environment status
        if not SimulationRunner.check_env_alive(simulation_id):
            return jsonify({
                "success": False,
                "error": "Simulation environment is not running or has been closed. Ensure simulation has completed and entered command-wait mode."
            }), 400
        
        # Optimize prompt by adding a prefix to avoid Agent tool calls
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
            "error": f"Timeout waiting for interview response: {str(e)}"
        }), 504
        
    except Exception as e:
        logger.error(f"Interview failed: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/interview/batch', methods=['POST'])
def interview_agents_batch():
    """
    Phỏng vấn hàng loạt nhiều Agent.

    Lưu ý: chức năng này yêu cầu môi trường mô phỏng đang chạy.

    Yêu cầu (JSON):
        {
            "simulation_id": "sim_xxxx",       // Bắt buộc, simulation ID
            "interviews": [                    // Bắt buộc, danh sách phỏng vấn
                {
                    "agent_id": 0,
                    "prompt": "Bạn nghĩ gì về A?",
                    "platform": "twitter"      // Tùy chọn, chỉ định nền tảng cho Agent này
                },
                {
                    "agent_id": 1,
                    "prompt": "Bạn nghĩ gì về B?"  // Nếu không chỉ định `platform`, dùng giá trị mặc định
                }
            ],
            "platform": "reddit",              // Tùy chọn, nền tảng mặc định (bị ghi đè bởi `platform` của từng mục)
                                               // Nếu không chỉ định: mô phỏng 2 nền tảng sẽ phỏng vấn cả hai nền tảng cho mỗi Agent
            "timeout": 120                     // Tùy chọn, timeout (giây), mặc định 120
        }

    Trả về:
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
        platform = data.get('platform')  # Tùy chọn: twitter/reddit/None
        timeout = data.get('timeout', 120)

        if not simulation_id:
            return jsonify({
                "success": False,
                "error": "Please provide simulation_id"
            }), 400

        if not interviews or not isinstance(interviews, list):
            return jsonify({
                "success": False,
                "error": "Please provide interviews (interview list)"
            }), 400

        # Validate platform parameter
        if platform and platform not in ("twitter", "reddit"):
            return jsonify({
                "success": False,
                "error": "platform must be 'twitter' or 'reddit'"
            }), 400

        # Validate each interview item
        for i, interview in enumerate(interviews):
            if 'agent_id' not in interview:
                return jsonify({
                    "success": False,
                    "error": f"Interview item {i+1} is missing agent_id"
                }), 400
            if 'prompt' not in interview:
                return jsonify({
                    "success": False,
                    "error": f"Interview item {i+1} is missing prompt"
                }), 400
            # Validate platform in each item (if provided)
            item_platform = interview.get('platform')
            if item_platform and item_platform not in ("twitter", "reddit"):
                return jsonify({
                    "success": False,
                    "error": f"platform in interview item {i+1} must be 'twitter' or 'reddit'"
                }), 400

        # Check environment status
        if not SimulationRunner.check_env_alive(simulation_id):
            return jsonify({
                "success": False,
                "error": "Simulation environment is not running or has been closed. Ensure simulation has completed and entered command-wait mode."
            }), 400

        # Optimize prompts in each interview item to avoid Agent tool calls
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
            "error": f"Timeout waiting for batch interview response: {str(e)}"
        }), 504

    except Exception as e:
        logger.error(f"Batch interview failed: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/interview/all', methods=['POST'])
def interview_all_agents():
    """
    Phỏng vấn toàn cục - dùng cùng một câu hỏi để phỏng vấn tất cả Agent.

    Lưu ý: chức năng này yêu cầu môi trường mô phỏng đang chạy.

    Yêu cầu (JSON):
        {
            "simulation_id": "sim_xxxx",            // Bắt buộc, simulation ID
            "prompt": "Bạn có quan điểm tổng thể gì về vấn đề này?",  // Bắt buộc, câu hỏi phỏng vấn (mọi Agent dùng cùng câu hỏi)
            "platform": "reddit",                   // Tùy chọn, chỉ định nền tảng (twitter/reddit)
                                                    // Nếu không chỉ định: mô phỏng 2 nền tảng sẽ phỏng vấn cả hai nền tảng cho mỗi Agent
            "timeout": 180                          // Tùy chọn, timeout (giây), mặc định 180
        }

    Trả về:
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
        platform = data.get('platform')  # Tùy chọn: twitter/reddit/None
        timeout = data.get('timeout', 180)

        if not simulation_id:
            return jsonify({
                "success": False,
                "error": "Please provide simulation_id"
            }), 400

        if not prompt:
            return jsonify({
                "success": False,
                "error": "Please provide prompt (interview question)"
            }), 400

        # Validate platform parameter
        if platform and platform not in ("twitter", "reddit"):
            return jsonify({
                "success": False,
                "error": "platform must be 'twitter' or 'reddit'"
            }), 400

        # Check environment status
        if not SimulationRunner.check_env_alive(simulation_id):
            return jsonify({
                "success": False,
                "error": "Simulation environment is not running or has been closed. Ensure simulation has completed and entered command-wait mode."
            }), 400

        # Optimize prompt by adding a prefix to avoid Agent tool calls
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
            "error": f"Timeout waiting for global interview response: {str(e)}"
        }), 504

    except Exception as e:
        logger.error(f"Global interview failed: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/interview/history', methods=['POST'])
def get_interview_history():
    """
    Lấy lịch sử Interview.

    Đọc toàn bộ bản ghi Interview từ cơ sở dữ liệu mô phỏng.

    Yêu cầu (JSON):
        {
            "simulation_id": "sim_xxxx",  // Bắt buộc, simulation ID
            "platform": "reddit",          // Tùy chọn, loại nền tảng (reddit/twitter)
                                           // Nếu không chỉ định, trả về toàn bộ lịch sử của cả hai nền tảng
            "agent_id": 0,                 // Tùy chọn, chỉ lấy lịch sử phỏng vấn của Agent này
            "limit": 100                   // Tùy chọn, số lượng trả về, mặc định 100
        }

    Trả về:
        {
            "success": true,
            "data": {
                "count": 10,
                "history": [
                    {
                        "agent_id": 0,
                        "response": "Tôi nghĩ...",
                        "prompt": "Bạn nghĩ gì về vấn đề này?",
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
        platform = data.get('platform')  # If omitted, return history from both platforms
        agent_id = data.get('agent_id')
        limit = data.get('limit', 100)
        
        if not simulation_id:
            return jsonify({
                "success": False,
                "error": "Please provide simulation_id"
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
        logger.error(f"Failed to get interview history: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/env-status', methods=['POST'])
def get_env_status():
    """
    Lấy trạng thái môi trường mô phỏng.

    Kiểm tra môi trường mô phỏng còn hoạt động không (có thể nhận lệnh Interview).

    Yêu cầu (JSON):
        {
            "simulation_id": "sim_xxxx"  // Bắt buộc, simulation ID
        }

    Trả về:
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "env_alive": true,
                "twitter_available": true,
                "reddit_available": true,
                "message": "Environment is running and can receive Interview commands"
            }
        }
    """
    try:
        data = request.get_json() or {}
        
        simulation_id = data.get('simulation_id')
        
        if not simulation_id:
            return jsonify({
                "success": False,
                "error": "Please provide simulation_id"
            }), 400

        env_alive = SimulationRunner.check_env_alive(simulation_id)
        
        # Get more detailed status information
        env_status = SimulationRunner.get_env_status_detail(simulation_id)

        if env_alive:
            message = "Environment is running and can receive Interview commands"
        else:
            message = "Environment is not running or has been closed"

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
        logger.error(f"Failed to get environment status: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/close-env', methods=['POST'])
def close_simulation_env():
    """
    Đóng môi trường mô phỏng.
    
    Gửi lệnh đóng môi trường tới mô phỏng để thoát chế độ chờ lệnh một cách graceful.
    
    Lưu ý: API này khác với `/stop`; `/stop` sẽ buộc dừng tiến trình,
    còn API này sẽ cho mô phỏng đóng môi trường và thoát một cách graceful.
    
    Yêu cầu (JSON):
        {
            "simulation_id": "sim_xxxx",  // Bắt buộc, simulation ID
            "timeout": 30                  // Tùy chọn, timeout (giây), mặc định 30
        }
    
    Trả về:
        {
            "success": true,
            "data": {
                "message": "Environment close command has been sent",
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
                "error": "Please provide simulation_id"
            }), 400
        
        result = SimulationRunner.close_simulation_env(
            simulation_id=simulation_id,
            timeout=timeout
        )
        
        # Update simulation status
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
        logger.error(f"Failed to close environment: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500