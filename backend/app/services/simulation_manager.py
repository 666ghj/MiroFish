"""
OASIS模拟管理器
管理Twitter和Reddit双平台并行模拟
使用预设脚本 + LLM智能生成配置参数
"""

import os
import json
import shutil
import time
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from zep_cloud.client import Zep

from ..config import Config
from ..utils.logger import get_logger
from .zep_entity_reader import ZepEntityReader, FilteredEntities
from .oasis_profile_generator import OasisProfileGenerator, OasisAgentProfile
from .simulation_config_generator import SimulationConfigGenerator, SimulationParameters

logger = get_logger('mirofish.simulation')


class SimulationStatus(str, Enum):
    """模拟状态"""
    CREATED = "created"
    PREPARING = "preparing"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"      # 模拟被手动停止
    COMPLETED = "completed"  # 模拟自然完成
    FAILED = "failed"


class PlatformType(str, Enum):
    """平台类型"""
    TWITTER = "twitter"
    REDDIT = "reddit"


@dataclass
class SimulationState:
    """模拟状态"""
    simulation_id: str
    project_id: str
    graph_id: str
    # 项目“源图谱”（只包含文档/本体构建结果，不应被模拟过程污染）
    project_graph_id: Optional[str] = None
    
    # 平台启用状态
    enable_twitter: bool = True
    enable_reddit: bool = True
    
    # 状态
    status: SimulationStatus = SimulationStatus.CREATED
    
    # 准备阶段数据
    entities_count: int = 0
    profiles_count: int = 0
    entity_types: List[str] = field(default_factory=list)
    
    # 配置生成信息
    config_generated: bool = False
    config_reasoning: str = ""
    
    # 运行时数据
    current_round: int = 0
    twitter_status: str = "not_started"
    reddit_status: str = "not_started"
    
    # 时间戳
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    # 错误信息
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """完整状态字典（内部使用）"""
        return {
            "simulation_id": self.simulation_id,
            "project_id": self.project_id,
            "graph_id": self.graph_id,
            "project_graph_id": self.project_graph_id,
            "enable_twitter": self.enable_twitter,
            "enable_reddit": self.enable_reddit,
            "status": self.status.value,
            "entities_count": self.entities_count,
            "profiles_count": self.profiles_count,
            "entity_types": self.entity_types,
            "config_generated": self.config_generated,
            "config_reasoning": self.config_reasoning,
            "current_round": self.current_round,
            "twitter_status": self.twitter_status,
            "reddit_status": self.reddit_status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "error": self.error,
        }
    
    def to_simple_dict(self) -> Dict[str, Any]:
        """简化状态字典（API返回使用）"""
        return {
            "simulation_id": self.simulation_id,
            "project_id": self.project_id,
            "graph_id": self.graph_id,
            "project_graph_id": self.project_graph_id,
            "status": self.status.value,
            "entities_count": self.entities_count,
            "profiles_count": self.profiles_count,
            "entity_types": self.entity_types,
            "config_generated": self.config_generated,
            "error": self.error,
        }


