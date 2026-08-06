"""
图谱构建服务
接口2：使用Zep API构建Standalone Graph
"""

import hashlib
import uuid
import time
import threading
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass

from zep_cloud import BatchAddItem, EntityEdgeSourceTarget, NotFoundError

from ..config import Config
from ..models.task import TaskManager, TaskStatus
from ..utils.zep_paging import fetch_all_nodes, fetch_all_edges
from ..utils.ontology import (
    MAX_ONTOLOGY_TYPES,
    RESERVED_ONTOLOGY_ATTRIBUTE_NAMES,
    normalize_ontology_attributes,
    normalize_ontology_source_targets,
)
from ..utils.zep import (
    ZEP_INGESTION_WAIT_TIMEOUT_SECONDS,
    call_zep_read_with_retry,
    get_zep_client,
    is_retryable_zep_error,
)
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


@dataclass(frozen=True)
class BatchSubmission:
    """Durable identity for one Zep Batch API ingestion operation."""

    batch_id: str
    operation_id: str
    episode_uuids: List[str]
    item_count: int


class GraphBuilderService:
    """
    图谱构建服务
    负责调用Zep API构建知识图谱
    """
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or Config.ZEP_API_KEY
        if not self.api_key:
            raise ValueError("ZEP_API_KEY 未配置")
        
        self.client = get_zep_client(self.api_key)
        self.task_manager = TaskManager()
    
    def build_graph_async(
        self,
        text: str,
        ontology: Dict[str, Any],
        graph_name: str = "MiroFish Graph",
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        batch_size: int = 350
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
            
            # Validate the complete ingestion payload before the first Cloud
            # mutation, including this legacy service entry point.
            chunks = TextProcessor.split_text(text, chunk_size, chunk_overlap)
            self.validate_batch_chunks(chunks, batch_size=batch_size)
            total_chunks = len(chunks)

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
            
            # 3. 文本分块已在 Cloud mutation 前完成并验证
            self.task_manager.update_task(
                task_id,
                progress=20,
                message=t('progress.textSplit', count=total_chunks)
            )
            
            # 4. 分批发送数据
            submission = self.add_text_batches(
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
            
            self._wait_for_batch(
                submission,
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
    
    def create_graph(
        self,
        name: str,
        *,
        graph_id: str | None = None,
        graph_id_callback: Optional[Callable[[str], None]] = None,
    ) -> str:
        """Create a graph with a caller-durable ID and reconcile lost replies."""

        graph_id = graph_id or f"mirofish_{uuid.uuid4().hex[:16]}"
        # Persist the client-generated ID before the non-idempotent POST so a
        # later reset can clean up a graph whose successful response was lost.
        if graph_id_callback:
            graph_id_callback(graph_id)

        try:
            self.client.graph.create(
                graph_id=graph_id,
                name=name,
                description="MiroFish Social Simulation Graph"
            )
        except Exception as error:
            if not is_retryable_zep_error(error):
                raise
            reconciliation_error = None
            for attempt in range(3):
                try:
                    call_zep_read_with_retry(
                        lambda: self.client.graph.get(graph_id),
                        operation_name=f"reconcile graph create {graph_id}",
                    )
                    reconciliation_error = None
                    break
                except NotFoundError as not_found:
                    reconciliation_error = not_found
                    if attempt < 2:
                        time.sleep(attempt + 1)
                except Exception as read_error:
                    reconciliation_error = read_error
                    break
            if reconciliation_error is not None:
                raise error from reconciliation_error

        return graph_id

    @staticmethod
    def build_operation_id(graph_id: str, chunks: List[str]) -> str:
        payload_hash = hashlib.sha256("\0".join(chunks).encode("utf-8")).hexdigest()
        return hashlib.sha256(
            f"{graph_id}:{payload_hash}".encode("utf-8")
        ).hexdigest()

    def _find_batch_by_operation_id(
        self,
        graph_id: str,
        operation_id: str,
        *,
        max_attempts: int = 3,
    ) -> Any | None:
        """Find one server-created batch after an ambiguous create reply."""

        for attempt in range(1, max_attempts + 1):
            matches: List[Any] = []
            cursor: int | None = None
            seen_cursors: set[int] = set()
            while True:
                page = call_zep_read_with_retry(
                    lambda: self.client.batch.list(limit=100, cursor=cursor),
                    operation_name=f"reconcile batch create {operation_id}",
                )
                for batch in getattr(page, "batches", None) or []:
                    metadata = getattr(batch, "metadata", None) or {}
                    if (
                        metadata.get("mirofish_operation_id") == operation_id
                        and metadata.get("graph_id") == graph_id
                    ):
                        matches.append(batch)
                next_cursor = getattr(page, "next_cursor", None)
                if next_cursor is None:
                    break
                if next_cursor == cursor or next_cursor in seen_cursors:
                    raise RuntimeError("Zep batch list cursor did not advance")
                seen_cursors.add(next_cursor)
                cursor = next_cursor

            if len(matches) > 1:
                raise RuntimeError(
                    f"Multiple Zep batches match operation {operation_id}; refusing ambiguity"
                )
            if matches:
                return matches[0]
            if attempt < max_attempts:
                time.sleep(attempt)
        return None
    
    def set_ontology(self, graph_id: str, ontology: Dict[str, Any]):
        """设置图谱本体（公开方法）"""
        import warnings
        from typing import Optional
        from pydantic import Field
        from zep_cloud.external_clients.ontology import EntityModel, EntityText, EdgeModel
        
        # 抑制 Pydantic v2 关于 Field(default=None) 的警告
        # 这是 Zep SDK 要求的用法，警告来自动态类创建，可以安全忽略
        warnings.filterwarnings('ignore', category=UserWarning, module='pydantic')
        
        def safe_attr_name(attr_name: str) -> str:
            """将保留名称转换为安全名称"""
            if attr_name.lower() in RESERVED_ONTOLOGY_ATTRIBUTE_NAMES:
                return f"entity_{attr_name}"
            return attr_name
        
        # 动态创建实体类型
        entity_types = {}
        for entity_def in ontology.get("entity_types", [])[:MAX_ONTOLOGY_TYPES]:
            name = entity_def["name"]
            description = entity_def.get("description", f"A {name} entity.")
            
            # 创建属性字典和类型注解（Pydantic v2 需要）
            attrs = {"__doc__": description}
            annotations = {}
            
            for normalized in normalize_ontology_attributes(
                entity_def.get("attributes", [])
            ):
                attr_name = safe_attr_name(normalized["name"])  # 使用安全名称
                attr_desc = normalized["description"]
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
        for edge_def in ontology.get("edge_types", [])[:MAX_ONTOLOGY_TYPES]:
            name = edge_def["name"]
            description = edge_def.get("description", f"A {name} relationship.")
            
            # 创建属性字典和类型注解
            attrs = {"__doc__": description}
            annotations = {}
            
            for normalized in normalize_ontology_attributes(
                edge_def.get("attributes", [])
            ):
                attr_name = safe_attr_name(normalized["name"])  # 使用安全名称
                attr_desc = normalized["description"]
                # Zep API 需要 Field 的 description，这是必需的
                attrs[attr_name] = Field(description=attr_desc, default=None)
                annotations[attr_name] = Optional[str]  # 边属性用str类型
            
            attrs["__annotations__"] = annotations
            
            # 动态创建类
            class_name = ''.join(word.capitalize() for word in name.split('_'))
            edge_class = type(class_name, (EdgeModel,), attrs)
            edge_class.__doc__ = description
            
            # 构建source_targets
            source_targets = []
            for st in normalize_ontology_source_targets(
                edge_def.get("source_targets", [])
            ):
                source_targets.append(
                    EntityEdgeSourceTarget(
                        source=st.get("source", "Entity"),
                        target=st.get("target", "Entity")
                    )
                )
            
            if source_targets:
                edge_definitions[name] = (edge_class, source_targets)
        
        # 调用Zep API设置本体
        if entity_types or edge_definitions:
            self.client.graph.set_ontology(
                graph_ids=[graph_id],
                # Zep iterates entities.items(), so edge-only ontologies must
                # pass an empty dictionary rather than None.
                entities=entity_types,
                edges=edge_definitions if edge_definitions else None,
            )
    
    def add_text_batches(
        self,
        graph_id: str,
        chunks: List[str],
        batch_size: int = 350,
        progress_callback: Optional[Callable] = None,
        batch_created_callback: Optional[Callable[[str | None, str], None]] = None,
    ) -> BatchSubmission:
        """Submit document chunks through Zep's current Batch API.

        Mutating calls are deliberately not retried: create/add are not
        documented as idempotent, and an ambiguous replay can duplicate graph
        episodes. The returned batch identity allows callers to persist and
        reconcile the operation instead.
        """

        if not graph_id:
            raise ValueError("graph_id is required")
        self.validate_batch_chunks(chunks, batch_size=batch_size)

        total_chunks = len(chunks)
        operation_id = self.build_operation_id(graph_id, chunks)
        if batch_created_callback:
            # Journal the deterministic operation before the server-generated
            # batch ID POST. This leaves enough identity for later diagnosis
            # even if both the response and immediate list reconciliation fail.
            batch_created_callback(None, operation_id)

        try:
            batch = self.client.batch.create(
                metadata={
                    "mirofish_operation_id": operation_id,
                    "graph_id": graph_id,
                    "chunk_count": total_chunks,
                }
            )
        except Exception as error:
            if not is_retryable_zep_error(error):
                raise
            batch = self._find_batch_by_operation_id(graph_id, operation_id)
            if batch is None:
                raise RuntimeError(
                    "Zep batch creation is unconfirmed and no matching operation was found"
                ) from error
        batch_id = getattr(batch, "batch_id", None)
        if not batch_id:
            raise RuntimeError("Zep Batch API returned no batch_id")
        if batch_created_callback:
            batch_created_callback(batch_id, operation_id)

        episode_uuids: List[str] = []
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
            
            items = [
                BatchAddItem(
                    type="graph_episode",
                    graph_id=graph_id,
                    data=chunk,
                    data_type="text",
                    source_description="MiroFish source document chunk",
                    metadata={
                        "mirofish_operation_id": operation_id,
                        "chunk_index": i + offset,
                        "chunk_sha256": hashlib.sha256(
                            chunk.encode("utf-8")
                        ).hexdigest(),
                    },
                )
                for offset, chunk in enumerate(batch_chunks)
            ]

            expected_item_count = i + len(items)
            try:
                item_details = self.client.batch.add(
                    batch_id=batch_id,
                    items=items,
                )
            except Exception as e:
                if progress_callback:
                    progress_callback(t('progress.batchFailed', batch=batch_num, error=str(e)), 0)
                if is_retryable_zep_error(e):
                    recovered_items = self._reconcile_batch_item_count(
                        batch_id,
                        expected_item_count,
                    )
                    recovered_indexes = {
                        getattr(item, "sequence_index", None)
                        for item in recovered_items
                    }
                    if (
                        len(recovered_items) == expected_item_count
                        and recovered_indexes == set(range(expected_item_count))
                    ):
                        item_details = recovered_items[i:expected_item_count]
                    else:
                        raise RuntimeError(
                            f"Zep batch {batch_id} item submission is unconfirmed; "
                            "the draft was not processed or replayed"
                        ) from e
                else:
                    raise RuntimeError(
                        f"Zep batch {batch_id} item submission failed"
                    ) from e

            if len(item_details or []) != len(items):
                recovered_items = self._reconcile_batch_item_count(
                    batch_id,
                    expected_item_count,
                )
                recovered_indexes = {
                    getattr(item, "sequence_index", None)
                    for item in recovered_items
                }
                if (
                    len(recovered_items) == expected_item_count
                    and recovered_indexes == set(range(expected_item_count))
                ):
                    item_details = recovered_items[i:expected_item_count]
                else:
                    raise RuntimeError(
                        f"Zep batch {batch_id} acknowledged {len(item_details or [])} "
                        f"of {len(items)} items"
                    )
            for item in item_details:
                episode_uuid = getattr(item, "episode_uuid", None)
                if episode_uuid:
                    episode_uuids.append(episode_uuid)

        try:
            self.client.batch.process(batch_id=batch_id)
        except Exception as error:
            # A process response can be lost after the server accepted it.
            # Reconcile with a safe GET instead of issuing a second POST.
            summary = call_zep_read_with_retry(
                lambda: self.client.batch.get(batch_id=batch_id),
                operation_name=f"reconcile batch {batch_id}",
            )
            if getattr(summary, "status", None) in {None, "draft"}:
                raise RuntimeError(
                    f"Zep batch {batch_id} processing is unconfirmed"
                ) from error

        return BatchSubmission(
            batch_id=batch_id,
            operation_id=operation_id,
            episode_uuids=episode_uuids,
            item_count=total_chunks,
        )

    @staticmethod
    def validate_batch_chunks(chunks: List[str], *, batch_size: int = 350) -> None:
        """Validate every Batch API limit before the first Cloud mutation."""

        if not chunks:
            raise ValueError("At least one text chunk is required")
        if not 1 <= batch_size <= 350:
            raise ValueError("batch_size must be between 1 and 350")
        if len(chunks) > 50_000:
            raise ValueError("A Zep batch cannot contain more than 50,000 items")
        oversized = [index for index, chunk in enumerate(chunks) if len(chunk) > 10_000]
        if oversized:
            raise ValueError(
                f"Zep batch item exceeds 10,000 characters at chunk {oversized[0]}"
            )

    def _list_batch_items(self, batch_id: str) -> List[Any]:
        items: List[Any] = []
        cursor: int | None = None
        seen_cursors: set[int] = set()
        while True:
            page = call_zep_read_with_retry(
                lambda: self.client.batch.list_items(
                    batch_id=batch_id,
                    limit=100,
                    cursor=cursor,
                ),
                operation_name=f"list batch items {batch_id}",
            )
            items.extend(getattr(page, "items", None) or [])
            next_cursor = getattr(page, "next_cursor", None)
            if next_cursor is None:
                break
            if next_cursor == cursor or next_cursor in seen_cursors:
                raise RuntimeError(f"Zep batch {batch_id} item cursor did not advance")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        return items

    def _reconcile_batch_item_count(
        self,
        batch_id: str,
        expected_item_count: int,
        *,
        max_attempts: int = 3,
    ) -> List[Any]:
        """Allow a short propagation window after an ambiguous add reply."""

        items: List[Any] = []
        for attempt in range(1, max_attempts + 1):
            items = self._list_batch_items(batch_id)
            if len(items) >= expected_item_count:
                return items
            if attempt < max_attempts:
                time.sleep(attempt)
        return items

    def get_batch_summary(self, batch_id: str) -> Any:
        """Read a persisted batch identity for restart reconciliation."""

        return call_zep_read_with_retry(
            lambda: self.client.batch.get(batch_id=batch_id),
            operation_name=f"get batch {batch_id}",
        )

    def _wait_for_batch(
        self,
        submission: BatchSubmission,
        progress_callback: Optional[Callable] = None,
        timeout: int | None = None,
    ) -> List[str]:
        """Wait for a Batch API terminal state and validate every item."""

        timeout = timeout or ZEP_INGESTION_WAIT_TIMEOUT_SECONDS
        start_time = time.time()
        terminal_states = {"succeeded", "partial", "failed", "invalid", "canceled"}

        while True:
            if time.time() - start_time > timeout:
                raise TimeoutError(
                    f"Zep batch {submission.batch_id} did not finish within {timeout}s"
                )

            summary = call_zep_read_with_retry(
                lambda: self.client.batch.get(batch_id=submission.batch_id),
                operation_name=f"poll batch {submission.batch_id}",
            )
            status = getattr(summary, "status", None)
            progress = getattr(summary, "progress", None)
            percent = float(getattr(progress, "percent_complete", 0) or 0) / 100
            if progress_callback:
                completed = int(getattr(progress, "succeeded_items", 0) or 0)
                progress_callback(
                    t(
                        'progress.zepProcessing',
                        completed=completed,
                        total=submission.item_count,
                        pending=max(submission.item_count - completed, 0),
                        elapsed=int(time.time() - start_time),
                    ),
                    min(max(percent, 0.0), 1.0),
                )

            if status in terminal_states:
                break
            time.sleep(3)

        items = self._list_batch_items(submission.batch_id)
        if status != "succeeded":
            failed_items = [
                item for item in items
                if getattr(item, "status", None) not in {"succeeded", "skipped"}
            ]
            first_error = getattr(failed_items[0], "error", None) if failed_items else None
            raise RuntimeError(
                f"Zep batch {submission.batch_id} ended as {status}; "
                f"failed_items={len(failed_items)}; first_error={first_error}"
            )
        if len(items) != submission.item_count:
            raise RuntimeError(
                f"Zep batch {submission.batch_id} contains {len(items)} items, "
                f"expected {submission.item_count}"
            )

        ordered_items = sorted(
            items,
            key=lambda item: getattr(item, "sequence_index", 0) or 0,
        )
        episode_uuids: List[str] = []
        for item in ordered_items:
            item_status = getattr(item, "status", None)
            episode_uuid = getattr(item, "episode_uuid", None)
            source_uuid = getattr(item, "source_uuid", None)
            if item_status != "succeeded" or not episode_uuid:
                raise RuntimeError(
                    f"Zep batch {submission.batch_id} returned an incomplete item"
                )
            if source_uuid and source_uuid != episode_uuid:
                raise RuntimeError(
                    f"Zep batch {submission.batch_id} returned mismatched episode UUIDs"
                )
            episode_uuids.append(episode_uuid)

        if progress_callback:
            progress_callback(
                t(
                    'progress.processingComplete',
                    completed=len(episode_uuids),
                    total=submission.item_count,
                ),
                1.0,
            )
        return episode_uuids
    
    def _wait_for_episodes(
        self,
        episode_uuids: List[str],
        progress_callback: Optional[Callable] = None,
        timeout: int = ZEP_INGESTION_WAIT_TIMEOUT_SECONDS
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
                raise TimeoutError(
                    f"Zep episode processing timed out with "
                    f"{len(pending_episodes)} episode(s) still pending"
                )
            
            # 检查每个 episode 的处理状态
            for ep_uuid in list(pending_episodes):
                episode = call_zep_read_with_retry(
                    lambda: self.client.graph.episode.get(uuid_=ep_uuid),
                    operation_name=f"poll episode {ep_uuid}",
                )
                is_processed = getattr(episode, 'processed', False)

                if is_processed:
                    pending_episodes.remove(ep_uuid)
                    completed_count += 1
            
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
        """获取图谱信息"""
        # 获取节点（分页）
        nodes = fetch_all_nodes(self.client, graph_id)

        # 获取边（分页）
        edges = fetch_all_edges(self.client, graph_id)

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
        nodes = fetch_all_nodes(self.client, graph_id)
        edges = fetch_all_edges(self.client, graph_id)

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
        self.client.graph.delete(graph_id=graph_id)
