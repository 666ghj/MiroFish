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


# ==============================================================================
# ENUM: SimulationStatus — Máy trạng thái (State Machine) của một Simulation
# ==============================================================================
# Mỗi simulation đi qua các trạng thái theo thứ tự:
#
#   CREATED ──► PREPARING ──► READY ──► RUNNING ──► COMPLETED
#                   │                      │
#                   └──────────────────────┴──► FAILED
#                                          │
#                                          └──► PAUSED ──► RUNNING (tiếp tục)
#                                          │
#                                          └──► STOPPED (người dùng chủ động dừng)
#
# Lưu ý: FAILED là trạng thái cuối cùng không thể tiếp tục — phải tạo simulation mới.
# ==============================================================================

class SimulationStatus(str, Enum):
    """Trạng thái hiện tại của quá trình mô phỏng"""
    CREATED = "created"      # Vừa được tạo, chưa làm gì cả
    PREPARING = "preparing"  # Đang chạy prepare_simulation() — đọc entity, sinh profile, tạo config
    READY = "ready"          # prepare_simulation() hoàn thành — sẵn sàng bấm nút chạy OASIS
    RUNNING = "running"      # OASIS subprocess đang chạy, agents đang hành động
    PAUSED = "paused"        # Người dùng ra lệnh pause qua IPC — OASIS tạm dừng vòng lặp
    STOPPED = "stopped"      # Người dùng chủ động dừng — OASIS bị kill, kết quả còn lại được giữ
    COMPLETED = "completed"  # OASIS chạy hết số vòng (max_rounds) và thoát thành công
    FAILED = "failed"        # Exception không xử lý được — pipeline bị gián đoạn


class PlatformType(str, Enum):
    """Phân loại nền tảng giả lập Mạng xã hội"""
    TWITTER = "twitter"
    REDDIT = "reddit"


# ==============================================================================
# DATACLASS: SimulationState — "Hộp đen" lưu toàn bộ thông tin một simulation
# ==============================================================================
# Đây là đối tượng trung tâm được đọc/ghi liên tục trong suốt vòng đời simulation.
# Nó được lưu ở hai nơi đồng thời:
#   1. RAM: `SimulationManager._simulations` dict (tra cứu nhanh O(1))
#   2. Disk: `<SIMULATION_DATA_DIR>/<simulation_id>/state.json` (bền vững qua restart)
# ==============================================================================

