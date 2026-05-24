"""
Trình tạo cấu hình Simulation tự động bằng LLM

Vị trí trong pipeline:
─────────────────────────────────────────────────────────────────────────────
  simulation_manager.prepare_simulation()  [Giai đoạn 3 — bước cuối cùng]
      └─ SimulationConfigGenerator.generate_config()
              ├─ _generate_time_config()      [LLM → bao nhiêu giờ, giờ nào cao điểm]
              ├─ _generate_event_config()     [LLM → hot topics, initial posts]
              ├─ _generate_agent_configs_batch() × N  [LLM → hành vi từng agent]
              └─ _assign_initial_post_agents()  [ghép poster_type → agent_id]
─────────────────────────────────────────────────────────────────────────────

Input:  List[EntityNode] từ ZepEntityReader + document_text + simulation_requirement
Output: SimulationParameters → ghi ra simulation_config.json
        (File này sau đó được đọc bởi run_parallel_simulation.py khi OASIS chạy)

Chiến lược LLM chia từng bước:
  Thay vì gửi toàn bộ dữ liệu 1 lần (dễ bị token limit), chia thành 4 bước nhỏ:
  1. Time config  — context cắt còn 10,000 ký tự 
  2. Event config — context cắt còn 8,000 ký tự
  3. Agent configs — chia batch 15 agent/lần (N batch)
  4. Platform config — hardcoded (không cần LLM)
"""

import json
import math
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field, asdict
from datetime import datetime

from openai import OpenAI

from ..config import Config
from ..utils.logger import get_logger
from ..utils.llm_cost import create_tracked_chat_completion
from .zep_entity_reader import EntityNode, ZepEntityReader

logger = get_logger('mirofish.simulation_config')


# ==============================================================================
# HẰNG SỐ: CHINA_TIMEZONE_CONFIG — Mẫu hoạt động theo múi giờ UTC+7
# ==============================================================================
# Lưu ý tên biến: được kế thừa từ codebase OASIS gốc của Trung Quốc (UTC+8).
# Thực tế trong MiroFish, hệ thống đã chuyển sang dùng múi giờ Việt Nam (UTC+7) —
# các prompt LLM đều chỉ định "người Việt Nam / giờ Hà Nội".
# Biến này hiện chỉ dùng để tham khảo/documentation, KHÔNG được import trực tiếp
# vào các hàm tạo config (logic thực tế nằm trong prompt LLM và rule fallback).
# ==============================================================================

CHINA_TIMEZONE_CONFIG = {
    # Khung giờ khuya (Hầu như không có hoạt động)
    "dead_hours": [0, 1, 2, 3, 4, 5],
    # Khung giờ sáng (Dần thức dậy)
    "morning_hours": [6, 7, 8],
    # Khung giờ làm việc
    "work_hours": [9, 10, 11, 12, 13, 14, 15, 16, 17, 18],
    # Khung giờ cao điểm buổi tối (Hoạt động mạnh nhất)
    "peak_hours": [19, 20, 21, 22],
    # Khung giờ ban đêm (Hoạt động giảm sút)
    "night_hours": [23],
    # Hệ số hoạt động tương ứng với mỗi thời điểm
    "activity_multipliers": {
        "dead": 0.05,      # Gần như không có ai lúc rạng sáng
        "morning": 0.4,    # Sáng sớm bắt đầu dần sôi động
        "work": 0.7,       # Mức trung bình trong giờ làm việc
        "peak": 1.5,       # Cao điểm tối
        "night": 0.5       # Giảm sút đêm khuya
    }
}


# ==============================================================================
# DATACLASS: AgentActivityConfig — Cấu hình hành vi của một agent trong OASIS
# ==============================================================================
# Mỗi AgentActivityConfig tương ứng với 1 EntityNode đã được map thành agent.
# OASIS đọc các field này để quyết định:
#   - Agent này có "thức dậy" trong round này không? (activity_level)
#   - Nếu thức, nó làm gì? (posts_per_hour, comments_per_hour, stance)
#   - Bài của nó được bao nhiêu agent khác nhìn thấy? (influence_weight)
# ==============================================================================

@dataclass
class AgentActivityConfig:
    """Cấu hình hoạt động cho một Agent"""

    # --- Định danh ---
    agent_id: int          # Phải khớp với user_id trong reddit_profiles.json / twitter_profiles.csv
    entity_uuid: str       # UUID trong Zep — dùng để trace ngược lại nguồn gốc
    entity_name: str       # Tên hiển thị (ví dụ: "Trần Văn An")
    entity_type: str       # Loại entity (ví dụ: "Student", "MediaOutlet")

    # --- Mức độ hoạt động tổng thể ---
    # 0.0 = không bao giờ hoạt động; 1.0 = luôn hoạt động mỗi round
    # OASIS dùng giá trị này nhân với activity_multiplier của giờ hiện tại
    # để tính xác suất agent được chọn trong round.
    activity_level: float = 0.5

    # --- Tần suất phát ngôn ---
    # Số lần trung bình agent đăng bài mới / bình luận trong 1 giờ mô phỏng
    posts_per_hour: float = 1.0
    comments_per_hour: float = 2.0

    # --- Khoảng thời gian hoạt động (hệ 24 giờ, 0–23) ---
    # Agent chỉ có thể được kích hoạt trong các giờ này.
    # Ví dụ: student=[8,9,10,18,19,20,21,22,23], university=[9,10,...,17]
    active_hours: List[int] = field(default_factory=lambda: list(range(8, 23)))

    # --- Tốc độ phản hồi ---
    # Độ trễ (phút mô phỏng) trước khi agent phản ứng với sự kiện nóng.
    # Nhỏ = phản ứng nhanh (sinh viên: 1-15 phút)
    # Lớn = phản ứng chậm (cơ quan chính phủ: 60-240 phút)
    response_delay_min: int = 5
    response_delay_max: int = 60

    # --- Khuynh hướng cảm xúc ---
    # -1.0 = rất tiêu cực (phản đối mạnh mẽ)
    #  0.0 = trung lập
    # +1.0 = rất tích cực (ủng hộ nhiệt tình)
    sentiment_bias: float = 0.0

    # --- Lập trường với chủ đề mô phỏng ---
    # "supportive": ủng hộ quyết định/sự kiện được mô phỏng
    # "opposing": phản đối
    # "neutral": không rõ ràng, phân tích khách quan
    # "observer": chỉ theo dõi, ít tham gia tranh luận
    stance: str = "neutral"

    # --- Trọng số ảnh hưởng ---
    # Mức độ bài đăng của agent này xuất hiện trên "timeline" của agent khác.
    # Cao = lan rộng hơn (mediaoutlet: 2.5, university: 3.0)
    # Thấp = ít người thấy (student: 0.8)
    influence_weight: float = 1.0


# ==============================================================================
# DATACLASS: TimeSimulationConfig — Cấu hình thời gian và nhịp hoạt động
# ==============================================================================
# Định nghĩa "lịch sinh hoạt" của thế giới mô phỏng:
#   - Tổng độ dài mô phỏng (total_simulation_hours)
#   - Mỗi round đại diện cho bao nhiêu phút thực (minutes_per_round)
#   - Khung giờ nào sẽ có nhiều hay ít agent hoạt động (peak/off_peak/morning/work)
#
# OASIS đọc các multiplier để tính số agent active mỗi round:
#   active_count = random(min, max) × multiplier[current_hour]
# ==============================================================================

