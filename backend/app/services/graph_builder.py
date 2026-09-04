"""Graph building service.

Endpoint 2: build a standalone graph through the Zep API.
"""

import hashlib
import os
import uuid
import time
import threading
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass

from zep_cloud import BatchAddItem, EntityEdgeSourceTarget, NotFoundError

from ..config import Config
from ..models.task import TaskManager, TaskStatus
from ..utils.logger import get_logger
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
from ..utils.locale import t

logger = get_logger('sosim.graph_builder')

# UXE fork: ingesting a document makes hundreds of local LLM calls, and nothing
# below the Batch API retries an openai.APITimeoutError. One timed-out call used
# to end the whole build as "partial" and throw away every episode that had
# already committed. Resubmit the failed items instead; keep the bound small so
# an endpoint that is genuinely down still fails within a sane wall time.
GRAPH_BUILD_MAX_ITEM_RETRIES = int(
    os.environ.get("GRAPH_BUILD_MAX_ITEM_RETRIES") or 2
)

# A journalled retry batch nobody can read back is not the same thing as one
# that was never journalled at all: the recorded batch already ingested
# something that is no longer visible, so resubmitting its chunks would commit
# their episodes a second time, while an absent record means nothing ran.
# _resume_recorded_retry_batch returns this instead of None so the two answers
# stay distinguishable.
UNREADABLE_RETRY_BATCH = object()


@dataclass
class GraphInfo:
    """Summary counts for one built graph."""
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


@dataclass(frozen=True)
class LostBatchItem:
    """One batch item that never produced an episode, after every retry."""

    sequence_index: int
    status: str | None
    error: Any


@dataclass(frozen=True)
class BatchItemPartition:
    """What one terminal batch listing says about the items it reported.

    ``reported_indexes`` covers every sequence index the listing mentioned at
    all, so a caller can tell an item it already accounted for from one the
    server never reported - a listing that comes back short is exactly how a
    chunk disappears without anyone raising.
    """

    episodes_by_index: Dict[int, str]
    lost_items: List[LostBatchItem]
    reported_indexes: set[int]


