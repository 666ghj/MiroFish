"""
Trình tạo Profile Agent (Hồ sơ Nhân vật) cho Agent bằng Framework OASIS
Chuyển đổi dữ liệu Thực thể được Query từ Zep ra chuẩn định dạng của các Agent tham gia vào mạng

Vị trí trong pipeline:
─────────────────────────────────────────────────────────────────────────────
  simulation_manager.prepare_simulation()  [Giai đoạn 2]
      └─ OasisProfileGenerator.generate_profiles_from_entities()
              └─ generate_profile_from_entity()  [mỗi entity 1 lần]
                      ├─ _build_entity_context()       [tổng hợp ngữ cảnh]
                      │       └─ _search_zep_for_entity()  [vector search]
                      └─ _generate_profile_with_llm()  [gọi LLM]
                              └─ _generate_profile_rule_based()  [fallback]
─────────────────────────────────────────────────────────────────────────────

Input:  List[EntityNode] từ ZepEntityReader (zep_entity_reader.py)
Output: List[OasisAgentProfile] → ghi ra reddit_profiles.json / twitter_profiles.csv

Nâng cấp cải thiện:
1. Kết hợp dùng chức năng Search trên Zep để lấy Profile giàu sắc thái
2. Gen các cấu hình về tính cách một cách sắc xảo và cực sâu cho Prompt
3. Nhận dạng rạch ròi người với Group/Công ty/Phe phái trên social network
"""

import json
import random
import time
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime

from openai import OpenAI
from zep_cloud.client import Zep

from ..config import Config
from ..utils.logger import get_logger
from ..utils.llm_cost import create_tracked_chat_completion
from .zep_entity_reader import EntityNode, ZepEntityReader

logger = get_logger('mirofish.oasis_profile')


# ==============================================================================
# DATACLASS: OasisAgentProfile — Cấu trúc hồ sơ 1 agent trong OASIS
# ==============================================================================
# Mỗi EntityNode từ Zep → 1 OasisAgentProfile sau khi qua bước generate.
# Class này đóng vai trò "adapter": chuẩn hoá dữ liệu thành 2 format
# mà OASIS yêu cầu (Twitter CSV / Reddit JSON).
#
# Quan hệ các field với OASIS:
#   user_id    → OASIS dùng để map agent trong agent_graph.get_agent()
#   user_name  → username trên mạng xã hội ảo (không có dấu cách)
#   bio        → thông tin hiển thị công khai trên trang cá nhân
#   persona    → system prompt bí mật điều khiển mọi hành vi của LLM agent
# ==============================================================================

@dataclass
class OasisAgentProfile:
    """Cấu trúc của Dataclass Profile Agent qua quy định của OASIS"""

    # --- Định danh bắt buộc ---
    user_id: int       # Index số nguyên, bắt đầu từ 0 (bắt buộc để OASIS map đúng agent)
    user_name: str     # Username không dấu cách, ví dụ: "nguyen_van_a_392" (sinh từ _generate_username)
    name: str          # Tên thật hiển thị, ví dụ: "Nguyễn Văn A"

    # --- Nội dung agent ---
    bio: str           # Tiểu sử ngắn (~150-200 ký tự), hiển thị công khai trên trang cá nhân
    persona: str       # Mô tả nhân cách chi tiết (~2000 từ), được nhét vào system prompt của agent LLM
                       # Đây là thứ THỰC SỰ điều khiển agent nghĩ và nói gì

    # --- Thông số mạng xã hội (tác động đến "trọng số" của agent trong OASIS) ---
    karma: int = 1000          # Reddit: điểm uy tín (cao = post được nhiều người thấy hơn)
    friend_count: int = 100    # Twitter: số người đang follow
    follower_count: int = 150  # Twitter: số người follow mình
    statuses_count: int = 500  # Twitter: số tweet đã đăng (độ hoạt động)

    # --- Thông tin cá nhân bổ sung (tùy chọn, làm phong phú persona) ---
    age: Optional[int] = None
    gender: Optional[str] = None          # "male", "female", hoặc "other" (tổ chức)
    mbti: Optional[str] = None            # Ví dụ: "INTJ", "ENFP" — gợi ý cách LLM phản ứng
    country: Optional[str] = None
    profession: Optional[str] = None
    interested_topics: List[str] = field(default_factory=list)  # Các chủ đề agent quan tâm

    # --- Metadata truy vết nguồn gốc ---
    source_entity_uuid: Optional[str] = None   # UUID của EntityNode gốc trong Zep
    source_entity_type: Optional[str] = None   # Loại entity (ví dụ: "Person", "Organization")
    entity_category: Optional[str] = None      # Kết quả LLM classification: "individual" | "organization"

    created_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))

    def to_reddit_format(self) -> Dict[str, Any]:
        """
        Xuất profile thành dict theo chuẩn Reddit của OASIS.

        Khác biệt với to_twitter_format(): có karma thay vì friend/follower_count.
        Các field tùy chọn (age, gender, ...) chỉ được thêm vào nếu có giá trị
        để tránh null gây lỗi trong OASIS engine.
        """
        profile = {
            "user_id": self.user_id,
            "username": self.user_name,  # OASIS yêu cầu không có dấu "_" là không có vấn đề nhưng không được có khoảng trắng
            "name": self.name,
            "bio": self.bio,
            "persona": self.persona,
            "karma": self.karma,
            "created_at": self.created_at,
        }

        # Chỉ thêm field nếu có giá trị — OASIS không xử lý được None
        if self.age:
            profile["age"] = self.age
        if self.gender:
            profile["gender"] = self.gender
        if self.mbti:
            profile["mbti"] = self.mbti
        if self.country:
            profile["country"] = self.country
        if self.profession:
            profile["profession"] = self.profession
        if self.interested_topics:
            profile["interested_topics"] = self.interested_topics

        return profile

    def to_twitter_format(self) -> Dict[str, Any]:
        """
        Xuất profile thành dict theo chuẩn Twitter của OASIS.

        Khác biệt với to_reddit_format(): có friend_count, follower_count, statuses_count
        thay vì karma. Cả hai format đều dùng chung bio và persona.
        """
        profile = {
            "user_id": self.user_id,
            "username": self.user_name,
            "name": self.name,
            "bio": self.bio,
            "persona": self.persona,
            "friend_count": self.friend_count,
            "follower_count": self.follower_count,
            "statuses_count": self.statuses_count,
            "created_at": self.created_at,
        }

        if self.age:
            profile["age"] = self.age
        if self.gender:
            profile["gender"] = self.gender
        if self.mbti:
            profile["mbti"] = self.mbti
        if self.country:
            profile["country"] = self.country
        if self.profession:
            profile["profession"] = self.profession
        if self.interested_topics:
            profile["interested_topics"] = self.interested_topics

        return profile

    def to_dict(self) -> Dict[str, Any]:
        """Xuất toàn bộ profile thành dict không lọc (kể cả source_entity_uuid/type)."""
        return {
            "user_id": self.user_id,
            "user_name": self.user_name,
            "name": self.name,
            "bio": self.bio,
            "persona": self.persona,
            "karma": self.karma,
            "friend_count": self.friend_count,
            "follower_count": self.follower_count,
            "statuses_count": self.statuses_count,
            "age": self.age,
            "gender": self.gender,
            "mbti": self.mbti,
            "country": self.country,
            "profession": self.profession,
            "interested_topics": self.interested_topics,
            "source_entity_uuid": self.source_entity_uuid,
            "source_entity_type": self.source_entity_type,
            "entity_category": self.entity_category,
            "created_at": self.created_at,
        }


# ==============================================================================
# CLASS: OasisProfileGenerator — Sinh agent profile từ EntityNode
# ==============================================================================
# Stateful: giữ OpenAI client, Zep client, và graph_id trong suốt vòng sống.
# Được khởi tạo 1 lần trong prepare_simulation() rồi dùng để sinh toàn bộ profiles.
# ==============================================================================

