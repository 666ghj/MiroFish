"""
图谱构建服务
Builds the standalone knowledge graph through the abstract memory backend.

Backend selection (Zep Cloud / self-hosted Graphiti) happens via the
``MEMORY_BACKEND`` environment variable; this service does not care
which one is active.
"""

import os
import uuid
import time
import threading
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass

from ..config import Config
from ..models.task import TaskManager, TaskStatus
from ..utils.locale import t, get_locale, set_locale
from .memory import (
    EpisodeInput,
    MemoryBackend,
    OntologySpec,
    get_memory_backend,
)
from .text_processor import TextProcessor


@dataclass
class GraphInfo:
    """图谱信息"""
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
    图谱构建服务
    负责调用Zep API构建知识图谱
    """
    
    def __init__(self, backend: Optional[MemoryBackend] = None):
        # Backwards compatible: legacy callers passed ``api_key`` as the
        # first positional arg. Accept that for one release while
        # callers migrate to the abstract backend.
        if isinstance(backend, str):  # type: ignore[unreachable]
            os.environ.setdefault("ZEP_API_KEY", backend)
            backend = None
        self.backend: MemoryBackend = backend or get_memory_backend()
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
        异步构建图谱
        
        Args:
            text: 输入文本
            ontology: 本体定义（来自接口1的输出）
            graph_name: 图谱名称
            chunk_size: 文本块大小
            chunk_overlap: 块重叠大小
            batch_size: 每批发送的块数量
            
        Returns:
            任务ID
        """
        # 创建任务
        task_id = self.task_manager.create_task(
            task_type="graph_build",
            metadata={
                "graph_name": graph_name,
                "chunk_size": chunk_size,
                "text_length": len(text),
            }
        )
        
        # Capture locale before spawning background thread
        current_locale = get_locale()

        # 在后台线程中执行构建
        thread = threading.Thread(
            target=self._build_graph_worker,
            args=(task_id, text, ontology, graph_name, chunk_size, chunk_overlap, batch_size, current_locale)
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
        batch_size: int,
        locale: str = 'zh'
    ):
        """图谱构建工作线程"""
        set_locale(locale)
        try:
            self.task_manager.update_task(
                task_id,
                status=TaskStatus.PROCESSING,
                progress=5,
                message=t('progress.startBuildingGraph')
            )
            
            # 1. 创建图谱
            graph_id = self.create_graph(graph_name)
            self.task_manager.update_task(
                task_id,
                progress=10,
                message=t('progress.graphCreated', graphId=graph_id)
            )
            
            # 2. 设置本体
            self.set_ontology(graph_id, ontology)
            self.task_manager.update_task(
                task_id,
                progress=15,
                message=t('progress.ontologySet')
            )
            
            # 3. 文本分块
            chunks = TextProcessor.split_text(text, chunk_size, chunk_overlap)
            total_chunks = len(chunks)
            self.task_manager.update_task(
                task_id,
                progress=20,
                message=t('progress.textSplit', count=total_chunks)
            )
            
            # 4. 分批发送数据
            episode_uuids = self.add_text_batches(
                graph_id, chunks, batch_size,
                lambda msg, prog: self.task_manager.update_task(
                    task_id,
                    progress=20 + int(prog * 0.4),  # 20-60%
                    message=msg
                )
            )
            
            # 5. 等待Zep处理完成
            self.task_manager.update_task(
                task_id,
                progress=60,
                message=t('progress.waitingZepProcess')
            )
            
            self._wait_for_episodes(
                episode_uuids,
                lambda msg, prog: self.task_manager.update_task(
                    task_id,
                    progress=60 + int(prog * 0.3),  # 60-90%
                    message=msg
                )
            )
            
            # 6. 获取图谱信息
            self.task_manager.update_task(
                task_id,
                progress=90,
                message=t('progress.fetchingGraphInfo')
            )
            
            graph_info = self._get_graph_info(graph_id)
            
            # 完成
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
        """Create a new memory graph and return its id."""
        graph_id = f"mirofish_{uuid.uuid4().hex[:16]}"
        self.backend.create_graph(
            graph_id,
            display_name=name,
            description="MiroFish Social Simulation Graph",
        )
        return graph_id
    
    def set_ontology(self, graph_id: str, ontology: Dict[str, Any]):
        """Set the entity / edge type schema for ``graph_id``.

        The dynamic Pydantic class construction that used to live here
        moved into the backend implementations, so this service stays
        free of any provider-specific concerns.
        """
        spec = OntologySpec.from_dict(ontology)
        if not spec.entity_types and not spec.edge_types:
            return
        self.backend.set_ontology(graph_id, spec)
    
    def add_text_batches(
        self,
        graph_id: str,
        chunks: List[str],
        batch_size: int = 3,
        progress_callback: Optional[Callable] = None
    ) -> List[str]:
        """分批添加文本到图谱，返回所有 episode 的 uuid 列表"""
        episode_uuids = []
        total_chunks = len(chunks)
        
        for i in range(0, total_chunks, batch_size):
            batch_chunks = chunks[i:i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (total_chunks + batch_size - 1) // batch_size
            
            if progress_callback:
                progress = (i + len(batch_chunks)) / total_chunks
                progress_callback(
                    t('progress.sendingBatch', current=batch_num, total=total_batches, chunks=len(batch_chunks)),
                    progress
                )
            
            # Build provider-neutral episode payload
            episodes = [
                EpisodeInput(content=chunk, episode_type="text")
                for chunk in batch_chunks
            ]

            try:
                batch_result = self.backend.add_episodes_bulk(
                    graph_id=graph_id,
                    episodes=episodes,
                )

                for ep in batch_result:
                    if ep.uuid:
                        episode_uuids.append(ep.uuid)

                # Friendly throttle for cloud backends with low rate limits.
                time.sleep(1)

            except Exception as e:
                if progress_callback:
                    progress_callback(t('progress.batchFailed', batch=batch_num, error=str(e)), 0)
                raise
        
        return episode_uuids
    
    def _wait_for_episodes(
        self,
        episode_uuids: List[str],
        progress_callback: Optional[Callable] = None,
        timeout: int = 600
    ):
        """等待所有 episode 处理完成（通过查询每个 episode 的 processed 状态）"""
        if not episode_uuids:
            if progress_callback:
                progress_callback(t('progress.noEpisodesWait'), 1.0)
            return
        
        start_time = time.time()
        pending_episodes = set(episode_uuids)
        completed_count = 0
        total_episodes = len(episode_uuids)
        
        if progress_callback:
            progress_callback(t('progress.waitingEpisodes', count=total_episodes), 0)
        
        while pending_episodes:
            if time.time() - start_time > timeout:
                if progress_callback:
                    progress_callback(
                        t('progress.episodesTimeout', completed=completed_count, total=total_episodes),
                        completed_count / total_episodes
                    )
                break
            
            # Poll each pending episode for processing completion.
            for ep_uuid in list(pending_episodes):
                try:
                    episode = self.backend.get_episode(ep_uuid)
                    if episode is not None and episode.processed:
                        pending_episodes.remove(ep_uuid)
                        completed_count += 1
                except Exception:
                    # Per-episode lookup failures are expected during
                    # transient rate limiting; carry on.
                    pass
            
            elapsed = int(time.time() - start_time)
            if progress_callback:
                progress_callback(
                    t('progress.zepProcessing', completed=completed_count, total=total_episodes, pending=len(pending_episodes), elapsed=elapsed),
                    completed_count / total_episodes if total_episodes > 0 else 0
                )
            
            if pending_episodes:
                time.sleep(3)  # 每3秒检查一次
        
        if progress_callback:
            progress_callback(t('progress.processingComplete', completed=completed_count, total=total_episodes), 1.0)
    
    def _get_graph_info(self, graph_id: str) -> GraphInfo:
        """Summarise a graph's node count, edge count and entity types."""
        nodes = self.backend.get_all_nodes(graph_id)
        edges = self.backend.get_all_edges(graph_id)

        entity_types: set[str] = set()
        for node in nodes:
            entity_types.update(node.custom_labels())

        return GraphInfo(
            graph_id=graph_id,
            node_count=len(nodes),
            edge_count=len(edges),
            entity_types=list(entity_types),
        )
    
    def get_graph_data(self, graph_id: str) -> Dict[str, Any]:
        """Return the full graph contents in the JSON shape the UI expects."""
        nodes = self.backend.get_all_nodes(graph_id)
        edges = self.backend.get_all_edges(graph_id)

        node_map: Dict[str, str] = {n.uuid: n.name or "" for n in nodes}

        nodes_data = [n.to_dict() for n in nodes]

        edges_data = []
        for edge in edges:
            edge_dict = edge.to_dict()
            edge_dict["source_node_name"] = node_map.get(edge.source_node_uuid, "")
            edge_dict["target_node_name"] = node_map.get(edge.target_node_uuid, "")
            edges_data.append(edge_dict)

        return {
            "graph_id": graph_id,
            "nodes": nodes_data,
            "edges": edges_data,
            "node_count": len(nodes_data),
            "edge_count": len(edges_data),
        }

    def delete_graph(self, graph_id: str):
        """Delete the graph and every entity / edge / episode under it."""
        self.backend.delete_graph(graph_id)

