"""
Graph build service
Interface 2: build a Standalone Graph via the Zep API.
"""

import os
import uuid
import time
import threading
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass

# Zep types (EpisodeData, EntityEdgeSourceTarget, EntityModel/EdgeModel from
# external_clients.ontology) are still referenced for ontology dynamic Pydantic
# classes. When zep-cloud is uninstalled, we provide stubs so module import
# succeeds and the Zep `client` attribute on this service is just the
# GraphitiAdapter (see __init__ below).
try:
    from zep_cloud.client import Zep
    from zep_cloud import EpisodeData, EntityEdgeSourceTarget
except ImportError:
    class Zep:
        def __init__(self, *a, **kw): pass
    class EpisodeData:
        def __init__(self, data, type="text"):
            self.data = data
            self.type = type
    class EntityEdgeSourceTarget:
        def __init__(self, source, target):
            self.source = source
            self.target = target

from ..config import Config
from ..models.task import TaskManager, TaskStatus
from ..utils.zep_paging import fetch_all_nodes, fetch_all_edges
from .text_processor import TextProcessor
from .graphiti_service import get_graphiti_adapter
from ..utils.locale import t, get_locale, set_locale


@dataclass
class GraphInfo:
    """Graph info"""
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
    Graph build service
    Responsible for calling the Zep API to build the knowledge graph.
    """

    def __init__(self, api_key: Optional[str] = None):
        # Zep's per-project graph becomes Graphiti's group_id (a partition).
        # The single shared GraphitiAdapter handles all projects.
        self.api_key = api_key  # kept for signature compat; no longer required
        self.client = get_graphiti_adapter()
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
        Build the graph asynchronously.

        Args:
            text: Input text
            ontology: Ontology definition (output of interface 1)
            graph_name: Graph name
            chunk_size: Text chunk size
            chunk_overlap: Chunk overlap size
            batch_size: Number of chunks sent per batch

        Returns:
            Task ID
        """
        # Create task
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

        # Execute the build in a background thread
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
        """Graph build worker thread"""
        set_locale(locale)
        try:
            self.task_manager.update_task(
                task_id,
                status=TaskStatus.PROCESSING,
                progress=5,
                message=t('progress.startBuildingGraph')
            )

            # 1. Create the graph
            graph_id = self.create_graph(graph_name)
            self.task_manager.update_task(
                task_id,
                progress=10,
                message=t('progress.graphCreated', graphId=graph_id)
            )

            # 2. Set the ontology
            self.set_ontology(graph_id, ontology)
            self.task_manager.update_task(
                task_id,
                progress=15,
                message=t('progress.ontologySet')
            )

            # 3. Split the text into chunks
            chunks = TextProcessor.split_text(text, chunk_size, chunk_overlap)
            total_chunks = len(chunks)
            self.task_manager.update_task(
                task_id,
                progress=20,
                message=t('progress.textSplit', count=total_chunks)
            )

            # 4. Send data in batches
            episode_uuids = self.add_text_batches(
                graph_id, chunks, batch_size,
                lambda msg, prog: self.task_manager.update_task(
                    task_id,
                    progress=20 + int(prog * 0.4),  # 20-60%
                    message=msg
                )
            )

            # 5. Wait for Zep processing to finish
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

            # 6. Fetch graph info
            self.task_manager.update_task(
                task_id,
                progress=90,
                message=t('progress.fetchingGraphInfo')
            )

            graph_info = self._get_graph_info(graph_id)

            # Complete
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
        """Create a graph (public method)"""
        graph_id = f"mirofish_{uuid.uuid4().hex[:16]}"
        # Graphiti creates the partition implicitly on first add_episode; this
        # call just reserves the group_id.
        self.client.create_graph(
            graph_id=graph_id,
            name=name,
            description="MiroFish Social Simulation Graph",
        )

        return graph_id

    def set_ontology(self, graph_id: str, ontology: Dict[str, Any]):
        """Set the graph ontology (public method)"""
        import warnings
        from typing import Optional
        from pydantic import Field
        # Base classes for the dynamic Pydantic ontology types. Try Zep's
        # EntityModel/EdgeModel first (preserves a tiny bit of compatibility if
        # zep-cloud is somehow still in the env), else fall back to Graphiti's
        # EntityNode/EntityEdge which is what we actually use.
        try:
            from zep_cloud.external_clients.ontology import EntityModel, EntityText, EdgeModel
        except ImportError:
            try:
                from graphiti_core.nodes import EntityNode as _GTEntity
                from graphiti_core.edges import EntityEdge as _GTEdge
                EntityModel = _GTEntity  # type: ignore[assignment,misc]
                EdgeModel = _GTEdge  # type: ignore[assignment,misc]
                EntityText = str  # type: ignore[assignment,misc]
            except ImportError:
                from pydantic import BaseModel as EntityModel  # type: ignore[assignment,misc]
                from pydantic import BaseModel as EdgeModel  # type: ignore[assignment,misc]
                EntityText = str  # type: ignore[assignment,misc]

        # Suppress Pydantic v2 warning about Field(default=None)
        # This is required by the Zep SDK; the warning comes from dynamic
        # class creation and can safely be ignored.
        warnings.filterwarnings('ignore', category=UserWarning, module='pydantic')

        # Zep reserved names; cannot be used as attribute names
        RESERVED_NAMES = {'uuid', 'name', 'group_id', 'name_embedding', 'summary', 'created_at'}

        def safe_attr_name(attr_name: str) -> str:
            """Convert a reserved name into a safe name"""
            if attr_name.lower() in RESERVED_NAMES:
                return f"entity_{attr_name}"
            return attr_name

        # Dynamically create entity types
        entity_types = {}
        for entity_def in ontology.get("entity_types", []):
            name = entity_def["name"]
            description = entity_def.get("description", f"A {name} entity.")

            # Build the attribute dict and type annotations (required by Pydantic v2)
            attrs = {"__doc__": description}
            annotations = {}

            for attr_def in entity_def.get("attributes", []):
                attr_name = safe_attr_name(attr_def["name"])  # Use the safe name
                attr_desc = attr_def.get("description", attr_name)
                # Zep API requires a description on Field; this is required
                attrs[attr_name] = Field(description=attr_desc, default=None)
                annotations[attr_name] = Optional[EntityText]  # type annotation

            attrs["__annotations__"] = annotations

            # Dynamically create the class
            entity_class = type(name, (EntityModel,), attrs)
            entity_class.__doc__ = description
            entity_types[name] = entity_class

        # Dynamically create edge types
        edge_definitions = {}
        for edge_def in ontology.get("edge_types", []):
            name = edge_def["name"]
            description = edge_def.get("description", f"A {name} relationship.")

            # Build the attribute dict and type annotations
            attrs = {"__doc__": description}
            annotations = {}

            for attr_def in edge_def.get("attributes", []):
                attr_name = safe_attr_name(attr_def["name"])  # Use the safe name
                attr_desc = attr_def.get("description", attr_name)
                # Zep API requires a description on Field; this is required
                attrs[attr_name] = Field(description=attr_desc, default=None)
                annotations[attr_name] = Optional[str]  # Edge attributes use str type

            attrs["__annotations__"] = annotations

            # Dynamically create the class
            class_name = ''.join(word.capitalize() for word in name.split('_'))
            edge_class = type(class_name, (EdgeModel,), attrs)
            edge_class.__doc__ = description

            # Build source_targets
            source_targets = []
            for st in edge_def.get("source_targets", []):
                source_targets.append(
                    EntityEdgeSourceTarget(
                        source=st.get("source", "Entity"),
                        target=st.get("target", "Entity")
                    )
                )

            if source_targets:
                edge_definitions[name] = (edge_class, source_targets)

        # Graphiti accepts the original JSON ontology directly. The Pydantic
        # class construction above was a Zep-specific quirk; we can skip it
        # for Graphiti and just forward the input. Keep the code path the same
        # shape (Pydantic EntityModel/EdgeModel classes still constructed and
        # exposed to introspection code), but the actual set_ontology call now
        # uses the adapter with the source-of-truth JSON.
        if entity_types or edge_definitions:
            self.client.set_ontology(graph_id=graph_id, ontology=ontology)

    def add_text_batches(
        self,
        graph_id: str,
        chunks: List[str],
        batch_size: int = 3,
        progress_callback: Optional[Callable] = None
    ) -> List[str]:
        """Add text to the graph in batches, returning a list of episode uuids"""
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

            # Build episode data
            episodes = [
                EpisodeData(data=chunk, type="text")
                for chunk in batch_chunks
            ]

            # Send to the graph (Graphiti via adapter — returns after sync extraction)
            try:
                batch_result = self.client.add_batch(
                    graph_id=graph_id,
                    episodes=episodes,
                )

                # Collect returned episode uuids
                if batch_result and isinstance(batch_result, list):
                    for ep in batch_result:
                        ep_uuid = getattr(ep, 'uuid_', None) or getattr(ep, 'uuid', None)
                        if ep_uuid:
                            episode_uuids.append(ep_uuid)

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
        """Wait for all episodes to finish processing.

        Graphiti's add_episode is synchronous (extraction completes before the
        call returns), so all episodes returned by add_batch are already done.
        We still surface progress messages and respect the timeout for the
        outer loop contract, but we never actually need to poll.
        """
        if not episode_uuids:
            if progress_callback:
                progress_callback(t('progress.noEpisodesWait'), 1.0)
            return

        if progress_callback:
            progress_callback(t('progress.waitingEpisodes', count=len(episode_uuids)), 0)
            progress_callback(t('progress.processingComplete', completed=len(episode_uuids), total=len(episode_uuids)), 1.0)

    def _get_graph_info(self, graph_id: str) -> GraphInfo:
        """Get graph info"""
        # Get nodes (paginated)
        nodes = fetch_all_nodes(self.client, graph_id)

        # Get edges (paginated)
        edges = fetch_all_edges(self.client, graph_id)

        # Aggregate entity types
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
        Get the complete graph data (including detailed info).

        Args:
            graph_id: Graph ID

        Returns:
            A dict containing nodes and edges, including timing info,
            attributes, and other detailed data.
        """
        nodes = fetch_all_nodes(self.client, graph_id)
        edges = fetch_all_edges(self.client, graph_id)

        # Build a node-name map
        node_map = {}
        for node in nodes:
            node_map[node.uuid_] = node.name or ""

        nodes_data = []
        for node in nodes:
            # Get creation time
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
            # Get time info
            created_at = getattr(edge, 'created_at', None)
            valid_at = getattr(edge, 'valid_at', None)
            invalid_at = getattr(edge, 'invalid_at', None)
            expired_at = getattr(edge, 'expired_at', None)

            # Get episodes
            episodes = getattr(edge, 'episodes', None) or getattr(edge, 'episode_ids', None)
            if episodes and not isinstance(episodes, list):
                episodes = [str(episodes)]
            elif episodes:
                episodes = [str(e) for e in episodes]

            # Get fact_type
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
        """Delete a graph"""
        self.client.delete_graph(graph_id=graph_id)