@dataclass
class TimeSimulationConfig:
    """Cấu hình thời gian mô phỏng"""

    # Tổng số giờ mô phỏng — 72 giờ = 3 ngày thực
    # (Với minutes_per_round=60, tổng số round = 72)
    total_simulation_hours: int = 72

    # Mỗi round đại diện cho bao nhiêu phút trong thế giới thực
    # 60 = mỗi round là 1 giờ (khuyến nghị để cân bằng tốc độ vs độ chi tiết)
    minutes_per_round: int = 60

    # Số agent được kích hoạt mỗi giờ — LLM chọn giá trị trong [min, max]
    # dựa trên quy mô simulation (số entity)
    agents_per_hour_min: int = 5
    agents_per_hour_max: int = 20

    # Khung giờ cao điểm: 19-22 giờ — đông nhất, nhân với 1.5
    peak_hours: List[int] = field(default_factory=lambda: [19, 20, 21, 22])
    peak_activity_multiplier: float = 1.5

    # Khung giờ chết: 0-5 giờ sáng — gần như không ai online, nhân với 0.05
    off_peak_hours: List[int] = field(default_factory=lambda: [0, 1, 2, 3, 4, 5])
    off_peak_activity_multiplier: float = 0.05

    # Buổi sáng: 6-8 giờ — hoạt động tăng dần, nhân với 0.4
    morning_hours: List[int] = field(default_factory=lambda: [6, 7, 8])
    morning_activity_multiplier: float = 0.4

    # Giờ làm việc: 9-18 giờ — hoạt động ổn định, nhân với 0.7
    work_hours: List[int] = field(default_factory=lambda: [9, 10, 11, 12, 13, 14, 15, 16, 17, 18])
    work_activity_multiplier: float = 0.7


# ==============================================================================
# DATACLASS: EventConfig — Cấu hình "ngòi nổ" khởi động cuộc mô phỏng
# ==============================================================================
# initial_posts là các bài đăng đầu tiên được post ngay khi simulation bắt đầu.
# Chúng tạo ra "sự kiện kích hoạt" để các agent khác phản ứng.
#
# Sau khi LLM sinh initial_posts (có poster_type), hàm _assign_initial_post_agents()
# sẽ map poster_type → agent_id thực để OASIS biết agent nào post bài đó.
# ==============================================================================

@dataclass
class EventConfig:
    """Cấu hình sự kiện cho Simulation gồm initial_posts, scheduled_events, hot_topics, narrative_direction"""

    # Bài đăng khởi đầu — post ngay round 1, tạo "tin nóng" để agent phản ứng
    # Mỗi phần tử: {"content": "...", "poster_type": "MediaOutlet", "poster_agent_id": 12}
    # poster_agent_id được gán sau bởi _assign_initial_post_agents()
    initial_posts: List[Dict[str, Any]] = field(default_factory=list)

    # Sự kiện lập lịch — chưa được implement, dành cho tính năng tương lai
    scheduled_events: List[Dict[str, Any]] = field(default_factory=list)

    # Từ khóa chủ đề nóng — OASIS dùng để tăng khả năng agent chú ý đến chủ đề này
    # Ví dụ: ["học phí", "biểu tình", "giáo dục"]
    hot_topics: List[str] = field(default_factory=list)

    # Hướng dẫn tổng quan diễn biến dư luận — LLM viết ra để định hướng
    # Ví dụ: "Thông báo tăng học phí → sinh viên phản đối → leo thang thành phong trào..."
    narrative_direction: str = ""


# ==============================================================================
# DATACLASS: PlatformConfig — Cấu hình riêng cho từng nền tảng mạng xã hội
# ==============================================================================
# Twitter và Reddit có thuật toán feed khác nhau → cần cấu hình riêng.
# Các giá trị này được OASIS dùng khi quyết định bài nào hiển thị trên timeline agent.
#
# recency_weight + popularity_weight + relevance_weight = 1.0 (không bắt buộc, nhưng
# nên cộng lại = 1 để tránh scale lệch)
# ==============================================================================

@dataclass
class PlatformConfig:
    """Cấu hình đặc thù dành riêng cho các nền tảng gồm platform, recency_weight, popularity_weight, relevance_weight, viral_threshold và echo_chamber_strength"""
    platform: str  # "twitter" hoặc "reddit"

    # Ba trọng số trong thuật toán đề xuất nội dung:
    recency_weight: float = 0.4    # Ưu tiên bài mới (Twitter: cao hơn Reddit)
    popularity_weight: float = 0.3  # Ưu tiên bài nhiều like/repost
    relevance_weight: float = 0.3   # Ưu tiên bài liên quan đến sở thích agent

    # Ngưỡng lan truyền "viral":
    # Twitter: 10 — dễ lan hơn (retweet lan nhanh)
    # Reddit:  15 — khó lan hơn (cần nhiều upvote hơn)
    # Khi bài đạt ngưỡng này, OASIS tăng xác suất nó xuất hiện trên feed của nhiều agent
    viral_threshold: int = 10

    # Hiệu ứng "buồng phản âm" (echo chamber):
    # 0.0 = không có — agent thấy đa chiều
    # 1.0 = tối đa — agent chỉ thấy bài cùng quan điểm
    # Reddit thường cao hơn (0.6) vì cơ chế subreddit tạo bong bóng thông tin
    echo_chamber_strength: float = 0.5


# ==============================================================================
# DATACLASS: SimulationParameters — Object tổng hợp toàn bộ cấu hình simulation
# ==============================================================================
# Đây là output cuối cùng của SimulationConfigGenerator.generate_config().
# Nó được serialize thành simulation_config.json — file trung tâm mà:
#   1. Flask đọc để điền metadata vào state.json
#   2. OASIS scripts đọc để khởi tạo môi trường và chạy simulation
#
# to_json() đảm bảo Unicode (tiếng Việt) không bị escape thành \uXXXX
# ==============================================================================

