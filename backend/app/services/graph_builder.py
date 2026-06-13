"""
Dịch vụ xây dựng Đồ thị Tri thức (Knowledge Graph)
API 2: Dùng graphiti_core (Neo4j backend) để xây dựng một Standalone Graph (Đồ thị độc lập)
"""

import os
import time
import uuid
import threading
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Callable, Type
from dataclasses import dataclass

from pydantic import BaseModel, Field

from graphiti_core.nodes import EntityNode, EpisodeType

from ..config import Config
from ..models.task import TaskManager, TaskStatus
from ..utils.zep_paging import fetch_all_nodes, fetch_all_edges
from ..utils.graphiti_client import get_graphiti, run_async
from .text_processor import TextProcessor


@dataclass
class GraphInfo:
    """Các trường thông tin cơ bản của Graph"""
    graph_id: str
    node_count: int
    edge_count: int
    entity_types: List[str]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "entity_types": self.entity_types,
        }


class GraphBuilderService:
    """
    Dịch vụ tạo lập Graph
    Đảm nhiệm logic dùng graphiti_core (Neo4j) để thiết lập Graph
    """

    def __init__(self, api_key: Optional[str] = None):
        # api_key giữ lại trong chữ ký để tương thích caller cũ, nhưng không còn dùng
        # (Graphiti dùng Neo4j + LLM config, lấy lazy qua get_graphiti()).
        self.api_key = api_key
        self.task_manager = TaskManager()

        # Ontology được build sẵn (Pydantic thuần) và truyền vào mỗi add_episode,
        # vì Graphiti không có set_ontology server-side như Zep.
        self._entity_types: Dict[str, Type[BaseModel]] = {}
        self._edge_types: Dict[str, Type[BaseModel]] = {}
        self._edge_type_map: Dict[tuple, List[str]] = {}
    
    def build_graph_async(
        self,
        text: str,
        ontology: Dict[str, Any],
        graph_name: str = "MiroFish Graph",
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        batch_size: int = 3
    ) -> str:
        """
        Khởi chạy tiến trình bất đồng bộ xây dựng Graph
        
        Args:
            text: Văn bản toàn văn làm nguồn vào
            ontology: Từ điển chuẩn cấu trúc Ontology (Đầu ra từ API số 1)
            graph_name: Tên đặt cho Graph
            chunk_size: Kích thước từng khối text (chunk)
            chunk_overlap: Giới hạn những từ đè lên nhau giữa các chunk (bảo toàn flow hội thoại / ngữ cảnh)
            batch_size: Chuyển dữ liệu theo mảng batch để tiết kiệm số lần Request
            
        Returns:
            Trạng thái Task ID vừa khởi tạo
        """
        # Đưa Task vào danh sách quản lý
        task_id = self.task_manager.create_task(
            task_type="graph_build",
            metadata={
                "graph_name": graph_name,
                "chunk_size": chunk_size,
                "text_length": len(text),
            }
        )
        
        # Bắt đầu gọi Workder ở luồng ảo (Back ground Thread) để người dùng không tắc giao diện đợi xử lý
        # Asynchronous Execution: Graph building runs in background threads with progress tracking through a task management system
        thread = threading.Thread(
            target=self._build_graph_worker,
            args=(task_id, text, ontology, graph_name, chunk_size, chunk_overlap, batch_size)
        )
        thread.daemon = True
        thread.start()
        
        return task_id
    
    def _build_graph_worker(
        self,
        task_id: str,
        text: str,
        ontology: Dict[str, Any],
        graph_name: str,
        chunk_size: int,
        chunk_overlap: int,
        batch_size: int
    ):
        """Tiến trình cài đặt ngầm tạo Graph với các bước tuần tự"""
        try:
            self.task_manager.update_task(
                task_id,
                status=TaskStatus.PROCESSING,
                progress=5,
                message="Building Knowledge Graph..."
            )
            
            # Bước 1. Init tạo khung xương Graph trên Zep
            graph_id = self.create_graph(graph_name)
            self.task_manager.update_task(
                task_id,
                progress=10,
                message=f"Created empty graph: {graph_id}"
            )
            
            # 2. Thiết lập ontology
            self.set_ontology(graph_id, ontology)
            self.task_manager.update_task(
                task_id,
                progress=15,
                message="Ontology scheme applied successfully"
            )
            
            # Bước 3. Chia nhỏ văn bản gốc
            # Text Processing: Chunks documents and sends them to Zep for entity extraction
            chunks = TextProcessor.split_text(text, chunk_size, chunk_overlap) # Split into chunks
            total_chunks = len(chunks)
            self.task_manager.update_task(
                task_id,
                progress=20,
                message=f"Split text into {total_chunks} chunk(s)"
            )
            
            # Bước 4. Gửi các đợt chunk tới Zep dưới dạng batch
            # Send in batches (size=3)
            episode_uuids = self.add_text_batches(
                graph_id, chunks, batch_size,
                lambda msg, prog: self.task_manager.update_task(
                    task_id,
                    progress=20 + int(prog * 0.4),  # Thể hiện từ 20-60%
                    message=msg
                )
            )
            
            # Bước 5. Đợi hàm Backend của Cloud Zep xử lý đồng bộ xong các episode
            self.task_manager.update_task(
                task_id,
                progress=60,
                message="Waiting for Zep to process data..."
            )
            
            # Wait for Zep processing
            self._wait_for_episodes(
                episode_uuids,
                lambda msg, prog: self.task_manager.update_task(
                    task_id,
                    progress=60 + int(prog * 0.3),  # Thể hiện từ 60-90%
                    message=msg
                )
            )
            
            # Bước 6. Thống kê lại Graph hoàn thiện
            self.task_manager.update_task(
                task_id,
                progress=90,
                message="Fetching finalized graph info..."
            )
            
            # Retrieve graph statistics
            graph_info = self._get_graph_info(graph_id)
            
            # Thông báo hoàn tất
            self.task_manager.complete_task(task_id, {
                "graph_id": graph_id,
                "graph_info": graph_info.to_dict(),
                "chunks_processed": total_chunks,
            })
            
        except Exception as e:
            import traceback
            error_msg = f"{str(e)}\n{traceback.format_exc()}"
            self.task_manager.fail_task(task_id, error_msg)
    
    def create_graph(self, name: str) -> str:
        """Sinh graph_id mới (dùng làm group_id của Graphiti).

        Graphiti không cần đăng ký partition trước — group_id là string tự do,
        sẽ được tạo ngầm khi add_episode đầu tiên ghi vào. Vì vậy method này
        chỉ sinh & trả về id, không gọi API nào.
        """
        graph_id = f"mirofish_{uuid.uuid4().hex[:16]}"
        return graph_id
    
    def set_ontology(self, graph_id: str, ontology: Dict[str, Any]):
        """
        Build schema Ontology (entity/edge types) dưới dạng Pydantic model thuần.

        Graphiti không có API set_ontology server-side như Zep. Thay vào đó,
        entity_types/edge_types/edge_type_map được truyền vào MỖI lần add_episode.
        Method này build sẵn và lưu trên self để add_text_batches dùng lại.
        """
        from typing import Optional

        # Các tên field trùng với EntityNode.model_fields của graphiti — không được dùng
        # làm attribute (graphiti raise EntityTypeValidationError nếu trùng).
        RESERVED_NAMES = {
            'uuid', 'name', 'group_id', 'labels',
            'name_embedding', 'summary', 'attributes', 'created_at',
        }

        def safe_attr_name(attr_name: str) -> str:
            """Đổi tên attribute nếu trùng field bảo lưu của graphiti."""
            if attr_name.lower() in RESERVED_NAMES:
                return f"entity_{attr_name}"
            return attr_name

        # --- Entity types (Pydantic thuần, key = tên PascalCase từ ontology) ---
        entity_types: Dict[str, Type[BaseModel]] = {}
        for entity_def in ontology.get("entity_types", []):
            name = entity_def["name"]
            description = entity_def.get("description", f"A {name} entity.")

            attrs: Dict[str, Any] = {"__doc__": description}
            annotations: Dict[str, Any] = {}

            for attr_def in entity_def.get("attributes", []):
                attr_name = safe_attr_name(attr_def["name"])
                attr_desc = attr_def.get("description", attr_name)
                attrs[attr_name] = Field(default=None, description=attr_desc)
                annotations[attr_name] = Optional[str]

            attrs["__annotations__"] = annotations
            entity_class = type(name, (BaseModel,), attrs)
            entity_class.__doc__ = description
            entity_types[name] = entity_class

        # --- Edge types (key = tên UPPER_SNAKE_CASE) + edge_type_map ---
        edge_types: Dict[str, Type[BaseModel]] = {}
        edge_type_map: Dict[tuple, List[str]] = {}

        for edge_def in ontology.get("edge_types", []):
            name = edge_def["name"]
            description = edge_def.get("description", f"A {name} relationship.")

            attrs = {"__doc__": description}
            annotations = {}
            for attr_def in edge_def.get("attributes", []):
                attr_name = safe_attr_name(attr_def["name"])
                attr_desc = attr_def.get("description", attr_name)
                attrs[attr_name] = Field(default=None, description=attr_desc)
                annotations[attr_name] = Optional[str]

            attrs["__annotations__"] = annotations
            # Class name PascalCase chỉ để debug; KEY của dict mới là cái graphiti dùng.
            class_name = ''.join(word.capitalize() for word in name.split('_'))
            edge_class = type(class_name, (BaseModel,), attrs)
            edge_class.__doc__ = description
            edge_types[name] = edge_class

            # Build edge_type_map: (source_label, target_label) -> [edge_name, ...]
            source_targets = edge_def.get("source_targets", [])
            if source_targets:
                for st in source_targets:
                    key = (st.get("source", "Entity"), st.get("target", "Entity"))
                    edge_type_map.setdefault(key, []).append(name)
            else:
                # Không khai báo source/target cụ thể → catch-all (Entity, Entity)
                edge_type_map.setdefault(("Entity", "Entity"), []).append(name)

        # Lưu lại để truyền vào add_episode (không gọi API nào ở đây).
        self._entity_types = entity_types
        self._edge_types = edge_types
        self._edge_type_map = edge_type_map
    
    def add_text_batches(
        self,
        graph_id: str,
        chunks: List[str],
        batch_size: int = 3,
        progress_callback: Optional[Callable] = None
    ) -> List[str]:
        """Nạp từng chunk văn bản vào graph qua graphiti.add_episode (tuần tự).

        Graphiti add_episode xử lý đồng bộ (await xong = đã extract & ghi Neo4j) và
        khuyến nghị chạy tuần tự để giữ ngữ cảnh temporal giữa các episode liên tiếp.
        Trả về list episode uuid.

        `batch_size` không còn nghĩa "nhiều episode/1 request" (mỗi chunk = 1 episode);
        giữ param cho tương thích caller, chỉ dùng để định nhịp progress.
        """
        graphiti = get_graphiti()
        episode_uuids: List[str] = []
        total_chunks = len(chunks)
        if total_chunks == 0:
            return episode_uuids

        # entity/edge types: truyền None nếu rỗng để graphiti dùng default.
        entity_types = self._entity_types or None
        edge_types = self._edge_types or None
        edge_type_map = self._edge_type_map or None

        for i, chunk in enumerate(chunks):
            if progress_callback:
                progress_callback(
                    f"Adding chunk {i + 1}/{total_chunks} to graph...",
                    (i + 1) / total_chunks,
                )

            # Lớp retry mỏng phòng LLM backend rate-limit / lỗi tạm thời.
            max_retries = 3
            delay = 2.0
            for attempt in range(max_retries):
                try:
                    result = run_async(graphiti.add_episode(
                        name=f"chunk_{i}",
                        episode_body=chunk,
                        source_description="MiroFish text chunk",
                        reference_time=datetime.now(timezone.utc),
                        source=EpisodeType.text,
                        group_id=graph_id,
                        entity_types=entity_types,
                        edge_types=edge_types,
                        edge_type_map=edge_type_map,
                    ))
                    ep_uuid = getattr(result.episode, "uuid", None)
                    if ep_uuid:
                        episode_uuids.append(ep_uuid)
                    break
                except Exception as e:
                    if attempt < max_retries - 1:
                        if progress_callback:
                            progress_callback(
                                f"Chunk {i + 1} failed ({str(e)[:80]}), retry in {delay:.0f}s...",
                                (i + 1) / total_chunks,
                            )
                        time.sleep(delay)
                        delay *= 2
                    else:
                        if progress_callback:
                            progress_callback(
                                f"Chunk {i + 1} failed after {max_retries} attempts: {str(e)[:120]}",
                                (i + 1) / total_chunks,
                            )
                        raise

        return episode_uuids
    
    def _wait_for_episodes(
        self,
        episode_uuids: List[str],
        progress_callback: Optional[Callable] = None,
        timeout: int = 1000
    ):
        """No-op với Graphiti: add_episode đã xử lý đồng bộ (extract + ghi Neo4j
        xong trước khi return), nên không cần poll trạng thái processing.

        Giữ method để tương thích caller (_build_graph_worker).
        """
        if progress_callback:
            progress_callback("Processing complete (synchronous)", 1.0)
        return

    def _get_graph_info(self, graph_id: str) -> GraphInfo:
        """Lấy/Get dữ liệu Graph Info hiện tại"""
        driver = get_graphiti().driver

        # Load các điểm nút/Entity đang có (phân trang)
        nodes = fetch_all_nodes(driver, graph_id)

        # Lấy theo mảng phân trang thông tin các Edges/Mối Liên Kết
        edges = fetch_all_edges(driver, graph_id)

        # Nối lại và thống kê những Entity Types
        entity_types = set()
        for node in nodes:
            if node.labels:
                for label in node.labels:
                    if label not in ["Entity", "Node"]:
                        entity_types.add(label)

        return GraphInfo(
            graph_id=graph_id,
            node_count=len(nodes),
            edge_count=len(edges),
            entity_types=list(entity_types)
        )
    
    def get_graph_data(self, graph_id: str) -> Dict[str, Any]:
        """
        Gói gọn toàn bộ dữ liệu cấu trúc (Bao gồm dữ liệu Graph chi tiết)
        
        Args:
            graph_id: ID của đồ thị
            
        Returns:
            Một object Dictionary bao hàm thông tin dữ liệu về Mạng lưới Cụm (nodes) và Cạnh (edges), 
            và toàn bộ chi tiết đi kèm khác (Time khởi tạo, Property).
        """
        driver = get_graphiti().driver
        nodes = fetch_all_nodes(driver, graph_id)
        edges = fetch_all_edges(driver, graph_id)

        # Giữ một map tra cứu để phục vụ lấy 'Tên' nhanh theo ID UUID
        node_map = {}
        for node in nodes:
            node_map[node.uuid] = node.name or ""
        
        nodes_data = []
        for node in nodes:
            # Lấy thông số về Thời gian được ghi nhận/khởi tạo
            created_at = getattr(node, 'created_at', None)
            if created_at:
                created_at = str(created_at)
            
            nodes_data.append({
                "uuid": node.uuid,
                "name": node.name,
                "labels": node.labels or [],
                "summary": node.summary or "",
                "attributes": node.attributes or {},
                "created_at": created_at,
            })
        
        edges_data = []
        for edge in edges:
            # Thu thập các timestamp gắn với cạnh
            created_at = getattr(edge, 'created_at', None)
            valid_at = getattr(edge, 'valid_at', None)
            invalid_at = getattr(edge, 'invalid_at', None)
            expired_at = getattr(edge, 'expired_at', None)
            
            # 获取 episodes
            episodes = getattr(edge, 'episodes', None) or getattr(edge, 'episode_ids', None)
            if episodes and not isinstance(episodes, list):
                episodes = [str(episodes)]
            elif episodes:
                episodes = [str(e) for e in episodes]
            
            # 获取 fact_type
            fact_type = getattr(edge, 'fact_type', None) or edge.name or ""
            
            edges_data.append({
                "uuid": edge.uuid,
                "name": edge.name or "",
                "fact": edge.fact or "",
                "fact_type": fact_type,
                "source_node_uuid": edge.source_node_uuid,
                "target_node_uuid": edge.target_node_uuid,
                "source_node_name": node_map.get(edge.source_node_uuid, ""),
                "target_node_name": node_map.get(edge.target_node_uuid, ""),
                "attributes": edge.attributes or {},
                "created_at": str(created_at) if created_at else None,
                "valid_at": str(valid_at) if valid_at else None,
                "invalid_at": str(invalid_at) if invalid_at else None,
                "expired_at": str(expired_at) if expired_at else None,
                "episodes": episodes or [],
            })
        
        return {
            "graph_id": graph_id,
            "nodes": nodes_data,
            "edges": edges_data,
            "node_count": len(nodes_data),
            "edge_count": len(edges_data),
        }
    
    def delete_graph(self, graph_id: str):
        """Xóa toàn bộ node/edge/episode thuộc group_id (DETACH DELETE cascade)."""
        driver = get_graphiti().driver
        run_async(EntityNode.delete_by_group_id(driver, graph_id))

