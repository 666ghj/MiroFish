"""
Trình Quản lý Mô Phỏng OASIS
Đảm nhiệm xây dựng và điều phối chạy mô phỏng song song trên hai nền tảng giả lập Twitter và Reddit.
Sử dụng các kịch bản có sẵn kết hợp cùng LLM để thiết lập thông minh bộ tham số mô phỏng.
"""

import os
import json
import shutil
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from ..config import Config
from ..utils.logger import get_logger
from .zep_entity_reader import ZepEntityReader, FilteredEntities
from .oasis_profile_generator import OasisProfileGenerator, OasisAgentProfile
from .simulation_config_generator import SimulationConfigGenerator, SimulationParameters

logger = get_logger('mirofish.simulation')


class SimulationStatus(str, Enum):
    """Trạng thái hiện tại của quá trình mô phỏng"""
    CREATED = "created"      # Đã khởi tạo
    PREPARING = "preparing"  # Đang chuẩn bị (chuẩn bị dữ liệu/profile)
    READY = "ready"          # Đã sẵn sàng chạy
    RUNNING = "running"      # Đang xử lý giả lập
    PAUSED = "paused"        # Tạm dừng
    STOPPED = "stopped"      # Hệ thống mô phỏng bị người dùng chủ động dừng lại
    COMPLETED = "completed"  # Quá trình mô phỏng kết thúc tự nhiên một cách thành công
    FAILED = "failed"        # Bị lỗi hệ thống gián đoạn


class PlatformType(str, Enum):
    """Phân loại nền tảng giả lập Mạng xã hội"""
    TWITTER = "twitter"
    REDDIT = "reddit"