@dataclass
class SimulationParameters:
    """Bộ tham số cấu hình đầy đủ cho một lượt Simulation"""

    # --- Định danh (bắt buộc khi tạo object) ---
    simulation_id: str
    project_id: str
    graph_id: str
    simulation_requirement: str  # Yêu cầu gốc từ người dùng — được lưu để traceback

    # --- Các cấu hình con (có default để tạo object không cần truyền hết) ---
    time_config: TimeSimulationConfig = field(default_factory=TimeSimulationConfig)
    agent_configs: List[AgentActivityConfig] = field(default_factory=list)
    event_config: EventConfig = field(default_factory=EventConfig)

    # None nếu platform tương ứng bị tắt (enable_twitter=False / enable_reddit=False)
    twitter_config: Optional[PlatformConfig] = None
    reddit_config: Optional[PlatformConfig] = None

    # --- Metadata LLM ---
    llm_model: str = ""     # Tên model đã dùng để gen (dùng để debug khi chất lượng kém)
    llm_base_url: str = ""  # Base URL API (có thể là OpenAI, Azure, local...)

    # --- Metadata tạo ---
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    # Chuỗi reasoning nối từ tất cả các bước: "Time config: ...|Event config: ...|Agent: ..."
    generation_reasoning: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialize toàn bộ object thành dict — dùng để truyền nội bộ."""
        time_dict = asdict(self.time_config)
        return {
            "simulation_id": self.simulation_id,
            "project_id": self.project_id,
            "graph_id": self.graph_id,
            "simulation_requirement": self.simulation_requirement,
            "time_config": time_dict,
            "agent_configs": [asdict(a) for a in self.agent_configs],
            "event_config": asdict(self.event_config),
            "twitter_config": asdict(self.twitter_config) if self.twitter_config else None,
            "reddit_config": asdict(self.reddit_config) if self.reddit_config else None,
            "llm_model": self.llm_model,
            "llm_base_url": self.llm_base_url,
            "generated_at": self.generated_at,
            "generation_reasoning": self.generation_reasoning,
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize thành chuỗi JSON — ensure_ascii=False để giữ nguyên tiếng Việt."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


# ==============================================================================
# CLASS: SimulationConfigGenerator — Trình điều phối sinh config bằng LLM
# ==============================================================================
# Được gọi bởi: SimulationManager.prepare_simulation() ở Giai đoạn 3.
# Input đến từ: ZepEntityReader.filter_defined_entities() (danh sách EntityNode)
#
# Sơ đồ luồng gọi LLM trong generate_config():
#
#   generate_config()
#     │
#     ├── Bước 1: _generate_time_config()         ← 1 LLM call
#     │       └── _parse_time_config()             ← validate + parse
#     │
#     ├── Bước 2: _generate_event_config()         ← 1 LLM call
#     │       └── _parse_event_config()            ← parse đơn giản
#     │
#     ├── Bước 3..N: _generate_agent_configs_batch() ← 1 LLM call × N batch
#     │       └── _generate_agent_config_by_rule() ← fallback nếu LLM fail/thiếu
#     │
#     ├── _assign_initial_post_agents()            ← không cần LLM, map bằng alias
#     │
#     └── Bước cuối: PlatformConfig hardcoded      ← không cần LLM
#
# Mỗi LLM call đi qua _call_llm_with_retry() với retry 3 lần, temperature giảm dần.
# ==============================================================================

class SimulationConfigGenerator:
    """
    Trình tạo cấu hình Simulation tự động bằng LLM

    Sử dụng LLM phân tích yêu cầu mô phỏng, nội dung tài liệu, Entity từ đồ thị,
    tự động xây dựng các thông số cấu trúc tối ưu cho đợt Simulation.

    Chiến lược chia từng bước (step-by-step generation):
    1. Tạo cấu hình thời gian và cấu hình Event (Nhẹ, chạy nhanh)
    2. Phân nhỏ đợt tạo cấu hình cho Agent (15 agent mỗi đợt)
    3. Tạo cấu hình nền tảng (hardcoded, không cần LLM)
    """

    MAX_CONTEXT_LENGTH = 50000    # Giới hạn tổng ngữ cảnh gửi cho LLM (ký tự)
    AGENTS_PER_BATCH = 15         # Số agent xử lý mỗi lần gọi LLM (tránh token limit)

    # Độ dài context cho từng bước — cắt ngắn để không waste token
    TIME_CONFIG_CONTEXT_LENGTH = 10000   # Bước 1: chỉ cần biết chủ đề + entity types
    EVENT_CONFIG_CONTEXT_LENGTH = 8000   # Bước 2: cần biết thêm về các entity điển hình
    ENTITY_SUMMARY_LENGTH = 300          # Tóm tắt mỗi entity trong context
    AGENT_SUMMARY_LENGTH = 300           # Tóm tắt entity trong prompt sinh agent config
    ENTITIES_PER_TYPE_DISPLAY = 20       # Tối đa bao nhiêu entity/loại trong context

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None
    ):
        self.api_key = api_key or Config.LLM_API_KEY
        self.base_url = base_url or Config.LLM_BASE_URL
        self.model_name = model_name or Config.LLM_MODEL_NAME

        if not self.api_key:
            raise ValueError("LLM_API_KEY has not been configured")

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )
        # Metadata runtime được inject vào mỗi LLM call để theo dõi cost/usage
        self._runtime_metadata: Dict[str, Any] = {}

    def generate_config(
        self,
        simulation_id: str,
        project_id: str,
        graph_id: str,
        simulation_requirement: str,
        document_text: str,
        entities: List[EntityNode],
        enable_twitter: bool = True,
        enable_reddit: bool = True,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> SimulationParameters:
        """
        Pipeline sinh cấu hình simulation hoàn chỉnh theo từng bước.

        Tổng quan luồng:
        ┌───────────────────────────────────────────────────────────────┐
        │ Bước 1: _generate_time_config()  → TimeSimulationConfig       │
        │ Bước 2: _generate_event_config() → EventConfig + initial_posts│
        │ Bước 3..N: _generate_agent_configs_batch() × ceil(N/15)       │
        │ _assign_initial_post_agents()    → gán poster_agent_id        │
        │ Bước cuối: PlatformConfig hardcoded                           │
        └───────────────────────────────────────────────────────────────┘

        Args:
            simulation_id: ID của simulation (dùng để điền vào SimulationParameters)
            project_id: ID project
            graph_id: ID Zep Graph (dùng để điền metadata, không query thêm ở đây)
            simulation_requirement: Yêu cầu người dùng (truyền thẳng vào LLM prompt)
            document_text: Văn bản tài liệu gốc (làm ngữ cảnh nền tảng cho LLM)
            entities: Danh sách EntityNode từ ZepEntityReader (đã lọc + enrich)
            enable_twitter: True → sinh twitter_config
            enable_reddit: True → sinh reddit_config
            progress_callback: Hàm nhận (current_step, total_steps, message: str)

        Returns:
            SimulationParameters đầy đủ — gọi .to_json() để ghi ra file.
        """
        logger.info(f"Start generating simulation configuration: simulation_id={simulation_id}, entity_count={len(entities)}")
        self._runtime_metadata = {
            "simulation_id": simulation_id,
            "project_id": project_id,
            "component": "simulation_config_generator",
            "phase": "prepare_simulation_config",
        }

        # Tính tổng số bước để progress_callback hiển thị đúng phần trăm
        # total_steps = 1 (time) + 1 (event) + N_batch (agents) + 1 (platform) = 3 + N_batch
        num_batches = math.ceil(len(entities) / self.AGENTS_PER_BATCH)
        total_steps = 3 + num_batches
        current_step = 0

        def report_progress(step: int, message: str):
            nonlocal current_step
            current_step = step
            if progress_callback:
                progress_callback(step, total_steps, message)
            logger.info(f"[{step}/{total_steps}] {message}")

        # Xây dựng context chung (tối đa 50,000 ký tự) dùng cho tất cả các bước
        # Bao gồm: simulation_requirement + entity summary + document_text (phần còn lại)
        context = self._build_context(
            simulation_requirement=simulation_requirement,
            document_text=document_text,
            entities=entities
        )

        # Mảng tích lũy reasoning từ mỗi bước — nối lại cuối để lưu vào SimulationParameters
        reasoning_parts = []

        # ========== Bước 1: Cấu hình Thời gian ==========
        report_progress(1, "Generating time configuration...")
        num_entities = len(entities)
        time_config_result = self._generate_time_config(context, num_entities)
        time_config = self._parse_time_config(time_config_result, num_entities)
        reasoning_parts.append(f"Time config reasoning: {time_config_result.get('reasoning', 'Success')}")

        # ========== Bước 2: Cấu hình Sự kiện ==========
        report_progress(2, "Generating event configuration and hot topics...")
        event_config_result = self._generate_event_config(context, simulation_requirement, entities)
        event_config = self._parse_event_config(event_config_result)
        reasoning_parts.append(f"Event config reasoning: {event_config_result.get('reasoning', 'Success')}")

        # ========== Bước 3..N: Cấu hình Agent (chia batch) ==========
        # Ví dụ: 47 entity → batch1(0-14) + batch2(15-29) + batch3(30-44) + batch4(45-46)
        all_agent_configs = []
        for batch_idx in range(num_batches):
            start_idx = batch_idx * self.AGENTS_PER_BATCH
            end_idx = min(start_idx + self.AGENTS_PER_BATCH, len(entities))
            batch_entities = entities[start_idx:end_idx]

            report_progress(
                3 + batch_idx,
                f"Generating agent configuration ({start_idx + 1}-{end_idx}/{len(entities)})..."
            )

            batch_configs = self._generate_agent_configs_batch(
                context=context,
                entities=batch_entities,
                start_idx=start_idx,
                simulation_requirement=simulation_requirement
            )
            all_agent_configs.extend(batch_configs)

        reasoning_parts.append(f"Agent config reasoning: Successfully generated {len(all_agent_configs)} agents")

        # ========== Gán agent cho initial posts ==========
        # Sau khi có đủ all_agent_configs, map poster_type → agent_id thực
        logger.info("Assigning poster agents for initial posts...")
        event_config = self._assign_initial_post_agents(event_config, all_agent_configs)
        assigned_count = len([p for p in event_config.initial_posts if p.get("poster_agent_id") is not None])
        reasoning_parts.append(f"Initial post assignment: {assigned_count} posts have been assigned to publishers")

        # ========== Bước cuối: Platform Config (hardcoded) ==========
        # Không cần LLM — các giá trị này là hằng số đã được tuning thực nghiệm
        report_progress(total_steps, "Generating platform configuration...")
        twitter_config = None
        reddit_config = None

        if enable_twitter:
            twitter_config = PlatformConfig(
                platform="twitter",
                recency_weight=0.4,    # Twitter ưu tiên bài mới hơn Reddit
                popularity_weight=0.3,
                relevance_weight=0.3,
                viral_threshold=10,    # Dễ lan hơn Reddit
                echo_chamber_strength=0.5
            )

        if enable_reddit:
            reddit_config = PlatformConfig(
                platform="reddit",
                recency_weight=0.3,    # Reddit cân bằng hơn giữa mới vs phổ biến
                popularity_weight=0.4, # Reddit ưu tiên upvote hơn thời gian
                relevance_weight=0.3,
                viral_threshold=15,    # Ngưỡng cao hơn → khó "bùng" hơn Twitter
                echo_chamber_strength=0.6  # Reddit có subreddit → buồng phản âm mạnh hơn
            )

        # Gộp tất cả vào SimulationParameters
        params = SimulationParameters(
            simulation_id=simulation_id,
            project_id=project_id,
            graph_id=graph_id,
            simulation_requirement=simulation_requirement,
            time_config=time_config,
            agent_configs=all_agent_configs,
            event_config=event_config,
            twitter_config=twitter_config,
            reddit_config=reddit_config,
            llm_model=self.model_name,
            llm_base_url=self.base_url,
            generation_reasoning=" | ".join(reasoning_parts)
        )

        logger.info(f"Simulation configuration generation complete: {len(params.agent_configs)} agent configs created")

        return params

    def _build_context(
        self,
        simulation_requirement: str,
        document_text: str,
        entities: List[EntityNode]
    ) -> str:
        """
        Tổng hợp ngữ cảnh cho LLM — tối đa MAX_CONTEXT_LENGTH ký tự.

        Ưu tiên (thứ tự giảm dần):
        1. simulation_requirement — giữ nguyên 100%, không cắt
        2. entity_summary — tóm tắt nhóm theo loại, tối đa ENTITIES_PER_TYPE_DISPLAY/loại
        3. document_text — phần còn lại sau khi đã dùng cho 1+2

        Document_text bị cắt cuối nếu tổng vượt quá 50,000 ký tự.
        """
        entity_summary = self._summarize_entities(entities)

        context_parts = [
            f"## Simulation Requirements\n{simulation_requirement}",
            f"\n## Entity Information ({len(entities)} entities)\n{entity_summary}",
        ]

        current_length = sum(len(p) for p in context_parts)
        # Dành 500 ký tự buffer để tránh off-by-one khi LLM đếm token
        remaining_length = self.MAX_CONTEXT_LENGTH - current_length - 500

        if remaining_length > 0 and document_text:
            doc_text = document_text[:remaining_length]
            if len(document_text) > remaining_length:
                doc_text += "\n...(Document Truncated)" # note: việc cắt bớt đi có bị ảnh hưởng gì nghiêm trọng không? nếu để full thì có tốn context không?
            context_parts.append(f"\n## Original Document Content\n{doc_text}")

        return "\n".join(context_parts)

    def _summarize_entities(self, entities: List[EntityNode]) -> str:
        """
        Tạo chuỗi tóm tắt entity theo nhóm loại — dùng trong _build_context().

        Format output:
        ### Student (5 entity)
        - Trần Văn An: Sinh viên năm 3 ngành CNTT...
        - Nguyễn Thị B: ...
        ### University (2 entity)
        - Đại học X: ...
        """
        lines = []

        # Nhóm entity theo loại để LLM dễ nắm phân phối nhân vật
        by_type: Dict[str, List[EntityNode]] = {}
        for e in entities:
            t = e.get_entity_type() or "Unknown"
            if t not in by_type:
                by_type[t] = []
            by_type[t].append(e)

        for entity_type, type_entities in by_type.items():
            lines.append(f"\n### {entity_type} ({len(type_entities)} entity)")
            display_count = self.ENTITIES_PER_TYPE_DISPLAY
            summary_len = self.ENTITY_SUMMARY_LENGTH
            for e in type_entities[:display_count]:
                summary_preview = (e.summary[:summary_len] + "...") if len(e.summary) > summary_len else e.summary
                lines.append(f"- {e.name}: {summary_preview}")
            if len(type_entities) > display_count:
                lines.append(f"  ... and {len(type_entities) - display_count} more entities")

        return "\n".join(lines)

        '''
        ### Student (5 entity)
        - Trần Văn An: Sinh viên năm 3 ngành CNTT tại Đại học X...
        - Nguyễn Thị B: Sinh viên năm 2, hoạt động phong trào...

        ### University (1 entity)
        - Đại học X: Trường đại học công lập lớn tại Hà Nội...

        ### MediaOutlet (2 entity)
        - VnExpress: Báo điện tử lớn nhất Việt Nam...
        '''

    def _call_llm_with_retry(self, prompt: str, system_prompt: str) -> Dict[str, Any]:
        """
        Gọi LLM và retry tối đa 3 lần với temperature giảm dần.

        Chiến lược retry:
          Attempt 1: temperature=0.7 (sáng tạo, đa dạng hơn)
          Attempt 2: temperature=0.6 + sleep 2s (nếu attempt 1 fail)
          Attempt 3: temperature=0.5 + sleep 4s (nếu attempt 2 fail)

        Temperature giảm dần → output ổn định hơn, ít hallucination → dễ parse JSON hơn.
        Nếu finish_reason="length" (bị cắt do token limit) → _fix_truncated_json() trước khi parse.
        Nếu json.loads() lỗi → _try_fix_config_json() để cố sửa.
        Nếu cả 3 lần đều fail → raise exception để caller dùng hardcode fallback.
        """
        import re

        max_attempts = 3
        last_error = None

        for attempt in range(max_attempts):
            try:
                response = create_tracked_chat_completion(
                    client=self.client,
                    model=self.model_name,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.7 - (attempt * 0.1),  # 0.7 → 0.6 → 0.5
                    metadata=self._runtime_metadata,
                )

                content = response.choices[0].message.content
                finish_reason = response.choices[0].finish_reason

                # Nếu bị cắt giữa chừng do max_tokens → thêm ngoặc đóng trước khi parse
                if finish_reason == 'length':
                    logger.warning(f"LLM output was truncated (attempt {attempt+1})")
                    content = self._fix_truncated_json(content)

                try:
                    return json.loads(content)
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse JSON (attempt {attempt+1}): {str(e)[:80]}")
                    # Thử sửa JSON trước khi bỏ cuộc
                    fixed = self._try_fix_config_json(content)
                    if fixed:
                        return fixed
                    last_error = e

            except Exception as e:
                logger.warning(f"Failed to call LLM (attempt {attempt+1}): {str(e)[:80]}")
                last_error = e
                import time
                time.sleep(2 * (attempt + 1))  # Sleep 2s → 4s → (không có attempt 3+)

        raise last_error or Exception("LLM connection completely failed")

    def _fix_truncated_json(self, content: str) -> str:
        """
        Đóng các ngoặc JSON bị bỏ ngỏ khi LLM bị cắt giữa chừng.

        Thuật toán:
          1. Đếm số { chưa có } đóng tương ứng → thêm } vào cuối
          2. Đếm số [ chưa có ] đóng tương ứng → thêm ] vào cuối
          3. Nếu ký tự cuối là dở dang (không phải ",}]) → thêm " để đóng string

        Ví dụ input bị cắt:
          '{"agent_configs": [{"agent_id": 0, "stance": "oppos'
        Sau fix:
          '{"agent_configs": [{"agent_id": 0, "stance": "oppos"}]}'
        """
        content = content.strip()

        open_braces = content.count('{') - content.count('}')
        open_brackets = content.count('[') - content.count(']')

        # Đóng string bị bỏ ngỏ trước khi đóng object/array
        if content and content[-1] not in '",}]':
            content += '"'

        content += ']' * open_brackets
        content += '}' * open_braces

        return content

    def _try_fix_config_json(self, content: str) -> Optional[Dict[str, Any]]:
        """
        Cố sửa JSON bị lỗi format bằng chuỗi bước:

        Bước 1: Gọi _fix_truncated_json() (đóng bracket thiếu)
        Bước 2: Regex tìm khối {...} lớn nhất trong chuỗi (loại bỏ text thừa trước/sau)
        Bước 3: Clean newline trong string values (LLM hay nhét \n trong string JSON)
        Bước 4: Thử json.loads() — nếu OK trả về luôn
        Bước 5: Xóa control characters (0x00-0x1F, 0x7F-0x9F) gây lỗi parse
        Bước 6: Chuẩn hóa whitespace thừa
        Bước 7: Thử json.loads() lần nữa — nếu vẫn fail trả về None

        Trả về None nếu không thể sửa → caller sẽ retry hoặc dùng fallback.
        """
        import re

        content = self._fix_truncated_json(content)

        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            json_str = json_match.group()

            # Clean newline và whitespace thừa bên trong string values
            def fix_string(match):
                s = match.group(0)
                s = s.replace('\n', ' ').replace('\r', ' ')
                s = re.sub(r'\s+', ' ', s)
                return s

            json_str = re.sub(r'"[^"\\]*(?:\\.[^"\\]*)*"', fix_string, json_str)

            try:
                return json.loads(json_str)
            except:
                # Xóa control characters và thử lần nữa
                json_str = re.sub(r'[\x00-\x1f\x7f-\x9f]', ' ', json_str)
                json_str = re.sub(r'\s+', ' ', json_str)
                try:
                    return json.loads(json_str)
                except:
                    pass

        return None

    # --------------------------------------------------------------------------
    # BƯỚC 1: Sinh cấu hình Thời gian
    # --------------------------------------------------------------------------

    def _generate_time_config(self, context: str, num_entities: int) -> Dict[str, Any]:
        """
        Gọi LLM để sinh cấu hình thời gian mô phỏng.

        LLM nhận context cắt còn TIME_CONFIG_CONTEXT_LENGTH (10,000 ký tự) và trả về:
        {
          "total_simulation_hours": 72,
          "minutes_per_round": 60,
          "agents_per_hour_min": 5,
          "agents_per_hour_max": 30,
          "peak_hours": [19, 20, 21, 22],
          "off_peak_hours": [0, 1, 2, 3, 4, 5],
          "morning_hours": [6, 7, 8],
          "work_hours": [9, 10, ..., 18],
          "reasoning": "Giải thích tại sao chọn các thông số này"
        }

        Ràng buộc gửi cho LLM:
        - Người dùng là người Việt Nam → giờ Hà Nội (UTC+7)
        - agents_per_hour tối đa = 90% số entity (max_agents_allowed = num_entities × 0.9)

        Fallback (LLM fail): _get_default_time_config() — hardcoded defaults.
        """
        context_truncated = context[:self.TIME_CONFIG_CONTEXT_LENGTH]
        max_agents_allowed = max(1, int(num_entities * 0.9))

        prompt = f"""Dựa trên các yêu cầu mô phỏng dưới đây, hãy tạo cấu hình mô phỏng thời gian.

{context_truncated}

## Nhiệm vụ
Hãy tạo JSON cấu hình thời gian.

### Nguyên tắc cơ bản (Chỉ mang tính chất tham khảo, cần điều chỉnh linh hoạt theo sự kiện cụ thể và nhóm đối tượng tham gia):
- Nhóm người dùng là người Việt Nam, cần phù hợp với thói quen sinh hoạt theo giờ Hà Nội.
- 0-5 giờ sáng: Hầu như không có hoạt động (Hệ số hoạt động: 0.05).
- 6-8 giờ sáng: Hoạt động tăng dần (Hệ số hoạt động: 0.4).
- 9-18 giờ (Giờ làm việc): Hoạt động trung bình (Hệ số hoạt động: 0.7).
- 19-22 giờ tối: Giai đoạn cao điểm (Hệ số hoạt động: 1.5).
- Sau 23 giờ: Mức độ hoạt động giảm xuống (Hệ số hoạt động: 0.5).
- Quy luật chung: Thấp vào rạng sáng, tăng dần vào buổi sáng, trung bình trong giờ làm việc và cao điểm vào buổi tối.
- **Quan trọng**: Các giá trị ví dụ dưới đây chỉ mang tính chất tham khảo, bạn cần điều chỉnh các khung giờ cụ thể dựa trên tính chất sự kiện và đặc điểm của nhóm đối tượng tham gia.
  - Ví dụ: Cao điểm của nhóm sinh viên có thể là 21-23 giờ; Nhóm truyền thông hoạt động cả ngày; Các cơ quan chính thống chỉ hoạt động trong giờ hành chính.
  - Ví dụ: Tin tức nóng hổi (hotspot) có thể dẫn đến thảo luận vào đêm muộn; off_peak_hours có thể được rút ngắn tương ứng.

### Định dạng JSON trả về (Không sử dụng markdown)

Ví dụ Format như sau:
{{
    "total_simulation_hours": 72,
    "minutes_per_round": 60,
    "agents_per_hour_min": 5,
    "agents_per_hour_max": 50,
    "peak_hours": [19, 20, 21, 22],
    "off_peak_hours": [0, 1, 2, 3, 4, 5],
    "morning_hours": [6, 7, 8],
    "work_hours": [9, 10, 11, 12, 13, 14, 15, 16, 17, 18],
    "reasoning": "Giải thích cấu hình thời gian cho sự kiện này."
}}

Mô tả các trường:
- total_simulation_hours (int): Tổng thời gian mô phỏng, từ 24-168 giờ. Ngắn cho sự kiện đột xuất, dài cho các chủ đề kéo dài.
- minutes_per_round (int): Thời gian mỗi hiệp, 30-120 phút, khuyến nghị 60 phút.
- agents_per_hour_min (int): Số lượng Agent kích hoạt tối thiểu mỗi giờ (Phạm vi: 1-{max_agents_allowed}).
- agents_per_hour_max (int): Số lượng Agent kích hoạt tối đa mỗi giờ (Phạm vi: 1-{max_agents_allowed}).
- peak_hours (int array): Khung giờ cao điểm, điều chỉnh theo nhóm tham gia.
- off_peak_hours (int array): Khung giờ thấp điểm, thường là đêm khuya rạng sáng.
- morning_hours (mảng int): Khung giờ buổi sáng.
- work_hours (mảng int): Khung giờ làm việc.
- reasoning (string): Giải thích ngắn gọn lý do tại sao cấu hình như vậy."""

        system_prompt = "Bạn là chuyên gia mô phỏng mạng xã hội. Trả về định dạng JSON thuần túy; cấu hình thời gian cần phù hợp với thói quen sinh hoạt của người Việt Nam."

        try:
            return self._call_llm_with_retry(prompt, system_prompt)
        except Exception as e:
            logger.warning(f"Failed to generate Time Config through LLM {e}. Returning the basic default rules...")
            return self._get_default_time_config(num_entities)

    def _get_default_time_config(self, num_entities: int) -> Dict[str, Any]:
        """
        Fallback hardcoded khi LLM fail hoàn toàn.

        agents_per_hour được tính theo công thức:
          min = num_entities // 15  (ví dụ: 47 entity → min=3)
          max = num_entities // 5   (ví dụ: 47 entity → max=9)
        Đảm bảo không vượt quá tổng số agent thực tế.
        """
        return {
            "total_simulation_hours": 72,
            "minutes_per_round": 60,
            "agents_per_hour_min": max(1, num_entities // 15),
            "agents_per_hour_max": max(5, num_entities // 5),
            "peak_hours": [19, 20, 21, 22],
            "off_peak_hours": [0, 1, 2, 3, 4, 5],
            "morning_hours": [6, 7, 8],
            "work_hours": [9, 10, 11, 12, 13, 14, 15, 16, 17, 18],
            "reasoning": "Defaults to Vietnamese users' daily routines and working hours (1 hour/round)"
        }

    def _parse_time_config(self, result: Dict[str, Any], num_entities: int) -> TimeSimulationConfig:
        """
        Parse dict từ LLM thành TimeSimulationConfig, kèm validation.

        Validation quan trọng: đảm bảo agents_per_hour không vượt tổng số agent thực tế.
        Nếu LLM trả về agents_per_hour_max=100 nhưng chỉ có 47 entity,
        OASIS sẽ cố chọn 100 agent nhưng không đủ → lỗi.

        Logic điều chỉnh:
          agents_per_hour_min > num_entities → reset về num_entities // 10
          agents_per_hour_max > num_entities → reset về num_entities // 2
          min >= max → reset min về max // 2
        """
        agents_per_hour_min = result.get("agents_per_hour_min", max(1, num_entities // 15))
        agents_per_hour_max = result.get("agents_per_hour_max", max(5, num_entities // 5))

        if agents_per_hour_min > num_entities:
            logger.warning(f"agents_per_hour_min ({agents_per_hour_min}) exceeds total number of Agents ({num_entities}), corrected.")
            agents_per_hour_min = max(1, num_entities // 10)

        if agents_per_hour_max > num_entities:
            logger.warning(f"agents_per_hour_max ({agents_per_hour_max}) exceeds total number of Agents ({num_entities}), corrected.")
            agents_per_hour_max = max(agents_per_hour_min + 1, num_entities // 2)

        if agents_per_hour_min >= agents_per_hour_max:
            agents_per_hour_min = max(1, agents_per_hour_max // 2)
            logger.warning(f"agents_per_hour_min >= max, modified to {agents_per_hour_min}")

        return TimeSimulationConfig(
            total_simulation_hours=result.get("total_simulation_hours", 72),
            minutes_per_round=result.get("minutes_per_round", 60),
            agents_per_hour_min=agents_per_hour_min,
            agents_per_hour_max=agents_per_hour_max,
            peak_hours=result.get("peak_hours", [19, 20, 21, 22]),
            off_peak_hours=result.get("off_peak_hours", [0, 1, 2, 3, 4, 5]),
            off_peak_activity_multiplier=0.05,
            morning_hours=result.get("morning_hours", [6, 7, 8]),
            morning_activity_multiplier=0.4,
            work_hours=result.get("work_hours", list(range(9, 19))),
            work_activity_multiplier=0.7,
            peak_activity_multiplier=1.5
        )

    # --------------------------------------------------------------------------
    # BƯỚC 2: Sinh cấu hình Sự kiện
    # --------------------------------------------------------------------------

    def _generate_event_config(
        self,
        context: str,
        simulation_requirement: str,
        entities: List[EntityNode]
    ) -> Dict[str, Any]:
        """
        Gọi LLM để sinh các bài đăng khởi động và hướng phát triển dư luận.

        Ràng buộc quan trọng gửi cho LLM: poster_type phải thuộc danh sách
        entity types thực sự có trong simulation. LLM được cung cấp danh sách
        type_examples (ví dụ điển hình của mỗi loại) để chọn đúng.

        Ví dụ output:
        {
          "hot_topics": ["học phí", "biểu tình"],
          "narrative_direction": "Thông báo tăng học phí → làn sóng phản đối...",
          "initial_posts": [
            {"content": "CHÍNH THỨC: Đại học X tăng học phí...", "poster_type": "University"},
            {"content": "Không thể chấp nhận được! #HọcPhíTăng", "poster_type": "Student"}
          ]
        }

        Sau bước này, _assign_initial_post_agents() sẽ gán poster_agent_id thực.
        Fallback khi LLM fail: hot_topics=[], initial_posts=[] — simulation vẫn chạy
        nhưng không có "ngòi nổ" → agent tự tạo bài đăng theo activity_level.
        """
        # Thu thập danh sách loại thực thể có thực để LLM chọn poster_type đúng
        entity_types_available = list(set(
            e.get_entity_type() or "Unknown" for e in entities
        ))

        # Ví dụ điển hình mỗi loại (tối đa 3) — giúp LLM biết tên thật của entity
        type_examples = {}
        for e in entities:
            etype = e.get_entity_type() or "Unknown"
            if etype not in type_examples:
                type_examples[etype] = []
            if len(type_examples[etype]) < 3:
                type_examples[etype].append(e.name)

        type_info = "\n".join([
            f"- {t}: {', '.join(examples)}"
            for t, examples in type_examples.items()
        ])

        context_truncated = context[:self.EVENT_CONFIG_CONTEXT_LENGTH]

        prompt = f"""Dựa trên các yêu cầu mô phỏng sau đây, hãy tạo cấu hình sự kiện.

Yêu cầu mô phỏng: {simulation_requirement}

{context_truncated}

## Các loại thực thể khả dụng và ví dụ
{type_info}

## Nhiệm vụ
Vui lòng tạo JSON cấu hình sự kiện:
- Trích xuất các từ khóa chủ đề nóng (hot topics).
- Mô tả hướng phát triển của dư luận.
- Thiết kế nội dung các bài đăng khởi tạo, **mỗi bài đăng phải chỉ định poster_type (loại người đăng)**.

**QUAN TRỌNG**: poster_type phải được chọn từ "Các loại thực thể khả dụng" ở trên để các bài đăng khởi tạo có thể được phân bổ cho đúng Agent phù hợp.
  Ví dụ: Các tuyên bố chính thức nên được đăng bởi loại Official/University, tin tức bởi MediaOutlet, và quan điểm sinh viên bởi Student.

Trả về định dạng JSON (không sử dụng markdown):
{{
    "hot_topics": ["Từ khóa 1", "Từ khóa 2", ...],
    "narrative_direction": "<Mô tả hướng phát triển dư luận>",
    "initial_posts": [
        {{"content": "Nội dung bài đăng...", "poster_type": "Loại thực thể (phải chọn từ các loại khả dụng)"}},
        ...
    ],
    "reasoning": "<Giải thích ngắn gọn>"
}}"""

        system_prompt = "Bạn là chuyên gia phân tích dư luận. Trả về định dạng JSON thuần túy. Lưu ý rằng poster_type phải khớp chính xác với các loại thực thể khả dụng."

        try:
            return self._call_llm_with_retry(prompt, system_prompt)
        except Exception as e:
            logger.warning(f"Failed to load LLM Event configurations: {e}, using default configs instead.")
            return {
                "hot_topics": [],
                "narrative_direction": "",
                "initial_posts": [],
                "reasoning": "Sử dụng Config mặc định do LLM lỗi"
            }

    def _parse_event_config(self, result: Dict[str, Any]) -> EventConfig:
        """Parse dict từ LLM thành EventConfig. Đơn giản — không có validation phức tạp."""
        return EventConfig(
            initial_posts=result.get("initial_posts", []),
            scheduled_events=[],  # Chưa implement — dành cho tính năng tương lai
            hot_topics=result.get("hot_topics", []),
            narrative_direction=result.get("narrative_direction", "")
        )

    def _assign_initial_post_agents(
        self,
        event_config: EventConfig,
        agent_configs: List[AgentActivityConfig]
    ) -> EventConfig:
        """
        Gán agent_id thực cho mỗi initial_post dựa trên poster_type.

        3 tầng matching (ưu tiên từ cao đến thấp):
        ┌─────────────────────────────────────────────────────────────────┐
        │ Tầng 1: Direct match                                            │
        │   poster_type.lower() khớp chính xác key trong agents_by_type  │
        │   Ví dụ: "student" → agents_by_type["student"][0]              │
        ├─────────────────────────────────────────────────────────────────┤
        │ Tầng 2: Alias match                                             │
        │   poster_type nằm trong danh sách alias của một key             │
        │   Ví dụ: "media" → alias của "mediaoutlet" → dùng mediaoutlet  │
        │   Cho phép LLM dùng tên biến thể mà vẫn map được đúng          │
        ├─────────────────────────────────────────────────────────────────┤
        │ Tầng 3: Influence fallback                                      │
        │   Không tìm được → lấy agent có influence_weight cao nhất      │
        │   (Thường là mediaoutlet hoặc university)                       │
        └─────────────────────────────────────────────────────────────────┘

        Lưu ý used_indices: mỗi loại có counter riêng để tránh dùng cùng 1 agent
        nhiều lần khi có nhiều post cùng poster_type.
        Ví dụ: 3 post "Student" → agent 0, 1, 2 (thay vì 0, 0, 0).
        """
        if not event_config.initial_posts:
            return event_config

        # Index agents theo loại để tra cứu nhanh
        agents_by_type: Dict[str, List[AgentActivityConfig]] = {}
        for agent in agent_configs:
            etype = agent.entity_type.lower()
            if etype not in agents_by_type:
                agents_by_type[etype] = []
            agents_by_type[etype].append(agent)

        # Bảng alias — LLM đôi khi dùng tên khác nhau cho cùng một loại
        type_aliases = {
            "official": ["official", "university", "governmentagency", "government"],
            "university": ["university", "official"],
            "mediaoutlet": ["mediaoutlet", "media"],
            "student": ["student", "person"],
            "professor": ["professor", "expert", "teacher"],
            "alumni": ["alumni", "person"],
            "organization": ["organization", "ngo", "company", "group"],
            "person": ["person", "student", "alumni"],
        }

        # Dùng round-robin trong mỗi loại (modulo len) để phân bổ đều
        used_indices: Dict[str, int] = {}

        updated_posts = []
        for post in event_config.initial_posts:
            poster_type = post.get("poster_type", "").lower()
            content = post.get("content", "")
            matched_agent_id = None

            # Tầng 1: Direct match
            if poster_type in agents_by_type:
                agents = agents_by_type[poster_type]
                idx = used_indices.get(poster_type, 0) % len(agents)
                matched_agent_id = agents[idx].agent_id
                used_indices[poster_type] = idx + 1
            else:
                # Tầng 2: Alias match
                for alias_key, aliases in type_aliases.items():
                    if poster_type in aliases or alias_key == poster_type:
                        for alias in aliases:
                            if alias in agents_by_type:
                                agents = agents_by_type[alias]
                                idx = used_indices.get(alias, 0) % len(agents)
                                matched_agent_id = agents[idx].agent_id
                                used_indices[alias] = idx + 1
                                break
                    if matched_agent_id is not None:
                        break

            # Tầng 3: Influence fallback
            if matched_agent_id is None:
                logger.warning(f"Could not find matching Agent type '{poster_type}', assigning to highest influence Agent instead")
                if agent_configs:
                    sorted_agents = sorted(agent_configs, key=lambda a: a.influence_weight, reverse=True)
                    matched_agent_id = sorted_agents[0].agent_id
                else:
                    matched_agent_id = 0

            updated_posts.append({
                "content": content,
                "poster_type": post.get("poster_type", "Unknown"),
                "poster_agent_id": matched_agent_id
            })

            logger.info(f"Initial post assignment: poster_type='{poster_type}' -> agent_id={matched_agent_id}")

        event_config.initial_posts = updated_posts
        return event_config

    # --------------------------------------------------------------------------
    # BƯỚC 3..N: Sinh cấu hình Agent (chia batch)
    # --------------------------------------------------------------------------

    def _generate_agent_configs_batch(
        self,
        context: str,
        entities: List[EntityNode],
        start_idx: int,
        simulation_requirement: str
    ) -> List[AgentActivityConfig]:
        """
        Gọi LLM để sinh cấu hình hoạt động cho một batch agents (tối đa AGENTS_PER_BATCH=15).

        Lý do chia batch: nếu có 50+ entity, gửi tất cả 1 lần sẽ vượt token limit
        và LLM có xu hướng bỏ sót entity cuối. Chia 15 agent/lần đảm bảo đủ.

        Mỗi entity trong batch được format thành:
          {"agent_id": 5, "entity_name": "Trần Văn An", "entity_type": "Student", "summary": "..."}

        LLM trả về dict với key "agent_configs": [...]
        → extract theo agent_id, map vào AgentActivityConfig object.
        → Nếu LLM bỏ sót agent nào → _generate_agent_config_by_rule() bù vào.

        agent_id trong output phải khớp chính xác với start_idx + i
        (để OASIS map đúng với user_id trong profile file).
        """
        entity_list = []
        summary_len = self.AGENT_SUMMARY_LENGTH
        for i, e in enumerate(entities):
            entity_list.append({
                "agent_id": start_idx + i,
                "entity_name": e.name,
                "entity_type": e.get_entity_type() or "Unknown",
                "summary": e.summary[:summary_len] if e.summary else ""
            })

        prompt = f"""Dựa trên các thông tin sau đây, hãy tạo cấu hình hoạt động trên mạng xã hội cho từng thực thể.

Yêu cầu mô phỏng: {simulation_requirement}

## Danh sách thực thể
```json
{json.dumps(entity_list, ensure_ascii=False, indent=2)}
```

## Nhiệm vụ
Tạo cấu hình hoạt động cho từng thực thể, lưu ý:
- **Thời gian phù hợp với thói quen của người Việt Nam**: Gần như không hoạt động từ 0-5 giờ sáng, hoạt động mạnh nhất từ 19-22 giờ tối.
- **Cơ quan chính thống (University/GovernmentAgency)**: Hoạt động thấp (0.1-0.3), hoạt động trong giờ làm việc (9:00-17:00), phản hồi chậm (60-240 phút), tầm ảnh hưởng cao (2.5-3.0).
- **Truyền thông (MediaOutlet)**: Hoạt động trung bình (0.4-0.6), hoạt động cả ngày (8:00-23:00), phản hồi nhanh (5-30 phút), tầm ảnh hưởng cao (2.0-2.5).
- **Cá nhân (Student/Person/Alumni)**: Hoạt động cao (0.6-0.9), hoạt động chủ yếu vào buổi tối (18:00-23:00), phản hồi nhanh (1-15 phút), tầm ảnh hưởng thấp (0.8-1.2).
- **Người công chúng/Chuyên gia**: Hoạt động trung bình (0.4-0.6), tầm ảnh hưởng trung bình cao (1.5-2.0).

Trả về định dạng JSON (không sử dụng markdown):
{{
    "agent_configs": [
        {{
            "agent_id": <Phải khớp chính xác với đầu vào>,
            "activity_level": <0.0-1.0>,
            "posts_per_hour": <Tần suất đăng bài>,
            "comments_per_hour": <Tần suất bình luận>,
            "active_hours": [<Danh sách giờ hoạt động, cân nhắc thói quen người Việt Nam>],
            "response_delay_min": <Độ trễ phản hồi tối thiểu tính bằng phút>,
            "response_delay_max": <Độ trễ phản hồi tối đa tính bằng phút>,
            "sentiment_bias": <-1.0 đến 1.0>,
            "stance": "<supportive/opposing/neutral/observer>",
            "influence_weight": <Trọng số ảnh hưởng>
        }},
        ...
    ]
}}"""

        system_prompt = "Bạn là chuyên gia phân tích hành vi mạng xã hội. Trả về JSON thuần túy. Cấu hình phải phù hợp với thói quen sinh hoạt của người Việt Nam."

        try:
            result = self._call_llm_with_retry(prompt, system_prompt)
            # Index theo agent_id để tra cứu O(1) khi fill vào từng entity
            llm_configs = {cfg["agent_id"]: cfg for cfg in result.get("agent_configs", [])}
        except Exception as e:
            logger.warning(f"Failed LLM generating Agent batch configs: {e}, falling back to default manual rules.")
            llm_configs = {}

        # Tạo AgentActivityConfig cho mỗi entity trong batch
        configs = []
        for i, entity in enumerate(entities):
            agent_id = start_idx + i
            cfg = llm_configs.get(agent_id, {})

            # Nếu LLM bỏ sót agent này → dùng rule-based fallback
            if not cfg:
                cfg = self._generate_agent_config_by_rule(entity)

            config = AgentActivityConfig(
                agent_id=agent_id,
                entity_uuid=entity.uuid,
                entity_name=entity.name,
                entity_type=entity.get_entity_type() or "Unknown",
                activity_level=cfg.get("activity_level", 0.5),
                posts_per_hour=cfg.get("posts_per_hour", 0.5),
                comments_per_hour=cfg.get("comments_per_hour", 1.0),
                active_hours=cfg.get("active_hours", list(range(9, 23))),
                response_delay_min=cfg.get("response_delay_min", 5),
                response_delay_max=cfg.get("response_delay_max", 60),
                sentiment_bias=cfg.get("sentiment_bias", 0.0),
                stance=cfg.get("stance", "neutral"),
                influence_weight=cfg.get("influence_weight", 1.0)
            )
            configs.append(config)

        return configs

    def _generate_agent_config_by_rule(self, entity: EntityNode) -> Dict[str, Any]:
        """
        Sinh cấu hình agent bằng rule cứng khi LLM fail hoặc bỏ sót entity này.

        Rule được xây dựng dựa trên hành vi thực tế trên mạng xã hội Việt Nam:

        ┌──────────────────────┬──────────┬──────────────────┬───────────┬───────────┐
        │ Loại entity          │ activity │ active_hours     │ delay(ph) │ influence │
        ├──────────────────────┼──────────┼──────────────────┼───────────┼───────────┤
        │ university/gov/ngo   │  0.2     │ 9-17 (hành chính)│  60-240   │   3.0     │
        │ mediaoutlet          │  0.5     │ 7-23 (cả ngày)   │   5-30    │   2.5     │
        │ professor/expert     │  0.4     │ 8-21             │  15-90    │   2.0     │
        │ student              │  0.8     │ sáng + tối       │   1-15    │   0.8     │
        │ alumni               │  0.6     │ trưa + tối       │   5-30    │   1.0     │
        │ (default)            │  0.7     │ 9-23             │   2-20    │   1.0     │
        └──────────────────────┴──────────┴──────────────────┴───────────┴───────────┘
        """
        entity_type = (entity.get_entity_type() or "Unknown").lower()

        if entity_type in ["university", "governmentagency", "ngo"]:
            # Cơ quan nhà nước/tổ chức: hoạt động giờ hành chính, phát ngôn ít nhưng ảnh hưởng lớn
            return {
                "activity_level": 0.2,
                "posts_per_hour": 0.1,
                "comments_per_hour": 0.05,
                "active_hours": list(range(9, 18)),
                "response_delay_min": 60,
                "response_delay_max": 240,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 3.0
            }
        elif entity_type in ["mediaoutlet"]:
            # Báo đài: hoạt động cả ngày, đưa tin nhanh, nhiều người theo dõi
            return {
                "activity_level": 0.5,
                "posts_per_hour": 0.8,
                "comments_per_hour": 0.3,
                "active_hours": list(range(7, 24)),
                "response_delay_min": 5,
                "response_delay_max": 30,
                "sentiment_bias": 0.0,
                "stance": "observer",
                "influence_weight": 2.5
            }
        elif entity_type in ["professor", "expert", "official"]:
            # Chuyên gia/giảng viên: phát biểu có chọn lọc, ban ngày và tối sớm
            return {
                "activity_level": 0.4,
                "posts_per_hour": 0.3,
                "comments_per_hour": 0.5,
                "active_hours": list(range(8, 22)),
                "response_delay_min": 15,
                "response_delay_max": 90,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 2.0
            }
        elif entity_type in ["student"]:
            # Sinh viên: rất tích cực, đặc biệt buổi tối, phản ứng nhanh
            return {
                "activity_level": 0.8,
                "posts_per_hour": 0.6,
                "comments_per_hour": 1.5,
                "active_hours": [8, 9, 10, 11, 12, 13, 18, 19, 20, 21, 22, 23],
                "response_delay_min": 1,
                "response_delay_max": 15,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 0.8
            }
        elif entity_type in ["alumni"]:
            # Cựu sinh viên: online giờ nghỉ trưa + buổi tối sau giờ làm
            return {
                "activity_level": 0.6,
                "posts_per_hour": 0.4,
                "comments_per_hour": 0.8,
                "active_hours": [12, 13, 19, 20, 21, 22, 23],
                "response_delay_min": 5,
                "response_delay_max": 30,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 1.0
            }
        else:
            # Default — cư dân mạng thông thường: hoạt động ban ngày + tối
            return {
                "activity_level": 0.7,
                "posts_per_hour": 0.5,
                "comments_per_hour": 1.2,
                "active_hours": [9, 10, 11, 12, 13, 18, 19, 20, 21, 22, 23],
                "response_delay_min": 2,
                "response_delay_max": 20,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 1.0
            }
