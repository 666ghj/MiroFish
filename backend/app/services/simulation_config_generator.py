"""
Trình tạo tạo ra cấu hình Simulation tự động
Sử dụng LLM theo yêu cầu mô phỏng, nội dung tài liệu và thông tin đồ thị để tự động thiết lập chi tiết các tham số
Tất cả đều tự động mà không cần can thiệp thủ công tạo tham số

Áp dụng chiến lược tạo từng bước để tránh lỗi do cố gắng tạo nội dung quá dài cùng một lúc:
1. Tạo cấu hình thời gian
2. Tạo cấu hình các Event
3. Tạo cấu hình cho các Agent theo đợt
4. Tạo cấu hình nền tảng
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

# Cấu hình thời gian thói quen Trung Quốc (Theo giờ Bắc Kinh)
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


@dataclass
class AgentActivityConfig:
    """Cấu hình hoạt động cho một Agent"""
    agent_id: int
    entity_uuid: str
    entity_name: str
    entity_type: str
    
    # Mức độ hoạt động (0.0-1.0)
    activity_level: float = 0.5  # Hoạt động tổng thể
    
    # Tần suất phát ngôn (Số lần comment dự kiến mỗi giờ)
    posts_per_hour: float = 1.0
    comments_per_hour: float = 2.0
    
    # Khoảng thời gian hoạt động (Hệ 24 giờ, 0-23)
    active_hours: List[int] = field(default_factory=lambda: list(range(8, 23)))
    
    # Tốc độ phản hồi (Độ trễ phản ứng với sự kiện nóng, đơn vị: phút mô phỏng)
    response_delay_min: int = 5
    response_delay_max: int = 60
    
    # Khuynh hướng cảm xúc (-1.0 đến 1.0, từ tiêu cực đến tích cực)
    sentiment_bias: float = 0.0
    
    # Lập trường (Thái độ đối với chủ đề cụ thể)
    stance: str = "neutral"  # supportive, opposing, neutral, observer
    
    # Trọng số ảnh hưởng (Xác định mức độ bài đăng được Agent khác nhìn thấy)
    influence_weight: float = 1.0


@dataclass  
class TimeSimulationConfig:
    """Cấu hình thời gian mô phỏng (Dựa trên thói quen sinh hoạt của người Trung)"""
    # Tổng thời gian mô phỏng (Giờ)
    total_simulation_hours: int = 72  # Mặc định là chạy mô phỏng 72 tiếng (3 ngày)
    
    # Số phút đại diện cho mỗi vòng - Mặc định 60 phút (1 giờ), đẩy nhanh thời gian
    minutes_per_round: int = 60
    
    # Phạm vi số lượng Agent kích hoạt mỗi giờ
    agents_per_hour_min: int = 5
    agents_per_hour_max: int = 20
    
    # Giờ cao điểm (19-22 giờ tối, thời gian sôi động nhất)
    peak_hours: List[int] = field(default_factory=lambda: [19, 20, 21, 22])
    peak_activity_multiplier: float = 1.5
    
    # Khung giờ chết (0-5 giờ, hầu như không ai on)
    off_peak_hours: List[int] = field(default_factory=lambda: [0, 1, 2, 3, 4, 5])
    off_peak_activity_multiplier: float = 0.05  # Rạng sáng gần như bằng không
    
    # Khung giờ buổi sáng
    morning_hours: List[int] = field(default_factory=lambda: [6, 7, 8])
    morning_activity_multiplier: float = 0.4
    
    # Khung giờ làm việc
    work_hours: List[int] = field(default_factory=lambda: [9, 10, 11, 12, 13, 14, 15, 16, 17, 18])
    work_activity_multiplier: float = 0.7


@dataclass
class EventConfig:
    """Cấu hình sự kiện cho Simulation"""
    # Các bài Post/Sự kiện khởi đầu (Bắt đầu ngay khi chạy mô phỏng)
    initial_posts: List[Dict[str, Any]] = field(default_factory=list)
    
    # Các sự kiện được lập lịch vào các thời điểm nhất định
    scheduled_events: List[Dict[str, Any]] = field(default_factory=list)
    
    # Từ khóa dành cho các chủ đề đang hot (Hot topics)
    hot_topics: List[str] = field(default_factory=list)
    
    # Hướng dẫn dư luận / Đường lối thảo luận
    narrative_direction: str = ""


@dataclass
class PlatformConfig:
    """Cấu hình đặc thù dành riêng cho các nền tảng"""
    platform: str  # twitter or reddit
    
    # Trọng số cho các thuật toán đề xuất
    recency_weight: float = 0.4  # Độ mới của bài
    popularity_weight: float = 0.3  # Mức độ phổ biến truyền miệng
    relevance_weight: float = 0.3  # Mức độ quan tâm / tương quan
    
    # Ngưỡng lan truyền virus (Cần bao nhiêu tương tác để nội dung bắt đầu phát tán mạnh)
    viral_threshold: int = 10
    
    # Độ mạnh của hiệu ứng lan truyền trong nhóm chung chí hướng (buồng phản âm)
    echo_chamber_strength: float = 0.5


@dataclass
class SimulationParameters:
    """完整的模拟参数配置"""
    # 基础信息
    simulation_id: str
    project_id: str
    graph_id: str
    simulation_requirement: str
    
    # Cấu hình thời gian
    time_config: TimeSimulationConfig = field(default_factory=TimeSimulationConfig)
    
    # Danh sách cấu hình Agent
    agent_configs: List[AgentActivityConfig] = field(default_factory=list)
    
    # Cấu hình Event
    event_config: EventConfig = field(default_factory=EventConfig)
    
    # Cấu hình nền tảng
    twitter_config: Optional[PlatformConfig] = None
    reddit_config: Optional[PlatformConfig] = None
    
    # Cấu hình LLM
    llm_model: str = ""
    llm_base_url: str = ""
    
    # Dữ liệu metadata khi tạo
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    generation_reasoning: str = ""  # Giải thích suy luận từ LLM
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert sang định dạng Dictionary"""
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
        """Convert sang định dạng chuỗi JSON"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


class SimulationConfigGenerator:
    """
    Trình tạo cấu hình Simulation tự động bằng LLM
    
    Sử dụng LLM phân tích yêu cầu mô phỏng, nội dung tài liệu, Entity từ đồ thị,
    Tự động xây dựng các thông số cấu trúc tối ưu cho đợt Simulation
    
    Áp dụng chiến lược tạo từng bước:
    1. Tạo cấu hình thời gian và cấu hình Event (Nhẹ, chạy nhanh)
    2. Phân nhỏ đợt tạo cấu hình cho Agent (Khoảng 10-20 agent mỗi đợt)
    3. Tạo cấu hình nền tảng
    """
    
    # Số lượng ký tự tối đa của bộ context
    MAX_CONTEXT_LENGTH = 50000
    # Số lượng Agent để gen cho một lần
    AGENTS_PER_BATCH = 15
    
    # Số lượng ký tự giới hạn ở các bước để cắt chuỗi (Ký tự đoạn)
    TIME_CONFIG_CONTEXT_LENGTH = 10000   # Cấu hình thời gian
    EVENT_CONFIG_CONTEXT_LENGTH = 8000   # Cấu hình sự kiện
    ENTITY_SUMMARY_LENGTH = 300          # Tóm tắt các thực thể
    AGENT_SUMMARY_LENGTH = 300           # Tóm tắt cấu hình Agent
    ENTITIES_PER_TYPE_DISPLAY = 20       # Lượng thực thể cho mổi loại để hiển thị
    
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
        Tạo cấu hình Simulation thông minh tự động hoàn chỉnh (Bằng tư duy chia từng bước)
        
        Args:
            simulation_id: Nhận dạng quy trình chạy Simulation
            project_id: Mã định danh dự án
            graph_id: Đồ thị đồ thị
            simulation_requirement: Yêu cầu của quá trình mô phỏng
            document_text: Nội dung file tài liệu nguồn
            entities: Danh sách các thực thể đã được lọc
            enable_twitter: Cờ hiệu để bật Twitter
            enable_reddit: Cờ hiệu để bật Reddit
            progress_callback: Hàm callback lấy trạng thái tiến trình hiện tại (current_step, total_steps, message)
            
        Returns:
            SimulationParameters: Bộ tổng cấu hình thông số đầy đủ
        """
        logger.info(f"Start generating simulation configuration: simulation_id={simulation_id}, entity_count={len(entities)}")
        self._runtime_metadata = {
            "simulation_id": simulation_id,
            "project_id": project_id,
            "component": "simulation_config_generator",
            "phase": "prepare_simulation_config",
        }
        
        # Tính toán tổng số bước
        num_batches = math.ceil(len(entities) / self.AGENTS_PER_BATCH)
        total_steps = 3 + num_batches  # Cấu hình tgian + Sự kiện + Nx(Agent Batch) + Nền tảng
        current_step = 0
        
        def report_progress(step: int, message: str):
            nonlocal current_step
            current_step = step
            if progress_callback:
                progress_callback(step, total_steps, message)
            logger.info(f"[{step}/{total_steps}] {message}")
        
        # 1. Xây dựng thông tin ngữ cảnh cơ bản
        context = self._build_context(
            simulation_requirement=simulation_requirement,
            document_text=document_text,
            entities=entities
        )
        
        reasoning_parts = []
        
        # ========== Bước 1: Tạo bộ cấu hình về Thời Gian ==========
        report_progress(1, "Generating time configuration...")
        num_entities = len(entities)
        time_config_result = self._generate_time_config(context, num_entities)
        time_config = self._parse_time_config(time_config_result, num_entities)
        reasoning_parts.append(f"Time config reasoning: {time_config_result.get('reasoning', 'Success')}")
        # ========== Bước 2: Tạo cấu hình Event ==========
        report_progress(2, "Generating event configuration and hot topics...")
        event_config_result = self._generate_event_config(context, simulation_requirement, entities)
        event_config = self._parse_event_config(event_config_result)
        reasoning_parts.append(f"Event config reasoning: {event_config_result.get('reasoning', 'Success')}")
        
        # ========== Bước 3-N: Chia thành các đợt để lấy cấu hình Agent ==========
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
        
        # ========== Tiến hành gán người (Agent) để đăng các bài Initial Post ==========
        logger.info("Assigning poster agents for initial posts...")
        event_config = self._assign_initial_post_agents(event_config, all_agent_configs)
        assigned_count = len([p for p in event_config.initial_posts if p.get("poster_agent_id") is not None])
        reasoning_parts.append(f"Initial post assignment: {assigned_count} posts have been assigned to publishers")
        
        # ========== Bước cuối: Thiết lập nền tảng ==========
        report_progress(total_steps, "Generating platform configuration...")
        twitter_config = None
        reddit_config = None
        
        if enable_twitter:
            twitter_config = PlatformConfig(
                platform="twitter",
                recency_weight=0.4,
                popularity_weight=0.3,
                relevance_weight=0.3,
                viral_threshold=10,
                echo_chamber_strength=0.5
            )
        
        if enable_reddit:
            reddit_config = PlatformConfig(
                platform="reddit",
                recency_weight=0.3,
                popularity_weight=0.4,
                relevance_weight=0.3,
                viral_threshold=15,
                echo_chamber_strength=0.6
            )
        
        # Xây dựng các tham số cuối cùng kết thúc quy trình
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
        """Thực hiện xây dựng nội dung Prompt Ngữ cảnh cho LLM, với độ dài có thể bị giới hạn"""
        
        # Tóm tắt lại Thực thể
        entity_summary = self._summarize_entities(entities)
        
        # Xây dựng nội dung
        context_parts = [
            f"## Simulation Requirements\n{simulation_requirement}",
            f"\n## Entity Information ({len(entities)} entities)\n{entity_summary}",
        ]
        
        current_length = sum(len(p) for p in context_parts)
        remaining_length = self.MAX_CONTEXT_LENGTH - current_length - 500  # Dành sẵn 500 ký tự trống
        
        if remaining_length > 0 and document_text:
            doc_text = document_text[:remaining_length]
            if len(document_text) > remaining_length:
                doc_text += "\n...(Document Truncated)"
            context_parts.append(f"\n## Original Document Content\n{doc_text}")
        
        return "\n".join(context_parts)
    
    def _summarize_entities(self, entities: List[EntityNode]) -> str:
        """Tạo chuỗi văn bản Tóm tắt cho các Thực thể"""
        lines = []
        
        # Phân nhóm bằng Loại
        by_type: Dict[str, List[EntityNode]] = {}
        for e in entities:
            t = e.get_entity_type() or "Unknown"
            if t not in by_type:
                by_type[t] = []
            by_type[t].append(e)
        
        for entity_type, type_entities in by_type.items():
            lines.append(f"\n### {entity_type} ({len(type_entities)} entity)")
            # Số lượng đã được thiết lập mặc định và Giới hạn chiều dài của bảng tóm tắt
            display_count = self.ENTITIES_PER_TYPE_DISPLAY
            summary_len = self.ENTITY_SUMMARY_LENGTH
            for e in type_entities[:display_count]:
                summary_preview = (e.summary[:summary_len] + "...") if len(e.summary) > summary_len else e.summary
                lines.append(f"- {e.name}: {summary_preview}")
            if len(type_entities) > display_count:
                lines.append(f"  ... and {len(type_entities) - display_count} more entities")
        
        return "\n".join(lines)
    
    def _call_llm_with_retry(self, prompt: str, system_prompt: str) -> Dict[str, Any]:
        """Tích hợp cơ chế retry mỗi lúc gọi Request LLM bị lỗi và Logic sửa lỗi JSON string"""
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
                    temperature=0.7 - (attempt * 0.1),  # Giảm temperature cho mỗi lần retry
                    metadata=self._runtime_metadata,
                )
                
                content = response.choices[0].message.content
                finish_reason = response.choices[0].finish_reason
                
                # Kiểm tra nội dung trã về xem có phải bị chặn vì thiếu token (Length vượt qua max) hay không
                if finish_reason == 'length':
                    logger.warning(f"LLM output was truncated (attempt {attempt+1})")
                    content = self._fix_truncated_json(content)
                
                # Phân tích nội dung JSON
                try:
                    return json.loads(content)
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse JSON (attempt {attempt+1}): {str(e)[:80]}")
                    
                    # Tiến hành sửa chữa nội dung JSON nếu bị lỗi
                    fixed = self._try_fix_config_json(content)
                    if fixed:
                        return fixed
                    
                    last_error = e
                    
            except Exception as e:
                logger.warning(f"Failed to call LLM (attempt {attempt+1}): {str(e)[:80]}")
                last_error = e
                import time
                time.sleep(2 * (attempt + 1))
        
        raise last_error or Exception("LLM connection completely failed")
    
    def _fix_truncated_json(self, content: str) -> str:
        """Đóng dấu ngoặc JSON một cách an toàn cho các string bị cắt ngang"""
        content = content.strip()
        
        # Đếm các dấu ngoặc mở bị bỏ sót chưa đóng
        open_braces = content.count('{') - content.count('}')
        open_brackets = content.count('[') - content.count(']')
        
        # Đảm bảo các thuộc tính string đã được bọc đủ dấu ngoặc kép
        if content and content[-1] not in '",}]':
            content += '"'
        
        # Thêm ngoặc đóng cho toàn bộ
        content += ']' * open_brackets
        content += '}' * open_braces
        
        return content
    
    def _try_fix_config_json(self, content: str) -> Optional[Dict[str, Any]]:
        """Cố gắng khôi phục, chắp ghép lại file cấu trúc config JSON"""
        import re
        
        # Điền những dấu ngoặc vào chuỗi bị cắt
        content = self._fix_truncated_json(content)
        
        # Regex ra đúng phần ruột nội dung JSON
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            json_str = json_match.group()
            
            # Loại bỏ các đoạn tab, ngắt line cho string
            def fix_string(match):
                s = match.group(0)
                s = s.replace('\n', ' ').replace('\r', ' ')
                s = re.sub(r'\s+', ' ', s)
                return s
            
            json_str = re.sub(r'"[^"\\]*(?:\\.[^"\\]*)*"', fix_string, json_str)
            
            try:
                return json.loads(json_str)
            except:
                # Tìm và xóa các control character
                json_str = re.sub(r'[\x00-\x1f\x7f-\x9f]', ' ', json_str)
                json_str = re.sub(r'\s+', ' ', json_str)
                try:
                    return json.loads(json_str)
                except:
                    pass
        
        return None
    
    def _generate_time_config(self, context: str, num_entities: int) -> Dict[str, Any]:
        """Tạo cấu hình thời gian (Time config) cho các tiến trình"""
        # Áp dụng nội dung ngữ cảnh đã được giới hạn chiều dài
        context_truncated = context[:self.TIME_CONFIG_CONTEXT_LENGTH]
        
        # Cắt lấy số lượng Tối đa số lượng (Chiếm 80% từ số lượng lượng Agent thực thể)
        max_agents_allowed = max(1, int(num_entities * 0.9))

