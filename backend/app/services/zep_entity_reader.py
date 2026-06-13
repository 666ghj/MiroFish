"""
Dịch vụ đọc và lọc thực thể Zep
Đọc các node từ đồ thị Zep, lọc ra các node phù hợp với các loại thực thể đã được định nghĩa trước

Vị trí trong pipeline (ai gọi file này?):
─────────────────────────────────────────────────────────────────────────────
  simulation_manager.py       → filter_defined_entities()  [caller chính]
      └─ prepare_simulation() gọi ở Giai đoạn 1 để lấy entity làm agent

  oasis_profile_generator.py  → get_entity_with_context()
      └─ khi cần đọc sâu thêm ngữ cảnh của 1 entity cụ thể để sinh persona

  simulation_config_generator.py → nhận FilteredEntities.entities làm input
      └─ không gọi trực tiếp, dùng kết quả đã lọc từ simulation_manager

  api/simulation.py           → qua SimulationManager, không gọi trực tiếp
─────────────────────────────────────────────────────────────────────────────

Luồng dữ liệu từ Zep vào hệ thống:
  Zep Graph (cloud)
      │
      ├── graph.node.get_by_graph_id()  ─→  get_all_nodes()   ─┐
      │       (phân trang qua zep_paging.fetch_all_nodes)       │
      │                                                          ├→ filter_defined_entities()
      └── graph.edge.get_by_graph_id()  ─→  get_all_edges()   ─┘
              (phân trang qua zep_paging.fetch_all_edges)
                        │
                        ▼
                FilteredEntities
                  └─ entities: List[EntityNode]  ← input cho OasisProfileGenerator
"""

import time
from typing import Dict, Any, List, Optional, Set, Callable, TypeVar
from dataclasses import dataclass, field

# Graphiti classes import dưới alias để không đụng dataclass EntityNode định nghĩa bên dưới.
from graphiti_core.nodes import EntityNode as GraphitiEntityNode
from graphiti_core.edges import EntityEdge as GraphitiEntityEdge

from ..config import Config
from ..utils.logger import get_logger
from ..utils.zep_paging import fetch_all_nodes, fetch_all_edges
from ..utils.graphiti_client import get_graphiti, run_async

logger = get_logger('mirofish.zep_entity_reader')

# TypeVar để _call_with_retry có thể trả về đúng kiểu dữ liệu của hàm được truyền vào
T = TypeVar('T')


# ==============================================================================
# DATACLASS: EntityNode — Đơn vị dữ liệu cơ bản của một thực thể
# ==============================================================================
# Mỗi EntityNode tương ứng với 1 node trong Zep Graph, đã được enrich thêm
# thông tin về edges và các node liên kết lân cận.
#
# Sau khi filter_defined_entities() chạy xong, mỗi EntityNode này sẽ được
# OasisProfileGenerator chuyển đổi thành 1 OasisAgentProfile (1 agent trong OASIS).
# ==============================================================================