class OasisProfileGenerator:
    """
    Trình Gen Profile cho Simulation (Hệ OASIS)

    Sử dụng các Node Entity lấy được từ ZEP -> OASIS Mocks cho Simulation Agent

    Các Option Cải Tiến Tối Ưu Tích Hợp:
    1. Có liên kết với Server Zep API cho bước Query Dữ liệu từ Vector Database
    2. Tập trung Mô tả Tiểu sử (Background) (Nhấn mạnh Nghề nghiệp/Tính cách/StatusMXH/...)
    3. Ngắt rời loại Person ra bên ngoài để nhận thức Phân Cấp Group
    """

    # 16 loại tính cách MBTI — dùng khi sinh ngẫu nhiên hoặc fallback
    MBTI_TYPES = [
        "INTJ", "INTP", "ENTJ", "ENTP",
        "INFJ", "INFP", "ENFJ", "ENFP",
        "ISTJ", "ISFJ", "ESTJ", "ESFJ",
        "ISTP", "ISFP", "ESTP", "ESFP"
    ]

    # Danh sách quốc tịch fallback khi LLM không sinh được
    COUNTRIES = [
        "Vietnam", "China", "US", "UK", "Japan", "Germany", "France",
        "Canada", "Australia", "Brazil", "India", "South Korea"
    ]

    # Loại entity được xem là CÁ NHÂN → dùng _build_individual_persona_prompt()
    # LLM sẽ sinh persona theo góc nhìn 1 người cụ thể (tuổi, nghề nghiệp, MBTI riêng)
    INDIVIDUAL_ENTITY_TYPES = [
        "student", "alumni", "professor", "person", "publicfigure",
        "expert", "faculty", "official", "journalist", "activist"
    ]

    # Loại entity được xem là TỔ CHỨC/NHÓM → dùng _build_group_persona_prompt()
    # LLM sẽ sinh persona như một tài khoản chính thức đại diện tổ chức
    # (age=30 cố định, gender="other")
    GROUP_ENTITY_TYPES = [
        "university", "governmentagency", "organization", "ngo",
        "mediaoutlet", "company", "institution", "group", "community"
    ]

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None,
        zep_api_key: Optional[str] = None,
        graph_id: Optional[str] = None
    ):
        # --- Khởi tạo OpenAI client (dùng để gọi LLM sinh persona) ---
        self.api_key = api_key or Config.LLM_API_KEY
        self.base_url = base_url or Config.LLM_BASE_URL
        self.model_name = model_name or Config.LLM_MODEL_NAME

        if not self.api_key:
            raise ValueError("Không tìm thấy LLM_API_KEY")

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )

        # Metadata dùng cho hệ thống tính cost API (llm_cost.py)
        self._runtime_metadata: Dict[str, Any] = {
            "component": "oasis_profile_generator",
            "phase": "generate_profiles",
        }

        # --- Khởi tạo Zep client (dùng để vector search tìm thêm context) ---
        # graph_id được truyền vào từ simulation_manager để tất cả search đều
        # trỏ đúng vào graph của simulation hiện tại
        self.zep_api_key = zep_api_key or Config.ZEP_API_KEY
        self.zep_client = None
        self.graph_id = graph_id

        if self.zep_api_key:
            try:
                self.zep_client = Zep(api_key=self.zep_api_key)
            except Exception as e:
                # Không raise — Zep search là tính năng bổ sung, không bắt buộc
                logger.warning(f"Failed to initialize Zep client: {e}")

    # --------------------------------------------------------------------------
    # PUBLIC: generate_profile_from_entity — Entry point sinh 1 profile đơn lẻ
    # --------------------------------------------------------------------------

    def generate_profile_from_entity(
        self,
        entity: EntityNode,
        user_id: int,
        use_llm: bool = True
    ) -> OasisAgentProfile:
        """
        Chuyển đổi 1 EntityNode thành 1 OasisAgentProfile.

        Luồng xử lý:
          EntityNode
              ↓
          _build_entity_context()   → gom tất cả context thành 1 chuỗi
              ↓
          _generate_profile_with_llm() hoặc _generate_profile_rule_based()
              ↓
          OasisAgentProfile

        Args:
            entity: EntityNode đọc từ Zep (có related_edges và related_nodes)
            user_id: Index số nguyên, bắt đầu từ 0, bắt buộc cho OASIS
            use_llm: True = gọi LLM (chậm, chất lượng cao); False = rule-based (nhanh, đơn giản)

        Returns:
            OasisAgentProfile đã điền đầy đủ thông tin
        """
        entity_type = entity.get_entity_type() or "Entity"

        name = entity.name
        user_name = self._generate_username(name)

        # Tổng hợp toàn bộ ngữ cảnh về entity (attributes + edges + Zep search)
        context = self._build_entity_context(entity)

        if use_llm:
            profile_data = self._generate_profile_with_llm(
                entity_name=name,
                entity_type=entity_type,
                entity_summary=entity.summary,
                entity_attributes=entity.attributes,
                context=context
            )
        else:
            # Fallback thủ công — không gọi LLM, dùng template cứng
            profile_data = self._generate_profile_rule_based(
                entity_name=name,
                entity_type=entity_type,
                entity_summary=entity.summary,
                entity_attributes=entity.attributes
            )

        # Ghép kết quả LLM vào OasisAgentProfile
        # .get(field, fallback) để an toàn nếu LLM bỏ sót field nào
        return OasisAgentProfile(
            user_id=user_id,
            user_name=user_name,
            name=name,
            bio=profile_data.get("bio", f"{entity_type}: {name}"),
            persona=profile_data.get("persona", entity.summary or f"A {entity_type} named {name}."),
            karma=profile_data.get("karma", random.randint(500, 5000)),
            friend_count=profile_data.get("friend_count", random.randint(50, 500)),
            follower_count=profile_data.get("follower_count", random.randint(100, 1000)),
            statuses_count=profile_data.get("statuses_count", random.randint(100, 2000)),
            age=profile_data.get("age"),
            gender=profile_data.get("gender"),
            mbti=profile_data.get("mbti"),
            country=profile_data.get("country"),
            profession=profile_data.get("profession"),
            interested_topics=profile_data.get("interested_topics", []),
            source_entity_uuid=entity.uuid,
            source_entity_type=entity_type,
            entity_category=profile_data.get("entity_category"),
        )

    # --------------------------------------------------------------------------
    # PRIVATE: _generate_username — Tạo username duy nhất từ tên entity
    # --------------------------------------------------------------------------

    def _generate_username(self, name: str) -> str:
        """
        Tạo username hợp lệ từ tên thật.

        Quy trình:
        1. Lowercase + thay khoảng trắng bằng "_"
        2. Giữ chỉ ký tự alphanumeric và "_"
        3. Thêm suffix số ngẫu nhiên 3 chữ số để tránh trùng

        Ví dụ: "Nguyễn Văn A" → "nguyn_vn_a_392"
        (ký tự Unicode bị strip vì isalnum() chỉ giữ ASCII)
        """
        username = name.lower().replace(" ", "_")
        username = ''.join(c for c in username if c.isalnum() or c == '_')

        suffix = random.randint(100, 999)
        return f"{username}_{suffix}"

    # --------------------------------------------------------------------------
    # PRIVATE: _search_zep_for_entity — Vector search song song trên Zep
    # --------------------------------------------------------------------------
    # Đây là bước "tăng cường" context: tìm thêm facts và summaries liên quan
    # đến entity trong Zep vector database bằng semantic search.
    #
    # Tại sao cần? related_edges trong EntityNode chỉ có edges kết nối trực tiếp.
    # Zep vector search có thể tìm được thông tin liên quan theo ngữ nghĩa,
    # kể cả những facts không có edge trực tiếp đến entity này.
    #
    # Tại sao cần chạy song song?
    # Zep API chưa hỗ trợ tìm cả nodes lẫn edges trong 1 request →
    # dùng ThreadPoolExecutor 2 workers để gọi song song, giảm latency từ 2x → 1x.
    # --------------------------------------------------------------------------

    def _search_zep_for_entity(self, entity: EntityNode) -> Dict[str, Any]:
        """
        Tìm kiếm semantic trong Zep Vector DB để bổ sung context cho entity.

        Gọi 2 loại search song song:
        - scope="edges": tìm các fact/quan hệ liên quan đến entity
        - scope="nodes": tìm các entity khác có liên quan theo ngữ nghĩa

        Mỗi search có retry 3 lần với exponential backoff (2s → 4s → 8s).

        Args:
            entity: EntityNode cần tìm thêm context

        Returns:
            Dict với:
            - facts: List[str] các fact tìm được từ edge search (loại trùng với related_edges)
            - node_summaries: List[str] summaries của các entity liên quan
            - context: Chuỗi text tổng hợp để nhét vào LLM prompt
        """
        import concurrent.futures

        # Nếu không có Zep client hoặc graph_id → trả về rỗng, không làm gì
        if not self.zep_client:
            return {"facts": [], "node_summaries": [], "context": ""}

        entity_name = entity.name

        results = {
            "facts": [],
            "node_summaries": [],
            "context": ""
        }

        if not self.graph_id:
            logger.debug(f"Skipping Zep search: graph_id not set")
            return results

        # Query tổng quát để Zep semantic search trả về nhiều kết quả nhất
        comprehensive_query = f"Provide all facts, activities, relationships, and context about: {entity_name}"

        def search_edges():
            """Tìm các fact/quan hệ qua edge search — có retry."""
            max_retries = 3
            last_exception = None
            delay = 2.0

            for attempt in range(max_retries):
                try:
                    return self.zep_client.graph.search(
                        query=comprehensive_query,
                        graph_id=self.graph_id,
                        limit=30,        # Lấy tối đa 30 facts
                        scope="edges",
                        reranker="rrf"   # Reciprocal Rank Fusion — kết hợp nhiều ranking strategies
                    )
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        logger.debug(f"Zep Edge search failed on attempt {attempt + 1}: {str(e)[:80]}, retrying...")
                        time.sleep(delay)
                        delay *= 2
                    else:
                        logger.debug(f"Zep Edge search entirely failed after {max_retries} attempts: {e}")
            return None

        def search_nodes():
            """Tìm các entity liên quan qua node search — có retry."""
            max_retries = 3
            last_exception = None
            delay = 2.0

            for attempt in range(max_retries):
                try:
                    return self.zep_client.graph.search(
                        query=comprehensive_query,
                        graph_id=self.graph_id,
                        limit=20,        # Lấy tối đa 20 node summaries
                        scope="nodes",
                        reranker="rrf"
                    )
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        logger.debug(f"Zep Node search failed on attempt {attempt + 1}: {str(e)[:80]}, retrying...")
                        time.sleep(delay)
                        delay *= 2
                    else:
                        logger.debug(f"Zep Node search entirely failed after {max_retries} attempts: {e}")
            return None

        try:
            # Chạy song song 2 search — giảm thời gian chờ từ ~2T xuống ~T
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                edge_future = executor.submit(search_edges)
                node_future = executor.submit(search_nodes)

                edge_result = edge_future.result(timeout=30)
                node_result = node_future.result(timeout=30)

            # Xử lý kết quả edge search → trích fact string
            all_facts = set()  # Set để tự dedup
            if edge_result and hasattr(edge_result, 'edges') and edge_result.edges:
                for edge in edge_result.edges:
                    if hasattr(edge, 'fact') and edge.fact:
                        all_facts.add(edge.fact)
            results["facts"] = list(all_facts)

            # Xử lý kết quả node search → trích summary và tên entity liên quan
            all_summaries = set()
            if node_result and hasattr(node_result, 'nodes') and node_result.nodes:
                for node in node_result.nodes:
                    if hasattr(node, 'summary') and node.summary:
                        all_summaries.add(node.summary)
                    if hasattr(node, 'name') and node.name and node.name != entity_name:
                        all_summaries.add(f"Related Entities: {node.name}")
            results["node_summaries"] = list(all_summaries)

            # Ghép thành 1 chuỗi context để truyền vào LLM prompt
            context_parts = []
            if results["facts"]:
                context_parts.append("Facts & Infomation:\n" + "\n".join(f"- {f}" for f in results["facts"][:20]))
            if results["node_summaries"]:
                context_parts.append("Related Entities:\n" + "\n".join(f"- {s}" for s in results["node_summaries"][:10]))
            results["context"] = "\n\n".join(context_parts)

            logger.info(f"Zep unified search completed: {entity_name}, fetched {len(results['facts'])} facts, {len(results['node_summaries'])} related nodes")

        except concurrent.futures.TimeoutError:
            logger.warning(f"Zep Retrieval Time-Out ({entity_name})")
        except Exception as e:
            logger.warning(f"Zep Retrieval Failed ({entity_name}): {e}")

        return results

    # --------------------------------------------------------------------------
    # PRIVATE: _build_entity_context — Tổng hợp 4 nguồn context cho LLM
    # --------------------------------------------------------------------------
    # Hàm này gom tất cả thông tin biết được về entity thành 1 chuỗi dài
    # để nhét vào LLM prompt. Có 4 nguồn theo thứ tự ưu tiên:
    #
    #   1. attributes  — thuộc tính key-value trực tiếp từ Zep node
    #   2. related_edges — facts/quan hệ từ các edge đã enrich (tránh trùng lặp với nguồn 4)
    #   3. related_nodes — mô tả ngắn của các entity lân cận
    #   4. Zep vector search — facts bổ sung từ semantic search (lọc bỏ trùng với nguồn 2)
    # --------------------------------------------------------------------------

    def _build_entity_context(self, entity: EntityNode) -> str:
        """
        Gom tất cả thông tin có thể biết về entity thành 1 chuỗi context hoàn chỉnh.

        Output chuỗi được cắt còn tối đa 3000 ký tự trước khi nhét vào LLM prompt.

        Cấu trúc output (nếu đủ dữ liệu):
            ### Entity Attributes
            - key1: value1
            - key2: value2

            ### Facts & Relationships
            - A làm việc tại B
            - C là sinh viên của D

            ### Related Entity Info
            - **Bộ GD** (Organization): Cơ quan quản lý giáo dục...

            ### Facts retrieved via ZEP
            - fact mới không trùng với phần trên

            ### Entity nodes retrieved via Zep
            - summary của entity liên quan

        Args:
            entity: EntityNode đã enrich với related_edges và related_nodes

        Returns:
            Chuỗi context markdown dùng trong LLM prompt
        """
        context_parts = []

        # --- Nguồn 1: Attributes trực tiếp của node ---
        if entity.attributes:
            attrs = []
            for key, value in entity.attributes.items():
                if value and str(value).strip():
                    attrs.append(f"- {key}: {value}")
            if attrs:
                context_parts.append("### Entity Attributes\n" + "\n".join(attrs))

        # --- Nguồn 2: Facts từ các edge đã enrich ---
        # Lưu vào set để sau đó lọc trùng với kết quả Zep search (nguồn 4)
        existing_facts = set()
        if entity.related_edges:
            relationships = []
            for edge in entity.related_edges:
                fact = edge.get("fact", "")
                edge_name = edge.get("edge_name", "")
                direction = edge.get("direction", "")

                if fact:
                    relationships.append(f"- {fact}")
                    existing_facts.add(fact)
                elif edge_name:
                    # Nếu không có fact text, tự tạo dạng arrow diagram
                    if direction == "outgoing":
                        relationships.append(f"- {entity.name} --[{edge_name}]--> (Related Entity)")
                    else:
                        relationships.append(f"- (Related Entity) --[{edge_name}]--> {entity.name}")

            if relationships:
                context_parts.append("### Facts & Relationships\n" + "\n".join(relationships))

        # --- Nguồn 3: Thông tin cơ bản của các node lân cận ---
        if entity.related_nodes:
            related_info = []
            for node in entity.related_nodes:
                node_name = node.get("name", "")
                node_labels = node.get("labels", [])
                node_summary = node.get("summary", "")

                # Loại bỏ label mặc định để chỉ hiện loại cụ thể
                custom_labels = [l for l in node_labels if l not in ["Entity", "Node"]]
                label_str = f" ({', '.join(custom_labels)})" if custom_labels else ""

                if node_summary:
                    related_info.append(f"- **{node_name}**{label_str}: {node_summary}")
                else:
                    related_info.append(f"- **{node_name}**{label_str}")

            if related_info:
                context_parts.append("### Related Entity Info\n" + "\n".join(related_info))

        # --- Nguồn 4: Vector search từ Zep (bổ sung, không trùng nguồn 2) ---
        zep_results = self._search_zep_for_entity(entity)

        if zep_results.get("facts"):
            # Lọc bỏ facts đã có trong nguồn 2 để tránh lặp lại
            new_facts = [f for f in zep_results["facts"] if f not in existing_facts]
            if new_facts:
                context_parts.append("### Facts retrieved via ZEP\n" + "\n".join(f"- {f}" for f in new_facts[:15]))

        if zep_results.get("node_summaries"):
            context_parts.append("### Entity nodes retrieved via Zep\n" + "\n".join(f"- {s}" for s in zep_results["node_summaries"][:10]))

        return "\n\n".join(context_parts)

    # --------------------------------------------------------------------------
    # PRIVATE: _is_individual_entity / _is_group_entity — Phân loại entity type
    # [DEPRECATED] Không còn dùng để quyết định prompt — classification đã chuyển
    # sang LLM trong _build_adaptive_persona_prompt(). Giữ lại để không break
    # code ngoài nếu có caller khác.
    # --------------------------------------------------------------------------

    def _is_individual_entity(self, entity_type: str) -> bool:
        """[Deprecated] Dùng _build_adaptive_persona_prompt() thay thế."""
        return entity_type.lower() in self.INDIVIDUAL_ENTITY_TYPES

    def _is_group_entity(self, entity_type: str) -> bool:
        """[Deprecated] Dùng _build_adaptive_persona_prompt() thay thế."""
        return entity_type.lower() in self.GROUP_ENTITY_TYPES

    # --------------------------------------------------------------------------
    # PRIVATE: _generate_profile_with_llm — Gọi LLM sinh profile, có retry và JSON repair
    # --------------------------------------------------------------------------
    # Đây là hàm LLM chính. Có 3 lớp bảo vệ:
    #   Lớp 1: Retry 3 lần nếu API call thất bại
    #   Lớp 2: Sửa JSON bị cắt gãy (finish_reason == 'length')
    #   Lớp 3: Fallback sang rule-based nếu tất cả LLM attempts thất bại
    # --------------------------------------------------------------------------

    def _generate_profile_with_llm(
        self,
        entity_name: str,
        entity_type: str,
        entity_summary: str,
        entity_attributes: Dict[str, Any],
        context: str
    ) -> Dict[str, Any]:
        """
        Gọi LLM để sinh profile dict với bio, persona, age, gender, mbti, ...

        Classification individual/organization do LLM tự quyết định dựa vào toàn bộ
        context (tên, loại, summary, Zep facts) thông qua _build_adaptive_persona_prompt().
        LLM trả về field "entity_category" trong JSON để ghi lại quyết định đó.

        Retry logic:
        - Lần 1: temperature=0.7
        - Lần 2 (nếu lỗi): temperature=0.6 (ít ngẫu nhiên hơn → dễ parse JSON hơn)
        - Lần 3 (nếu lỗi): temperature=0.5

        Nếu hết 3 lần vẫn fail → fallback sang _generate_profile_rule_based()

        Returns:
            Dict với ít nhất: {"bio": ..., "persona": ...}
        """
        prompt = self._build_adaptive_persona_prompt(
            entity_name, entity_type, entity_summary, entity_attributes, context
        )

        max_attempts = 3
        last_error = None

        for attempt in range(max_attempts):
            try:
                response = create_tracked_chat_completion(
                    client=self.client,
                    model=self.model_name,
                    messages=[
                        {"role": "system", "content": self._get_system_prompt()},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={"type": "json_object"},  # Force JSON output mode
                    temperature=0.7 - (attempt * 0.1),  # Giảm dần: 0.7 → 0.6 → 0.5
                    metadata=self._runtime_metadata,
                )

                content = response.choices[0].message.content

                # Kiểm tra tại sao LLM dừng lại
                finish_reason = response.choices[0].finish_reason
                if finish_reason == 'length':
                    # LLM bị cắt ngang vì hết token → JSON có thể bị thiếu dấu đóng
                    logger.warning(f"LLM output truncated (attempt {attempt+1}), attempting to fix...")
                    content = self._fix_truncated_json(content)

                try:
                    result = json.loads(content)

                    # Đảm bảo 2 field quan trọng nhất luôn có giá trị
                    if "bio" not in result or not result["bio"]:
                        result["bio"] = entity_summary[:200] if entity_summary else f"{entity_type}: {entity_name}"
                    if "persona" not in result or not result["persona"]:
                        result["persona"] = entity_summary or f"{entity_name} is a {entity_type}."

                    return result

                except json.JSONDecodeError as je:
                    logger.warning(f"JSON Parsing Failed (attempt {attempt+1}): {str(je)[:80]}")

                    # Thử sửa JSON bằng tool tự chế
                    result = self._try_fix_json(content, entity_name, entity_type, entity_summary)
                    if result.get("_fixed"):
                        del result["_fixed"]
                        return result

                    last_error = je

            except Exception as e:
                logger.warning(f"LLM call Failed (attempt {attempt+1}): {str(e)[:80]}")
                last_error = e
                import time
                time.sleep(1 * (attempt + 1))

        # Đã hết số lần thử → fallback sang rule-based
        logger.warning(f"Generating profile through LLM failed totally after {max_attempts} attempts: {last_error}, switching to basic hard-code rules configs")
        return self._generate_profile_rule_based(
            entity_name, entity_type, entity_summary, entity_attributes
        )

    # --------------------------------------------------------------------------
    # PRIVATE: _fix_truncated_json — Sửa JSON bị cắt gãy do hết token
    # --------------------------------------------------------------------------

    def _fix_truncated_json(self, content: str) -> str:
        """
        Cố gắng vá JSON bị cắt ngang bằng cách đóng các dấu ngoặc còn thiếu.

        Thuật toán:
        1. Đếm số '{' và '}' → tính số ngoặc nhọn còn thiếu
        2. Đếm số '[' và ']' → tính số ngoặc vuông còn thiếu
        3. Nếu ký tự cuối không phải dấu đóng hợp lệ → thêm '"' để đóng string
        4. Thêm ']' và '}' còn thiếu vào cuối

        Ví dụ:
            Input:  '{"bio": "Nguyễn Văn A là...", "persona": "Anh ấy sinh ra'
            Output: '{"bio": "Nguyễn Văn A là...", "persona": "Anh ấy sinh ra"}'
        """
        import re

        content = content.strip()

        open_braces = content.count('{') - content.count('}')
        open_brackets = content.count('[') - content.count(']')

        # Nếu chuỗi bị cắt giữa chừng trong một string value → đóng string lại
        if content and content[-1] not in '",}]':
            content += '"'

        # Đóng array và object còn thiếu
        content += ']' * open_brackets
        content += '}' * open_braces

        return content

    # --------------------------------------------------------------------------
    # PRIVATE: _try_fix_json — Sửa JSON lỗi syntax theo nhiều cấp độ
    # --------------------------------------------------------------------------

    def _try_fix_json(self, content: str, entity_name: str, entity_type: str, entity_summary: str = "") -> Dict[str, Any]:
        """
        Thử sửa JSON hỏng theo 7 bước từ nhẹ đến nặng:

        1. _fix_truncated_json() — đóng ngoặc còn thiếu
        2. Extract block {} lớn nhất bằng regex
        3. Escape newline trong string values
        4. json.loads() — lần 1
        5. Strip control chars (\\x00-\\x1f) → json.loads() — lần 2
        6. Regex rescue: lụm bio và persona riêng lẻ (dù JSON hỏng hoàn toàn)
        7. Trả về dict tối thiểu nếu không cứu được gì

        Returns:
            Dict (có thể rất đơn giản) với "_fixed": True nếu cứu được
        """
        import re

        # Bước 1: Đóng ngoặc
        content = self._fix_truncated_json(content)

        # Bước 2: Tìm block JSON lớn nhất trong chuỗi
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            json_str = json_match.group()

            # Bước 3: Escape newline ẩn trong string values
            def fix_string_newlines(match):
                s = match.group(0)
                s = s.replace('\n', ' ').replace('\r', ' ')
                s = re.sub(r'\s+', ' ', s)
                return s

            json_str = re.sub(r'"[^"\\]*(?:\\.[^"\\]*)*"', fix_string_newlines, json_str)

            # Bước 4: Parse lần 1
            try:
                result = json.loads(json_str)
                result["_fixed"] = True
                return result
            except json.JSONDecodeError as e:
                # Bước 5: Strip control characters ẩn rồi parse lại
                try:
                    json_str = re.sub(r'[\x00-\x1f\x7f-\x9f]', ' ', json_str)
                    json_str = re.sub(r'\s+', ' ', json_str)
                    result = json.loads(json_str)
                    result["_fixed"] = True
                    return result
                except:
                    pass

        # Bước 6: Regex rescue — tìm bio và persona trong đống hỗn độn
        bio_match = re.search(r'"bio"\s*:\s*"([^"]*)"', content)
        persona_match = re.search(r'"persona"\s*:\s*"([^"]*)', content)

        bio = bio_match.group(1) if bio_match else (entity_summary[:200] if entity_summary else f"{entity_type}: {entity_name}")
        persona = persona_match.group(1) if persona_match else (entity_summary or f"{entity_name} is a {entity_type}.")

        if bio_match or persona_match:
            logger.info(f"Successfully extracted partial info from corrupted JSON")
            return {
                "bio": bio,
                "persona": persona,
                "_fixed": True
            }

        # Bước 7: Không cứu được gì → trả về dict tối thiểu (không có _fixed → caller biết dùng fallback)
        logger.warning(f"Failed to fix JSON, returning basic structured data")
        return {
            "bio": entity_summary[:200] if entity_summary else f"{entity_type}: {entity_name}",
            "persona": entity_summary or f"{entity_name} is a {entity_type}."
        }

    # --------------------------------------------------------------------------
    # PRIVATE: _get_system_prompt — System prompt cho LLM
    # --------------------------------------------------------------------------

    def _get_system_prompt(self) -> str:
        """
        Trả về system prompt cho LLM.
        Nhấn mạnh: trả về JSON hợp lệ, không có newline thô trong string values.
        Không phân biệt individual/group — classification do LLM tự xử lý trong prompt.
        """
        return (
            "Bạn là chuyên gia tạo hồ sơ người dùng mạng xã hội. "
            "Hãy tạo các nhân vật chi tiết và chân thực phục vụ cho việc mô phỏng dư luận, "
            "nhằm tái hiện tối đa các tình huống thực tế hiện có. "
            "Phân tích kỹ thông tin thực thể để tự xác định đây là cá nhân hay tổ chức, "
            "rồi sinh hồ sơ phù hợp. "
            "Phải trả về định dạng JSON hợp lệ; "
            "tất cả các giá trị chuỗi không được chứa ký tự xuống dòng chưa được xử lý (unescaped). "
            "Sử dụng tiếng Việt."
        )

    # --------------------------------------------------------------------------
    # PRIVATE: _build_adaptive_persona_prompt — Prompt thống nhất có LLM classification
    # --------------------------------------------------------------------------
    # Thay thế _build_individual_persona_prompt + _build_group_persona_prompt.
    # LLM tự phán đoán individual/organization từ context rồi sinh profile phù hợp.
    # Kết quả JSON chứa field "entity_category" ghi lại quyết định phân loại.
    # --------------------------------------------------------------------------

    def _build_adaptive_persona_prompt(
        self,
        entity_name: str,
        entity_type: str,
        entity_summary: str,
        entity_attributes: Dict[str, Any],
        context: str
    ) -> str:
        """
        Tạo prompt thống nhất — LLM tự phân loại individual/organization rồi sinh profile.

        Luồng trong prompt:
          Bước 1: LLM đọc entity_name, entity_type, summary, attributes, Zep context
          Bước 2: LLM phán đoán "individual" hay "organization"
          Bước 3: LLM sinh JSON 9 fields với giá trị phù hợp theo phân loại đó:
                  - individual → age thực, gender "male"/"female", persona góc nhìn cá nhân
                  - organization → age=30, gender="other", persona góc nhìn tổ chức

        Ưu điểm so với 2 prompt cũ:
        - Không phụ thuộc hardcoded INDIVIDUAL_ENTITY_TYPES / GROUP_ENTITY_TYPES
        - Hoạt động đúng với mọi domain (tài chính, giáo dục, chính trị...)
        - LLM dùng full context (tên + summary + Zep facts) để classify chính xác hơn
        """
        attrs_str = json.dumps(entity_attributes, ensure_ascii=False) if entity_attributes else "Không có"
        context_str = context[:3000] if context else "Không có ngữ cảnh bổ sung"

        return f"""Phân tích thực thể sau và tạo hồ sơ mạng xã hội phù hợp.

Tên thực thể: {entity_name}
Loại thực thể: {entity_type}
Tóm tắt thực thể: {entity_summary}
Thuộc tính thực thể: {attrs_str}

Thông tin ngữ cảnh:
{context_str}

---

BƯỚC 1 — PHÂN LOẠI THỰC THỂ:
Dựa vào toàn bộ thông tin trên, xác định thực thể này thuộc loại nào:
- "individual": một con người cụ thể (ví dụ: nhà đầu tư, sinh viên, nhà báo, chuyên gia, trader...)
- "organization": tổ chức, công ty, quỹ, cơ quan, sàn giao dịch, trường học, nhóm...

BƯỚC 2 — TẠO HỒ SƠ:
Tạo JSON với các trường sau, điều chỉnh theo kết quả phân loại:

1. entity_category: Kết quả phân loại ở Bước 1 — "individual" hoặc "organization"

2. bio: Tiểu sử mạng xã hội ngắn gọn, tối đa 200 ký tự.

3. persona: Mô tả nhân vật/tài khoản chi tiết (~2000 từ, văn bản thuần túy), bao gồm:
   [Nếu individual]:
   - Thông tin cơ bản (tuổi thực, nghề nghiệp, học vấn, nơi ở)
   - Nền tảng nhân vật (trải nghiệm quan trọng, mối liên hệ với sự kiện, quan hệ xã hội)
   - Đặc điểm tính cách (MBTI, tính cách cốt lõi, cách biểu đạt cảm xúc)
   - Hành vi mạng xã hội (tần suất đăng bài, loại nội dung, phong cách tương tác)
   - Lập trường quan điểm (thái độ với chủ đề, điều dễ gây kích động hoặc xúc động)
   - Ký ức cá nhân (mối liên hệ với sự kiện, các hành động và phản ứng đã có)
   [Nếu organization]:
   - Thông tin tổ chức (tên chính thức, tính chất, bối cảnh thành lập, chức năng)
   - Định vị tài khoản (đối tượng mục tiêu, chức năng cốt lõi trên MXH)
   - Phong cách phát ngôn (đặc điểm ngôn ngữ, các chủ đề cấm kỵ)
   - Lập trường chính thức (quan điểm về các chủ đề cốt lõi, cách xử lý tranh cãi)
   - Ký ức tổ chức (mối liên hệ với sự kiện, các hành động và phản ứng đã có)

4. age:
   - Nếu individual: tuổi thực của người đó (số nguyên)
   - Nếu organization: cố định là 30

5. gender:
   - Nếu individual: "male" hoặc "female"
   - Nếu organization: "other"

6. mbti: Loại MBTI (ví dụ: INTJ, ENFP...) mô tả tính cách cá nhân hoặc phong cách tổ chức

7. country: Quốc gia bằng tiếng Việt (ví dụ: "Việt Nam", "Hoa Kỳ")

8. profession: Nghề nghiệp (cá nhân) hoặc chức năng chính (tổ chức)

9. interested_topics: Mảng các chủ đề quan tâm

QUAN TRỌNG:
- Tất cả giá trị phải là chuỗi hoặc số, không dùng ký tự xuống dòng trong string.
- 'persona' phải là một đoạn văn bản mạch lạc, không dùng bullet points hay newline.
- Sử dụng tiếng Việt (ngoại trừ 'gender' dùng tiếng Anh: "male", "female", hoặc "other").
- Nội dung phải nhất quán với thông tin thực thể và ngữ cảnh được cung cấp.
"""

    # --------------------------------------------------------------------------
    # PRIVATE: _build_individual_persona_prompt / _build_group_persona_prompt
    # [DEPRECATED] Thay thế bởi _build_adaptive_persona_prompt().
    # Giữ lại để không break code nếu có nơi nào gọi trực tiếp.
    # --------------------------------------------------------------------------

    def _build_individual_persona_prompt(
        self,
        entity_name: str,
        entity_type: str,
        entity_summary: str,
        entity_attributes: Dict[str, Any],
        context: str
    ) -> str:
        """
        [Deprecated] Dùng _build_adaptive_persona_prompt() thay thế.

        Tạo user prompt cho entity CÁ NHÂN — giữ lại để tương thích ngược.
        Yêu cầu LLM sinh JSON 8 fields:
        bio, persona, age (int), gender ("male"/"female"), mbti, country, profession, interested_topics
        """
        attrs_str = json.dumps(entity_attributes, ensure_ascii=False) if entity_attributes else "Không có"
        context_str = context[:3000] if context else "Không có ngữ cảnh bổ sung"

        return f"""Tạo hồ sơ người dùng mạng xã hội chi tiết cho thực thể, tái hiện tối đa các tình huống thực tế hiện có.

Tên thực thể: {entity_name}
Loại thực thể: {entity_type}
Tóm tắt thực thể: {entity_summary}
Thuộc tính thực thể: {attrs_str}

Thông tin ngữ cảnh:
{context_str}

Vui lòng tạo JSON bao gồm các trường sau:

1. bio: Tiểu sử mạng xã hội, 200 ký tự.
2. persona: Mô tả nhân vật chi tiết (văn bản thuần túy khoảng 2000 từ), cần bao gồm:
   - Thông tin cơ bản (tuổi, nghề nghiệp, trình độ học vấn, nơi ở)
   - Nền tảng nhân vật (trải nghiệm quan trọng, mối liên hệ với sự kiện, quan hệ xã hội)
   - Đặc điểm tính cách (loại MBTI, tính cách cốt lõi, cách biểu đạt cảm xúc)
   - Hành vi mạng xã hội (tần suất đăng bài, sở thích nội dung, phong cách tương tác, đặc điểm ngôn ngữ)
   - Lập trường quan điểm (thái độ đối với chủ đề, nội dung dễ gây kích động hoặc gây xúc động)
   - Đặc điểm độc đáo (câu cửa miệng, trải nghiệm đặc biệt, sở thích cá nhân)
   - Ký ức cá nhân (phần quan trọng của nhân vật, giới thiệu mối liên hệ của cá nhân này với sự kiện, cũng như các hành động và phản ứng đã có của họ trong sự kiện)
3. age: Con số tuổi (phải là số nguyên)
4. gender: Giới tính, phải là tiếng Anh: "male" hoặc "female"
5. mbti: Loại MBTI (như INTJ, ENFP, v.v.)
6. country: Quốc gia (sử dụng tiếng Việt, ví dụ: "Việt Nam")
7. profession: Nghề nghiệp
8. interested_topics: Mảng các chủ đề quan tâm

QUAN TRỌNG:
- Tất cả giá trị các trường phải là chuỗi hoặc số, không sử dụng ký tự xuống dòng.
- 'persona' phải là một đoạn mô tả văn bản mạch lạc.
- Sử dụng tiếng Việt (ngoại trừ trường 'gender' phải dùng tiếng Anh male/female).
- Nội dung phải nhất quán với thông tin thực thể.
- 'age' phải là số nguyên hợp lệ, 'gender' phải là "male" hoặc "female".
"""

    def _build_group_persona_prompt(
        self,
        entity_name: str,
        entity_type: str,
        entity_summary: str,
        entity_attributes: Dict[str, Any],
        context: str
    ) -> str:
        """
        [Deprecated] Dùng _build_adaptive_persona_prompt() thay thế.

        Tạo user prompt cho entity TỔ CHỨC/NHÓM — giữ lại để tương thích ngược.
        Khác biệt so với individual prompt:
        - age: cố định 30 (tuổi ảo cho tài khoản tổ chức)
        - gender: cố định "other"
        - persona nhấn mạnh "ký ức tổ chức" và phong cách phát ngôn chính thức
        """
        attrs_str = json.dumps(entity_attributes, ensure_ascii=False) if entity_attributes else "None"
        context_str = context[:3000] if context else "No additional context"

        return f"""Tạo thiết lập tài khoản mạng xã hội chi tiết cho thực thể tổ chức/nhóm, tái hiện tối đa các tình huống thực tế hiện có.

Tên thực thể: {entity_name}
Loại thực thể: {entity_type}
Tóm tắt thực thể: {entity_summary}
Thuộc tính thực thể: {attrs_str}

Thông tin ngữ cảnh:
{context_str}

Vui lòng tạo JSON bao gồm các trường sau:

1. bio: Tiểu sử tài khoản chính thức, 200 ký tự, chuyên nghiệp và chuẩn mực.
2. persona: Mô tả chi tiết thiết lập tài khoản (văn bản thuần túy khoảng 2000 từ), cần bao gồm:
   - Thông tin cơ bản về tổ chức (tên chính thức, tính chất tổ chức, bối cảnh thành lập, chức năng chính)
   - Định vị tài khoản (loại tài khoản, đối tượng mục tiêu, chức năng cốt lõi)
   - Phong cách phát ngôn (đặc điểm ngôn ngữ, biểu đạt thường dùng, các chủ đề cấm kỵ)
   - Đặc điểm nội dung đăng tải (loại nội dung, tần suất đăng, khung giờ hoạt động)
   - Lập trường thái độ (quan điểm chính thức về các chủ đề cốt lõi, cách xử lý tranh cãi)
   - Ghi chú đặc biệt (hồ sơ của nhóm mà tổ chức đại diện, thói quen vận hành)
   - Ký ức tổ chức (phần quan trọng của hồ sơ, giới thiệu mối liên hệ của tổ chức này với sự kiện, cũng như các hành động và phản ứng đã có của tổ chức trong sự kiện)
3. age: Cố định là 30 (tuổi ảo cho tài khoản tổ chức)
4. gender: Cố định là "other" (biểu thị tài khoản tổ chức, không phải cá nhân)
5. mbti: Loại MBTI dùng để mô tả phong cách tài khoản (ví dụ: ISTJ đại diện cho sự nghiêm túc, bảo thủ)
6. country: Quốc gia (sử dụng tiếng Việt, ví dụ: "Việt Nam")
7. profession: Mô tả chức năng của tổ chức
8. interested_topics: Mảng các lĩnh vực quan tâm

QUAN TRỌNG: 
- Tất cả giá trị các trường phải là chuỗi hoặc số, không cho phép giá trị null.
- 'persona' phải là một đoạn mô tả văn bản mạch lạc, không sử dụng ký tự xuống dòng.
- Sử dụng tiếng Việt (ngoại trừ trường 'gender' phải dùng chuỗi tiếng Anh "other").
- 'age' phải là số nguyên 30, 'gender' phải là chuỗi "other".
- Phát ngôn và giọng điệu của tài khoản phải phù hợp tuyệt đối với định vị danh tính và đặc thù của tổ chức.
"""

    # --------------------------------------------------------------------------
    # PRIVATE: _generate_profile_rule_based — Fallback không dùng LLM
    # --------------------------------------------------------------------------
    # Khi LLM fail hoàn toàn, hàm này trả về profile "cứng" dựa trên entity_type.
    # Chất lượng thấp hơn LLM nhiều nhưng đảm bảo pipeline không bị block.
    # --------------------------------------------------------------------------

    def _generate_profile_rule_based(
        self,
        entity_name: str,
        entity_type: str,
        entity_summary: str,
        entity_attributes: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Sinh profile bằng template cứng theo loại entity — không gọi LLM.

        Ưu điểm: nhanh, không tốn token, không bao giờ fail
        Nhược điểm: generic, thiếu cá tính, không phản ánh context thực của entity

        Các loại được xử lý riêng: student/alumni, publicfigure/expert/faculty,
        mediaoutlet, university/governmentagency/ngo/organization.
        Tất cả loại khác → profile mặc định chung.
        """
        entity_type_lower = entity_type.lower()

        if entity_type_lower in ["student", "alumni"]:
            return {
                "bio": f"{entity_type} with interests in academics and social issues.",
                "persona": f"{entity_name} is a {entity_type.lower()} who is actively engaged in academic and social discussions. They enjoy sharing perspectives and connecting with peers.",
                "age": random.randint(18, 30),
                "gender": random.choice(["male", "female"]),
                "mbti": random.choice(self.MBTI_TYPES),
                "country": random.choice(self.COUNTRIES),
                "profession": "Student",
                "interested_topics": ["Education", "Social Issues", "Technology"],
            }

        elif entity_type_lower in ["publicfigure", "expert", "faculty"]:
            return {
                "bio": f"Expert and thought leader in their field.",
                "persona": f"{entity_name} is a recognized {entity_type.lower()} who shares insights and opinions on important matters. They are known for their expertise and influence in public discourse.",
                "age": random.randint(35, 60),
                "gender": random.choice(["male", "female"]),
                "mbti": random.choice(["ENTJ", "INTJ", "ENTP", "INTP"]),  # Nhóm MBTI thiên về tư duy/lãnh đạo
                "country": random.choice(self.COUNTRIES),
                "profession": entity_attributes.get("occupation", "Expert"),
                "interested_topics": ["Politics", "Economics", "Culture & Society"],
            }

        elif entity_type_lower in ["mediaoutlet", "socialmediaplatform"]:
            return {
                "bio": f"Official account for {entity_name}. News and updates.",
                "persona": f"{entity_name} is a media entity that reports news and facilitates public discourse. The account shares timely updates and engages with the audience on current events.",
                "age": 30,        # Tuổi ảo cố định cho tổ chức
                "gender": "other",  # Không phải cá nhân
                "mbti": "ISTJ",   # Nghiêm túc, thận trọng, bảo thủ — phù hợp media chính thống
                "country": "Việt Nam",
                "profession": "Media",
                "interested_topics": ["General News", "Current Events", "Public Affairs"],
            }

        elif entity_type_lower in ["university", "governmentagency", "ngo", "organization"]:
            return {
                "bio": f"Official account of {entity_name}.",
                "persona": f"{entity_name} is an institutional entity that communicates official positions, announcements, and engages with stakeholders on relevant matters.",
                "age": 30,
                "gender": "other",
                "mbti": "ISTJ",
                "country": "Việt Nam",
                "profession": entity_type,
                "interested_topics": ["Public Policy", "Community", "Official Announcements"],
            }

        else:
            # Fallback hoàn toàn chung — dùng cho mọi loại không match trên
            return {
                "bio": entity_summary[:150] if entity_summary else f"{entity_type}: {entity_name}",
                "persona": entity_summary or f"{entity_name} is a {entity_type.lower()} participating in social discussions.",
                "age": random.randint(25, 50),
                "gender": random.choice(["male", "female"]),
                "mbti": random.choice(self.MBTI_TYPES),
                "country": random.choice(self.COUNTRIES),
                "profession": entity_type,
                "interested_topics": ["General", "Social Issues"],
            }

    def set_graph_id(self, graph_id: str):
        """Cập nhật graph_id sau khi khởi tạo (dùng khi graph_id chưa biết lúc __init__)."""
        self.graph_id = graph_id

    # --------------------------------------------------------------------------
    # PUBLIC: generate_profiles_from_entities — Sinh hàng loạt song song
    # --------------------------------------------------------------------------
    # Đây là hàm được gọi bởi simulation_manager.prepare_simulation() (Giai đoạn 2).
    # Dùng ThreadPoolExecutor để chạy parallel_count threads đồng thời.
    #
    # Tại sao cần parallel?
    # Mỗi profile cần 1-3 LLM API call + 1 Zep search call → ~5-15 giây/profile.
    # Với 50 profiles: sequential = 250-750s, parallel (3 threads) = ~100-250s.
    #
    # Thứ tự profile:
    # ThreadPoolExecutor.as_completed() không đảm bảo thứ tự → dùng mảng profiles[idx]
    # được cấp phát trước để đảm bảo user_id đúng với entity ban đầu.
    #
    # Realtime output:
    # Mỗi khi 1 thread hoàn thành, gọi save_profiles_realtime() để ghi file ngay.
    # Frontend có thể đọc file này để hiển thị tiến độ thực tế.
    # --------------------------------------------------------------------------

    def generate_profiles_from_entities(
        self,
        entities: List[EntityNode],
        use_llm: bool = True,
        progress_callback: Optional[callable] = None,
        graph_id: Optional[str] = None,
        parallel_count: int = 5,
        realtime_output_path: Optional[str] = None,
        output_platform: str = "reddit",
        metadata_platform: Optional[str] = None,
        simulation_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> List[OasisAgentProfile]:
        """
        Sinh hàng loạt profiles từ danh sách entities — chạy song song.

        Đảm bảo:
        - profiles[i] luôn tương ứng với entities[i] (thứ tự không bị xáo trộn)
        - Nếu 1 entity fail → vẫn tạo fallback profile, không block cả batch
        - File được ghi realtime sau mỗi profile hoàn thành

        Args:
            entities: Danh sách EntityNode từ ZepEntityReader
            use_llm: True = gọi LLM; False = rule-based
            progress_callback: callback(current, total, message) để báo tiến độ
            graph_id: Zep graph ID cho vector search
            parallel_count: Số threads chạy đồng thời (mặc định 5)
            realtime_output_path: Đường dẫn file để ghi realtime (None = không ghi)
            output_platform: "reddit" (JSON) hoặc "twitter" (CSV)
            metadata_platform: Tên platform cho log cost API
            simulation_id, project_id: Metadata cho cost tracking

        Returns:
            List[OasisAgentProfile] với len == len(entities), không có None
        """
        import concurrent.futures
        from threading import Lock

        if graph_id:
            self.graph_id = graph_id

        # Cập nhật metadata cho cost tracking
        self._runtime_metadata = {
            "component": "oasis_profile_generator",
            "phase": "generate_profiles",
            "simulation_id": simulation_id,
            "project_id": project_id,
            "platform": metadata_platform,
        }

        total = len(entities)
        profiles = [None] * total   # Pre-allocate để giữ đúng thứ tự index
        completed_count = [0]       # List thay vì int để closure có thể mutate
        lock = Lock()               # Bảo vệ completed_count và file write khỏi race condition

        def save_profiles_realtime():
            """Ghi file ngay lập tức khi có profile mới (thread-safe qua lock)."""
            if not realtime_output_path:
                return

            with lock:
                existing_profiles = [p for p in profiles if p is not None]
                if not existing_profiles:
                    return

                try:
                    if output_platform == "reddit":
                        profiles_data = [p.to_reddit_format() for p in existing_profiles]
                        with open(realtime_output_path, 'w', encoding='utf-8') as f:
                            json.dump(profiles_data, f, ensure_ascii=False, indent=2)
                    else:
                        # Twitter: CSV format
                        import csv
                        profiles_data = [p.to_twitter_format() for p in existing_profiles]
                        if profiles_data:
                            fieldnames = list(profiles_data[0].keys())
                            with open(realtime_output_path, 'w', encoding='utf-8', newline='') as f:
                                writer = csv.DictWriter(f, fieldnames=fieldnames)
                                writer.writeheader()
                                writer.writerows(profiles_data)
                except Exception as e:
                    logger.warning(f"Failed to save profile in realtime: {e}")

        def generate_single_profile(idx: int, entity: EntityNode) -> tuple:
            """
            Worker function chạy trong thread riêng cho mỗi entity.

            Returns:
                (idx, profile, error_message_or_None)
            """
            entity_type = entity.get_entity_type() or "Entity"

            try:
                profile = self.generate_profile_from_entity(
                    entity=entity,
                    user_id=idx,
                    use_llm=use_llm
                )
                self._print_generated_profile(entity.name, entity_type, profile)
                return idx, profile, None

            except Exception as e:
                logger.error(f"Failed to generate profile for entity {entity.name}: {str(e)}")
                # Tạo profile tối thiểu để pipeline không bị block
                fallback_profile = OasisAgentProfile(
                    user_id=idx,
                    user_name=self._generate_username(entity.name),
                    name=entity.name,
                    bio=f"{entity_type}: {entity.name}",
                    persona=entity.summary or f"A participant in social discussions.",
                    source_entity_uuid=entity.uuid,
                    source_entity_type=entity_type,
                )
                return idx, fallback_profile, str(e)

        logger.info(f"Start parallel profile generation for {total} entities (Concurrency: {parallel_count})...")
        print(f"\n{'='*60}")
        print(f"Starting Agent Profile Generation - Total {total} entities, concurrency: {parallel_count}")
        print(f"{'='*60}\n")

        # Chạy ThreadPoolExecutor với parallel_count workers đồng thời
        with concurrent.futures.ThreadPoolExecutor(max_workers=parallel_count) as executor:
            # Submit tất cả tasks cùng lúc
            future_to_entity = {
                executor.submit(generate_single_profile, idx, entity): (idx, entity)
                for idx, entity in enumerate(entities)
            }

            # Thu kết quả theo thứ tự hoàn thành (không phải thứ tự submit)
            for future in concurrent.futures.as_completed(future_to_entity):
                idx, entity = future_to_entity[future]
                entity_type = entity.get_entity_type() or "Entity"

                try:
                    result_idx, profile, error = future.result()
                    profiles[result_idx] = profile  # Đặt vào đúng index, không theo thứ tự hoàn thành

                    with lock:
                        completed_count[0] += 1
                        current = completed_count[0]

                    # Ghi file ngay sau khi có thêm 1 profile
                    save_profiles_realtime()

                    if progress_callback:
                        progress_callback(
                            current,
                            total,
                            f"Completed {current}/{total}: {entity.name} ({entity_type})"
                        )

                    if error:
                        logger.warning(f"[{current}/{total}] Entity {entity.name} applied fallback profile due to error: {error}")
                    else:
                        logger.info(f"[{current}/{total}] Automatically generated profile for: {entity.name} ({entity_type})")

                except Exception as e:
                    logger.error(f"Error handling profile for entity {entity.name}: {str(e)}")
                    with lock:
                        completed_count[0] += 1
                    # Emergency fallback — đảm bảo slot không bị None
                    profiles[idx] = OasisAgentProfile(
                        user_id=idx,
                        user_name=self._generate_username(entity.name),
                        name=entity.name,
                        bio=f"{entity_type}: {entity.name}",
                        persona=entity.summary or "A participant in social discussions.",
                        source_entity_uuid=entity.uuid,
                        source_entity_type=entity_type,
                    )
                    save_profiles_realtime()

        print(f"\n{'='*60}")
        print(f"Profile generation complete! Successfully created {len([p for p in profiles if p])} Agents")
        print(f"{'='*60}\n")

        return profiles

    # --------------------------------------------------------------------------
    # PRIVATE: _print_generated_profile — In log profile ra terminal
    # --------------------------------------------------------------------------

    def _print_generated_profile(self, entity_name: str, entity_type: str, profile: OasisAgentProfile):
        """
        In thông tin profile vừa tạo ra terminal để review.

        Dùng print() thay vì logger để tránh logger truncate persona dài.
        Format rõ ràng với separator và các section riêng biệt.
        """
        separator = "-" * 70
        topics_str = ', '.join(profile.interested_topics) if profile.interested_topics else 'Không có'

        output_lines = [
            f"\n{separator}",
            f"[Generated] {entity_name} ({entity_type})",
            f"{separator}",
            f"Tên tài khoản (Username): {profile.user_name}",
            f"",
            f"【Tiểu sử / Bio】",
            f"{profile.bio}",
            f"",
            f"【Nhân cách cụ thể / Persona】",
            f"{profile.persona}",
            f"",
            f"【Thuộc tính cơ bản / Attributes】",
            f"Tuổi: {profile.age} | Giới tính: {profile.gender} | MBTI: {profile.mbti}",
            f"Nghề nghiệp: {profile.profession} | Quốc gia: {profile.country}",
            f"Chủ đề quan tâm: {topics_str}",
            separator
        ]

        print("\n".join(output_lines))

    # --------------------------------------------------------------------------
    # PUBLIC: save_profiles — Dispatcher ghi file theo nền tảng
    # --------------------------------------------------------------------------

    def save_profiles(
        self,
        profiles: List[OasisAgentProfile],
        file_path: str,
        platform: str = "reddit"
    ):
        """
        Ghi toàn bộ profiles ra file theo định dạng của từng nền tảng.

        Dispatcher: gọi đúng hàm save dựa vào platform:
        - "twitter" → _save_twitter_csv() (OASIS yêu cầu CSV)
        - "reddit" (mặc định) → _save_reddit_json() (OASIS yêu cầu JSON)

        Args:
            profiles: Danh sách profiles cần lưu
            file_path: Đường dẫn file output
            platform: "reddit" hoặc "twitter"
        """
        if platform == "twitter":
            self._save_twitter_csv(profiles, file_path)
        else:
            self._save_reddit_json(profiles, file_path)

    # --------------------------------------------------------------------------
    # PRIVATE: _save_twitter_csv — Lưu profiles theo chuẩn CSV của OASIS Twitter
    # --------------------------------------------------------------------------

    def _save_twitter_csv(self, profiles: List[OasisAgentProfile], file_path: str):
        """
        Ghi profiles ra file CSV theo đúng chuẩn OASIS Twitter framework.

        Cấu trúc CSV (5 cột cố định):
        ┌──────────┬──────────┬──────────┬──────────────────────┬─────────────────┐
        │ user_id  │ name     │ username │ user_char            │ description     │
        ├──────────┼──────────┼──────────┼──────────────────────┼─────────────────┤
        │ 0        │ Tên thật │ alias_xx │ bio + " " + persona  │ bio (public)    │
        └──────────┴──────────┴──────────┴──────────────────────┴─────────────────┘

        Lưu ý quan trọng:
        - user_char = bio + persona → đây là system prompt bí mật của LLM agent
        - description = bio → thông tin hiển thị công khai
        - Tất cả newline trong string phải được strip (CSV không chịu được)
        """
        import csv

        # Tự sửa đuôi file nếu nhầm
        if not file_path.endswith('.csv'):
            file_path = file_path.replace('.json', '.csv')

        with open(file_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            headers = ['user_id', 'name', 'username', 'user_char', 'description']
            writer.writerow(headers)

            for idx, profile in enumerate(profiles):
                # Ghép bio + persona thành user_char (system prompt của agent)
                user_char = profile.bio
                if profile.persona and profile.persona != profile.bio:
                    user_char = f"{profile.bio} {profile.persona}"
                # Strip newline vì CSV không xử lý được multiline trong 1 cell
                user_char = user_char.replace('\n', ' ').replace('\r', ' ')

                description = profile.bio.replace('\n', ' ').replace('\r', ' ')

                row = [
                    idx,
                    profile.name,
                    profile.user_name,
                    user_char,
                    description
                ]
                writer.writerow(row)

        logger.info(f"Saved {len(profiles)} Twitter Profiles to {file_path} (OASIS CSV Format)")

    # --------------------------------------------------------------------------
    # PRIVATE: _normalize_gender — Chuẩn hoá gender về enum OASIS chấp nhận
    # --------------------------------------------------------------------------

    def _normalize_gender(self, gender: Optional[str]) -> str:
        """
        Chuyển đổi mọi dạng gender string về 3 giá trị OASIS chấp nhận: "male", "female", "other".

        Xử lý:
        - Tiếng Việt: "nam" → "male", "nữ" → "female", "tổ chức" → "other"
        - Tiếng Trung: "男" → "male", "女" → "female", "机构" → "other"
        - Không có giá trị → "other" (an toàn nhất)
        - Không match bất kỳ → "other" (fallback)
        """
        if not gender:
            return "other"

        gender_lower = gender.lower().strip()

        gender_map = {
            # Tiếng Việt
            "nam": "male",
            "nữ": "female",
            "tổ chức": "other",
            "khác": "other",
            # Tiếng Anh
            "male": "male",
            "female": "female",
            "other": "other",
        }

        return gender_map.get(gender_lower, "other")

    # --------------------------------------------------------------------------
    # PRIVATE: _save_reddit_json — Lưu profiles theo chuẩn JSON của OASIS Reddit
    # --------------------------------------------------------------------------

    def _save_reddit_json(self, profiles: List[OasisAgentProfile], file_path: str):
        """
        Ghi profiles ra file JSON theo đúng chuẩn OASIS Reddit framework.

        Fields bắt buộc (OASIS sẽ crash nếu thiếu):
        - user_id: int — dùng bởi agent_graph.get_agent() để map agent
        - username: str — tên tài khoản (không có khoảng trắng)
        - name: str — tên hiển thị
        - bio: str — thông tin công khai
        - persona: str — system prompt bí mật của agent
        - karma: int — ảnh hưởng đến visibility của post/comment
        - age, gender, mbti, country: — dùng trong logic agent nếu OASIS cần

        Lưu ý: gender được normalize qua _normalize_gender() trước khi ghi.
        """
        data = []
        for idx, profile in enumerate(profiles):
            item = {
                "user_id": profile.user_id if profile.user_id is not None else idx,
                "username": profile.user_name,
                "name": profile.name,
                "bio": profile.bio[:150] if profile.bio else f"{profile.name}",  # Cap ở 150 ký tự
                "persona": profile.persona or f"{profile.name} is a participant in social discussions.",
                "karma": profile.karma if profile.karma else 1000,
                "created_at": profile.created_at,
                # Fallback values cho các field tùy chọn để tránh null
                "age": profile.age if profile.age else 30,
                "gender": self._normalize_gender(profile.gender),
                "mbti": profile.mbti if profile.mbti else "ISTJ",
                "country": profile.country if profile.country else "Việt Nam",
            }

            if profile.profession:
                item["profession"] = profile.profession
            if profile.interested_topics:
                item["interested_topics"] = profile.interested_topics

            data.append(item)

        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info(f"Saved {len(profiles)} Reddit Profiles to {file_path} (JSON Config File - with user_id mapped)")

    # --------------------------------------------------------------------------
    # DEPRECATED: save_profiles_to_json — Tên cũ, giữ để tương thích ngược
    # --------------------------------------------------------------------------

    def save_profiles_to_json(
        self,
        profiles: List[OasisAgentProfile],
        file_path: str,
        platform: str = "reddit"
    ):
        """[Deprecated] Dùng save_profiles() thay thế. Giữ lại để không break code cũ."""
        logger.warning("save_profiles_to_json is Deprecated. Use save_profiles method instead!")
        self.save_profiles(profiles, file_path, platform)