#         prompt = f"""Based on the following simulation requirements, generate a time simulation configuration.

# {context_truncated}

# ## Task
# Please generate a time configuration JSON.

# ### General Principles (For reference only; adjust flexibly based on specific events and participant groups):
# - The user group consists of Vietnamese people; must comply with Hanoi Time (CST) daily routines.
# - 0:00–5:00 AM: Almost no activity (Activity Coefficient: 0.05).
# - 6:00–8:00 AM: Gradual increase in activity (Activity Coefficient: 0.4).
# - 9:00 AM–6:00 PM (Work hours): Moderate activity (Activity Coefficient: 0.7).
# - 7:00 PM–10:00 PM: Peak period (Activity Coefficient: 1.5).
# - After 11:00 PM: Activity declines (Activity Coefficient: 0.5).
# - General Pattern: Low activity in the early morning, gradual increase in the morning, moderate during work hours, and peak in the evening.
# - **Important:**: The example values below are for reference only. You need to adjust specific periods based on the nature of the event and characteristics of the participant group.
#   - e.g., The peak for students might be 9:00 PM–11:00 PM; Media groups remain active all day; Official organizations only during work hours.
#   - e.g., Breaking news may lead to discussions late at night; off_peak_hours can be shortened accordingly.

# ### Return JSON Format (Do not use Markdown)