@dataclass
class SimulationState:
    """Class lưu trữ cấu trúc Dữ liệu/Trạng thái của một lượt mô phỏng"""
    simulation_id: str
    project_id: str
    graph_id: str
    
    # Cờ trạng thái bật/tắt nền tảng chạy
    enable_twitter: bool = True
    enable_reddit: bool = True
    
    # Current status
    status: SimulationStatus = SimulationStatus.CREATED
    
    # Dữ liệu thu thập / thống kê của Preparing Phase
    entities_count: int = 0
    profiles_count: int = 0
    entity_types: List[str] = field(default_factory=list)
    
    # Thông tin các nội dung cấu hình mà LLM đã tự động tạo
    config_generated: bool = False
    config_reasoning: str = ""
    
    # Dữ liệu cập nhật theo thời gian thực (Runtime Phase)
    current_round: int = 0
    twitter_status: str = "not_started"
    reddit_status: str = "not_started"
    
    # Nhãn Timestamp lịch sử
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    # Lịch sử thông báo Lỗi (nếu có để render trả về frontend)
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Tạo thành Dictionary đầy đủ nhất (Dùng cho việc lưu cấu hình local cho hệ thống bên trong đọc)"""
        return {
            "simulation_id": self.simulation_id,
            "project_id": self.project_id,
            "graph_id": self.graph_id,
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
        """Tạo thành Dictionary bao hàm các thông số vắn tắt hơn (Dùng cho API response trả về Client - Frontend)"""
        return {
            "simulation_id": self.simulation_id,
            "project_id": self.project_id,
            "graph_id": self.graph_id,
            "status": self.status.value,
            "entities_count": self.entities_count,
            "profiles_count": self.profiles_count,
            "entity_types": self.entity_types,
            "config_generated": self.config_generated,
            "error": self.error,
        }


class SimulationManager:
    """
    Kịch bản Quản lý trung tâm của tính năng Mô Phỏng
    
    Luồng thiết lập cốt lõi:
    1. Trích xuất nhóm các Thực Thể (Entity) được định nghĩa sẵn trong hệ thống lưu trữ Graph của Zep.
    2. Chế lại thành các hồ sơ Profile thiết lập tiêu chuẩn của OASIS framework (Agent)
    3. Trao quyền cho sức mạnh mô hình LLM tự đánh giá số liệu rồi tự sinh ra cấu hình cài đặt cho quá trình mô phỏng
    4. Cài đặt các thư mục và tập tin tương ứng, phục vụ sẵn sàng để những Script lập trình riêng (pre-set script) có thể khai thác sử dụng.
    """
    
    # Nơi chứa thư mục chứa Dữ liệu mô phỏng Local
    SIMULATION_DATA_DIR = os.path.join(
        os.path.dirname(__file__), 
        '../../uploads/simulations'
    )
    
    def __init__(self):
        # Đảm bảo môi trường file data đã được set up
        os.makedirs(self.SIMULATION_DATA_DIR, exist_ok=True)
        
        # Biến dictionary ở mức Application theo dõi trạng thái simulation qua Cache RAM.
        self._simulations: Dict[str, SimulationState] = {}
    
    def _get_simulation_dir(self, simulation_id: str) -> str:
        """Lấy trả về các đường dẫn thư mục gốc tương ứng với Simulation ID"""
        sim_dir = os.path.join(self.SIMULATION_DATA_DIR, simulation_id)
        os.makedirs(sim_dir, exist_ok=True)
        return sim_dir
    
    def _save_simulation_state(self, state: SimulationState):
        """Bật tính năng lưu state định dạng JSON ra ổ cứng"""
        sim_dir = self._get_simulation_dir(state.simulation_id)
        state_file = os.path.join(sim_dir, "state.json")
        
        state.updated_at = datetime.now().isoformat()
        
        with open(state_file, 'w', encoding='utf-8') as f:
            json.dump(state.to_dict(), f, ensure_ascii=False, indent=2)
        
        self._simulations[state.simulation_id] = state
    
    def _load_simulation_state(self, simulation_id: str) -> Optional[SimulationState]:
        """Load ngược lại data của tiến trình Mô Phỏng thông qua tệp cấu hình JSON"""
        if simulation_id in self._simulations:
            return self._simulations[simulation_id]
        
        sim_dir = self._get_simulation_dir(simulation_id)
        state_file = os.path.join(sim_dir, "state.json")
        
        if not os.path.exists(state_file):
            return None
        
        with open(state_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        state = SimulationState(
            simulation_id=simulation_id,
            project_id=data.get("project_id", ""),
            graph_id=data.get("graph_id", ""),
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
        Khởi tạo môi trường ảo / mới cho Mô Phỏng
        
        Args:
            project_id: Mã ID của Project (Quản lý cấp đầu vào)
            graph_id: Đồ thị ID tương ứng lấy bên Zep
            enable_twitter: Công tắc (Bật/Tắt) luồng giả lập Twitter
            enable_reddit: Công tắc (Bật/Tắt) luồng giả lập Reddit
            
        Returns:
            Đối tượng Class SimulationState
        """
        import uuid
        simulation_id = f"sim_{uuid.uuid4().hex[:12]}"
        
        state = SimulationState(
            simulation_id=simulation_id,
            project_id=project_id,
            graph_id=graph_id,
            enable_twitter=enable_twitter,
            enable_reddit=enable_reddit,
            status=SimulationStatus.CREATED,
        )
        
        self._save_simulation_state(state)
        logger.info(f"Created simulation: {simulation_id}, project={project_id}, graph={graph_id}")
        
        return state
    
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
        Giai đoạn chuẩn bị dữ liệu tạo giả lập mô phỏng (Tiến trình Automation 100%)
        
        Các bước diễn ra:
        1. Gọi lấy các cụm Entity (thực thể) và bộ lọt (filter) từ Zep Graph API
        2. Tự động khởi tạo hàng loạt Agent Profile chạy OASIS tương ứng với Entity (Hỗ trợ gọi AI LLM để làm mượt văn bản / tăng tốc chạy song song)
        3. Hỏi và bắt bot LLM suy luận ra hệ tham số setting thông minh nhất (thời gian mô phỏng rò rỉ, hệ số tần suất nói chuyện hoạt động ...)
        4. In ra các file cấu hình và JSON của profile để hệ thống dễ đọc
        5. Copy nguyên các Scripts chuẩn được cấu hình sẵn (preset) ném vào thư mục để chạy
        
        Args:
            simulation_id: Mã ID của chu trình giả lập
            simulation_requirement: Chuỗi text từ người dùng yêu cầu mô phỏng gì (gửi cho config sinh cấu hình)
            document_text: Nội dung file Raw nguyên thủy (Cho LLM đánh giá context bối cảnh ban đầu)
            defined_entity_types: Dánh sách các Entity Model có sẵn do Zep định nghĩa (Option)
            use_llm_for_profiles: Toggle tính năng sử dụng mô hình LLM để buff thêm chi tiết cài đặt con Bot
            progress_callback: Hàm callback update log progress (chuyển về màn hình Frontend view) format (stage, progress, message)
            parallel_profile_count: Giới hạn concurrent threading chạy LLM gọi profile (Default là 3 luồng cùng lúc để làm nhanh hơn)
            
        Returns:
            Class cài đặt Data - SimulationState
        """
        state = self._load_simulation_state(simulation_id)
        if not state:
            raise ValueError(f"Giả lập với ID: {simulation_id} không tồn tại")
        
        try:
            state.status = SimulationStatus.PREPARING
            self._save_simulation_state(state)
            
            sim_dir = self._get_simulation_dir(simulation_id)
            
            # ========== Giai đoạn 1: Kết nối lấy Node Data Entity và Sàng lọc ==========
            if progress_callback:
                progress_callback("reading", 0, "Connecting to Zep Graph data store...")
            
            reader = ZepEntityReader()
            
            if progress_callback:
                progress_callback("reading", 30, "Extracting Node data from graph...")
            
            filtered = reader.filter_defined_entities(
                graph_id=state.graph_id,
                defined_entity_types=defined_entity_types,
                enrich_with_edges=True
            )
            
            state.entities_count = filtered.filtered_count
            state.entity_types = list(filtered.entity_types)
            
            if progress_callback:
                progress_callback(
                    "reading", 100, 
                    f"Extraction complete, filtered entity count: {filtered.filtered_count} empty entities",
                    current=filtered.filtered_count,
                    total=filtered.filtered_count
                )
            
            if filtered.filtered_count == 0:
                state.status = SimulationStatus.FAILED
                state.error = "No valid entities extracted for simulation. Please check if the Graph was generated properly with valid text."
                self._save_simulation_state(state)
                return state
            
            # ========== Giai đoạn 2: Bắt đầu sinh Agent Profiles cho OASIS ==========
            total_entities = len(filtered.entities)
            
            if progress_callback:
                progress_callback(
                    "generating_profiles", 0, 
                    "Ready for AI Generation process...",
                    current=0,
                    total=total_entities
                )
            
            # Gửi mã graph_id để bộ Profile có thể fetch thêm tài liệu nếu model cần lục vấn sâu
            generator = OasisProfileGenerator(graph_id=state.graph_id)
            
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
            
            # Khai báo đường dẫn tạm để AI lưu Real-time kết quả (Đặt ưu tiên Platform Reddit JSON làm chuẩn)
            realtime_output_path = None
            realtime_platform = "reddit"
            if state.enable_reddit:
                realtime_output_path = os.path.join(sim_dir, "reddit_profiles.json")
                realtime_platform = "reddit"
            elif state.enable_twitter:
                realtime_output_path = os.path.join(sim_dir, "twitter_profiles.csv")
                realtime_platform = "twitter"

            # Nền tảng dùng cho metadata cost.
            if state.enable_twitter and state.enable_reddit:
                runtime_platform = "parallel"
            elif state.enable_twitter:
                runtime_platform = "twitter"
            elif state.enable_reddit:
                runtime_platform = "reddit"
            else:
                runtime_platform = None
            
            profiles = generator.generate_profiles_from_entities(
                entities=filtered.entities,
                use_llm=use_llm_for_profiles,
                progress_callback=profile_progress,
                graph_id=state.graph_id,  # Để tìm kiếm Zep Search Index
                parallel_count=parallel_profile_count,  # Số dòng luồng Async
                realtime_output_path=realtime_output_path,  # Lưu log thời gian thực
                output_platform=realtime_platform,  # Đuôi file xuất
                metadata_platform=runtime_platform,
                simulation_id=simulation_id,
                project_id=state.project_id,
            )
            
            state.profiles_count = len(profiles)
            
            # Backup lại kết quả Profile (Twitter xuất ra text CSV, Reddit thì bắt buộc JSON cho cấu trúc OASIS)
            # Reddit đã được render đồng thời ở block trên nhưng đây là re-save toàn bộ
            if progress_callback:
                progress_callback(
                    "generating_profiles", 95, 
                    "Compressing Profile data...",
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
                # Riêng Twitter với code Script base OAsis của họ yêu cầu CSV format
                generator.save_profiles(
                    profiles=profiles,
                    file_path=os.path.join(sim_dir, "twitter_profiles.csv"),
                    platform="twitter"
                )
            
            if progress_callback:
                progress_callback(
                    "generating_profiles", 100, 
                    f"Done, created {len(profiles)} Profiles",
                    current=len(profiles),
                    total=len(profiles)
                )
            
            # ========== Giai đoạn 3: Uỷ thác cho LLM phân tích và xuất tham số mô phỏng ==========
            if progress_callback:
                progress_callback(
                    "generating_config", 0, 
                    "Analyzing input requirements...",
                    current=0,
                    total=3
                )
            
            config_generator = SimulationConfigGenerator()
            
            if progress_callback:
                progress_callback(
                    "generating_config", 30, 
                    "LLM Bot is generating configuration...",
                    current=1,
                    total=3
                )
            
            sim_params = config_generator.generate_config(
                simulation_id=simulation_id,
                project_id=state.project_id,
                graph_id=state.graph_id,
                simulation_requirement=simulation_requirement,
                document_text=document_text,
                entities=filtered.entities,
                enable_twitter=state.enable_twitter,
                enable_reddit=state.enable_reddit
            )
            
            if progress_callback:
                progress_callback(
                    "generating_config", 70, 
                    "Saving Config parameters...",
                    current=2,
                    total=3
                )
            
            # Lưu file cứng simulation_config.json
            config_path = os.path.join(sim_dir, "simulation_config.json")
            with open(config_path, 'w', encoding='utf-8') as f:
                f.write(sim_params.to_json())
            
            state.config_generated = True
            state.config_reasoning = sim_params.generation_reasoning
            
            if progress_callback:
                progress_callback(
                    "generating_config", 100, 
                    "Configuration Generation complete",
                    current=3,
                    total=3
                )
            
            # Lưu ý kiến trúc: Các scripts thao tác thực thi vẫn để gốc ở `backend/scripts/`, SẼ KHÔNG CẦN chép đè sang folder Project
            # Tại thời gian Khởi chạy, `simulation_runner` sẽ nạp base chạy thẳng từ folder `scripts/` đó.
            
            # Cập nhật status
            state.status = SimulationStatus.READY
            self._save_simulation_state(state)
            
            logger.info(f"Finished simulation preparation phase for ID: {simulation_id}, "
                       f"Total entities={state.entities_count}, Created profiles={state.profiles_count}")
            
            return state
            
        except Exception as e:
            logger.error(f"Error occurred during Simulation preparation (Sim ID: {simulation_id}), ERROR CODE: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            state.status = SimulationStatus.FAILED
            state.error = str(e)
            self._save_simulation_state(state)
            raise
    
    def get_simulation(self, simulation_id: str) -> Optional[SimulationState]:
        """Đọc và lấy State hiện tại của Simulator"""
        return self._load_simulation_state(simulation_id)
    
    def list_simulations(self, project_id: Optional[str] = None) -> List[SimulationState]:
        """Liệt kê toàn bộ danh sách các Mô Phỏng (Simulations) đã khởi tạo"""
        simulations = []
        
        if os.path.exists(self.SIMULATION_DATA_DIR):
            for sim_id in os.listdir(self.SIMULATION_DATA_DIR):
                # Loại bỏ các folder/file rác do hệ điều hành sinh ra (ví dụ: .DS_Store của macOS) hoặc không phải thư mục
                sim_path = os.path.join(self.SIMULATION_DATA_DIR, sim_id)
                if sim_id.startswith('.') or not os.path.isdir(sim_path):
                    continue
                
                state = self._load_simulation_state(sim_id)
                if state:
                    if project_id is None or state.project_id == project_id:
                        simulations.append(state)
        
        return simulations
    
    def get_profiles(self, simulation_id: str, platform: str = "reddit") -> List[Dict[str, Any]]:
        """Lấy/Tải dữ liệu Agent Profile do AI sinh ra dựa theo nền tảng mạng xã hội"""
        state = self._load_simulation_state(simulation_id)
        if not state:
            raise ValueError(f"Simulation with ID {simulation_id} does not exist")
        
        sim_dir = self._get_simulation_dir(simulation_id)
        profile_path = os.path.join(sim_dir, f"{platform}_profiles.json")
        
        if not os.path.exists(profile_path):
            return []
        
        with open(profile_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def get_simulation_config(self, simulation_id: str) -> Optional[Dict[str, Any]]:
        """Lấy thông số cấu hình của bản mô phỏng"""
        sim_dir = self._get_simulation_dir(simulation_id)
        config_path = os.path.join(sim_dir, "simulation_config.json")
        
        if not os.path.exists(config_path):
            return None
        
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def get_run_instructions(self, simulation_id: str) -> Dict[str, str]:
        """Output ra hướng dẫn / Các câu lệnh dòng lệnh (CMD) để thực thi chạy bản đồ mô phỏng này"""
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
                f"1. Khởi động môi trường môi trường lập trình Conda (nếu có): conda activate MiroFish\n"
                f"2. Bắt đầu Run giả lập (Scripts gốc được gọi ra tại {scripts_dir}):\n"
                f"   - Nếu muốn chỉ giả lập trên Twitter: python {scripts_dir}/run_twitter_simulation.py --config {config_path}\n"
                f"   - Nếu muốn chỉ giả lập trên Reddit: python {scripts_dir}/run_reddit_simulation.py --config {config_path}\n"
                f"   - Chạy giả lập cả hai phân luồng song song: python {scripts_dir}/run_parallel_simulation.py --config {config_path}"
            )
        }
