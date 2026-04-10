"""
图谱构建服务
接口2：使用Zep API构建Standalone Graph
"""

import os
import uuid
import time
import threading
import json
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass
from zep_cloud import EpisodeData, EntityEdgeSourceTarget

from ..config import Config
from ..graph import get_graph_backend
from ..models.task import TaskManager, TaskStatus
from .text_processor import TextProcessor
from ..utils.locale import t, get_locale, set_locale


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
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = Config.ZEP_API_KEY if api_key is None else api_key
        errors = Config.get_graph_backend_config_errors(api_key=self.api_key)
        if errors:
            raise ValueError("; ".join(errors))
        
        self.backend = get_graph_backend(api_key=self.api_key)
        self.task_manager = TaskManager()
    
    def build_graph_async(
        self,
        text: str,
        ontology: Dict[str, Any],
        graph_name: str = "MiroFish Graph",
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        batch_size: int = 1
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
                graph_id,
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
        """创建Zep图谱（公开方法）"""
        graph_id = f"mirofish_{uuid.uuid4().hex[:16]}"
        
        self.backend.create_graph(
            graph_id=graph_id,
            name=name,
            description="MiroFish Social Simulation Graph",
        )
        
        return graph_id
    
    def set_ontology(self, graph_id: str, ontology: Dict[str, Any]):
        """设置图谱本体（公开方法）"""
        import warnings
        from typing import Optional
        from pydantic import Field
        from zep_cloud.external_clients.ontology import EntityModel, EntityText, EdgeModel
        
        # 抑制 Pydantic v2 关于 Field(default=None) 的警告
        # 这是 Zep SDK 要求的用法，警告来自动态类创建，可以安全忽略
        warnings.filterwarnings('ignore', category=UserWarning, module='pydantic')
        
        # Zep 保留名称，不能作为属性名
        RESERVED_NAMES = {'uuid', 'name', 'group_id', 'name_embedding', 'summary', 'created_at'}

        def safe_attr_name(attr_name: str) -> str:
            """将保留名称转换为安全名称"""
            if attr_name.lower() in RESERVED_NAMES:
                return f"entity_{attr_name}"
            return attr_name

        def normalize_attributes(raw_attributes: Any) -> List[Dict[str, str]]:
            normalized: List[Dict[str, str]] = []
            for attr_def in raw_attributes or []:
                if isinstance(attr_def, str):
                    attr_def = {"name": attr_def, "description": attr_def}
                if not isinstance(attr_def, dict):
                    continue

                attr_name = str(attr_def.get("name", "")).strip()
                if not attr_name:
                    continue

                normalized.append({
                    "name": attr_name,
                    "description": str(attr_def.get("description") or attr_name),
                })
            return normalized

        def normalize_source_targets(raw_source_targets: Any) -> List[EntityEdgeSourceTarget]:
            normalized: List[EntityEdgeSourceTarget] = []
            for source_target in raw_source_targets or []:
                if not isinstance(source_target, dict):
                    continue

                normalized.append(
                    EntityEdgeSourceTarget(
                        source=str(source_target.get("source", "Entity")) or "Entity",
                        target=str(source_target.get("target", "Entity")) or "Entity",
                    )
                )

            # Zep API allows max 10 source_targets per edge type.
            return normalized[:10]

        # 动态创建实体类型
        entity_types = {}
        for entity_def in ontology.get("entity_types", []):
            if not isinstance(entity_def, dict):
                continue

            name = str(entity_def.get("name", "")).strip()
            if not name:
                continue

            description = entity_def.get("description", f"A {name} entity.")

            # 创建属性字典和类型注解（Pydantic v2 需要）
            attrs = {"__doc__": description}
            annotations = {}

            for attr_def in normalize_attributes(entity_def.get("attributes", [])):
                attr_name = safe_attr_name(attr_def["name"])  # 使用安全名称
                attr_desc = attr_def.get("description", attr_name)
                # Zep API 需要 Field 的 description，这是必需的
                attrs[attr_name] = Field(description=attr_desc, default=None)
                annotations[attr_name] = Optional[EntityText]  # 类型注解

            attrs["__annotations__"] = annotations

            # 动态创建类
            entity_class = type(name, (EntityModel,), attrs)
            entity_class.__doc__ = description
            entity_types[name] = entity_class

        # 动态创建边类型
        edge_definitions = {}
        for edge_def in ontology.get("edge_types", []):
            if not isinstance(edge_def, dict):
                continue

            name = str(edge_def.get("name", "")).strip()
            if not name:
                continue

            description = edge_def.get("description", f"A {name} relationship.")

            # 创建属性字典和类型注解
            attrs = {"__doc__": description}
            annotations = {}

            for attr_def in normalize_attributes(edge_def.get("attributes", [])):
                attr_name = safe_attr_name(attr_def["name"])  # 使用安全名称
                attr_desc = attr_def.get("description", attr_name)
                # Zep API 需要 Field 的 description，这是必需的
                attrs[attr_name] = Field(description=attr_desc, default=None)
                annotations[attr_name] = Optional[str]  # 边属性用str类型

            attrs["__annotations__"] = annotations

            # 动态创建类
            class_name = ''.join(word.capitalize() for word in name.split('_'))
            edge_class = type(class_name, (EdgeModel,), attrs)
            edge_class.__doc__ = description

            source_targets = normalize_source_targets(edge_def.get("source_targets", []))
            if source_targets:
                edge_definitions[name] = (edge_class, source_targets)

        # 调用Zep API设置本体
        if entity_types or edge_definitions:
            self.backend.set_ontology(
                graph_id=graph_id,
                entities=entity_types if entity_types else None,
                edges=edge_definitions if edge_definitions else None,
            )
    
    def add_text_batches(
        self,
        graph_id: str,
        chunks: List[str],
        batch_size: int = 1,
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
            
            # 构建episode数据
            episodes = [
                EpisodeData(data=chunk, type="text")
                for chunk in batch_chunks
            ]
            
            # 发送到Zep
            try:
                batch_result = self.backend.add_batch(
                    graph_id=graph_id,
                    episodes=episodes
                )
                
                # 收集返回的 episode uuid
                if batch_result and isinstance(batch_result, list):
                    for ep in batch_result:
                        ep_uuid = getattr(ep, 'uuid_', None) or getattr(ep, 'uuid', None)
                        if ep_uuid:
                            episode_uuids.append(ep_uuid)
                
                # 避免请求过快
                time.sleep(1)
                
            except Exception as e:
                if progress_callback:
                    progress_callback(t('progress.batchFailed', batch=batch_num, error=str(e)), 0)
                raise
        
        return episode_uuids



    def _get_live_graph_statistics(self, graph_id: str) -> Optional[Dict[str, int]]:
        """直接读取后端的实时图谱统计。"""
        return self.backend.get_live_graph_statistics(graph_id)

    def _wait_for_episodes(
        self,
        graph_id: str,
        episode_uuids: List[str],
        progress_callback: Optional[Callable] = None,
        timeout: int = 600
    ):
        """等待 OpenZep 处理完成，优先参考真实图谱状态。"""
        if not episode_uuids:
            if progress_callback:
                progress_callback(t('progress.noEpisodesWait'), 1.0)
            return

        start_time = time.time()
        pending_episodes = set(episode_uuids)
        completed_count = 0
        total_episodes = len(episode_uuids)
        last_graph_signature: Optional[tuple[int, int, int]] = None
        stable_graph_polls = 0
        stable_graph_required = 2
        last_live_stats: Optional[Dict[str, int]] = None

        if progress_callback:
            progress_callback(f"开始等待 {total_episodes} 个文本块处理...", 0)

        while pending_episodes:
            elapsed_seconds = time.time() - start_time
            if elapsed_seconds > timeout:
                if last_live_stats is not None:
                    graph_episode_count = min(last_live_stats["episode_count"], total_episodes)
                    graph_node_count = last_live_stats["node_count"]
                    graph_edge_count = last_live_stats["edge_count"]
                    graph_entity_like_nodes = max(0, graph_node_count - last_live_stats["episode_count"])
                    if graph_episode_count >= total_episodes and (graph_entity_like_nodes > 0 or graph_edge_count > 0):
                        if progress_callback:
                            progress_callback(
                                (
                                    f"OpenZep 接口进度未返回完成标记，但真实图谱已写入 "
                                    f"episodes={graph_episode_count}/{total_episodes}, "
                                    f"nodes={graph_node_count}, edges={graph_edge_count}"
                                ),
                                1.0,
                            )
                        return
                if progress_callback:
                    progress_callback(
                        t('progress.episodesTimeout', completed=completed_count, total=total_episodes),
                        completed_count / total_episodes
                    )
                break

            for ep_uuid in list(pending_episodes):
                try:
                    episode = self.backend.get_episode(ep_uuid)
                    is_processed = getattr(episode, 'processed', False)

                    if is_processed:
                        pending_episodes.remove(ep_uuid)
                        completed_count += 1

                except Exception:
                    pass

            live_stats = self._get_live_graph_statistics(graph_id)
            graph_episode_count = 0
            graph_node_count = 0
            graph_edge_count = 0
            graph_entity_like_nodes = 0
            graph_progress = 0.0

            if live_stats is not None:
                last_live_stats = live_stats
                graph_episode_count = min(live_stats["episode_count"], total_episodes)
                graph_node_count = live_stats["node_count"]
                graph_edge_count = live_stats["edge_count"]
                graph_entity_like_nodes = max(0, graph_node_count - live_stats["episode_count"])
                graph_progress = graph_episode_count / total_episodes if total_episodes > 0 else 1.0

                graph_signature = (
                    graph_episode_count,
                    graph_entity_like_nodes,
                    graph_edge_count,
                )
                if graph_signature == last_graph_signature:
                    stable_graph_polls += 1
                else:
                    last_graph_signature = graph_signature
                    stable_graph_polls = 0

                graph_ready = (
                    graph_episode_count >= total_episodes
                    and (graph_entity_like_nodes > 0 or graph_edge_count > 0)
                    and stable_graph_polls >= stable_graph_required
                )
                if graph_ready:
                    if progress_callback:
                        progress_callback(
                            (
                                f"OpenZep 图谱已稳定: episodes={graph_episode_count}/{total_episodes}, "
                                f"nodes={graph_node_count}, edges={graph_edge_count}"
                            ),
                            1.0,
                        )
                    return

            elapsed = int(elapsed_seconds)
            effective_progress = max(
                completed_count / total_episodes if total_episodes > 0 else 1.0,
                graph_progress,
            )
            if progress_callback:
                if live_stats is not None:
                    progress_callback(
                        (
                            f"OpenZep处理中... 接口完成 {completed_count}/{total_episodes}, "
                            f"图中已写入 episodes={graph_episode_count}/{total_episodes}, "
                            f"nodes={graph_node_count}, edges={graph_edge_count} ({elapsed}秒)"
                        ),
                        effective_progress,
                    )
                else:
                    progress_callback(
                        f"Zep处理中... {completed_count}/{total_episodes} 完成, {len(pending_episodes)} 待处理 ({elapsed}秒)",
                        completed_count / total_episodes if total_episodes > 0 else 0
                    )

            if pending_episodes:
                time.sleep(3)

        if progress_callback:
            progress_callback(f"处理完成: {completed_count}/{total_episodes}", 1.0)

    def _get_graph_info(self, graph_id: str) -> GraphInfo:
        """获取图谱信息"""
        # 获取节点（分页）
        nodes = self.backend.get_all_nodes(graph_id)

        # 获取边（分页）
        edges = self.backend.get_all_edges(graph_id)

        # 统计实体类型
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
        获取完整图谱数据（包含详细信息）
        
        Args:
            graph_id: 图谱ID
            
        Returns:
            包含nodes和edges的字典，包括时间信息、属性等详细数据
        """
        nodes = self.backend.get_all_nodes(graph_id)
        edges = self.backend.get_all_edges(graph_id)

        # 创建节点映射用于获取节点名称
        node_map = {}
        for node in nodes:
            node_map[node.uuid_] = node.name or ""
        
        nodes_data = []
        for node in nodes:
            # 获取创建时间
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
            # 获取时间信息
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
        self.backend.delete_graph(graph_id)