# Example:
# {{
#     "total_simulation_hours": 72,
#     "minutes_per_round": 60,
#     "agents_per_hour_min": 5,
#     "agents_per_hour_max": 50,
#     "peak_hours": [19, 20, 21, 22],
#     "off_peak_hours": [0, 1, 2, 3, 4, 5],
#     "morning_hours": [6, 7, 8],
#     "work_hours": [9, 10, 11, 12, 13, 14, 15, 16, 17, 18],
#     "reasoning": "Time configuration explanation for this specific event."
# }}

# Field Descriptions:
# - total_simulation_hours (int): Total simulation duration, 24–168 hours. Short for breaking news, long for sustained topics.
# - minutes_per_round (int): Duration per round, 30–120 minutes, suggested 60 minutes.
# - agents_per_hour_min (int): Minimum activated agents per hour (Range: 1-{max_agents_allowed}).
# - agents_per_hour_max (int): Maximum activated agents per hour (Range: 1-{max_agents_allowed}).
# - peak_hours (int array): Peak hours, adjusted based on the participant group.
# - off_peak_hours (int array): Off-peak hours, usually late night/early morning.
# - morning_hours (int array): Morning hours.
# - work_hours (int array): Working hours.
# - reasoning (string): Brief explanation of why this configuration was chosen."""
        
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
        
        # system_prompt = "You are a social media simulation expert. Return in pure JSON format; time configurations must comply with Vietnamese daily routines."

        system_prompt = "Bạn là chuyên gia mô phỏng mạng xã hội. Trả về định dạng JSON thuần túy; cấu hình thời gian cần phù hợp với thói quen sinh hoạt của người Việt Nam."
        
        try:
            return self._call_llm_with_retry(prompt, system_prompt)
        except Exception as e:
            logger.warning(f"Failed to generate Time Config through LLM {e}. Returning the basic default rules...")
            return self._get_default_time_config(num_entities)
    
    def _get_default_time_config(self, num_entities: int) -> Dict[str, Any]:
        """Tạo sẵn file chuẩn nếu bị đơ để trả ra theo múi giờ chuẩn sinh hoạt China"""
        return {
            "total_simulation_hours": 72,
            "minutes_per_round": 60,  # 1 Hour / Vòng -> Rút ngắn Time
            "agents_per_hour_min": max(1, num_entities // 15),
            "agents_per_hour_max": max(5, num_entities // 5),
            "peak_hours": [19, 20, 21, 22],
            "off_peak_hours": [0, 1, 2, 3, 4, 5],
            "morning_hours": [6, 7, 8],
            "work_hours": [9, 10, 11, 12, 13, 14, 15, 16, 17, 18],
            "reasoning": "Defaults to Vietnamese users' daily routines and working hours (1 hour/round)"
        }
    
    def _parse_time_config(self, result: Dict[str, Any], num_entities: int) -> TimeSimulationConfig:
        """Phân tích nội dung được định hình của JSON qua hàm parse kiểm tra, Xác nhận nếu lượng agents_per_hour vượt ngưỡng giới hạn """
        # Lấy giá trị chưa chỉnh sửa
        agents_per_hour_min = result.get("agents_per_hour_min", max(1, num_entities // 15))
        agents_per_hour_max = result.get("agents_per_hour_max", max(5, num_entities // 5))
        
        # Tiến hành kiểm tra xác minh: Đảm bảo độ lớn không lớn hơn con số Total Agent
        if agents_per_hour_min > num_entities:
            logger.warning(f"agents_per_hour_min ({agents_per_hour_min}) exceeds total number of Agents ({num_entities}), corrected.")
            agents_per_hour_min = max(1, num_entities // 10)
        
        if agents_per_hour_max > num_entities:
            logger.warning(f"agents_per_hour_max ({agents_per_hour_max}) exceeds total number of Agents ({num_entities}), corrected.")
            agents_per_hour_max = max(agents_per_hour_min + 1, num_entities // 2)
        
        # Đảm bảo min luôn luôn nhỏ hơn max
        if agents_per_hour_min >= agents_per_hour_max:
            agents_per_hour_min = max(1, agents_per_hour_max // 2)
            logger.warning(f"agents_per_hour_min >= max, modified to {agents_per_hour_min}")
        
        return TimeSimulationConfig(
            total_simulation_hours=result.get("total_simulation_hours", 72),
            minutes_per_round=result.get("minutes_per_round", 60),  # Mặc định mỗi vòng = 1 giờ
            agents_per_hour_min=agents_per_hour_min,
            agents_per_hour_max=agents_per_hour_max,
            peak_hours=result.get("peak_hours", [19, 20, 21, 22]),
            off_peak_hours=result.get("off_peak_hours", [0, 1, 2, 3, 4, 5]),
            off_peak_activity_multiplier=0.05,  # Gần như 0 mạng sáng rạng sáng
            morning_hours=result.get("morning_hours", [6, 7, 8]),
            morning_activity_multiplier=0.4,
            work_hours=result.get("work_hours", list(range(9, 19))),
            work_activity_multiplier=0.7,
            peak_activity_multiplier=1.5
        )
    
    def _generate_event_config(
        self, 
        context: str, 
        simulation_requirement: str,
        entities: List[EntityNode]
    ) -> Dict[str, Any]:
        """Tạo ra cho các thông số Event config"""
        
        # Tự liệt kê các Loại có thể xuất hiện để LLM tham khảo
        entity_types_available = list(set(
            e.get_entity_type() or "Unknown" for e in entities
        ))
        
        # Ghi các Thực thể điển hình của mổi loại
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
        
        # Có chặn để lấy chuỗi theo cấu hình chiều dài giới hạn
        context_truncated = context[:self.EVENT_CONFIG_CONTEXT_LENGTH]

#         prompt = f"""Based on the following simulation requirements, generate an event configuration.

# Simulation Requirements: {simulation_requirement}

# {context_truncated}

# ## Available Entity Types and Examples
# {type_info}

# ## Task 
# Please generate an event configuration JSON:
# - Extract key hot topic keywords.
# - Describe the direction of public opinion development.
# - Design initial post content; **each post must specify a poster_type (publisher type)**.

# **IMPORTANT**: The poster_type must be selected from the "Available Entity Types" above so that initial posts can be assigned to the appropriate Agent for publishing.
#   For example: Official statements should be posted by Official/University types, news by MediaOutlet, and student perspectives by Student.

# Return in JSON format (no markdown):
# {{
#     "hot_topics": ["Keyword1", "Keyword2", ...],
#     "narrative_direction": "<Description of the public opinion development path>",
#     "initial_posts": [
#         {{"content": "Post Content...", "poster_type": "Entity type (must be selected from available types)"}},
#         ...
#     ],
#     "reasoning": "<Short Explanation>"
# }}"""

#         system_prompt = "You are a public opinion analysis expert. Return in pure JSON format. Ensure that poster_type exactly matches the available entity types."
        
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
        """Parse lấy các Thuộc Tính cấu hình Event"""
        return EventConfig(
            initial_posts=result.get("initial_posts", []),
            scheduled_events=[],
            hot_topics=result.get("hot_topics", []),
            narrative_direction=result.get("narrative_direction", "")
        )
    
    def _assign_initial_post_agents(
        self,
        event_config: EventConfig,
        agent_configs: List[AgentActivityConfig]
    ) -> EventConfig:
        """
        Khớp quyền Agent với loại Poster_type cho các Bài Post đầu
        
        So sánh cho phù hợp của mỗi post để phân bố Agent id tối ưu nhất
        """
        if not event_config.initial_posts:
            return event_config
        
        # Build hệ thống agent index bằng kiểu loại
        agents_by_type: Dict[str, List[AgentActivityConfig]] = {}
        for agent in agent_configs:
            etype = agent.entity_type.lower()
            if etype not in agents_by_type:
                agents_by_type[etype] = []
            agents_by_type[etype].append(agent)
        
        # Bảng Alias ánh xạ tương đương (Cho phép LLM sử dụng nhiều quy ước format khác nhau)
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
        
        # Ghi chú từng loại agent đã dùng index nào, tránh dùng lại cùng 1 agent lặp đi lặp lại
        used_indices: Dict[str, int] = {}
        
        updated_posts = []
        for post in event_config.initial_posts:
            poster_type = post.get("poster_type", "").lower()
            content = post.get("content", "")
            
            # Khớp tìm agent phù hợp
            matched_agent_id = None
            
            # 1. Trùng khớp trực tiếp lấy luôn
            if poster_type in agents_by_type:
                agents = agents_by_type[poster_type]
                idx = used_indices.get(poster_type, 0) % len(agents)
                matched_agent_id = agents[idx].agent_id
                used_indices[poster_type] = idx + 1
            else:
                # 2. Sử dụng bí danh alias để khớp nếu dùng sai keyword
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
            
            # 3. Nếu xui xẻo vẫn không tìm thấy, lấy thẳng Agent có điểm Influence (Sức ảnh hưởng) cao nhất
            if matched_agent_id is None:
                logger.warning(f"Could not find matching Agent type '{poster_type}', assigning to highest influence Agent instead")
                if agent_configs:
                    # Sort ảnh hưởng giảm dần, lấy index [0]
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
    
    def _generate_agent_configs_batch(
        self,
        context: str,
        entities: List[EntityNode],
        start_idx: int,
        simulation_requirement: str
    ) -> List[AgentActivityConfig]:
        """Chia đợt gửi lên gọi tạo Cấu hình mạng lưới Agents"""
        
        # Build các node Entity (Dựa trên cấu hình lượng chữ giới hạn)
        entity_list = []
        summary_len = self.AGENT_SUMMARY_LENGTH
        for i, e in enumerate(entities):
            entity_list.append({
                "agent_id": start_idx + i,
                "entity_name": e.name,
                "entity_type": e.get_entity_type() or "Unknown",
                "summary": e.summary[:summary_len] if e.summary else ""
            })
        
#         prompt = f"""Based on the following information, generate social media activity configurations for each entity.

# Simulation Requirements: {simulation_requirement}

# ## Entity List
# ```json
# {json.dumps(entity_list, ensure_ascii=False, indent=2)}
# ```

# ## Task 
# Generate activity configurations for each entity, noting:
# - **Time aligns with Vietnamese daily routines**: Almost no activity between 0-5 AM; most active during 7-10 PM (19:00-22:00).
# - **Official Institutions (University/GovernmentAgency)**: Low activity (0.1-0.3), active during work hours (9:00-17:00), slow response (60-240 mins), high influence (2.5-3.0).
# - **Media (MediaOutlet)**: Medium activity (0.4-0.6), active all day (8:00-23:00), fast response (5-30 mins), high influence (2.0-2.5).
# - **Individuals (Student/Person/Alumni)**: High activity (0.6-0.9), active mainly in the evening (18:00-23:00), fast response (1-15 mins), low influence (0.8-1.2).
# - **Public Figures/Experts**: Medium activity (0.4-0.6), medium-high influence (1.5-2.0).

# Return in JSON format (no markdown):
# {{
#     "agent_configs": [
#         {{
#             "agent_id": <Must match the input exactly>,
#             "activity_level": <0.0-1.0>,
#             "posts_per_hour": <Post frequency>,
#             "comments_per_hour": <Comment frequency>,
#             "active_hours": [<List of active hours, considering Vietnamese routines>],
#             "response_delay_min": <Minimum response delay in minutes>,
#             "response_delay_max": <Maximum response delay in minutes>,
#             "sentiment_bias": <-1.0 to 1.0>,
#             "stance": "<supportive/opposing/neutral/observer>",
#             "influence_weight": <Influence weight>
#         }},
#         ...
#     ]
# }}"""

#         system_prompt = "You are a social media behavior analysis expert. Return pure JSON. Configurations must comply with Vietnamese daily routines."

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
            llm_configs = {cfg["agent_id"]: cfg for cfg in result.get("agent_configs", [])}
        except Exception as e:
            logger.warning(f"Failed LLM generating Agent batch configs: {e}, falling back to default manual rules.")
            llm_configs = {}
        
        # Tạo object list cho AgentActivityConfig
        configs = []
        for i, entity in enumerate(entities):
            agent_id = start_idx + i
            cfg = llm_configs.get(agent_id, {})
            
            # Gán Manual tự động nếu Bot LLM thiếu xót
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
        """Tự động gen cấu hình 1 người (agent) dựa trên bộ rule cứng có sẵn nếu gọi bot LLM bị fail (Luật theo múi giờ sinh học)"""
        entity_type = (entity.get_entity_type() or "Unknown").lower()
        
        if entity_type in ["university", "governmentagency", "ngo"]:
            # Cơ quan chức năng Nhà nước / Doanh nghiệp: làm việc trong khung giờ chuẩn hành chính, trả lời ít nhưng nặng đô
            return {
                "activity_level": 0.2,
                "posts_per_hour": 0.1,
                "comments_per_hour": 0.05,
                "active_hours": list(range(9, 18)),  # 9:00-17:59
                "response_delay_min": 60,
                "response_delay_max": 240,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 3.0
            }
        elif entity_type in ["mediaoutlet"]:
            # Báo đài truyền thông: cả ngày đưa tin, ra bài lẹ giật tít, tốc độ cao
            return {
                "activity_level": 0.5,
                "posts_per_hour": 0.8,
                "comments_per_hour": 0.3,
                "active_hours": list(range(7, 24)),  # 7:00-23:59
                "response_delay_min": 5,
                "response_delay_max": 30,
                "sentiment_bias": 0.0,
                "stance": "observer",
                "influence_weight": 2.5
            }
        elif entity_type in ["professor", "expert", "official"]:
            # Giáo sư đại học/Người phát biểu: Chỉ nói ban ngày và tối, ra bài ít
            return {
                "activity_level": 0.4,
                "posts_per_hour": 0.3,
                "comments_per_hour": 0.5,
                "active_hours": list(range(8, 22)),  # 8:00-21:59
                "response_delay_min": 15,
                "response_delay_max": 90,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 2.0
            }
        elif entity_type in ["student"]:
            # Tần suất cho lứa Sinh viên: hay ra bài / cãi nhau liên tục ban đêm rất nhiều
            return {
                "activity_level": 0.8,
                "posts_per_hour": 0.6,
                "comments_per_hour": 1.5,
                "active_hours": [8, 9, 10, 11, 12, 13, 18, 19, 20, 21, 22, 23],  # Sáng + Đêm Tối
                "response_delay_min": 1,
                "response_delay_max": 15,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 0.8
            }
        elif entity_type in ["alumni"]:
            # Cựu sinh viên: Thường online đêm là chính
            return {
                "activity_level": 0.6,
                "posts_per_hour": 0.4,
                "comments_per_hour": 0.8,
                "active_hours": [12, 13, 19, 20, 21, 22, 23],  # Giờ nghỉ trưa + Buổi tối
                "response_delay_min": 5,
                "response_delay_max": 30,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 1.0
            }
        else:
            # Thuộc cho số đông (Cư dân mạng / Người Qua Đường): Phấn khích về đêm
            return {
                "activity_level": 0.7,
                "posts_per_hour": 0.5,
                "comments_per_hour": 1.2,
                "active_hours": [9, 10, 11, 12, 13, 18, 19, 20, 21, 22, 23],  # Ban Ngày rảnh + Buổi tối rảnh
                "response_delay_min": 2,
                "response_delay_max": 20,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 1.0
            }
    