@dataclass
class SimulationState:
    """Class lưu trữ cấu trúc Dữ liệu/Trạng thái của một lượt mô phỏng"""

    # --- Định danh ---
    simulation_id: str   # UUID dạng "sim_<12 ký tự hex>", ví dụ: "sim_a3f8c21b004e"
    project_id: str      # ID của Project chứa simulation này (quản lý nhiều sim cùng lúc)
    graph_id: str        # ID của Zep Graph — xác định kho Entity nào sẽ dùng làm agent

    # --- Công tắc nền tảng ---
    # Cho phép chọn chạy 1 hoặc cả 2 nền tảng. Nếu cả hai False → pipeline sẽ bỏ qua bước sinh profile.
    enable_twitter: bool = True
    enable_reddit: bool = True

    # --- Trạng thái vòng đời ---
    # Giá trị mặc định CREATED; được cập nhật qua _save_simulation_state() mỗi khi chuyển giai đoạn.
    status: SimulationStatus = SimulationStatus.CREATED

    # --- Kết quả thống kê của giai đoạn PREPARING ---
    entities_count: int = 0          # Số entity đọc được từ Zep (sau khi lọc)
    profiles_count: int = 0          # Số agent profile đã sinh thành công
    entity_types: List[str] = field(default_factory=list)  # Danh sách loại entity (ví dụ: ["Person", "Organization"])

    # --- Kết quả sinh config ---
    config_generated: bool = False   # True sau khi simulation_config.json được ghi ra đĩa
    config_reasoning: str = ""       # Chuỗi giải thích của LLM tại sao chọn các tham số này

    # --- Dữ liệu runtime (cập nhật theo thời gian thực trong khi RUNNING) ---
    current_round: int = 0           # Vòng hiện tại OASIS đang chạy (0-indexed)
    twitter_status: str = "not_started"  # Trạng thái chi tiết của luồng Twitter
    reddit_status: str = "not_started"   # Trạng thái chi tiết của luồng Reddit

    # --- Timestamp lịch sử ---
    # Lưu dạng ISO 8601 (ví dụ: "2025-01-15T10:30:45.123456") để dễ parse lại
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    # --- Lỗi ---
    # None nếu không có lỗi; nếu có chứa message dạng string để hiển thị cho frontend
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """
        Xuất toàn bộ state thành dict đầy đủ.

        Dùng khi:
        - Ghi ra file state.json (để khôi phục lại khi server restart)
        - Truyền nội bộ giữa các service Python

        Khác với to_simple_dict(): bản này có đầy đủ mọi trường,
        kể cả các trường nặng như config_reasoning và timestamps.
        """
        return {
            "simulation_id": self.simulation_id,
            "project_id": self.project_id,
            "graph_id": self.graph_id,
            "enable_twitter": self.enable_twitter,
            "enable_reddit": self.enable_reddit,
            "status": self.status.value,          # Enum → string (ví dụ: "preparing")
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
        """
        Xuất state thành dict gọn nhẹ cho API response trả về client/frontend.

        Lược bỏ các trường nội bộ nặng (config_reasoning, timestamps, platform statuses...)
        để giảm payload JSON và không để lộ thông tin debug ra ngoài.
        """
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


# ==============================================================================
# CLASS: SimulationManager — Trung tâm điều phối toàn bộ vòng đời simulation
# ==============================================================================
# SimulationManager là singleton (dùng chung 1 instance) được Flask khởi tạo lúc boot.
# Nó KHÔNG chạy OASIS trực tiếp — việc đó do SimulationRunner đảm nhiệm.
# Nhiệm vụ chính: chuẩn bị dữ liệu (prepare) và theo dõi trạng thái (state tracking).
# ==============================================================================

class SimulationManager:
    """
    Kịch bản Quản lý trung tâm của tính năng Mô Phỏng

    Luồng thiết lập cốt lõi:
    1. Trích xuất nhóm các Thực Thể (Entity) được định nghĩa sẵn trong hệ thống lưu trữ Graph của Zep.
    2. Chế lại thành các hồ sơ Profile thiết lập tiêu chuẩn của OASIS framework (Agent)
    3. Trao quyền cho sức mạnh mô hình LLM tự đánh giá số liệu rồi tự sinh ra cấu hình cài đặt cho quá trình mô phỏng
    4. Cài đặt các thư mục và tập tin tương ứng, phục vụ sẵn sàng để những Script lập trình riêng (pre-set script) có thể khai thác sử dụng.
    """

    # Đường dẫn gốc nơi lưu tất cả dữ liệu simulation (mỗi sim có subfolder riêng).
    # __file__ = .../backend/app/services/simulation_manager.py
    # → join 2 cấp "../.." → .../backend/
    # → join "uploads/simulations" → .../backend/uploads/simulations/
    SIMULATION_DATA_DIR = os.path.join(
        os.path.dirname(__file__),
        '../../uploads/simulations'
    )

    def __init__(self):
        # Tạo thư mục gốc nếu chưa tồn tại (exist_ok=True → không báo lỗi nếu đã có)
        os.makedirs(self.SIMULATION_DATA_DIR, exist_ok=True)

        # Cache RAM: dict ánh xạ simulation_id → SimulationState
        # Mục đích: tránh đọc file state.json mỗi lần có request API → tra cứu O(1)
        # Nhược điểm: mất dữ liệu khi server restart → có disk backup bù lại
        self._simulations: Dict[str, SimulationState] = {}

    # --------------------------------------------------------------------------
    # PRIVATE HELPERS — Quản lý file/thư mục và cơ chế hai lớp cache
    # --------------------------------------------------------------------------

    def _get_simulation_dir(self, simulation_id: str) -> str:
        """
        Trả về đường dẫn thư mục chứa dữ liệu của một simulation cụ thể.
        Tự động tạo thư mục nếu chưa tồn tại (lazy creation).

        Cấu trúc thư mục sau khi READY:
            uploads/simulations/<simulation_id>/
            ├── state.json              ← trạng thái vòng đời
            ├── simulation_config.json  ← tham số OASIS do LLM sinh
            ├── reddit_profiles.json    ← agent profiles cho Reddit
            └── twitter_profiles.csv   ← agent profiles cho Twitter
        """
        sim_dir = os.path.join(self.SIMULATION_DATA_DIR, simulation_id)
        os.makedirs(sim_dir, exist_ok=True)  # Idempotent: gọi nhiều lần vẫn an toàn
        return sim_dir

    def _save_simulation_state(self, state: SimulationState):
        """
        Ghi state xuống disk VÀ cập nhật vào RAM cache đồng thời.

        Đây là cơ chế "write-through cache":
        - Mỗi khi state thay đổi, cả RAM lẫn file đều được cập nhật ngay lập tức.
        - Đảm bảo: nếu server crash giữa chừng, state.json vẫn phản ánh trạng thái mới nhất.

        Tự động cập nhật updated_at thành thời điểm hiện tại trước khi ghi.
        """
        sim_dir = self._get_simulation_dir(state.simulation_id)
        state_file = os.path.join(sim_dir, "state.json")

        # Stamp thời gian ghi cuối cùng
        state.updated_at = datetime.now().isoformat()

        # Ghi JSON ra đĩa (ensure_ascii=False để Unicode/tiếng Việt không bị escape)
        with open(state_file, 'w', encoding='utf-8') as f:
            json.dump(state.to_dict(), f, ensure_ascii=False, indent=2)

        # Cập nhật đồng thời vào RAM cache
        self._simulations[state.simulation_id] = state

    def _load_simulation_state(self, simulation_id: str) -> Optional[SimulationState]:
        """
        Đọc state của một simulation — ưu tiên dùng RAM cache, fallback về disk.

        Chiến lược "cache-aside":
        1. Kiểm tra RAM cache trước (nhanh, không I/O)
        2. Nếu không có trong RAM → tìm file state.json trên disk
        3. Nếu tìm thấy → deserialize thành SimulationState object, nạp vào RAM cache
        4. Nếu không tìm thấy file → trả về None

        Trường hợp None: simulation_id không hợp lệ hoặc chưa từng được tạo.
        """
        # --- Bước 1: Kiểm tra RAM cache ---
        if simulation_id in self._simulations:
            return self._simulations[simulation_id]

        # --- Bước 2: Tìm trên disk ---
        sim_dir = self._get_simulation_dir(simulation_id)
        state_file = os.path.join(sim_dir, "state.json")

        if not os.path.exists(state_file):
            return None  # Simulation này chưa từng tồn tại

        # --- Bước 3: Deserialize từ JSON thành dataclass ---
        with open(state_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Khôi phục từng field, dùng .get() với giá trị mặc định để tương thích ngược
        # khi có field mới được thêm vào SimulationState sau này
        state = SimulationState(
            simulation_id=simulation_id,
            project_id=data.get("project_id", ""),
            graph_id=data.get("graph_id", ""),
            enable_twitter=data.get("enable_twitter", True),
            enable_reddit=data.get("enable_reddit", True),
            status=SimulationStatus(data.get("status", "created")),  # string → Enum
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

        # --- Bước 4: Nạp vào RAM cache để lần sau không cần đọc file nữa ---
        self._simulations[simulation_id] = state
        return state

    # --------------------------------------------------------------------------
    # PUBLIC: create_simulation — Khởi tạo một simulation mới (trạng thái CREATED)
    # --------------------------------------------------------------------------

    def create_simulation(
        self,
        project_id: str,
        graph_id: str,
        enable_twitter: bool = True,
        enable_reddit: bool = True,
    ) -> SimulationState:
        """
        Tạo một simulation mới với trạng thái ban đầu CREATED.

        Chỉ tạo metadata — KHÔNG đọc entity, KHÔNG gọi LLM.
        Sau khi gọi hàm này, cần gọi tiếp prepare_simulation() để chuẩn bị dữ liệu.

        Args:
            project_id: Mã ID của Project (Quản lý cấp đầu vào)
            graph_id: Đồ thị ID tương ứng lấy bên Zep — quyết định kho Entity nào được dùng
            enable_twitter: Có sinh profile và chạy mô phỏng trên Twitter không?
            enable_reddit: Có sinh profile và chạy mô phỏng trên Reddit không?

        Returns:
            SimulationState với status=CREATED, chưa có entity/profile/config.
        """
        import uuid

        # Tạo ID ngắn gọn, dễ đọc: "sim_" + 12 ký tự hex ngẫu nhiên
        # Ví dụ: "sim_a3f8c21b004e" — đủ ngẫu nhiên để tránh va chạm trong phạm vi project
        simulation_id = f"sim_{uuid.uuid4().hex[:12]}"

        # Khởi tạo object state với giá trị mặc định
        state = SimulationState(
            simulation_id=simulation_id,
            project_id=project_id,
            graph_id=graph_id,
            enable_twitter=enable_twitter,
            enable_reddit=enable_reddit,
            status=SimulationStatus.CREATED,
        )

        # Ghi ra disk ngay lập tức để đảm bảo bền vững
        self._save_simulation_state(state)
        logger.info(f"Created simulation: {simulation_id}, project={project_id}, graph={graph_id}")

        return state

    # --------------------------------------------------------------------------
    # PUBLIC: prepare_simulation — Pipeline chuẩn bị dữ liệu (3 giai đoạn chính)
    # --------------------------------------------------------------------------

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

        Hàm này chạy trong một background thread (được Flask gọi không đồng bộ).
        Progress được báo cáo liên tục về frontend qua progress_callback.

        3 giai đoạn chính:
        ┌─────────────────────────────────────────────────────────────────────────┐
        │ Giai đoạn 1: ĐỌC ENTITY từ Zep Graph                                   │
        │   ZepEntityReader → lọc theo defined_entity_types → FilteredEntities    │
        │   Nếu không có entity nào → FAILED (không thể tiếp tục)                │
        ├─────────────────────────────────────────────────────────────────────────┤
        │ Giai đoạn 2: SINH AGENT PROFILE                                         │
        │   OasisProfileGenerator → gọi LLM song song (ThreadPoolExecutor)        │
        │   → reddit_profiles.json + twitter_profiles.csv                         │
        ├─────────────────────────────────────────────────────────────────────────┤
        │ Giai đoạn 3: SINH SIMULATION CONFIG                                     │
        │   SimulationConfigGenerator → LLM phân tích → simulation_config.json   │
        └─────────────────────────────────────────────────────────────────────────┘

        Args:
            simulation_id: ID của simulation đã tạo bằng create_simulation()
            simulation_requirement: Yêu cầu mô phỏng từ người dùng (gửi cho LLM sinh config)
            document_text: Nội dung văn bản gốc (ngữ cảnh để LLM hiểu chủ đề đang mô phỏng)
            defined_entity_types: Danh sách loại entity cần lọc (None = lấy tất cả)
            use_llm_for_profiles: True = gọi LLM để làm giàu persona; False = dùng rule-based
            progress_callback: Hàm nhận (stage: str, percent: int, message: str, **kwargs)
            parallel_profile_count: Số thread LLM chạy song song khi sinh profile (mặc định 3)

        Returns:
            SimulationState với status=READY (thành công) hoặc status=FAILED (thất bại)

        Raises:
            ValueError: Nếu simulation_id không tồn tại
            Exception: Re-raise mọi lỗi sau khi đã cập nhật state sang FAILED
        """
        # Load state hiện tại — phải tồn tại trước (đã gọi create_simulation())
        state = self._load_simulation_state(simulation_id)
        if not state:
            raise ValueError(f"Giả lập với ID: {simulation_id} không tồn tại")

        try:
            # --- Chuyển trạng thái sang PREPARING ngay từ đầu ---
            # Quan trọng: ghi xuống disk trước để nếu crash sau đó,
            # frontend không bị thấy state "CREATED" mãi mãi
            state.status = SimulationStatus.PREPARING
            self._save_simulation_state(state)

            # Lấy đường dẫn thư mục để ghi các file output
            sim_dir = self._get_simulation_dir(simulation_id)

            # ==========================================================================
            # GIAI ĐOẠN 1: Kết nối Zep và lọc Entity
            # ==========================================================================
            # ZepEntityReader đọc TẤT CẢ nodes trong graph (có thể hàng nghìn nodes),
            # sau đó lọc chỉ giữ lại các node có label nằm trong defined_entity_types.
            # Kết quả trả về là FilteredEntities chứa danh sách EntityNode đã enrich.
            # Retry: 3 lần với exponential backoff (2s → 4s → 8s).
            # ==========================================================================
            if progress_callback:
                progress_callback("reading", 0, "Connecting to Zep Graph data store...")

            reader = ZepEntityReader()

            if progress_callback:
                progress_callback("reading", 30, "Extracting Node data from graph...")

            # filter_defined_entities: đọc nodes → lọc theo label → enrich với edges
            # enrich_with_edges=True → mỗi EntityNode sẽ có related_edges & related_nodes
            # (cần thiết để LLM hiểu mối quan hệ giữa các entity khi sinh persona)
            filtered = reader.filter_defined_entities(
                graph_id=state.graph_id,
                defined_entity_types=defined_entity_types,
                enrich_with_edges=True
            )

            # Ghi số liệu thống kê vào state
            state.entities_count = filtered.filtered_count
            state.entity_types = list(filtered.entity_types)

            if progress_callback:
                progress_callback(
                    "reading", 100,
                    f"Extraction complete, filtered entity count: {filtered.filtered_count} empty entities",
                    current=filtered.filtered_count,
                    total=filtered.filtered_count
                )

            # --- Early exit: không có entity nào → không thể chạy simulation ---
            # Lý do có thể: graph chưa được populate, hoặc defined_entity_types quá hẹp
            if filtered.filtered_count == 0:
                state.status = SimulationStatus.FAILED
                state.error = "No valid entities extracted for simulation. Please check if the Graph was generated properly with valid text."
                self._save_simulation_state(state)
                return state  # Trả về sớm, không raise exception

            # ==========================================================================
            # GIAI ĐOẠN 2: Sinh Agent Profile cho từng Entity
            # ==========================================================================
            # Mỗi EntityNode → 1 OasisAgentProfile (có user_id, bio, persona, mbti, ...)
            # Nếu use_llm=True: gọi LLM để viết bio/persona phong phú hơn
            # Nếu use_llm=False: dùng rule-based (nhanh hơn, ít tốn token hơn)
            # Chạy parallel_profile_count threads đồng thời để tăng tốc.
            # ==========================================================================
            total_entities = len(filtered.entities)

            if progress_callback:
                progress_callback(
                    "generating_profiles", 0,
                    "Ready for AI Generation process...",
                    current=0,
                    total=total_entities
                )

            # Khởi tạo generator — truyền graph_id để nó có thể search Zep thêm nếu cần
            generator = OasisProfileGenerator(graph_id=state.graph_id)

            # Wrapper chuyển đổi format callback:
            # generate_profiles_from_entities gọi: callback(current_count, total, entity_name)
            # Nhưng prepare_simulation cần format:  callback(stage, percent, message, ...)
            def profile_progress(current, total, msg):
                if progress_callback:
                    progress_callback(
                        "generating_profiles",
                        int(current / total * 100),  # Tính phần trăm hoàn thành
                        msg,
                        current=current,
                        total=total,
                        item_name=msg
                    )

            # --- Xác định đường dẫn real-time output ---
            # Real-time output: trong khi LLM đang sinh profile, file được ghi dần dần
            # (không đợi hết rồi mới ghi một lần) → frontend có thể theo dõi tiến độ
            # Ưu tiên Reddit vì đó là format JSON chuẩn; Twitter dùng CSV (chỉ khi Reddit tắt)
            realtime_output_path = None
            realtime_platform = "reddit"
            if state.enable_reddit:
                realtime_output_path = os.path.join(sim_dir, "reddit_profiles.json")
                realtime_platform = "reddit"
            elif state.enable_twitter:
                # Chỉ đến đây nếu Reddit bị tắt hẳn
                realtime_output_path = os.path.join(sim_dir, "twitter_profiles.csv")
                realtime_platform = "twitter"

            # --- Xác định platform metadata (để tính cost API) ---
            # "parallel" = cả hai nền tảng đều bật → profiles được dùng cho cả hai
            if state.enable_twitter and state.enable_reddit:
                runtime_platform = "parallel"
            elif state.enable_twitter:
                runtime_platform = "twitter"
            elif state.enable_reddit:
                runtime_platform = "reddit"
            else:
                runtime_platform = None  # Không nên xảy ra trong thực tế

            # Gọi hàm sinh profile chính (blocking — chờ tất cả thread hoàn thành)
            profiles = generator.generate_profiles_from_entities(
                entities=filtered.entities,
                use_llm=use_llm_for_profiles,
                progress_callback=profile_progress,
                graph_id=state.graph_id,            # Để tìm kiếm trong Zep Search Index nếu cần
                parallel_count=parallel_profile_count,  # Số thread LLM chạy đồng thời
                realtime_output_path=realtime_output_path,  # Ghi từng profile vừa xong ngay
                output_platform=realtime_platform,  # Định dạng file (json/csv)
                metadata_platform=runtime_platform, # Cho logging cost
                simulation_id=simulation_id,
                project_id=state.project_id,
            )

            state.profiles_count = len(profiles)

            # --- Lưu lần cuối toàn bộ profiles ra file ---
            # (real-time output ở trên có thể bị thiếu nếu một thread crash)
            # Đây là lần ghi đảm bảo file hoàn chỉnh 100%
            if progress_callback:
                progress_callback(
                    "generating_profiles", 95,
                    "Compressing Profile data...",
                    current=total_entities,
                    total=total_entities
                )

            if state.enable_reddit:
                # Reddit: JSON array các object profile (cấu trúc OASIS yêu cầu)
                generator.save_profiles(
                    profiles=profiles,
                    file_path=os.path.join(sim_dir, "reddit_profiles.json"),
                    platform="reddit"
                )

            if state.enable_twitter:
                # Twitter: CSV với header row (cấu trúc OASIS gốc yêu cầu)
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

            # ==========================================================================
            # GIAI ĐOẠN 3: Sinh simulation_config.json bằng LLM
            # ==========================================================================
            # SimulationConfigGenerator gọi LLM với:
            #   - simulation_requirement (yêu cầu của user)
            #   - document_text (văn bản nguồn)
            #   - entities (danh sách entity)
            # LLM trả về SimulationParameters gồm: time_config, event_config, agent_configs
            # Toàn bộ được serialize thành JSON và ghi ra simulation_config.json.
            # File này sau đó được đọc bởi run_parallel_simulation.py khi OASIS chạy.
            # ==========================================================================
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

            # generate_config: gọi LLM tạo time_config → event_config → agent_configs
            # (3 lần gọi LLM riêng biệt, mỗi lần có retry với exponential backoff)
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

            # Ghi simulation_config.json ra thư mục của simulation
            config_path = os.path.join(sim_dir, "simulation_config.json")
            with open(config_path, 'w', encoding='utf-8') as f:
                f.write(sim_params.to_json())  # to_json() đã xử lý serialize Enum, nested dict

            # Đánh dấu config đã sinh xong và lưu lý do LLM giải thích
            state.config_generated = True
            state.config_reasoning = sim_params.generation_reasoning

            if progress_callback:
                progress_callback(
                    "generating_config", 100,
                    "Configuration Generation complete",
                    current=3,
                    total=3
                )

            # ==========================================================================
            # LƯU Ý KIẾN TRÚC QUAN TRỌNG:
            # Scripts OASIS (run_parallel_simulation.py, v.v.) vẫn để GỐC tại
            # `backend/scripts/` — KHÔNG copy sang thư mục simulation.
            # Khi SimulationRunner.start() chạy, nó sẽ gọi thẳng script gốc và
            # truyền --config <config_path> để script đọc đúng dữ liệu simulation.
            # Lý do: tránh code duplication, dễ update script mà không ảnh hưởng
            # các simulation đã chuẩn bị sẵn.
            # ==========================================================================

            # --- Chuyển trạng thái sang READY — pipeline hoàn tất ---
            state.status = SimulationStatus.READY
            self._save_simulation_state(state)

            logger.info(f"Finished simulation preparation phase for ID: {simulation_id}, "
                       f"Total entities={state.entities_count}, Created profiles={state.profiles_count}")

            return state

        except Exception as e:
            # --- Xử lý lỗi toàn cục: bất kỳ exception nào cũng → FAILED ---
            # Ghi lại traceback đầy đủ để debug, sau đó re-raise để Flask xử lý tiếp
            logger.error(f"Error occurred during Simulation preparation (Sim ID: {simulation_id}), ERROR CODE: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())

            # Cập nhật state FAILED với message lỗi để frontend hiển thị
            state.status = SimulationStatus.FAILED
            state.error = str(e)
            self._save_simulation_state(state)

            raise  # Re-raise để Flask API handler nhận và trả HTTP 500

    # --------------------------------------------------------------------------
    # PUBLIC UTILITIES — Các hàm đọc/truy vấn trạng thái
    # --------------------------------------------------------------------------

    def get_simulation(self, simulation_id: str) -> Optional[SimulationState]:
        """
        Lấy trạng thái hiện tại của một simulation.
        Dùng cache-aside (RAM trước, disk fallback) nên rất nhanh.
        Trả về None nếu simulation_id không tồn tại.
        """
        return self._load_simulation_state(simulation_id)

    def list_simulations(self, project_id: Optional[str] = None) -> List[SimulationState]:
        """
        Liệt kê tất cả simulations, có thể lọc theo project_id.

        Duyệt qua toàn bộ thư mục con trong SIMULATION_DATA_DIR,
        load state.json của từng cái, rồi lọc theo project_id nếu có yêu cầu.

        Args:
            project_id: Nếu None → trả về tất cả; nếu có → chỉ trả về của project đó

        Returns:
            Danh sách SimulationState (có thể rỗng nếu chưa có simulation nào)
        """
        simulations = []

        if os.path.exists(self.SIMULATION_DATA_DIR):
            for sim_id in os.listdir(self.SIMULATION_DATA_DIR):
                # Bỏ qua các file ẩn (ví dụ: .DS_Store của macOS, .gitkeep)
                # và các entry không phải thư mục (ví dụ: file rác nào đó)
                sim_path = os.path.join(self.SIMULATION_DATA_DIR, sim_id)
                if sim_id.startswith('.') or not os.path.isdir(sim_path):
                    continue

                state = self._load_simulation_state(sim_id)
                if state:
                    # Lọc theo project_id nếu được chỉ định
                    if project_id is None or state.project_id == project_id:
                        simulations.append(state)

        return simulations

    def get_profiles(self, simulation_id: str, platform: str = "reddit") -> List[Dict[str, Any]]:
        """
        Đọc và trả về danh sách agent profiles đã sinh cho một simulation.

        Chỉ hoạt động sau khi prepare_simulation() hoàn thành (status=READY trở lên).
        Trả về [] nếu file chưa tồn tại (simulation chưa READY hoặc nền tảng bị tắt).

        Args:
            simulation_id: ID của simulation
            platform: "reddit" → đọc reddit_profiles.json | "twitter" → đọc twitter_profiles.json
                      (Twitter thực ra lưu .csv nhưng hàm này chỉ dùng cho Reddit JSON)

        Returns:
            List của các dict profile (mỗi dict là 1 agent)
        """
        state = self._load_simulation_state(simulation_id)
        if not state:
            raise ValueError(f"Simulation with ID {simulation_id} does not exist")

        sim_dir = self._get_simulation_dir(simulation_id)
        profile_path = os.path.join(sim_dir, f"{platform}_profiles.json")

        if not os.path.exists(profile_path):
            return []  # File chưa được sinh, trả về rỗng thay vì raise lỗi

        with open(profile_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def get_simulation_config(self, simulation_id: str) -> Optional[Dict[str, Any]]:
        """
        Đọc và trả về nội dung simulation_config.json của một simulation.

        Trả về None nếu config chưa được sinh (chưa qua giai đoạn 3 của prepare_simulation).
        Dữ liệu trả về là dict Python (đã parse JSON), không phải string.
        """
        sim_dir = self._get_simulation_dir(simulation_id)
        config_path = os.path.join(sim_dir, "simulation_config.json")

        if not os.path.exists(config_path):
            return None

        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def get_run_instructions(self, simulation_id: str) -> Dict[str, str]:
        """
        Tạo ra các câu lệnh terminal để chạy simulation này thủ công.

        Hữu ích khi developer muốn chạy OASIS trực tiếp ngoài Flask,
        hoặc để debug từng nền tảng riêng lẻ.

        Returns:
            Dict gồm:
            - simulation_dir: thư mục chứa dữ liệu simulation
            - scripts_dir: thư mục chứa các script OASIS
            - config_file: đường dẫn đầy đủ đến simulation_config.json
            - commands: dict các lệnh python để chạy từng loại
            - instructions: chuỗi hướng dẫn dạng đọc được cho con người
        """
        sim_dir = self._get_simulation_dir(simulation_id)
        config_path = os.path.join(sim_dir, "simulation_config.json")

        # Tính đường dẫn tuyệt đối đến thư mục scripts từ vị trí file này
        # __file__ = .../backend/app/services/simulation_manager.py
        # → abspath("../../scripts") = .../backend/scripts/
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