class GraphBuilderService:
    """Build a knowledge graph through the Zep API."""

    # Zep counts "skipped" and "canceled" items separately from failures: the
    # server declined the work rather than tripping over it. Neither produced
    # an episode, so both are still losses the caller has to hear about, but
    # resubmitting them would override that decision - and, for an item skipped
    # as a duplicate, commit a second episode for a chunk already in the graph.
    NON_RETRYABLE_ITEM_STATUSES = frozenset({"skipped", "canceled"})

    # A status alone does not say whether resubmitting is worth anything: a
    # truncation fails as an ordinary "failed" item, and it is deterministic -
    # the same chunk under the same token cap clips its JSON again on every
    # resubmission, so the retries only burn the budget the other items need.
    # The Zep-compatible shim records the failing exception class in the item
    # error, and graphiti raises TruncatedResponseError for exactly this, so
    # match on that name rather than on the message text.
    NON_RETRYABLE_ITEM_ERROR_TYPES = frozenset({"TruncatedResponseError"})

    @classmethod
    def _item_is_retryable(cls, item: "LostBatchItem") -> bool:
        """Report whether resubmitting one lost item could ever recover it."""

        if item.status in cls.NON_RETRYABLE_ITEM_STATUSES:
            return False
        error = item.error
        error_type = (
            error.get("type") if isinstance(error, dict)
            else getattr(error, "type", None)
        )
        return error_type not in cls.NON_RETRYABLE_ITEM_ERROR_TYPES

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or Config.ZEP_API_KEY
        if not self.api_key:
            raise ValueError("ZEP_API_KEY is not configured.")
        
        self.client = get_zep_client(self.api_key)
        self.task_manager = TaskManager()
    
    def build_graph_async(
        self,
        text: str,
        ontology: Dict[str, Any],
        graph_name: str = "SoSim Graph",
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        batch_size: int = 350
    ) -> str:
        """Build a graph on a background thread and return its task ID.

        Args:
            text: Source text to ingest.
            ontology: Ontology definition produced by endpoint 1.
            graph_name: Human-readable graph name.
            chunk_size: Characters per text chunk.
            chunk_overlap: Overlap between adjacent chunks.
            batch_size: Chunks sent per Batch API call.

        Returns:
            The task ID to poll for progress.
        """
        task_id = self.task_manager.create_task(
            task_type="graph_build",
            metadata={
                "graph_name": graph_name,
                "chunk_size": chunk_size,
                "text_length": len(text),
            }
        )

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
        batch_size: int,
    ):
        """Run one graph build to completion on a worker thread."""
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

            # 1. Create the graph.
            graph_id = self.create_graph(graph_name)
            self.task_manager.update_task(
                task_id,
                progress=10,
                message=t('progress.graphCreated', graphId=graph_id)
            )
            
            # 2. Install the ontology.
            self.set_ontology(graph_id, ontology)
            self.task_manager.update_task(
                task_id,
                progress=15,
                message=t('progress.ontologySet')
            )
            
            # 3. Chunking already ran and was validated before the first
            #    Cloud mutation.
            self.task_manager.update_task(
                task_id,
                progress=20,
                message=t('progress.textSplit', count=total_chunks)
            )
            
            # 4. Send the chunks in batches.
            submission = self.add_text_batches(
                graph_id, chunks, batch_size,
                lambda msg, prog: self.task_manager.update_task(
                    task_id,
                    progress=20 + int(prog * 0.4),  # 20-60%
                    message=msg
                )
            )
            
            # 5. Wait for Zep to finish processing.
            self.task_manager.update_task(
                task_id,
                progress=60,
                message=t('progress.waitingZepProcess')
            )
            
            # Opting into salvage means this path can now finish with chunks
            # missing, so it has to hear about them: discarding the callback
            # and reporting completion regardless is the silent-success shape
            # the other build path was just fixed for.
            lost_items: List[LostBatchItem] = []
            self._wait_for_batch(
                submission,
                lambda msg, prog: self.task_manager.update_task(
                    task_id,
                    progress=60 + int(prog * 0.3),  # 60-90%
                    message=msg
                ),
                # This path salvages a partial batch instead of failing it, so
                # it opts in explicitly and hands over the chunks a failed item
                # has to be resubmitted with.
                allow_partial=True,
                retry_chunks=chunks,
                lost_items_callback=lost_items.extend,
            )

            # 6. Read the resulting graph summary.
            self.task_manager.update_task(
                task_id,
                progress=90,
                message=t('progress.fetchingGraphInfo')
            )

            graph_info = self._get_graph_info(graph_id)

            lost_indexes = [item.sequence_index for item in lost_items]
            if lost_indexes:
                logger.warning(
                    "Task %s built graph %s without %s of %s chunk(s): "
                    "chunk_indexes=%s",
                    task_id,
                    graph_id,
                    len(lost_indexes),
                    total_chunks,
                    lost_indexes,
                )

            self.task_manager.update_task(
                task_id,
                status=TaskStatus.COMPLETED,
                progress=100,
                # A graph missing chunks is usable but incomplete, and the
                # completion message is the only place a caller polling the
                # task will ever see that.
                message=(
                    t(
                        'progress.episodesTimeout',
                        completed=total_chunks - len(lost_indexes),
                        total=total_chunks,
                    )
                    if lost_indexes
                    else t('progress.taskComplete')
                ),
                result={
                    "graph_id": graph_id,
                    "graph_info": graph_info.to_dict(),
                    # The chunks that actually landed, not the chunks that were
                    # submitted: the two differ exactly when items were lost.
                    "chunks_processed": total_chunks - len(lost_indexes),
                    "chunk_count": total_chunks,
                    "lost_chunk_count": len(lost_indexes),
                    "lost_chunk_indexes": lost_indexes,
                },
            )

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

        graph_id = graph_id or f"sosim_{uuid.uuid4().hex[:16]}"
        # Persist the client-generated ID before the non-idempotent POST so a
        # later reset can clean up a graph whose successful response was lost.
        if graph_id_callback:
            graph_id_callback(graph_id)

        try:
            self.client.graph.create(
                graph_id=graph_id,
                name=name,
                description="SoSim Social Simulation Graph"
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
                        metadata.get("sosim_operation_id") == operation_id
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
        """Install entity and edge types on a graph."""
        import warnings
        from typing import Optional
        from pydantic import Field
        from zep_cloud.external_clients.ontology import EntityModel, EntityText, EdgeModel
        
        # Pydantic v2 warns about Field(default=None), but that is exactly
        # what the Zep SDK requires, and the warning comes from dynamic class
        # creation rather than from anything the caller can fix.
        warnings.filterwarnings('ignore', category=UserWarning, module='pydantic')
        
        def safe_attr_name(attr_name: str) -> str:
            """Rename a reserved attribute so Zep will accept it."""
            if attr_name.lower() in RESERVED_ONTOLOGY_ATTRIBUTE_NAMES:
                return f"entity_{attr_name}"
            return attr_name
        
        # Build the entity classes.
        entity_types = {}
        for entity_def in ontology.get("entity_types", [])[:MAX_ONTOLOGY_TYPES]:
            name = entity_def["name"]
            description = entity_def.get("description", f"A {name} entity.")
            
            # Pydantic v2 needs both the attribute values and __annotations__.
            attrs = {"__doc__": description}
            annotations = {}
            
            for normalized in normalize_ontology_attributes(
                entity_def.get("attributes", [])
            ):
                attr_name = safe_attr_name(normalized["name"])
                attr_desc = normalized["description"]
                # The Zep API rejects a Field without a description.
                attrs[attr_name] = Field(description=attr_desc, default=None)
                annotations[attr_name] = Optional[EntityText]

            attrs["__annotations__"] = annotations

            entity_class = type(name, (EntityModel,), attrs)
            entity_class.__doc__ = description
            entity_types[name] = entity_class
        
        # Build the edge classes.
        edge_definitions = {}
        for edge_def in ontology.get("edge_types", [])[:MAX_ONTOLOGY_TYPES]:
            name = edge_def["name"]
            description = edge_def.get("description", f"A {name} relationship.")
            
            # Pydantic v2 needs both the attribute values and __annotations__.
            attrs = {"__doc__": description}
            annotations = {}
            
            for normalized in normalize_ontology_attributes(
                edge_def.get("attributes", [])
            ):
                attr_name = safe_attr_name(normalized["name"])
                attr_desc = normalized["description"]
                # The Zep API rejects a Field without a description.
                attrs[attr_name] = Field(description=attr_desc, default=None)
                annotations[attr_name] = Optional[str]

            attrs["__annotations__"] = annotations

            class_name = ''.join(word.capitalize() for word in name.split('_'))
            edge_class = type(class_name, (EdgeModel,), attrs)
            edge_class.__doc__ = description
            
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
                    "sosim_operation_id": operation_id,
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
        logger.info(
            "Zep batch %s created for graph %s with %s chunk(s)",
            batch_id,
            graph_id,
            total_chunks,
        )

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
                    source_description="SoSim source document chunk",
                    metadata={
                        "sosim_operation_id": operation_id,
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

        logger.info(
            "Zep batch %s submitted for processing (%s item(s))",
            batch_id,
            total_chunks,
        )
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

    def _poll_batch_until_terminal(
        self,
        batch_id: str,
        timeout: float,
        progress_callback: Optional[Callable] = None,
        completed_offset: int = 0,
        progress_total: int = 0,
    ) -> str:
        """Poll one batch until it reports a terminal status.

        ``timeout`` is the budget for this call alone: a follow-up retry batch
        is polled with whatever is left of the caller's deadline, never with a
        fresh copy of it. ``completed_offset`` and ``progress_total`` let that
        retry batch report progress against the whole ingest instead of
        restarting the counter at zero for the handful of items resubmitted.
        """

        start_time = time.time()
        total = progress_total
        terminal_states = {"succeeded", "partial", "failed", "invalid", "canceled"}

        while True:
            if time.time() - start_time > timeout:
                raise TimeoutError(
                    f"Zep batch {batch_id} did not finish within {int(timeout)}s"
                )

            summary = call_zep_read_with_retry(
                lambda: self.client.batch.get(batch_id=batch_id),
                operation_name=f"poll batch {batch_id}",
            )
            status = getattr(summary, "status", None)
            progress = getattr(summary, "progress", None)
            if progress_callback:
                completed = completed_offset + int(
                    getattr(progress, "succeeded_items", 0) or 0
                )
                progress_callback(
                    t(
                        'progress.zepProcessing',
                        completed=completed,
                        total=total,
                        pending=max(total - completed, 0),
                        elapsed=int(time.time() - start_time),
                    ),
                    min(max(completed / total if total else 1.0, 0.0), 1.0),
                )

            if status in terminal_states:
                # One line per batch, not per poll: a build polls for the best
                # part of an hour.
                logger.info(
                    "Zep batch %s reached terminal status %s after %ss",
                    batch_id,
                    status,
                    int(time.time() - start_time),
                )
                return status
            time.sleep(3)

    @staticmethod
    def _batch_item_landed(item: Any) -> bool:
        """Report whether one batch item actually committed an episode.

        The failure summary and the retry partition both ask this question and
        used to answer it differently: the summary read "skipped" as a
        non-failure while the partition called it lost and resubmitted the
        chunk. One definition now serves both, so they cannot drift apart.
        """

        return bool(
            getattr(item, "status", None) == "succeeded"
            and getattr(item, "episode_uuid", None)
        )

    def _partition_batch_items(
        self,
        batch_id: str,
        items: List[Any],
    ) -> BatchItemPartition:
        """Split terminal batch items into landed episodes and lost items."""

        episodes_by_index: Dict[int, str] = {}
        lost_items: List[LostBatchItem] = []
        reported_indexes: set[int] = set()
        for item in items:
            sequence_index = getattr(item, "sequence_index", 0) or 0
            reported_indexes.add(sequence_index)
            episode_uuid = getattr(item, "episode_uuid", None)
            source_uuid = getattr(item, "source_uuid", None)
            if not self._batch_item_landed(item):
                lost_items.append(
                    LostBatchItem(
                        sequence_index=sequence_index,
                        status=getattr(item, "status", None),
                        error=getattr(item, "error", None),
                    )
                )
                continue
            if source_uuid and source_uuid != episode_uuid:
                raise RuntimeError(
                    f"Zep batch {batch_id} returned mismatched episode UUIDs"
                )
            episodes_by_index[sequence_index] = episode_uuid
        return BatchItemPartition(
            episodes_by_index=episodes_by_index,
            lost_items=lost_items,
            reported_indexes=reported_indexes,
        )

    @staticmethod
    def _batch_graph_id(items: List[Any]) -> str | None:
        """Read the target graph back from the batch items themselves."""

        graph_ids = {
            graph_id
            for graph_id in (getattr(item, "graph_id", None) for item in items)
            if graph_id
        }
        if len(graph_ids) != 1:
            return None
        return graph_ids.pop()

    def _resume_recorded_retry_batch(
        self,
        graph_id: str,
        recorded: Optional[Dict[str, Any]],
    ) -> str | object | None:
        """Return a retry batch a previous run already submitted, if there is one.

        Retry batches are journaled the same way the main batch is, so a build
        that died after recovering its failed chunks resumes by polling the
        batch it already created instead of ingesting those chunks a second
        time and duplicating the episodes they committed.

        Returns the batch ID to poll, ``None`` when this attempt still has to
        be submitted, or ``UNREADABLE_RETRY_BATCH`` when a journalled batch
        exists but the server will not say what became of it.
        """

        if not recorded:
            return None
        batch_id = recorded.get("batch_id")
        try:
            if not batch_id:
                # The create response was lost before the batch ID could be
                # persisted; the deterministic operation ID is what still
                # names it.
                operation_id = recorded.get("operation_id")
                if not operation_id:
                    return None
                batch = self._find_batch_by_operation_id(graph_id, operation_id)
                batch_id = getattr(batch, "batch_id", None) if batch else None
                if not batch_id:
                    # The journal entry is written before the create POST, so
                    # an operation the server has never heard of ingested
                    # nothing: this attempt still has to be submitted.
                    return None
            summary = self.get_batch_summary(batch_id)
        except Exception as error:
            # get_batch_summary raises - NotFoundError for a batch that has
            # aged out, for instance - and this call sits inside the attempt
            # loop, so one unreadable entry used to abandon every remaining
            # retry, including a later journalled batch that reads perfectly
            # well. Report it as unresolvable and let the caller keep going.
            logger.warning(
                "Zep retry batch %s from the journal could not be read (%s: %s)",
                batch_id or recorded.get("operation_id"),
                type(error).__name__,
                error,
            )
            return UNREADABLE_RETRY_BATCH
        if getattr(summary, "status", None) in {None, "draft"}:
            # Created but never handed to Zep for processing, so it ingested
            # nothing: this attempt still has to be submitted.
            return None
        return batch_id

    def _retry_failed_batch_items(
        self,
        submission: BatchSubmission,
        items: List[Any],
        episodes_by_index: Dict[int, str],
        lost_items: List[LostBatchItem],
        retry_chunks: Optional[List[str]],
        deadline: float,
        progress_callback: Optional[Callable] = None,
        *,
        retry_batch_callback: Optional[Callable[[str | None, str], None]] = None,
        known_retry_batches: Optional[List[Dict[str, Any]]] = None,
    ) -> List[LostBatchItem]:
        """Resubmit only the failed items and merge whatever they produce.

        Each item commits its own episode, so the ones that already succeeded
        must never be re-ingested; the follow-up batch carries the failed
        chunks alone. ``episodes_by_index`` is updated in place and the items
        still missing an episode are returned.
        """

        graph_id = self._batch_graph_id(items)
        # Items Zep declined, and items that failed deterministically, stay
        # lost whatever the retries do; see NON_RETRYABLE_ITEM_STATUSES and
        # NON_RETRYABLE_ITEM_ERROR_TYPES for why replaying them is not safe.
        declined = [
            item for item in lost_items
            if not self._item_is_retryable(item)
        ]
        pending = [
            item for item in lost_items
            if self._item_is_retryable(item)
        ]

        def all_lost(remaining: List[LostBatchItem]) -> List[LostBatchItem]:
            return sorted(
                declined + remaining, key=lambda item: item.sequence_index
            )

        if not pending:
            return all_lost([])
        if not retry_chunks or graph_id is None:
            logger.warning(
                "Zep batch %s cannot resubmit %s failed item(s): "
                "retry chunks are %s and the target graph is %s",
                submission.batch_id,
                len(pending),
                "present" if retry_chunks else "missing",
                graph_id or "unknown",
            )
            return all_lost(pending)

        recorded = list(known_retry_batches or [])
        # Set once a journalled attempt turns out to be unusable - unreadable,
        # or recorded for a different chunk set. From that point on the chunks
        # it carried may or may not already be in the graph, so a fresh
        # submission of the same chunks is no longer a recovery - it is a coin
        # flip on duplicating their episodes.
        unresolved_retry_batch: str | None = None
        for attempt in range(1, GRAPH_BUILD_MAX_ITEM_RETRIES + 1):
            indexes = [item.sequence_index for item in pending]
            if any(index >= len(retry_chunks) for index in indexes):
                logger.error(
                    "Zep batch %s reported item indexes %s outside the "
                    "submitted chunk list; refusing to guess the payload",
                    submission.batch_id,
                    indexes,
                )
                return all_lost(pending)

            # The retries spend the caller's timeout, they do not renew it. A
            # per-attempt clock turned a 2-hour budget into 6 hours of holding
            # the project in GRAPH_BUILDING, during which /reset and /delete
            # answer 409 and the project cannot be recovered by hand.
            remaining_budget = deadline - time.time()
            if remaining_budget <= 0:
                logger.error(
                    "Zep batch %s: ingestion budget exhausted with %s item(s) "
                    "%s still missing; not resubmitting",
                    submission.batch_id,
                    len(indexes),
                    indexes,
                )
                return all_lost(pending)

            # "recovering", not "resubmitting": this attempt may replay a batch
            # a previous run already submitted, or skip a journalled one it
            # cannot read, without ingesting anything at all.
            logger.warning(
                "Zep batch %s: recovering %s failed item(s) %s (attempt %s/%s)",
                submission.batch_id,
                len(indexes),
                indexes,
                attempt,
                GRAPH_BUILD_MAX_ITEM_RETRIES,
            )
            journal_entry = (
                recorded[attempt - 1] if attempt <= len(recorded) else None
            )
            if journal_entry is not None:
                # A journalled batch may only be replayed against the exact
                # chunk set it was submitted for. Retry results are merged
                # back by position - indexes[retry_index] below - so an entry
                # recorded when `pending` held a different set maps its
                # episodes onto the wrong source chunks, silently, which is
                # worse than reporting the chunks lost. `pending` does drift:
                # an attempt spent on an unreadable entry does not shrink it,
                # and a later listing can report a different set of failures
                # than the run that wrote the journal saw. The operation ID is
                # a hash of the graph ID and the submitted chunk texts, so
                # recomputing it here is that identity check.
                expected_operation_id = self.build_operation_id(
                    graph_id, [retry_chunks[index] for index in indexes]
                )
                if journal_entry.get("operation_id") != expected_operation_id:
                    logger.error(
                        "Zep batch %s: journalled retry batch %s was submitted "
                        "for a different chunk set than item(s) %s, so its "
                        "episodes cannot be mapped back; not replaying it",
                        submission.batch_id,
                        journal_entry.get("batch_id")
                        or journal_entry.get("operation_id"),
                        indexes,
                    )
                    # Like an unreadable entry: that batch may already hold
                    # episodes for these chunks, so a fresh submission of them
                    # is a coin flip on duplicating those episodes.
                    unresolved_retry_batch = str(
                        journal_entry.get("batch_id")
                        or journal_entry.get("operation_id")
                    )
                    continue
            try:
                retry_batch_id = self._resume_recorded_retry_batch(
                    graph_id,
                    journal_entry,
                )
                if retry_batch_id is UNREADABLE_RETRY_BATCH:
                    # Spend the attempt without ingesting anything: a later
                    # journalled batch may still be readable and may already
                    # hold the episodes these chunks need.
                    unresolved_retry_batch = str(
                        (journal_entry or {}).get("batch_id")
                        or (journal_entry or {}).get("operation_id")
                    )
                    continue
                if retry_batch_id is None:
                    if unresolved_retry_batch:
                        logger.error(
                            "Zep batch %s: retry batch %s from the journal is "
                            "unusable, so item(s) %s cannot be resubmitted "
                            "without risking a duplicate episode; reporting "
                            "them lost",
                            submission.batch_id,
                            unresolved_retry_batch,
                            indexes,
                        )
                        return all_lost(pending)
                    retry_batch_id = self.add_text_batches(
                        graph_id,
                        [retry_chunks[index] for index in indexes],
                        batch_created_callback=retry_batch_callback,
                    ).batch_id
                self._poll_batch_until_terminal(
                    retry_batch_id,
                    remaining_budget,
                    progress_callback,
                    completed_offset=len(episodes_by_index),
                    progress_total=submission.item_count,
                )
                retry_items = self._list_batch_items(retry_batch_id)
                partition = self._partition_batch_items(
                    retry_batch_id, retry_items
                )
            except Exception as error:
                # A retry that blows up must not cost the caller the episodes
                # that already committed: stop here and report the losses.
                logger.warning(
                    "Zep batch %s: retry attempt %s failed (%s: %s)",
                    submission.batch_id,
                    attempt,
                    type(error).__name__,
                    error,
                )
                return all_lost(pending)

            if not partition.reported_indexes <= set(range(len(indexes))):
                logger.error(
                    "Zep batch %s: retry batch %s returned sequence indexes %s "
                    "that do not map back to the resubmitted items",
                    submission.batch_id,
                    retry_batch_id,
                    sorted(partition.reported_indexes),
                )
                return all_lost(pending)

            for retry_index, episode_uuid in partition.episodes_by_index.items():
                episodes_by_index[indexes[retry_index]] = episode_uuid

            # A retry listing can come back short exactly like the main one. An
            # index it never mentions is in neither bucket, so the subset guard
            # above passes, the item silently drops out of `pending` and the
            # build reports every chunk recovered while one is still missing.
            unreported = [
                LostBatchItem(sequence_index=index, status=None, error=None)
                for index in range(len(indexes))
                if index not in partition.reported_indexes
            ]
            remaining = sorted(
                (
                    LostBatchItem(
                        sequence_index=indexes[item.sequence_index],
                        status=item.status,
                        error=item.error,
                    )
                    for item in partition.lost_items + unreported
                ),
                key=lambda item: item.sequence_index,
            )
            declined.extend(
                item for item in remaining
                if not self._item_is_retryable(item)
            )
            pending = [
                item for item in remaining
                if self._item_is_retryable(item)
            ]
            if not pending:
                logger.info(
                    "Zep batch %s: retry attempt %s recovered every "
                    "resubmitted item",
                    submission.batch_id,
                    attempt,
                )
                return all_lost([])

        return all_lost(pending)

    def _wait_for_batch(
        self,
        submission: BatchSubmission,
        progress_callback: Optional[Callable] = None,
        timeout: int | None = None,
        *,
        allow_partial: bool = False,
        retry_chunks: Optional[List[str]] = None,
        lost_items_callback: Optional[Callable[[List[LostBatchItem]], None]] = None,
        retry_batch_callback: Optional[Callable[[str | None, str], None]] = None,
        known_retry_batches: Optional[List[Dict[str, Any]]] = None,
    ) -> List[str]:
        """Wait for a Batch API terminal state and keep every landed episode.

        A "partial" batch need not be a failed build. Every item commits its
        own episode independently, so one item dying on a single LLM timeout
        used to discard the 61 episodes that were already in the graph and
        force a 50-minute re-ingest. Salvaging that is opt-in: pass
        ``allow_partial`` together with ``retry_chunks`` - the ordered chunk
        list this batch was built from - to have the failed items resubmitted
        as a follow-up batch, and ``lost_items_callback`` to hear about
        whatever is still missing once the retries are exhausted. Without
        ``allow_partial`` a short ingest still raises, so a caller that only
        counts the returned episodes cannot read a lossy batch as a clean one.

        ``retry_batch_callback`` reports every follow-up batch the retries
        create, and ``known_retry_batches`` replays the ones a previous run
        recorded, so resuming an interrupted build never re-ingests a chunk a
        retry batch already committed.
        """

        timeout = timeout or ZEP_INGESTION_WAIT_TIMEOUT_SECONDS
        # One absolute deadline for the whole wait, retries included. Restarting
        # the clock per retry turned a 2-hour budget into 6 hours of holding the
        # project in GRAPH_BUILDING, with /reset and /delete answering 409.
        deadline = time.time() + timeout
        status = self._poll_batch_until_terminal(
            submission.batch_id,
            timeout,
            progress_callback,
            progress_total=submission.item_count,
        )

        items = self._list_batch_items(submission.batch_id)
        salvageable = {"succeeded"} | ({"partial"} if allow_partial else set())
        if status not in salvageable:
            failed_items = [
                item for item in items if not self._batch_item_landed(item)
            ]
            first_error = getattr(failed_items[0], "error", None) if failed_items else None
            logger.error(
                "Zep batch %s ended as %s with %s failed item(s); first_error=%s",
                submission.batch_id,
                status,
                len(failed_items),
                first_error,
            )
            raise RuntimeError(
                f"Zep batch {submission.batch_id} ended as {status}; "
                f"failed_items={len(failed_items)}; first_error={first_error}"
            )

        partition = self._partition_batch_items(submission.batch_id, items)
        episodes_by_index = partition.episodes_by_index
        lost_items = list(partition.lost_items)

        if status == "succeeded":
            # A batch the server calls succeeded while still holding an
            # unfinished item is a contract violation, not a partial ingest.
            if lost_items:
                raise RuntimeError(
                    f"Zep batch {submission.batch_id} returned an incomplete item"
                )
            # Count the distinct indexes that produced an episode rather than
            # the listing rows: a listing of the right length that repeats one
            # sequence_index would otherwise pass while a chunk is missing.
            if len(episodes_by_index) != submission.item_count:
                raise RuntimeError(
                    f"Zep batch {submission.batch_id} produced "
                    f"{len(episodes_by_index)} episode(s), "
                    f"expected {submission.item_count}"
                )

        if status == "partial":
            # A partial batch can also come back short. An item the listing
            # never mentions is just as lost as one that failed, so account for
            # it here instead of silently dropping the chunk.
            lost_items.extend(
                LostBatchItem(sequence_index=index, status=None, error=None)
                for index in range(submission.item_count)
                if index not in partition.reported_indexes
            )
            lost_items.sort(key=lambda item: item.sequence_index)

        if lost_items:
            lost_items = self._retry_failed_batch_items(
                submission,
                items,
                episodes_by_index,
                lost_items,
                retry_chunks,
                deadline,
                progress_callback,
                retry_batch_callback=retry_batch_callback,
                known_retry_batches=known_retry_batches,
            )

        episode_uuids = [
            episodes_by_index[index] for index in sorted(episodes_by_index)
        ]

        if lost_items:
            logger.error(
                "Zep batch %s lost %s of %s item(s); sequence_indexes=%s "
                "first_error=%s",
                submission.batch_id,
                len(lost_items),
                submission.item_count,
                [item.sequence_index for item in lost_items],
                lost_items[0].error,
            )
            if lost_items_callback:
                lost_items_callback(lost_items)
            if not episode_uuids:
                # Nothing landed at all, so there is no graph to salvage.
                raise RuntimeError(
                    f"Zep batch {submission.batch_id} ended as {status}; "
                    f"failed_items={len(lost_items)}; "
                    f"first_error={lost_items[0].error}"
                )

        if progress_callback:
            progress_callback(
                t(
                    'progress.episodesTimeout' if lost_items
                    else 'progress.processingComplete',
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
        """Wait until every episode reports itself as processed."""
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
                time.sleep(3)
        
        if progress_callback:
            progress_callback(t('progress.processingComplete', completed=completed_count, total=total_episodes), 1.0)
    
    def _get_graph_info(self, graph_id: str) -> GraphInfo:
        """Read node and edge counts and the distinct entity types."""
        nodes = fetch_all_nodes(self.client, graph_id)
        edges = fetch_all_edges(self.client, graph_id)

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
        """Read the full graph, including timestamps and attributes.

        Args:
            graph_id: The graph to read.

        Returns:
            A dictionary of nodes and edges with their detailed fields.
        """
        nodes = fetch_all_nodes(self.client, graph_id)
        edges = fetch_all_edges(self.client, graph_id)

        # Edges carry endpoint UUIDs only, so index the names once.
        node_map = {}
        for node in nodes:
            node_map[node.uuid_] = node.name or ""
        
        nodes_data = []
        for node in nodes:
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
            created_at = getattr(edge, 'created_at', None)
            valid_at = getattr(edge, 'valid_at', None)
            invalid_at = getattr(edge, 'invalid_at', None)
            expired_at = getattr(edge, 'expired_at', None)
            
            episodes = getattr(edge, 'episodes', None) or getattr(edge, 'episode_ids', None)
            if episodes and not isinstance(episodes, list):
                episodes = [str(episodes)]
            elif episodes:
                episodes = [str(e) for e in episodes]
            
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
        """Delete a graph and everything in it."""
        self.client.graph.delete(graph_id=graph_id)
