"""
Dịch vụ xây dựng Đồ thị Tri thức (Knowledge Graph)
API 2: Sử dụng Zep API để xây dựng một Standalone Graph (Đồ thị độc lập)
"""

import os
import re  # changed
import uuid
import time
import threading
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass

from zep_cloud.client import Zep
from zep_cloud import EpisodeData, EntityEdgeSourceTarget

from ..config import Config
from ..models.task import TaskManager, TaskStatus
from ..utils.zep_paging import fetch_all_nodes, fetch_all_edges
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
    Đảm nhiệm logic gọi request lên Zep API để thiết lập Graph
    """
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or Config.ZEP_API_KEY
        if not self.api_key:
            raise ValueError("ZEP_API_KEY has not been configured.")
        
        self.client = Zep(api_key=self.api_key)
        self.task_manager = TaskManager()
    
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
        """Graph Creation: Initializes a new graph in Zep Cloud with a unique ID"""

        # Generate unique graph_id
        graph_id = f"mirofish_{uuid.uuid4().hex[:16]}"
        
        # Call Zep API create()
        self.client.graph.create(
            graph_id=graph_id,
            name=name,
            description="MiroFish Social Simulation Graph"
        )
        
        return graph_id
    
    def set_ontology(self, graph_id: str, ontology: Dict[str, Any]):
        """
        Cấu hình dữ liệu Ontology (Bản thể học) cho Graph trên server Zep (Public access)
        Ontology Setup: Defines the schema for entities and relationships using dynamic class creation.
        """
        import warnings
        from typing import Optional
        from pydantic import Field
        from zep_cloud.external_clients.ontology import EntityModel, EntityText, EdgeModel
        
        # Ẩn bỏ đi các Warning (Cảnh báo) của thư viện Pydantic v2 liên quan đến Field(default=None)
        # Vì đây là format bắt buộc phải có từ Zep SDK, các cảnh báo này phát sinh do tự động khởi tạo lớp ảo, hoàn toàn có thể bỏ qua được.
        warnings.filterwarnings('ignore', category=UserWarning, module='pydantic')
        
        # Danh sách các tên định danh (variable/name) trùng với từ khoá bảo lưu của Zep, không được dùng làm tên thuộc tính
        RESERVED_NAMES = {'uuid', 'name', 'group_id', 'name_embedding', 'summary', 'created_at'}
        
        def safe_attr_name(attr_name: str) -> str:
            """Hàm thay đổi các tên thuộc tính bị trùng với keyword của hệ thống để an toàn hơn"""
            if attr_name.lower() in RESERVED_NAMES:
                return f"entity_{attr_name}"
            return attr_name
        
        # Khởi tạo động (Dynamic Class Creation) các Model Loại Thực thể từ JSON đầu vào
        entity_types = {}

        # Processes each entity type from ontology definition
        for entity_def in ontology.get("entity_types", []):
            name = entity_def["name"]
            description = entity_def.get("description", f"A {name} entity.")
            
            # Chuẩn bị file từ điển cho Attribute và kiểu chú thích (Theo chuẩn Pydantic v2)
            attrs = {"__doc__": description}
            annotations = {}
            
            for attr_def in entity_def.get("attributes", []):
                attr_name = safe_attr_name(attr_def["name"])  # Áp dụng hàm chống bị trùng từ khoá
                attr_desc = attr_def.get("description", attr_name)
                # Zep API bắt buộc phải nhận vào field description
                attrs[attr_name] = Field(description=attr_desc, default=None)
                annotations[attr_name] = Optional[EntityText]  # Chú thích kiểu dữ liệu
            
            attrs["__annotations__"] = annotations
            
            # Dynamic class generation - Create Pydnatic model class for entity type at runtime
            entity_class = type(name, (EntityModel,), attrs)
            entity_class.__doc__ = description
            entity_types[name] = entity_class # Store in entity_types dict
        
        # Tương tự, dựa vào JSON để khởi tạo động khai báo các Model Loại Quan Hệ
        edge_definitions = {}
        for edge_def in ontology.get("edge_types", []):
            name = edge_def["name"]
            description = edge_def.get("description", f"A {name} relationship.")
            
            # Dọn các attribute dictionary và typing tương tự
            attrs = {"__doc__": description}
            annotations = {}
            
            for attr_def in edge_def.get("attributes", []):
                attr_name = safe_attr_name(attr_def["name"])  # Filter an toàn
                attr_desc = attr_def.get("description", attr_name)
                # Đảm bảo giữ format Zep API
                attrs[attr_name] = Field(description=attr_desc, default=None)
                annotations[attr_name] = Optional[str]  # Định dạng Data cho thuộc tình của loại Quan Hệ là chuỗi String
            
            attrs["__annotations__"] = annotations
            
            # Khởi tạo Class động với Tên chuẩn format (PascalCase)
            class_name = ''.join(word.capitalize() for word in name.split('_'))
            # Creates Pydantic model class for relationship type
            edge_class = type(class_name, (EdgeModel,), attrs)
            edge_class.__doc__ = description
            
            # Mapping thông số luồng thực thể gắn kết với Quan Hệ (Source/Targets config)
            source_targets = []
            for st in edge_def.get("source_targets", []):
                source_targets.append(
                    EntityEdgeSourceTarget(
                        source=st.get("source", "Entity"),
                        target=st.get("target", "Entity")
                    )
                )
            
            if source_targets:
                edge_definitions[name] = (edge_class, source_targets) # Store in edge_definitions dict
        
        # Action Gọi lệnh thay đổi Ontology cho môi trường GraphID của Zep
        if entity_types or edge_definitions:
            # Call Zep set_ontology() 
            self.client.graph.set_ontology(
                graph_ids=[graph_id],
                entities=entity_types if entity_types else None,
                edges=edge_definitions if edge_definitions else None,
            )
    
    def add_text_batches(
        self,
        graph_id: str,
        chunks: List[str],
        batch_size: int = 3,
        progress_callback: Optional[Callable] = None
    ) -> List[str]:
        """Tải các đoạn văn bản (text chunks) lên Graph theo từng gói nhỏ (batch) và trả về id (Episode UUID) của mọi phân đoạn dữ liệu gửi đi."""
        episode_uuids = []
        total_chunks = len(chunks)
        
        for i in range(0, total_chunks, batch_size):
            batch_chunks = chunks[i:i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (total_chunks + batch_size - 1) // batch_size
            
            if progress_callback:
                progress = (i + len(batch_chunks)) / total_chunks
                progress_callback(
                    f"Sending data batch {batch_num}/{total_batches} ({len(batch_chunks)} chunks)...",
                    progress
                )
            
            # Create EpisodeData objects
            episodes = [
                EpisodeData(data=chunk, type="text")
                for chunk in batch_chunks
            ]
            
            # Khởi chạy gửi cho Zep Server
            max_retries = 10  # changed
            for attempt in range(max_retries):  # changed
                try:
                    # UPLOAD BATCH TO ZEP - Sends batch of episodes for entity extraction
                    batch_result = self.client.graph.add_batch(
                        graph_id=graph_id,
                        episodes=episodes
                    )

                    # Cập nhật và thu thập lại UUID của các Episode được trả về sau khi tạo mới
                    if batch_result and isinstance(batch_result, list):
                        for ep in batch_result:
                            ep_uuid = getattr(ep, 'uuid_', None) or getattr(ep, 'uuid', None)
                            if ep_uuid:
                                episode_uuids.append(ep_uuid)

                    # Cài thời gian chờ (delay) nhỏ để tránh rate-limit bị quá tải số lượng requests
                    time.sleep(3)
                    break  # changed: thoát retry loop nếu thành công

                except Exception as e:  # changed
                    err_str = str(e)
                    if "episode usage limit" in err_str or ("status_code: 429" in err_str):  # changed: bắt lỗi rate-limit
                        # Đọc thời điểm reset từ error message để biết cần chờ bao lâu
                        reset_match = re.search(r"x-ratelimit-reset['\"]:\s*['\"]?(\d+)", err_str)  # changed
                        if reset_match:  # changed
                            wait_seconds = max(int(reset_match.group(1)) - int(time.time()) + 2, 5)  # changed
                        else:  # changed
                            wait_seconds = 20  # changed: fallback 12s (5 calls/phút → cách nhau 12s)
                        if progress_callback:  # changed
                            progress_callback(  # changed
                                f"Rate limited by Zep. Waiting {wait_seconds}s then retry (attempt {attempt + 1}/{max_retries})...",  # changed
                                (i + len(batch_chunks)) / total_chunks  # changed
                            )  # changed
                        time.sleep(wait_seconds)  # changed
                    else:  # changed: lỗi khác thì raise luôn, không retry
                        if progress_callback:
                            progress_callback(f"Failed to send batch {batch_num}: {err_str}", 0)
                        raise  # changed
            else:  # changed: for...else — chạy khi hết max_retries mà vẫn chưa break
                raise Exception(f"Batch {batch_num} failed after {max_retries} retries due to rate limiting")  # changed
        
        return episode_uuids
    
    def _wait_for_episodes(
        self,
        episode_uuids: List[str],
        progress_callback: Optional[Callable] = None,
        timeout: int = 1000
    ):
        """Chạy vòng lặp để kiểm tra và chờ cho tới khi mọi Episode (các khối Text) đều hoàn tất quá trình process từ hệ thống"""
        if not episode_uuids:
            if progress_callback:
                progress_callback("No episodes to scan (Progress 100%)", 1.0)
            return
        
        start_time = time.time()
        pending_episodes = set(episode_uuids)
        completed_count = 0
        total_episodes = len(episode_uuids)
        
        if progress_callback:
            progress_callback(f"Waiting for analysis of {total_episodes} text chunks to begin...", 0)
        
        while pending_episodes:
            # Ngắt thoát và trả về lỗi nếu bị Timeout (Chạy quá thời gian cho phép)
            if time.time() - start_time > timeout:
                if progress_callback:
                    progress_callback(
                        f"Some text segments have timed out, but {completed_count}/{total_episodes} have completed successfully",
                        completed_count / total_episodes
                    )
                break
            
            # Duyệt vòng lặp mỗi episode uuid để lấy cập nhật tiến trình check của từng episode một
            for ep_uuid in list(pending_episodes):
                try:
                    # CHECK EPISODE STATUS - Queries individual episode processing status
                    episode = self.client.graph.episode.get(uuid_=ep_uuid)
                    # CHECK PROCESSED FLAG - Determines if Zep 
                    is_processed = getattr(episode, 'processed', False)
                    
                    if is_processed:
                        # if processed: remove from set
                        pending_episodes.remove(ep_uuid)
                        completed_count += 1
                        
                except Exception as e:
                    # Tạm thời bỏ qua nếu request lỗi, vòng lặp kế theo sẽ tự động call tiếp để get status
                    pass
            
            elapsed = int(time.time() - start_time)
            # update progress callback
            if progress_callback:
                progress_callback(
                    f"Zep is processing in the background... {completed_count}/{total_episodes} done, {len(pending_episodes)} tasks remaining ({elapsed}s elapsed)",
                    completed_count / total_episodes if total_episodes > 0 else 0
                )
            
            if pending_episodes:
                time.sleep(3)  # Lặp chu kỳ check mỗi 3 giây
        
        if progress_callback:
            # Final completion message
            progress_callback(f"Data upload process completed: {completed_count}/{total_episodes}", 1.0)
    
    def _get_graph_info(self, graph_id: str) -> GraphInfo:
        """Lấy/Get dữ liệu Graph Info hiện tại"""
        # Load các điểm nút/Entity đang có (Qua trình duyệt web/paging)
        nodes = fetch_all_nodes(self.client, graph_id)

        # Lấy theo mảng phân trang thông tin các Edges/Mối Liên Kết
        edges = fetch_all_edges(self.client, graph_id)

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
        nodes = fetch_all_nodes(self.client, graph_id)
        edges = fetch_all_edges(self.client, graph_id)

        # Giữ một map tra cứu để phục vụ lấy 'Tên' nhanh theo ID UUID
        node_map = {}
        for node in nodes:
            node_map[node.uuid_] = node.name or ""
        
        nodes_data = []
        for node in nodes:
            # Lấy thông số về Thời gian được ghi nhận/khởi tạo
            created_at = getattr(node, 'created_at', None)
            if created_at:
                created_at = str(created_at)
            
            nodes_data.append({
                "uuid": node.uuid_,
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
                "uuid": edge.uuid_,
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
        """删除图谱"""
        self.client.graph.delete(graph_id=graph_id)