@dataclass
class EntityNode:
    """Cấu trúc dữ liệu của node thực thể"""

    # --- Định danh từ Zep ---
    uuid: str          # UUID của node trong Zep (dùng để lookup edges)
    name: str          # Tên hiển thị của entity (ví dụ: "Nguyễn Văn A", "Bộ Giáo Dục")

    # --- Phân loại ---
    # Zep gắn label mặc định "Entity" cho mọi node.
    # Node có loại cụ thể sẽ có thêm label như "Person", "Organization", "Event"...
    # Ví dụ: ["Entity", "Person"] hoặc ["Entity", "Organization"]
    labels: List[str]

    # --- Nội dung ---
    # summary: Đoạn mô tả tóm tắt về entity, do Zep tự sinh khi trích xuất từ văn bản
    summary: str
    # attributes: Các thuộc tính bổ sung dạng key-value (tuổi, nghề nghiệp, v.v.)
    attributes: Dict[str, Any]

    # --- Ngữ cảnh mối quan hệ (được enrich khi enrich_with_edges=True) ---
    # related_edges: Danh sách các quan hệ mà entity này tham gia
    #   Mỗi edge có: direction ("incoming"/"outgoing"), edge_name, fact, target/source_node_uuid
    #   Ví dụ: {"direction": "outgoing", "edge_name": "WORKS_AT", "fact": "A làm việc tại B", ...}
    related_edges: List[Dict[str, Any]] = field(default_factory=list)

    # related_nodes: Thông tin cơ bản của các node ở đầu kia của related_edges
    #   Giúp LLM biết entity này liên kết với những ai/gì mà không cần fetch thêm
    related_nodes: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize toàn bộ EntityNode thành dict — dùng để truyền vào LLM prompt."""
        return {
            "uuid": self.uuid,
            "name": self.name,
            "labels": self.labels,
            "summary": self.summary,
            "attributes": self.attributes,
            "related_edges": self.related_edges,
            "related_nodes": self.related_nodes,
        }

    def get_entity_type(self) -> Optional[str]:
        """
        Trả về loại thực thể đầu tiên tìm thấy (loại trừ label mặc định "Entity" và "Node").

        Ví dụ:
            labels = ["Entity", "Person"]  → trả về "Person"
            labels = ["Entity", "Node"]    → trả về None (không có loại cụ thể)
            labels = ["Entity"]            → trả về None

        Dùng để nhóm agent theo loại khi sinh prompt.
        """
        for label in self.labels:
            if label not in ["Entity", "Node"]:
                return label
        return None


# ==============================================================================
# DATACLASS: FilteredEntities — Kết quả đầu ra của bước đọc và lọc
# ==============================================================================
# Đây là "gói hàng" được trả về cho simulation_manager.py sau khi đọc Zep.
# simulation_manager lưu entities_count và entity_types vào SimulationState,
# rồi truyền entities vào OasisProfileGenerator và SimulationConfigGenerator.
# ==============================================================================

@dataclass
class FilteredEntities:
    """Tập hợp các thực thể sau khi lọc"""

    entities: List[EntityNode]   # Danh sách entity đã lọc và enrich — input cho profile/config generator
    entity_types: Set[str]       # Tập hợp các loại entity có mặt (ví dụ: {"Person", "Organization"})
    total_count: int             # Tổng số node đọc được từ Zep (trước khi lọc)
    filtered_count: int          # Số node còn lại sau khi lọc (bằng len(entities))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entities": [e.to_dict() for e in self.entities],
            "entity_types": list(self.entity_types),
            "total_count": self.total_count,
            "filtered_count": self.filtered_count,
        }


# ==============================================================================
# CLASS: ZepEntityReader — Cầu nối giữa Zep Cloud API và pipeline MiroFish
# ==============================================================================
# Khởi tạo 1 instance mỗi lần gọi prepare_simulation() (stateless, không có cache).
# Toàn bộ kết nối Zep đi qua đây — không service nào khác gọi trực tiếp Zep client
# để đọc nodes/edges.
# ==============================================================================

class ZepEntityReader:
    """
    Dịch vụ đọc và lọc thực thể Zep

    Chức năng chính:
    1. Đọc toàn bộ các node từ đồ thị Zep (có phân trang, tối đa 2000 nodes)
    2. Lọc ra các node phù hợp với các loại thực thể đã được định nghĩa
       (Các node có Labels không chỉ là "Entity"/"Node")
    3. Enrich mỗi entity với edges và related_nodes lân cận
    """

    def __init__(self, api_key: Optional[str] = None):
        # api_key giữ lại trong chữ ký để tương thích caller cũ, nhưng không còn dùng:
        # Graphiti lấy cấu hình Neo4j + LLM qua get_graphiti() (lazy, per-thread).
        self.api_key = api_key

    # --------------------------------------------------------------------------
    # PRIVATE: _call_with_retry — Retry wrapper cho các API call Zep đơn lẻ
    # --------------------------------------------------------------------------
    # Lưu ý: hàm này CHỈ được dùng bởi get_node_edges() và get_entity_with_context().
    # filter_defined_entities() KHÔNG dùng hàm này — nó dùng fetch_all_nodes/edges
    # từ zep_paging.py, vốn đã có retry riêng ở cấp trang.
    # --------------------------------------------------------------------------

    def _call_with_retry(
        self,
        func: Callable[[], T],
        operation_name: str,
        max_retries: int = 3,
        initial_delay: float = 2.0
    ) -> T:
        """
        Gọi một hàm Zep API với cơ chế thử lại (exponential backoff).

        Chiến lược retry:
            Lần 1: chạy ngay
            Lần 2 (nếu lần 1 lỗi): chờ 2 giây
            Lần 3 (nếu lần 2 lỗi): chờ 4 giây
            Sau 3 lần đều lỗi → raise exception cuối cùng

        Args:
            func: Lambda/callable không tham số bọc lệnh gọi API
            operation_name: Tên thao tác để ghi vào log (ví dụ: "Fetch node edges")
            max_retries: Số lần thử tối đa (mặc định 3)
            initial_delay: Delay ban đầu tính bằng giây (tự nhân đôi mỗi lần)

        Returns:
            Kết quả trả về từ func() nếu thành công

        Raises:
            Exception: Exception cuối cùng sau khi hết số lần thử
        """
        last_exception = None
        delay = initial_delay

        for attempt in range(max_retries):
            try:
                return func()
            except Exception as e:
                last_exception = e
                if attempt < max_retries - 1:
                    logger.warning(
                        f"Zep {operation_name} attempt {attempt + 1} failed: {str(e)[:100]}, "
                        f"retrying in {delay:.1f} seconds..."
                    )
                    time.sleep(delay)
                    delay *= 2  # Exponential backoff: 2s → 4s → 8s
                else:
                    logger.error(f"Zep {operation_name} failed after {max_retries} attempts: {str(e)}")

        raise last_exception

    # --------------------------------------------------------------------------
    # PUBLIC: get_all_nodes / get_all_edges — Bulk fetch toàn bộ nodes và edges
    # --------------------------------------------------------------------------
    # Hai hàm này là wrapper mỏng quanh fetch_all_nodes/fetch_all_edges từ
    # zep_paging.py. Logic phân trang và retry theo trang nằm hoàn toàn trong
    # zep_paging.py (UUID cursor-based pagination, tối đa 2000 nodes).
    #
    # Tại sao dùng bulk fetch thay vì fetch từng node?
    # → Hiệu quả hơn nhiều: 2 API calls cho toàn bộ graph thay vì N calls
    # → filter_defined_entities() dùng chiến lược này
    # --------------------------------------------------------------------------

    def get_all_nodes(self, graph_id: str) -> List[Dict[str, Any]]:
        """
        Lấy toàn bộ các node của đồ thị bằng cách phân trang.

        Uỷ thác cho fetch_all_nodes() (zep_paging.py) để xử lý:
        - Cursor-based pagination (100 nodes/trang)
        - Retry từng trang khi lỗi mạng
        - Giới hạn tổng 2000 nodes

        Args:
            graph_id: ID của Zep Graph

        Returns:
            Danh sách dict, mỗi dict là 1 node với: uuid, name, labels, summary, attributes
        """
        logger.info(f"Fetching all nodes for graph {graph_id}...")

        nodes = fetch_all_nodes(get_graphiti().driver, graph_id)

        # Chuẩn hoá từ graphiti EntityNode sang Python dict thuần
        nodes_data = []
        for node in nodes:
            nodes_data.append({
                "uuid": getattr(node, 'uuid', ''),
                "name": node.name or "",
                "labels": node.labels or [],
                "summary": node.summary or "",
                "attributes": node.attributes or {},
            })

        logger.info(f"Total {len(nodes_data)} nodes fetched")
        return nodes_data

    def get_all_edges(self, graph_id: str) -> List[Dict[str, Any]]:
        """
        Lấy toàn bộ các edge của đồ thị bằng cách phân trang.

        Tương tự get_all_nodes() — uỷ thác cho fetch_all_edges() (zep_paging.py).
        Không có giới hạn tổng số edge (khác với nodes giới hạn 2000).

        Args:
            graph_id: ID của Zep Graph

        Returns:
            Danh sách dict, mỗi dict là 1 edge với:
            uuid, name, fact, source_node_uuid, target_node_uuid, attributes
        """
        logger.info(f"Fetching all edges for graph {graph_id}...")

        edges = fetch_all_edges(get_graphiti().driver, graph_id)

        edges_data = []
        for edge in edges:
            edges_data.append({
                "uuid": getattr(edge, 'uuid', ''),
                "name": edge.name or "",
                "fact": edge.fact or "",           # Mô tả quan hệ dạng câu (ví dụ: "A làm việc tại B")
                "source_node_uuid": edge.source_node_uuid,  # UUID node nguồn
                "target_node_uuid": edge.target_node_uuid,  # UUID node đích
                "attributes": edge.attributes or {},
            })

        logger.info(f"Total {len(edges_data)} edges fetched")
        return edges_data

    # --------------------------------------------------------------------------
    # PUBLIC: get_node_edges — Fetch edges của 1 node cụ thể (per-node API call)
    # --------------------------------------------------------------------------
    # ĐÂY KHÔNG PHẢI hàm được dùng trong filter_defined_entities().
    # filter_defined_entities() lấy ALL edges rồi tự scan — không gọi hàm này.
    #
    # Hàm này chỉ được dùng bởi get_entity_with_context() khi cần fetch
    # edges cho 1 entity đơn lẻ theo UUID cụ thể.
    # --------------------------------------------------------------------------

    def get_node_edges(self, node_uuid: str) -> List[Dict[str, Any]]:
        """
        Lấy tất cả edges liên quan của 1 node cụ thể qua UUID.

        Dùng Zep API: client.graph.node.get_entity_edges(node_uuid=...)
        Có retry qua _call_with_retry() (không qua zep_paging vì không phân trang).

        Args:
            node_uuid: UUID của node cần lấy edges

        Returns:
            Danh sách edge dict (cùng format với get_all_edges()).
            Trả về [] nếu lỗi (không raise exception — caller tự xử lý thiếu data).
        """
        try:
            driver = get_graphiti().driver
            edges = self._call_with_retry(
                func=lambda: run_async(GraphitiEntityEdge.get_by_node_uuid(driver, node_uuid)),
                operation_name=f"Fetch node edges(node={node_uuid[:8]}...)"
            )

            edges_data = []
            for edge in edges:
                edges_data.append({
                    "uuid": getattr(edge, 'uuid', ''),
                    "name": edge.name or "",
                    "fact": edge.fact or "",
                    "source_node_uuid": edge.source_node_uuid,
                    "target_node_uuid": edge.target_node_uuid,
                    "attributes": edge.attributes or {},
                })

            return edges_data
        except Exception as e:
            # Lỗi khi fetch edge của 1 node không nên làm hỏng cả pipeline
            # → log warning và trả về rỗng, caller (get_entity_with_context) tiếp tục
            logger.warning(f"Failed to fetch edges for node {node_uuid}: {str(e)}")
            return []

    # --------------------------------------------------------------------------
    # PUBLIC: filter_defined_entities — Hàm CHÍNH của class
    # --------------------------------------------------------------------------
    # Đây là hàm được gọi bởi simulation_manager.prepare_simulation() ở Giai đoạn 1.
    # Toàn bộ pipeline phụ thuộc vào output của hàm này.
    #
    # Thuật toán:
    #   1. Bulk fetch TẤT CẢ nodes (2 API calls qua phân trang)
    #   2. Bulk fetch TẤT CẢ edges (nếu enrich_with_edges=True)
    #   3. Duyệt từng node, áp dụng logic lọc label
    #   4. Với mỗi node hợp lệ: scan toàn bộ all_edges để tìm edges liên quan
    #   5. Trả về FilteredEntities
    #
    # Độ phức tạp: O(N * M) với N = số node lọc được, M = tổng số edge
    # Trong thực tế graph nhỏ (< 100 nodes, < 500 edges) nên không ảnh hưởng
    # --------------------------------------------------------------------------

    def filter_defined_entities(
        self,
        graph_id: str,
        defined_entity_types: Optional[List[str]] = None,
        enrich_with_edges: bool = True
    ) -> FilteredEntities:
        """
        Đọc toàn bộ graph từ Zep rồi lọc ra các entity có loại được định nghĩa.

        Logic lọc label (quan trọng — đây là cách phân biệt entity "có ý nghĩa"):
        ┌──────────────────────────────────────────────────────┐
        │ Node trong Zep có 2 loại label:                      │
        │                                                      │
        │ "Generic" node: labels = ["Entity"] hoặc ["Node"]    │
        │   → Zep tạo ra khi trích xuất context chung,         │
        │     không phải thực thể cụ thể nào → BỎ QUA          │
        │                                                      │
        │ "Typed" node:   labels = ["Entity", "Person"]        │
        │                 labels = ["Entity", "Organization"]  │
        │   → Thực thể được định danh rõ ràng → GIỮ LẠI        │
        └──────────────────────────────────────────────────────┘

        Hai chế độ lọc:
        - defined_entity_types=None: giữ TẤT CẢ typed nodes (mọi custom label đều OK)
        - defined_entity_types=["Person", "Organization"]: chỉ giữ nodes có label trong danh sách

        Enrich với edges:
        - Sau khi lọc, với mỗi entity, scan all_edges để tìm edges có
          source_node_uuid hoặc target_node_uuid trùng với entity.uuid
        - Phân loại: source = outgoing, target = incoming
        - Lấy thêm thông tin cơ bản của node ở đầu kia (tên, labels, summary)

        Ví dụ minh hoạ:
        ─────────────────────────────────────────────────────────────────────
        Giả sử Zep Graph có 4 nodes và 2 edges sau:

        NODES:
          uuid="aaa", name="Nguyễn Văn A", labels=["Entity", "Person"]
          uuid="bbb", name="Bộ Giáo Dục",  labels=["Entity", "Organization"]
          uuid="ccc", name="context-001",   labels=["Entity"]              ← generic, bị loại
          uuid="ddd", name="Hà Nội",        labels=["Entity", "Location"]

        EDGES:
          source="aaa" → target="bbb", fact="Nguyễn Văn A làm việc tại Bộ Giáo Dục"
          source="ddd" → target="aaa", fact="Nguyễn Văn A sinh sống tại Hà Nội"

        ── Gọi với defined_entity_types=None ──────────────────────────────
        filter_defined_entities(graph_id, defined_entity_types=None)

        → Giữ lại: "aaa" (Person), "bbb" (Organization), "ddd" (Location)
        → Loại bỏ: "ccc" (chỉ có label "Entity")
        → entity_types = {"Person", "Organization", "Location"}
        → filtered_count = 3, total_count = 4

        EntityNode uuid="aaa" (Nguyễn Văn A) sau enrich:
          related_edges = [
            {"direction": "outgoing", "edge_name": "...", "fact": "A làm việc tại Bộ GD", "target_node_uuid": "bbb"},
            {"direction": "incoming", "edge_name": "...", "fact": "A sinh sống tại Hà Nội", "source_node_uuid": "ddd"},
          ]
          related_nodes = [
            {"uuid": "bbb", "name": "Bộ Giáo Dục", "labels": ["Entity", "Organization"], "summary": "..."},
            {"uuid": "ddd", "name": "Hà Nội",       "labels": ["Entity", "Location"],     "summary": "..."},
          ]

        ── Gọi với defined_entity_types=["Person"] ─────────────────────────
        filter_defined_entities(graph_id, defined_entity_types=["Person"])

        → Giữ lại: chỉ "aaa" (Person)
        → Loại bỏ: "bbb" (Organization không match), "ccc" (generic), "ddd" (Location không match)
        → filtered_count = 1
        ─────────────────────────────────────────────────────────────────────

        Args:
            graph_id: ID của Zep Graph
            defined_entity_types: Danh sách loại cần lọc (None = lấy tất cả)
            enrich_with_edges: True = thêm related_edges + related_nodes vào mỗi entity

        Returns:
            FilteredEntities chứa danh sách EntityNode đã enrich
        """
        logger.info(f"Start filtering entities for graph {graph_id}...")

        # --- Bước 1: Bulk fetch nodes và edges ---
        all_nodes = self.get_all_nodes(graph_id)
        total_count = len(all_nodes)

        # Chỉ fetch edges nếu cần enrich (tiết kiệm 1 API call nếu không cần)
        all_edges = self.get_all_edges(graph_id) if enrich_with_edges else []

        # Xây dựng dict ánh xạ uuid → node data để tra cứu O(1) khi enrich related_nodes
        node_map = {n["uuid"]: n for n in all_nodes}

        # --- Bước 2: Lọc nodes theo label ---
        filtered_entities = []
        entity_types_found = set()

        for node in all_nodes:
            labels = node.get("labels", [])

            # Tìm custom labels (loại trừ "Entity" và "Node" là labels mặc định của Zep)
            custom_labels = [l for l in labels if l not in ["Entity", "Node"]]

            if not custom_labels:
                # Node này chỉ có labels mặc định → không phải entity cụ thể → bỏ qua
                continue

            # Nếu người dùng chỉ định danh sách loại, kiểm tra xem node có match không
            if defined_entity_types:
                matching_labels = [l for l in custom_labels if l in defined_entity_types]
                if not matching_labels:
                    continue  # Node này có custom label nhưng không nằm trong danh sách cho phép
                entity_type = matching_labels[0]  # Lấy loại match đầu tiên
            else:
                entity_type = custom_labels[0]  # Lấy custom label đầu tiên làm loại

            entity_types_found.add(entity_type)

            # Tạo EntityNode (related_edges và related_nodes vẫn rỗng, enrich ở bước sau)
            entity = EntityNode(
                uuid=node["uuid"],
                name=node["name"],
                labels=labels,
                summary=node["summary"],
                attributes=node["attributes"],
            )

            # --- Bước 3: Enrich với edges và related nodes ---
            if enrich_with_edges:
                related_edges = []
                related_node_uuids = set()

                # Scan toàn bộ all_edges để tìm edges có liên quan đến node này
                # (không gọi get_node_edges() vì đã có all_edges trong memory)
                for edge in all_edges:
                    if edge["source_node_uuid"] == node["uuid"]:
                        # Entity này là nguồn → quan hệ "outgoing" (chiều đi ra)
                        related_edges.append({
                            "direction": "outgoing",
                            "edge_name": edge["name"],
                            "fact": edge["fact"],
                            "target_node_uuid": edge["target_node_uuid"],
                        })
                        related_node_uuids.add(edge["target_node_uuid"])

                    elif edge["target_node_uuid"] == node["uuid"]:
                        # Entity này là đích → quan hệ "incoming" (chiều đi vào)
                        related_edges.append({
                            "direction": "incoming",
                            "edge_name": edge["name"],
                            "fact": edge["fact"],
                            "source_node_uuid": edge["source_node_uuid"],
                        })
                        related_node_uuids.add(edge["source_node_uuid"])

                entity.related_edges = related_edges

                # Lấy thông tin cơ bản của các node lân cận (không lấy full để tránh vòng lặp)
                related_nodes = []
                for related_uuid in related_node_uuids:
                    if related_uuid in node_map:
                        related_node = node_map[related_uuid]
                        related_nodes.append({
                            "uuid": related_node["uuid"],
                            "name": related_node["name"],
                            "labels": related_node["labels"],
                            "summary": related_node.get("summary", ""),
                            # Không lấy attributes để tránh payload quá lớn khi truyền vào LLM
                        })

                entity.related_nodes = related_nodes

            filtered_entities.append(entity)

        logger.info(f"Filtering completed: Total nodes {total_count}, Matched {len(filtered_entities)}, "
                   f"Entity types: {entity_types_found}")

        return FilteredEntities(
            entities=filtered_entities,
            entity_types=entity_types_found,
            total_count=total_count,
            filtered_count=len(filtered_entities),
        )

    # --------------------------------------------------------------------------
    # PUBLIC: get_entity_with_context — Fetch 1 entity đơn lẻ theo UUID
    # --------------------------------------------------------------------------
    # Dùng bởi oasis_profile_generator.py khi cần đọc sâu thêm 1 entity cụ thể.
    # Khác với filter_defined_entities():
    #   - Fetch 1 node theo UUID (không scan toàn bộ graph)
    #   - Dùng get_node_edges() per-node (per-node API call)
    #   - Nhưng vẫn cần fetch all_nodes để build related_nodes → tốn hơn
    # --------------------------------------------------------------------------

    def get_entity_with_context(
        self,
        graph_id: str,
        entity_uuid: str
    ) -> Optional[EntityNode]:
        """
        Lấy thông tin đầy đủ của 1 entity cụ thể và toàn bộ ngữ cảnh liên kết.

        Dùng per-node API call (khác với filter_defined_entities dùng bulk fetch).
        Phù hợp khi chỉ cần 1 entity — không hiệu quả nếu cần nhiều entities.

        Args:
            graph_id: ID của Zep Graph (dùng để lấy node_map cho related_nodes)
            entity_uuid: UUID của entity cần lấy

        Returns:
            EntityNode đầy đủ hoặc None nếu không tìm thấy / lỗi
        """
        try:
            # Fetch node theo UUID với retry.
            # GraphitiEntityNode.get_by_uuid raise NodeNotFoundError nếu không có →
            # được bắt bởi except phía dưới (log + trả None).
            driver = get_graphiti().driver
            node = self._call_with_retry(
                func=lambda: run_async(GraphitiEntityNode.get_by_uuid(driver, entity_uuid)),
                operation_name=f"Fetch node detail(uuid={entity_uuid[:8]}...)"
            )

            if not node:
                return None

            # Fetch edges của node này (per-node call, có retry)
            edges = self.get_node_edges(entity_uuid)

            # Cần all_nodes để build related_nodes map — đây là điểm tốn kém nhất
            all_nodes = self.get_all_nodes(graph_id)
            node_map = {n["uuid"]: n for n in all_nodes}

            # Xử lý edges (cùng logic với filter_defined_entities)
            related_edges = []
            related_node_uuids = set()

            for edge in edges:
                if edge["source_node_uuid"] == entity_uuid:
                    related_edges.append({
                        "direction": "outgoing",
                        "edge_name": edge["name"],
                        "fact": edge["fact"],
                        "target_node_uuid": edge["target_node_uuid"],
                    })
                    related_node_uuids.add(edge["target_node_uuid"])
                else:
                    related_edges.append({
                        "direction": "incoming",
                        "edge_name": edge["name"],
                        "fact": edge["fact"],
                        "source_node_uuid": edge["source_node_uuid"],
                    })
                    related_node_uuids.add(edge["source_node_uuid"])

            related_nodes = []
            for related_uuid in related_node_uuids:
                if related_uuid in node_map:
                    related_node = node_map[related_uuid]
                    related_nodes.append({
                        "uuid": related_node["uuid"],
                        "name": related_node["name"],
                        "labels": related_node["labels"],
                        "summary": related_node.get("summary", ""),
                    })

            return EntityNode(
                uuid=getattr(node, 'uuid', ''),
                name=node.name or "",
                labels=node.labels or [],
                summary=node.summary or "",
                attributes=node.attributes or {},
                related_edges=related_edges,
                related_nodes=related_nodes,
            )

        except Exception as e:
            logger.error(f"Failed to fetch entity {entity_uuid}: {str(e)}")
            return None

    # --------------------------------------------------------------------------
    # PUBLIC: get_entities_by_type — Convenience wrapper cho 1 loại entity cụ thể
    # --------------------------------------------------------------------------

    def get_entities_by_type(
        self,
        graph_id: str,
        entity_type: str,
        enrich_with_edges: bool = True
    ) -> List[EntityNode]:
        """
        Lấy tất cả entities của một loại cụ thể.

        Là thin wrapper quanh filter_defined_entities() với defined_entity_types=[entity_type].
        Tiện dụng khi chỉ cần 1 loại thay vì nhiều loại.

        Args:
            graph_id: ID của Zep Graph
            entity_type: Loại entity cần lọc (ví dụ: "Person", "Organization")
            enrich_with_edges: Có enrich với edges không

        Returns:
            Danh sách EntityNode thuộc loại đã chỉ định
        """
        result = self.filter_defined_entities(
            graph_id=graph_id,
            defined_entity_types=[entity_type],
            enrich_with_edges=enrich_with_edges
        )
        return result.entities
