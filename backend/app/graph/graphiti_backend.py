"""
Graphiti + Neo4j graph backend implementation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, create_model

from ..config import Config
from .base import GraphBackend

logger = logging.getLogger(__name__)


@dataclass
class _CompatEpisode:
    uuid: str
    processed: bool = True
    name: str = ""
    content: str = ""
    valid_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    @property
    def uuid_(self) -> str:
        return self.uuid


@dataclass
class _CompatNode:
    uuid: str
    name: str = ""
    labels: List[str] = field(default_factory=list)
    summary: str = ""
    attributes: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[datetime] = None

    @property
    def uuid_(self) -> str:
        return self.uuid


@dataclass
class _CompatEdge:
    uuid: str
    name: str
    fact: str
    source_node_uuid: str
    target_node_uuid: str
    source_node_name: str = ""
    target_node_name: str = ""
    attributes: Dict[str, Any] = field(default_factory=dict)
    episodes: List[str] = field(default_factory=list)
    created_at: Optional[datetime] = None
    valid_at: Optional[datetime] = None
    invalid_at: Optional[datetime] = None
    expired_at: Optional[datetime] = None

    @property
    def uuid_(self) -> str:
        return self.uuid


@dataclass
class _CompatSearchResults:
    edges: List[_CompatEdge] = field(default_factory=list)
    nodes: List[_CompatNode] = field(default_factory=list)


@dataclass
class _OntologyBundle:
    entity_types: Dict[str, type[BaseModel]] = field(default_factory=dict)
    edge_types: Dict[str, type[BaseModel]] = field(default_factory=dict)
    edge_type_map: Dict[tuple[str, str], List[str]] = field(default_factory=dict)
    spec: Dict[str, Any] = field(default_factory=dict)


class _AsyncBridge:
    """Run async Graphiti calls from the app's synchronous service layer."""

    def __init__(self):
        self._ready = threading.Event()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._ready.wait()

    def _run_loop(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._ready.set()
        loop.run_forever()

    def run(self, coro):
        if self._loop is None:
            raise RuntimeError("Graphiti async loop 未初始化")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()


class GraphitiBackend(GraphBackend):
    """Graph backend backed by Graphiti OSS + Neo4j."""

    _bridge: Optional[_AsyncBridge] = None
    _bridge_lock = threading.Lock()
    _indices_ready = False
    _indices_lock = threading.Lock()
    _ontology_registry: Dict[str, _OntologyBundle] = {}
    _ontology_lock = threading.Lock()
    _cross_encoder_warning_emitted = False
    PAGE_SIZE = 200

    def __init__(self, api_key: Optional[str] = None):
        del api_key

        errors = Config.get_graphiti_config_errors()
        if errors:
            raise ValueError("; ".join(errors))

        try:
            from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
            from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
            from graphiti_core.graphiti import Graphiti
            from graphiti_core.llm_client import OpenAIClient
            from graphiti_core.llm_client.config import LLMConfig
            from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
        except ImportError as exc:
            raise ImportError(
                "Graphiti 依赖未安装，请先在 backend 环境中安装 graphiti-core 与 neo4j"
            ) from exc

        llm_config = LLMConfig(
            api_key=Config.GRAPHITI_LLM_API_KEY,
            base_url=Config.GRAPHITI_LLM_BASE_URL,
            model=Config.GRAPHITI_LLM_MODEL,
            small_model=Config.GRAPHITI_LLM_SMALL_MODEL,
            temperature=0,
        )
        reranker_config = LLMConfig(
            api_key=Config.GRAPHITI_RERANKER_API_KEY,
            base_url=Config.GRAPHITI_RERANKER_BASE_URL,
            model=Config.GRAPHITI_RERANKER_MODEL,
            temperature=0,
        )
        embedder_config = OpenAIEmbedderConfig(
            api_key=Config.GRAPHITI_EMBEDDER_API_KEY,
            base_url=Config.GRAPHITI_EMBEDDER_BASE_URL,
            embedding_model=Config.GRAPHITI_EMBEDDER_MODEL,
            embedding_dim=Config.GRAPHITI_EMBEDDER_DIM,
        )

        llm_client_mode = (Config.GRAPHITI_LLM_CLIENT_MODE or "openai").lower()
        if llm_client_mode == "generic":
            llm_client = OpenAIGenericClient(
                config=llm_config,
                max_tokens=Config.GRAPHITI_LLM_MAX_TOKENS,
            )
        else:
            llm_client = OpenAIClient(
                config=llm_config,
                max_tokens=Config.GRAPHITI_LLM_MAX_TOKENS,
            )

        self._graphiti = Graphiti(
            uri=Config.GRAPHITI_URI,
            user=Config.GRAPHITI_USER,
            password=Config.GRAPHITI_PASSWORD,
            llm_client=llm_client,
            embedder=OpenAIEmbedder(config=embedder_config),
            cross_encoder=OpenAIRerankerClient(config=reranker_config),
            max_coroutines=Config.GRAPHITI_MAX_COROUTINES,
        )
        self._driver = self._graphiti.driver.with_database(Config.GRAPHITI_DATABASE)
        self._graphiti.driver = self._driver
        self._graphiti.clients.driver = self._driver
        self._bridge = self._get_bridge()

        self._ensure_indices()

    @classmethod
    def _get_bridge(cls) -> _AsyncBridge:
        with cls._bridge_lock:
            if cls._bridge is None:
                cls._bridge = _AsyncBridge()
            return cls._bridge

    @property
    def raw_client(self) -> Any:
        return self._graphiti

    def _run(self, coro):
        return self._bridge.run(coro)

    def _ensure_indices(self) -> None:
        if self.__class__._indices_ready:
            return

        with self.__class__._indices_lock:
            if self.__class__._indices_ready:
                return
            self._run(self._graphiti.build_indices_and_constraints())
            self.__class__._indices_ready = True

    def _validate_graph_id(self, graph_id: str) -> None:
        from graphiti_core.helpers import validate_group_id

        validate_group_id(graph_id)

    def _normalize_model_spec(self, model: type[BaseModel]) -> Dict[str, Any]:
        fields = []
        for field_name, model_field in model.model_fields.items():
            fields.append(
                {
                    "name": field_name,
                    "description": model_field.description or field_name,
                }
            )

        return {
            "description": (getattr(model, "__doc__", "") or "").strip(),
            "fields": fields,
        }

    def _build_dynamic_model(self, name: str, spec: Dict[str, Any]) -> type[BaseModel]:
        field_definitions = {}
        for field_spec in spec.get("fields", []):
            field_name = field_spec.get("name", "").strip()
            if not field_name:
                continue
            field_definitions[field_name] = (
                Optional[str],
                Field(
                    default=None,
                    description=field_spec.get("description") or field_name,
                ),
            )

        model = create_model(name, __base__=BaseModel, **field_definitions)
        model.__doc__ = spec.get("description") or name
        return model

    def _serialize_ontology_spec(
        self,
        entity_specs: Dict[str, Dict[str, Any]],
        edge_specs: Dict[str, Dict[str, Any]],
        edge_type_map: Dict[tuple[str, str], List[str]],
    ) -> Dict[str, Any]:
        return {
            "entity_types": entity_specs,
            "edge_types": edge_specs,
            "edge_type_map": [
                {
                    "source": source,
                    "target": target,
                    "edges": edge_names,
                }
                for (source, target), edge_names in sorted(edge_type_map.items())
            ],
        }

    def _bundle_from_spec(self, spec: Dict[str, Any]) -> _OntologyBundle:
        entity_types = {
            name: self._build_dynamic_model(name, model_spec)
            for name, model_spec in (spec.get("entity_types") or {}).items()
        }
        edge_types = {
            name: self._build_dynamic_model(name, model_spec)
            for name, model_spec in (spec.get("edge_types") or {}).items()
        }
        edge_type_map: Dict[tuple[str, str], List[str]] = {}
        for entry in spec.get("edge_type_map") or []:
            source = entry.get("source", "Entity")
            target = entry.get("target", "Entity")
            edge_type_map[(source, target)] = list(entry.get("edges") or [])

        return _OntologyBundle(
            entity_types=entity_types,
            edge_types=edge_types,
            edge_type_map=edge_type_map,
            spec=spec,
        )

    def _build_ontology_bundle(self, entities: Any = None, edges: Any = None) -> _OntologyBundle:
        entity_specs = {}
        entity_types = {}
        for entity_name, entity_model in (entities or {}).items():
            entity_spec = self._normalize_model_spec(entity_model)
            entity_specs[entity_name] = entity_spec
            entity_types[entity_name] = self._build_dynamic_model(entity_name, entity_spec)

        edge_specs = {}
        edge_types = {}
        edge_type_map: Dict[tuple[str, str], List[str]] = {}
        for edge_name, edge_value in (edges or {}).items():
            if not isinstance(edge_value, tuple) or len(edge_value) != 2:
                continue
            edge_model, source_targets = edge_value
            edge_spec = self._normalize_model_spec(edge_model)
            edge_specs[edge_name] = edge_spec
            edge_types[edge_name] = self._build_dynamic_model(edge_name, edge_spec)

            for source_target in source_targets or []:
                source = getattr(source_target, "source", "Entity") or "Entity"
                target = getattr(source_target, "target", "Entity") or "Entity"
                edge_type_map.setdefault((source, target), []).append(edge_name)

        if not edge_type_map:
            edge_type_map = {("Entity", "Entity"): list(edge_types.keys())}

        spec = self._serialize_ontology_spec(entity_specs, edge_specs, edge_type_map)
        return _OntologyBundle(
            entity_types=entity_types,
            edge_types=edge_types,
            edge_type_map=edge_type_map,
            spec=spec,
        )

    async def _upsert_graph_metadata_async(
        self,
        graph_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        ontology_spec: Optional[Dict[str, Any]] = None,
    ) -> None:
        payload = json.dumps(ontology_spec, ensure_ascii=False) if ontology_spec is not None else None

        await self._driver.execute_query(
            """
            MERGE (m:GraphMetadata {graph_id: $graph_id})
            ON CREATE SET
                m.group_id = $graph_id,
                m.created_at = datetime()
            SET
                m.name = CASE WHEN $name IS NULL OR $name = '' THEN coalesce(m.name, '') ELSE $name END,
                m.description = CASE
                    WHEN $description IS NULL OR $description = ''
                    THEN coalesce(m.description, '')
                    ELSE $description
                END,
                m.ontology_json = CASE
                    WHEN $ontology_json IS NULL OR $ontology_json = ''
                    THEN m.ontology_json
                    ELSE $ontology_json
                END,
                m.updated_at = datetime()
            """,
            graph_id=graph_id,
            name=name,
            description=description,
            ontology_json=payload,
        )

    async def _load_ontology_bundle_async(self, graph_id: str) -> _OntologyBundle:
        records, _, _ = await self._driver.execute_query(
            """
            MATCH (m:GraphMetadata {graph_id: $graph_id})
            RETURN m.ontology_json AS ontology_json
            """,
            graph_id=graph_id,
            routing_="r",
        )

        if not records:
            return _OntologyBundle()

        ontology_json = records[0].get("ontology_json")
        if not ontology_json:
            return _OntologyBundle()

        try:
            spec = json.loads(ontology_json)
        except (TypeError, ValueError, json.JSONDecodeError):
            logger.warning("Graphiti ontology metadata 解析失败，graph_id=%s", graph_id)
            return _OntologyBundle()

        return self._bundle_from_spec(spec)

    async def _get_ontology_bundle_async(self, graph_id: str) -> _OntologyBundle:
        with self.__class__._ontology_lock:
            cached = self.__class__._ontology_registry.get(graph_id)
        if cached is not None:
            return cached

        bundle = await self._load_ontology_bundle_async(graph_id)
        with self.__class__._ontology_lock:
            self.__class__._ontology_registry[graph_id] = bundle
        return bundle

    def _get_ontology_bundle(self, graph_id: str) -> _OntologyBundle:
        return self._run(self._get_ontology_bundle_async(graph_id))

    def _set_ontology_bundle(self, graph_id: str, bundle: _OntologyBundle) -> None:
        with self.__class__._ontology_lock:
            self.__class__._ontology_registry[graph_id] = bundle

    def get_ontology_spec(self, graph_id: str) -> Optional[Dict[str, Any]]:
        self._validate_graph_id(graph_id)
        bundle = self._get_ontology_bundle(graph_id)
        return dict(bundle.spec) if bundle.spec else None

    def create_graph(self, graph_id: str, name: str, description: str) -> None:
        self._validate_graph_id(graph_id)
        self._run(
            self._upsert_graph_metadata_async(
                graph_id=graph_id,
                name=name,
                description=description,
            )
        )

    def set_ontology(
        self,
        graph_id: str,
        entities: Any = None,
        edges: Any = None,
    ) -> None:
        self._validate_graph_id(graph_id)
        bundle = self._build_ontology_bundle(entities=entities, edges=edges)
        self._set_ontology_bundle(graph_id, bundle)
        self._run(
            self._upsert_graph_metadata_async(
                graph_id=graph_id,
                ontology_spec=bundle.spec,
            )
        )

    async def _add_text_async(self, graph_id: str, data: str) -> _CompatEpisode:
        from graphiti_core.helpers import validate_excluded_entity_types
        from graphiti_core.nodes import EpisodeType, EpisodicNode
        from graphiti_core.search.search_utils import RELEVANT_SCHEMA_LIMIT
        from graphiti_core.utils.datetime_utils import utc_now
        from graphiti_core.utils.maintenance.node_operations import (
            extract_attributes_from_nodes,
            extract_nodes,
            resolve_extracted_nodes,
        )
        from graphiti_core.utils.ontology_utils.entity_types_utils import validate_entity_types

        bundle = await self._get_ontology_bundle_async(graph_id)
        entity_types = bundle.entity_types or None
        edge_types = bundle.edge_types or None
        edge_type_map = bundle.edge_type_map or {("Entity", "Entity"): []}

        validate_entity_types(entity_types)
        validate_excluded_entity_types(None, entity_types)

        now = utc_now()
        previous_episodes = await self._graphiti.retrieve_episodes(
            reference_time=now,
            last_n=RELEVANT_SCHEMA_LIMIT,
            group_ids=[graph_id],
            source=EpisodeType.text,
            driver=self._driver,
        )

        episode = EpisodicNode(
            name=f"episode_{now.strftime('%Y%m%d%H%M%S%f')}",
            group_id=graph_id,
            labels=[],
            source=EpisodeType.text,
            content=data,
            source_description="text",
            created_at=now,
            valid_at=now,
        )

        extracted_nodes = await extract_nodes(
            self._graphiti.clients,
            episode,
            previous_episodes,
            entity_types,
            None,
            None,
        )
        nodes, uuid_map, _ = await resolve_extracted_nodes(
            self._graphiti.clients,
            extracted_nodes,
            episode,
            previous_episodes,
            entity_types,
        )
        resolved_edges, invalidated_edges, new_edges = await self._graphiti._extract_and_resolve_edges(
            episode,
            extracted_nodes,
            previous_episodes,
            edge_type_map,
            graph_id,
            edge_types,
            nodes,
            uuid_map,
            None,
        )
        entity_edges = resolved_edges + invalidated_edges
        hydrated_nodes = await extract_attributes_from_nodes(
            self._graphiti.clients,
            nodes,
            episode,
            previous_episodes,
            entity_types,
            edges=new_edges,
        )
        _, saved_episode = await self._graphiti._process_episode_data(
            episode,
            hydrated_nodes,
            entity_edges,
            now,
            graph_id,
            None,
            None,
        )

        return _CompatEpisode(
            uuid=saved_episode.uuid,
            processed=True,
            name=saved_episode.name,
            content=saved_episode.content,
            valid_at=saved_episode.valid_at,
            created_at=saved_episode.created_at,
        )

    def add_batch(self, graph_id: str, episodes: List[Any]) -> List[Any]:
        results = []
        for episode in episodes:
            data = getattr(episode, "data", None)
            if data is None and isinstance(episode, dict):
                data = episode.get("data", "")
            results.append(self.add_text(graph_id=graph_id, data=str(data or "")))
        return results

    def add_text(self, graph_id: str, data: str) -> Any:
        self._validate_graph_id(graph_id)
        return self._run(self._add_text_async(graph_id=graph_id, data=data))

    async def _get_episode_async(self, episode_uuid: str) -> _CompatEpisode:
        from graphiti_core.nodes import EpisodicNode

        episode = await EpisodicNode.get_by_uuid(self._driver, episode_uuid)
        return _CompatEpisode(
            uuid=episode.uuid,
            processed=True,
            name=episode.name,
            content=episode.content,
            valid_at=episode.valid_at,
            created_at=episode.created_at,
        )

    def get_episode(self, episode_uuid: str) -> Any:
        return self._run(self._get_episode_async(episode_uuid))

    def _warn_cross_encoder_fallback(self) -> None:
        if self.__class__._cross_encoder_warning_emitted:
            return
        logger.info(
            "Graphiti cross_encoder 默认已降级为 rrf；如需启用请设置 GRAPHITI_ENABLE_CROSS_ENCODER=true"
        )
        self.__class__._cross_encoder_warning_emitted = True

    def _build_search_config(self, scope: str, limit: int, reranker: Optional[str]):
        from graphiti_core.search.search_config import (
            EdgeReranker,
            EdgeSearchConfig,
            EdgeSearchMethod,
            NodeReranker,
            NodeSearchConfig,
            NodeSearchMethod,
            SearchConfig,
        )

        reranker_name = (reranker or "rrf").strip().lower()
        edge_reranker_map = {
            "rrf": EdgeReranker.rrf,
            "reciprocal_rank_fusion": EdgeReranker.rrf,
            "cross_encoder": EdgeReranker.cross_encoder,
            "node_distance": EdgeReranker.node_distance,
            "episode_mentions": EdgeReranker.episode_mentions,
            "mmr": EdgeReranker.mmr,
        }
        node_reranker_map = {
            "rrf": NodeReranker.rrf,
            "reciprocal_rank_fusion": NodeReranker.rrf,
            "cross_encoder": NodeReranker.cross_encoder,
            "node_distance": NodeReranker.node_distance,
            "episode_mentions": NodeReranker.episode_mentions,
            "mmr": NodeReranker.mmr,
        }

        edge_reranker = edge_reranker_map.get(reranker_name, EdgeReranker.rrf)
        node_reranker = node_reranker_map.get(reranker_name, NodeReranker.rrf)
        edge_methods = [EdgeSearchMethod.bm25, EdgeSearchMethod.cosine_similarity]
        node_methods = [NodeSearchMethod.bm25, NodeSearchMethod.cosine_similarity]

        if reranker_name == "cross_encoder":
            if Config.GRAPHITI_ENABLE_CROSS_ENCODER:
                edge_methods.append(EdgeSearchMethod.bfs)
                node_methods.append(NodeSearchMethod.bfs)
            else:
                self._warn_cross_encoder_fallback()
                edge_reranker = EdgeReranker.rrf
                node_reranker = NodeReranker.rrf

        edge_config = None
        node_config = None
        if scope in {"edges", "both"}:
            edge_config = EdgeSearchConfig(
                search_methods=edge_methods,
                reranker=edge_reranker,
            )
        if scope in {"nodes", "both"}:
            node_config = NodeSearchConfig(
                search_methods=node_methods,
                reranker=node_reranker,
            )

        return SearchConfig(
            edge_config=edge_config,
            node_config=node_config,
            limit=max(1, limit),
        )

    def _wrap_node(self, node: Any) -> _CompatNode:
        return _CompatNode(
            uuid=getattr(node, "uuid", ""),
            name=getattr(node, "name", "") or "",
            labels=list(getattr(node, "labels", []) or []),
            summary=getattr(node, "summary", "") or "",
            attributes=dict(getattr(node, "attributes", {}) or {}),
            created_at=getattr(node, "created_at", None),
        )

    def _wrap_edge(
        self,
        edge: Any,
        source_node_name: str = "",
        target_node_name: str = "",
    ) -> _CompatEdge:
        return _CompatEdge(
            uuid=getattr(edge, "uuid", ""),
            name=getattr(edge, "name", "") or "",
            fact=getattr(edge, "fact", "") or "",
            source_node_uuid=getattr(edge, "source_node_uuid", "") or "",
            target_node_uuid=getattr(edge, "target_node_uuid", "") or "",
            source_node_name=source_node_name,
            target_node_name=target_node_name,
            attributes=dict(getattr(edge, "attributes", {}) or {}),
            episodes=list(getattr(edge, "episodes", []) or []),
            created_at=getattr(edge, "created_at", None),
            valid_at=getattr(edge, "valid_at", None),
            invalid_at=getattr(edge, "invalid_at", None),
            expired_at=getattr(edge, "expired_at", None),
        )

    async def _search_async(
        self,
        graph_id: str,
        query: str,
        limit: int,
        scope: str,
        reranker: Optional[str],
    ) -> _CompatSearchResults:
        from graphiti_core.nodes import EntityNode

        search_config = self._build_search_config(scope=scope, limit=limit, reranker=reranker)
        results = await self._graphiti.search_(
            query=query,
            config=search_config,
            group_ids=[graph_id],
            driver=self._driver,
        )

        nodes = [self._wrap_node(node) for node in results.nodes]
        node_name_map = {node.uuid: node.name for node in nodes if node.uuid}

        missing_node_ids = {
            node_uuid
            for edge in results.edges
            for node_uuid in (edge.source_node_uuid, edge.target_node_uuid)
            if node_uuid and node_uuid not in node_name_map
        }
        if missing_node_ids:
            for node in await EntityNode.get_by_uuids(self._driver, list(missing_node_ids)):
                node_name_map[node.uuid] = node.name or ""

        edges = [
            self._wrap_edge(
                edge,
                source_node_name=node_name_map.get(edge.source_node_uuid, ""),
                target_node_name=node_name_map.get(edge.target_node_uuid, ""),
            )
            for edge in results.edges
        ]

        return _CompatSearchResults(edges=edges, nodes=nodes)

    def search(
        self,
        graph_id: str,
        query: str,
        limit: int = 10,
        scope: str = "edges",
        reranker: Optional[str] = None,
    ) -> Any:
        self._validate_graph_id(graph_id)
        return self._run(
            self._search_async(
                graph_id=graph_id,
                query=query,
                limit=limit,
                scope=scope,
                reranker=reranker,
            )
        )


    async def _get_all_nodes_async(self, graph_id: str) -> List[_CompatNode]:
        from graphiti_core.nodes import EntityNode

        result = []
        cursor = None
        while True:
            batch = await EntityNode.get_by_group_ids(
                self._driver,
                [graph_id],
                limit=self.PAGE_SIZE,
                uuid_cursor=cursor,
            )
            if not batch:
                break
            result.extend(self._wrap_node(node) for node in batch)
            if len(batch) < self.PAGE_SIZE:
                break
            cursor = batch[-1].uuid

        return result

    def get_all_nodes(self, graph_id: str) -> List[Any]:
        self._validate_graph_id(graph_id)
        return self._run(self._get_all_nodes_async(graph_id))

    async def _get_all_edges_async(self, graph_id: str) -> List[_CompatEdge]:
        from graphiti_core.edges import EntityEdge, GroupsEdgesNotFoundError

        result = []
        cursor = None
        while True:
            try:
                batch = await EntityEdge.get_by_group_ids(
                    self._driver,
                    [graph_id],
                    limit=self.PAGE_SIZE,
                    uuid_cursor=cursor,
                )
            except GroupsEdgesNotFoundError:
                break

            if not batch:
                break

            result.extend(self._wrap_edge(edge) for edge in batch)
            if len(batch) < self.PAGE_SIZE:
                break
            cursor = batch[-1].uuid

        return result

    def get_all_edges(self, graph_id: str) -> List[Any]:
        self._validate_graph_id(graph_id)
        return self._run(self._get_all_edges_async(graph_id))

    async def _get_node_async(self, node_uuid: str) -> _CompatNode:
        from graphiti_core.nodes import EntityNode

        return self._wrap_node(await EntityNode.get_by_uuid(self._driver, node_uuid))

    def get_node(self, node_uuid: str) -> Any:
        return self._run(self._get_node_async(node_uuid))

    async def _get_node_edges_async(self, node_uuid: str) -> List[_CompatEdge]:
        from graphiti_core.edges import EntityEdge
        from graphiti_core.nodes import EntityNode

        edges = await EntityEdge.get_by_node_uuid(self._driver, node_uuid)
        related_node_ids = {
            related_uuid
            for edge in edges
            for related_uuid in (edge.source_node_uuid, edge.target_node_uuid)
            if related_uuid
        }
        node_name_map = {}
        if related_node_ids:
            for node in await EntityNode.get_by_uuids(self._driver, list(related_node_ids)):
                node_name_map[node.uuid] = node.name or ""

        return [
            self._wrap_edge(
                edge,
                source_node_name=node_name_map.get(edge.source_node_uuid, ""),
                target_node_name=node_name_map.get(edge.target_node_uuid, ""),
            )
            for edge in edges
        ]

    def get_node_edges(self, node_uuid: str) -> List[Any]:
        return self._run(self._get_node_edges_async(node_uuid))

    async def _delete_graph_async(self, graph_id: str) -> None:
        from graphiti_core.nodes import Node

        await self._driver.execute_query(
            """
            MATCH (s:Saga {group_id: $graph_id})
            DETACH DELETE s
            """,
            graph_id=graph_id,
        )
        await Node.delete_by_group_id(self._driver, graph_id)
        await self._driver.execute_query(
            """
            MATCH (m:GraphMetadata {graph_id: $graph_id})
            DETACH DELETE m
            """,
            graph_id=graph_id,
        )

    def delete_graph(self, graph_id: str) -> None:
        self._validate_graph_id(graph_id)
        self._run(self._delete_graph_async(graph_id))
        with self.__class__._ontology_lock:
            self.__class__._ontology_registry.pop(graph_id, None)

    async def _get_live_graph_statistics_async(self, graph_id: str) -> Dict[str, int]:
        node_records, _, _ = await self._driver.execute_query(
            """
            MATCH (n:Entity {group_id: $graph_id})
            RETURN count(n) AS node_count
            """,
            graph_id=graph_id,
            routing_="r",
        )
        edge_records, _, _ = await self._driver.execute_query(
            """
            MATCH ()-[e:RELATES_TO {group_id: $graph_id}]->()
            RETURN count(e) AS edge_count
            """,
            graph_id=graph_id,
            routing_="r",
        )
        episode_records, _, _ = await self._driver.execute_query(
            """
            MATCH (n:Episodic {group_id: $graph_id})
            RETURN count(n) AS episode_count
            """,
            graph_id=graph_id,
            routing_="r",
        )

        return {
            "node_count": int((node_records[0] if node_records else {}).get("node_count", 0) or 0),
            "edge_count": int((edge_records[0] if edge_records else {}).get("edge_count", 0) or 0),
            "episode_count": int(
                (episode_records[0] if episode_records else {}).get("episode_count", 0) or 0
            ),
        }

    def get_live_graph_statistics(self, graph_id: str) -> Optional[Dict[str, int]]:
        self._validate_graph_id(graph_id)
        return self._run(self._get_live_graph_statistics_async(graph_id))