class SimulationManager:
    """
    模拟管理器
    
    核心功能：
    1. 从Zep图谱读取实体并过滤
    2. 生成OASIS Agent Profile
    3. 使用LLM智能生成模拟配置参数
    4. 准备预设脚本所需的所有文件
    """
    
    # 模拟数据存储目录
    SIMULATION_DATA_DIR = os.path.join(
        os.path.dirname(__file__), 
        '../../uploads/simulations'
    )
    
    def __init__(self):
        # 确保目录存在
        os.makedirs(self.SIMULATION_DATA_DIR, exist_ok=True)
        
        # 内存中的模拟状态缓存
        self._simulations: Dict[str, SimulationState] = {}
    
    def _get_simulation_dir(self, simulation_id: str) -> str:
        """获取模拟数据目录"""
        sim_dir = os.path.join(self.SIMULATION_DATA_DIR, simulation_id)
        os.makedirs(sim_dir, exist_ok=True)
        return sim_dir
    
    def _save_simulation_state(self, state: SimulationState):
        """保存模拟状态到文件"""
        sim_dir = self._get_simulation_dir(state.simulation_id)
        state_file = os.path.join(sim_dir, "state.json")
        
        state.updated_at = datetime.now().isoformat()
        
        with open(state_file, 'w', encoding='utf-8') as f:
            json.dump(state.to_dict(), f, ensure_ascii=False, indent=2)
        
        self._simulations[state.simulation_id] = state
    
    def _load_simulation_state(self, simulation_id: str) -> Optional[SimulationState]:
        """从文件加载模拟状态"""
        if simulation_id in self._simulations:
            return self._simulations[simulation_id]
        
        sim_dir = self._get_simulation_dir(simulation_id)
        state_file = os.path.join(sim_dir, "state.json")
        
        if not os.path.exists(state_file):
            return None
        
        with open(state_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        graph_id = data.get("graph_id", "")
        project_graph_id = data.get("project_graph_id") or None
        if not project_graph_id and graph_id:
            # 兼容旧数据：历史上 graph_id 直接指向项目图谱
            project_graph_id = graph_id
        
        state = SimulationState(
            simulation_id=simulation_id,
            project_id=data.get("project_id", ""),
            graph_id=graph_id,
            project_graph_id=project_graph_id,
            enable_twitter=data.get("enable_twitter", True),
            enable_reddit=data.get("enable_reddit", True),
            status=SimulationStatus(data.get("status", "created")),
            entities_count=data.get("entities_count", 0),
            profiles_count=data.get("profiles_count", 0),
            entity_types=data.get("entity_types", []),
            config_generated=data.get("config_generated", False),
            config_reasoning=data.get("config_reasoning", ""),
            current_round=data.get("current_round", 0),
            twitter_status=data.get("twitter_status", "not_started"),
            reddit_status=data.get("reddit_status", "not_started"),
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
            error=data.get("error"),
        )
        
        self._simulations[simulation_id] = state
        return state
    
    def create_simulation(
        self,
        project_id: str,
        graph_id: str,
        enable_twitter: bool = True,
        enable_reddit: bool = True,
    ) -> SimulationState:
        """
        创建新的模拟
        
        Args:
            project_id: 项目ID
            graph_id: Zep图谱ID
            enable_twitter: 是否启用Twitter模拟
            enable_reddit: 是否启用Reddit模拟
            
        Returns:
            SimulationState
        """
        import uuid
        simulation_id = f"sim_{uuid.uuid4().hex[:12]}"
        
        state = SimulationState(
            simulation_id=simulation_id,
            project_id=project_id,
            graph_id=graph_id,
            project_graph_id=graph_id,
            enable_twitter=enable_twitter,
            enable_reddit=enable_reddit,
            status=SimulationStatus.CREATED,
        )
        
        self._save_simulation_state(state)
        logger.info(f"创建模拟: {simulation_id}, project={project_id}, graph={graph_id}")
        
        return state

    def _wait_for_zep_task(self, client: Zep, task_id: str, *, timeout_seconds: int = 300):
        """等待 Zep 异步任务完成（用于 graph.clone 等）。"""
        start = time.time()
        last_status = None
        while True:
            if time.time() - start > timeout_seconds:
                raise TimeoutError(f"等待 Zep 任务超时: task_id={task_id}, last_status={last_status}")

            task = client.task.get(task_id)
            status = (getattr(task, "status", None) or "").lower().strip() or None
            last_status = status

            if getattr(task, "completed_at", None):
                return
            if status in {"completed", "succeeded", "success", "done"}:
                return
            if status in {"failed", "error", "canceled", "cancelled"}:
                err = getattr(task, "error", None)
                raise RuntimeError(f"Zep 任务失败: task_id={task_id}, status={status}, error={err}")

            time.sleep(1)

    def ensure_isolated_simulation_graph(self, state: SimulationState, *, timeout_seconds: int = 300) -> str:
        """
        确保当前 simulation 拥有“隔离的”图谱副本，用于写入模拟过程（避免污染 project_graph_id）。

        - 若 state.graph_id 已经不同于 project_graph_id，则认为已隔离，直接返回。
        - 否则，通过 Zep graph.clone 从 project_graph_id 克隆一个新图谱，并将 state.graph_id 指向该副本。
        """
        base_graph_id = (state.project_graph_id or state.graph_id or "").strip()
        if not base_graph_id:
            raise ValueError("缺少 project_graph_id / graph_id，无法创建模拟图谱副本")

        if not state.project_graph_id:
            state.project_graph_id = base_graph_id

        # 已隔离
        if state.graph_id and state.graph_id != state.project_graph_id:
            return state.graph_id

        if not Config.ZEP_API_KEY:
            raise ValueError("ZEP_API_KEY 未配置，无法克隆图谱用于隔离写入")

        import uuid

        target_graph_id = f"mirofish_sim_{state.simulation_id}_{uuid.uuid4().hex[:8]}"
        client = Zep(api_key=Config.ZEP_API_KEY)
        resp = client.graph.clone(source_graph_id=base_graph_id, target_graph_id=target_graph_id)
        new_graph_id = (getattr(resp, "graph_id", None) or target_graph_id).strip()
        task_id = getattr(resp, "task_id", None)
        if task_id:
            self._wait_for_zep_task(client, task_id, timeout_seconds=timeout_seconds)

        state.graph_id = new_graph_id
        self._save_simulation_state(state)
        logger.info(
            f"已为模拟创建隔离图谱: simulation_id={state.simulation_id}, "
            f"project_graph_id={base_graph_id}, graph_id={new_graph_id}"
        )
        return new_graph_id
    
    def prepare_simulation(
        self,
        simulation_id: str,
        simulation_requirement: str,
        document_text: str,
        defined_entity_types: Optional[List[str]] = None,
        use_llm_for_profiles: bool = True,
        progress_callback: Optional[callable] = None,
        parallel_profile_count: int = 3
    ) -> SimulationState:
        """
        准备模拟环境（全程自动化）
        
        步骤：
        1. 从Zep图谱读取并过滤实体
        2. 为每个实体生成OASIS Agent Profile（可选LLM增强，支持并行）
        3. 使用LLM智能生成模拟配置参数（时间、活跃度、发言频率等）
        4. 保存配置文件和Profile文件
        5. 复制预设脚本到模拟目录
        
        Args:
            simulation_id: 模拟ID
            simulation_requirement: 模拟需求描述（用于LLM生成配置）
            document_text: 原始文档内容（用于LLM理解背景）
            defined_entity_types: 预定义的实体类型（可选）
            use_llm_for_profiles: 是否使用LLM生成详细人设
            progress_callback: 进度回调函数 (stage, progress, message)
            parallel_profile_count: 并行生成人设的数量，默认3
            
        Returns:
            SimulationState
        """
        state = self._load_simulation_state(simulation_id)
        if not state:
            raise ValueError(f"模拟不存在: {simulation_id}")
        
        try:
            state.status = SimulationStatus.PREPARING
            self._save_simulation_state(state)

            # 准备阶段固定使用“源图谱”（只包含文档/本体构建结果）
            source_graph_id = (state.project_graph_id or state.graph_id or "").strip()
            if not source_graph_id:
                raise ValueError("缺少 project_graph_id / graph_id，无法读取实体")
            if not state.project_graph_id:
                state.project_graph_id = source_graph_id
                self._save_simulation_state(state)
            
            sim_dir = self._get_simulation_dir(simulation_id)
            entity_order_path = os.path.join(sim_dir, "entity_order.json")
            
            # ========== 阶段1: 读取并过滤实体 ==========
            if progress_callback:
                progress_callback("reading", 0, "正在连接Zep图谱...")
            
            reader = ZepEntityReader()
            
            if progress_callback:
                progress_callback("reading", 30, "正在读取节点数据...")
            
            filtered = reader.filter_defined_entities(
                graph_id=source_graph_id,
                defined_entity_types=defined_entity_types,
                enrich_with_edges=True
            )

            # 断点续跑：如果已有实体顺序文件，则用它固定 user_id/实体映射，避免重启后错位
            try:
                if os.path.exists(entity_order_path):
                    with open(entity_order_path, "r", encoding="utf-8") as f:
                        order_data = json.load(f) or {}
                    entity_uuids = order_data.get("entity_uuids") or []
                    if isinstance(entity_uuids, list) and entity_uuids:
                        by_uuid = {e.uuid: e for e in filtered.entities}
                        ordered_entities = []
                        used = set()
                        for uuid in entity_uuids:
                            if uuid in by_uuid:
                                ordered_entities.append(by_uuid[uuid])
                                used.add(uuid)
                        for e in filtered.entities:
                            if e.uuid not in used:
                                ordered_entities.append(e)
                        filtered.entities = ordered_entities
                else:
                    with open(entity_order_path, "w", encoding="utf-8") as f:
                        json.dump(
                            {
                                "graph_id": source_graph_id,
                                "defined_entity_types": defined_entity_types,
                                "entity_uuids": [e.uuid for e in filtered.entities],
                                "created_at": datetime.now().isoformat(),
                            },
                            f,
                            ensure_ascii=False,
                            indent=2,
                        )
            except Exception as e:
                logger.warning(f"处理 entity_order.json 失败（不影响继续生成）: {e}")
            
            state.entities_count = filtered.filtered_count
            state.entity_types = list(filtered.entity_types)
            
            if progress_callback:
                progress_callback(
                    "reading", 100, 
                    f"完成，共 {filtered.filtered_count} 个实体",
                    current=filtered.filtered_count,
                    total=filtered.filtered_count
                )
            
            if filtered.filtered_count == 0:
                state.status = SimulationStatus.FAILED
                state.error = "没有找到符合条件的实体，请检查图谱是否正确构建"
                self._save_simulation_state(state)
                return state
            
            # ========== 阶段2: 生成Agent Profile ==========
            total_entities = len(filtered.entities)
            
            if progress_callback:
                progress_callback(
                    "generating_profiles", 0, 
                    "开始生成...",
                    current=0,
                    total=total_entities
                )
            
            # 传入graph_id以启用Zep检索功能，获取更丰富的上下文
            generator = OasisProfileGenerator(graph_id=source_graph_id)
            
            def profile_progress(current, total, msg):
                if progress_callback:
                    progress_callback(
                        "generating_profiles", 
                        int(current / total * 100), 
                        msg,
                        current=current,
                        total=total,
                        item_name=msg
                    )
            
            # 设置实时保存的文件路径（优先使用 Reddit JSON 格式）
            realtime_output_path = None
            realtime_platform = "reddit"
            if state.enable_reddit:
                realtime_output_path = os.path.join(sim_dir, "reddit_profiles.json")
                realtime_platform = "reddit"
            elif state.enable_twitter:
                realtime_output_path = os.path.join(sim_dir, "twitter_profiles.csv")
                realtime_platform = "twitter"
            
            profiles = generator.generate_profiles_from_entities(
                entities=filtered.entities,
                use_llm=use_llm_for_profiles,
                progress_callback=profile_progress,
                graph_id=source_graph_id,  # 传入graph_id用于Zep检索
                parallel_count=parallel_profile_count,  # 并行生成数量
                realtime_output_path=realtime_output_path,  # 实时保存路径
                output_platform=realtime_platform  # 输出格式
            )
            
            state.profiles_count = len(profiles)
            
            # 保存Profile文件（注意：Twitter使用CSV格式，Reddit使用JSON格式）
            # Reddit 已经在生成过程中实时保存了，这里再保存一次确保完整性
            if progress_callback:
                progress_callback(
                    "generating_profiles", 95, 
                    "保存Profile文件...",
                    current=total_entities,
                    total=total_entities
                )
            
            if state.enable_reddit:
                generator.save_profiles(
                    profiles=profiles,
                    file_path=os.path.join(sim_dir, "reddit_profiles.json"),
                    platform="reddit"
                )
            
            if state.enable_twitter:
                # Twitter使用CSV格式！这是OASIS的要求
                generator.save_profiles(
                    profiles=profiles,
                    file_path=os.path.join(sim_dir, "twitter_profiles.csv"),
                    platform="twitter"
                )
            
            if progress_callback:
                progress_callback(
                    "generating_profiles", 100, 
                    f"完成，共 {len(profiles)} 个Profile",
                    current=len(profiles),
                    total=len(profiles)
                )
            
            # ========== 阶段3: LLM智能生成模拟配置 ==========
            if progress_callback:
                progress_callback(
                    "generating_config", 0, 
                    "正在分析模拟需求...",
                    current=0,
                    total=3
                )

            # 断点续跑：如果配置文件已存在（例如后端重启前已写入但未更新 state），直接复用
            config_path = os.path.join(sim_dir, "simulation_config.json")
            existing_config = None
            if os.path.exists(config_path):
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        existing_config = json.load(f)
                except Exception:
                    existing_config = None

            if isinstance(existing_config, dict):
                state.config_generated = True
                state.config_reasoning = existing_config.get("generation_reasoning", state.config_reasoning)
                if progress_callback:
                    progress_callback(
                        "generating_config",
                        100,
                        "检测到已有配置文件，跳过重复生成",
                        current=3,
                        total=3,
                    )
            else:
                config_generator = SimulationConfigGenerator()

                if progress_callback:
                    progress_callback(
                        "generating_config", 30,
                        "正在调用LLM生成配置...",
                        current=1,
                        total=3
                    )

                sim_params = config_generator.generate_config(
                    simulation_id=simulation_id,
                    project_id=state.project_id,
                    graph_id=source_graph_id,
                    simulation_requirement=simulation_requirement,
                    document_text=document_text,
                    entities=filtered.entities,
                    enable_twitter=state.enable_twitter,
                    enable_reddit=state.enable_reddit,
                    usage_log_path=os.path.join(sim_dir, "llm_usage.jsonl"),
                )

                if progress_callback:
                    progress_callback(
                        "generating_config", 70,
                        "正在保存配置文件...",
                        current=2,
                        total=3
                    )

                # 保存配置文件
                with open(config_path, 'w', encoding='utf-8') as f:
                    f.write(sim_params.to_json())

                state.config_generated = True
                state.config_reasoning = sim_params.generation_reasoning
            
            if progress_callback:
                progress_callback(
                    "generating_config", 100, 
                    "配置生成完成",
                    current=3,
                    total=3
                )
            
            # 注意：运行脚本保留在 backend/scripts/ 目录，不再复制到模拟目录
            # 启动模拟时，simulation_runner 会从 scripts/ 目录运行脚本
            
            # 更新状态
            state.status = SimulationStatus.READY
            self._save_simulation_state(state)
            
            logger.info(f"模拟准备完成: {simulation_id}, "
                       f"entities={state.entities_count}, profiles={state.profiles_count}")
            
            return state
            
        except Exception as e:
            logger.error(f"模拟准备失败: {simulation_id}, error={str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            state.status = SimulationStatus.FAILED
            state.error = str(e)
            self._save_simulation_state(state)
            raise
    
    def get_simulation(self, simulation_id: str) -> Optional[SimulationState]:
        """获取模拟状态"""
        return self._load_simulation_state(simulation_id)
    
    def list_simulations(self, project_id: Optional[str] = None) -> List[SimulationState]:
        """列出所有模拟"""
        simulations = []
        
        if os.path.exists(self.SIMULATION_DATA_DIR):
            for sim_id in os.listdir(self.SIMULATION_DATA_DIR):
                state = self._load_simulation_state(sim_id)
                if state:
                    if project_id is None or state.project_id == project_id:
                        simulations.append(state)
        
        return simulations

    def delete_simulation(self, simulation_id: str) -> bool:
        """
        删除模拟及其所有相关文件

        Args:
            simulation_id: 模拟ID

        Returns:
            是否删除成功
        """
        from .simulation_runner import SimulationRunner

        state = self._load_simulation_state(simulation_id)
        if not state:
            return False

        # 如果模拟进程还在运行，先停止
        try:
            run_state = SimulationRunner.get_run_state(simulation_id)
            if run_state and run_state.runner_status.value == "running":
                logger.info(f"模拟进程仍在运行，正在停止: {simulation_id}")
                SimulationRunner.stop_simulation(simulation_id)
        except Exception as e:
            logger.warning(f"停止模拟进程时出现警告: {e}")

        # 删除模拟目录
        sim_dir = os.path.join(self.SIMULATION_DATA_DIR, simulation_id)
        if os.path.exists(sim_dir):
            try:
                shutil.rmtree(sim_dir)
                logger.info(f"已删除模拟目录: {sim_dir}")
            except Exception as e:
                logger.error(f"删除模拟目录失败: {e}")
                return False

        # 从内存缓存中移除
        if simulation_id in self._simulations:
            del self._simulations[simulation_id]

        return True

    def branch_simulation(self, source_simulation_id: str) -> SimulationState:
        """
        基于已有模拟创建“安全分支”（新 simulation_id + 新目录）

        目标：
        - 不修改/不删除源模拟目录中的任何文件（避免污染其他分支）
        - 仅复制“准备阶段产物”（profiles + simulation_config.json）
        - 新分支处于 READY 状态，可继续 start 运行并进入 interview 等待模式
        """
        source_state = self.get_simulation(source_simulation_id)
        if not source_state:
            raise ValueError(f"模拟不存在: {source_simulation_id}")

        src_dir = self._get_simulation_dir(source_simulation_id)
        src_config = os.path.join(src_dir, "simulation_config.json")
        if not os.path.exists(src_config):
            raise ValueError("源模拟未准备完成：缺少 simulation_config.json（请先调用 /prepare）")

        src_twitter_profiles = os.path.join(src_dir, "twitter_profiles.csv")
        src_reddit_profiles = os.path.join(src_dir, "reddit_profiles.json")

        if source_state.enable_twitter and not os.path.exists(src_twitter_profiles):
            raise ValueError("源模拟未准备完成：缺少 twitter_profiles.csv")
        if source_state.enable_reddit and not os.path.exists(src_reddit_profiles):
            raise ValueError("源模拟未准备完成：缺少 reddit_profiles.json")

        # 创建新 simulation（新目录）
        base_graph_id = source_state.project_graph_id or source_state.graph_id
        new_state = self.create_simulation(
            project_id=source_state.project_id,
            graph_id=base_graph_id,
            enable_twitter=source_state.enable_twitter,
            enable_reddit=source_state.enable_reddit,
        )
        dst_dir = self._get_simulation_dir(new_state.simulation_id)

        # 复制 profiles（不复制 DB/logs/run_state 等）
        if source_state.enable_twitter and os.path.exists(src_twitter_profiles):
            shutil.copy2(src_twitter_profiles, os.path.join(dst_dir, "twitter_profiles.csv"))
        if source_state.enable_reddit and os.path.exists(src_reddit_profiles):
            shutil.copy2(src_reddit_profiles, os.path.join(dst_dir, "reddit_profiles.json"))

        # 复制并修正 config（确保 simulation_id 不复用）
        with open(src_config, "r", encoding="utf-8") as f:
            config_data = json.load(f)
        config_data["simulation_id"] = new_state.simulation_id
        config_data["project_id"] = new_state.project_id
        config_data["graph_id"] = new_state.graph_id

        with open(os.path.join(dst_dir, "simulation_config.json"), "w", encoding="utf-8") as f:
            json.dump(config_data, f, ensure_ascii=False, indent=2)

        # 继承部分元数据，方便 History/展示
        new_state.status = SimulationStatus.READY
        new_state.config_generated = True
        new_state.config_reasoning = source_state.config_reasoning
        new_state.entities_count = source_state.entities_count
        new_state.profiles_count = source_state.profiles_count
        new_state.entity_types = list(source_state.entity_types)
        self._save_simulation_state(new_state)

        logger.info(f"创建模拟分支: {source_simulation_id} -> {new_state.simulation_id}")
        return new_state
    
    def get_profiles(self, simulation_id: str, platform: str = "reddit") -> List[Dict[str, Any]]:
        """获取模拟的Agent Profile"""
        state = self._load_simulation_state(simulation_id)
        if not state:
            raise ValueError(f"模拟不存在: {simulation_id}")
        
        sim_dir = self._get_simulation_dir(simulation_id)
        profile_path = os.path.join(sim_dir, f"{platform}_profiles.json")
        
        if not os.path.exists(profile_path):
            return []
        
        with open(profile_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def get_simulation_config(self, simulation_id: str) -> Optional[Dict[str, Any]]:
        """获取模拟配置"""
        sim_dir = self._get_simulation_dir(simulation_id)
        config_path = os.path.join(sim_dir, "simulation_config.json")
        
        if not os.path.exists(config_path):
            return None
        
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def get_run_instructions(self, simulation_id: str) -> Dict[str, str]:
        """获取运行说明"""
        sim_dir = self._get_simulation_dir(simulation_id)
        config_path = os.path.join(sim_dir, "simulation_config.json")
        scripts_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../scripts'))
        
        return {
            "simulation_dir": sim_dir,
            "scripts_dir": scripts_dir,
            "config_file": config_path,
            "commands": {
                "twitter": f"python {scripts_dir}/run_twitter_simulation.py --config {config_path}",
                "reddit": f"python {scripts_dir}/run_reddit_simulation.py --config {config_path}",
                "parallel": f"python {scripts_dir}/run_parallel_simulation.py --config {config_path}",
            },
            "instructions": (
                f"1. 激活conda环境: conda activate MiroFish\n"
                f"2. 运行模拟 (脚本位于 {scripts_dir}):\n"
                f"   - 单独运行Twitter: python {scripts_dir}/run_twitter_simulation.py --config {config_path}\n"
                f"   - 单独运行Reddit: python {scripts_dir}/run_reddit_simulation.py --config {config_path}\n"
                f"   - 并行运行双平台: python {scripts_dir}/run_parallel_simulation.py --config {config_path}"
            )
        }
