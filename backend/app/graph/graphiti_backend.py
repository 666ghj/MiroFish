"""Graphiti + Neo4j implementation of GraphBackend."""
import asyncio
import json
import threading
import typing
import uuid as uuid_mod
from typing import Any, Dict, List, Optional

from .base import GraphBackend
from ..config import Config
from ..utils.logger import get_logger
from ..utils.llm_client import parse_azure_url


def _neo4j_val(v: Any) -> Any:
    """Convert Neo4j native types to JSON-serializable Python types."""
    if v is None:
        return None
    t = type(v).__name__
    if t in ('DateTime', 'Date', 'Time', 'LocalDateTime', 'LocalTime', 'Duration'):
        return str(v)
    if isinstance(v, (list, tuple)):
        return [_neo4j_val(i) for i in v]
    if isinstance(v, dict):
        return {k: _neo4j_val(vv) for k, vv in v.items()}
    return v


def _flatten_attributes(attrs: dict) -> dict:
    """Flatten entity attribute dicts so every value is a Neo4j-safe primitive.

    Graphiti extracts entity attributes via a Pydantic model, but the raw LLM
    response sometimes wraps each value in a nested dict (e.g. {"value": "CTTI"}).
    Neo4j only accepts primitive types or arrays thereof, so we coerce any
    dict value to its string representation. Lists of primitives are kept as-is
    because Neo4j supports array properties.
    """
    result = {}
    for k, v in attrs.items():
        if v is None:
            continue
        if isinstance(v, dict):
            # Unwrap {"value": "..."} pattern emitted by some LLMs; fall back to str()
            result[k] = v.get("value") or v.get("text") or str(v)
        else:
            result[k] = v
    return result


def _neo4j_props(node_or_rel: Any) -> Dict[str, Any]:
    """Return a JSON-safe dict of a Neo4j node or relationship's properties."""
    return {k: _neo4j_val(v) for k, v in dict(node_or_rel).items()}

logger = get_logger('mirofish.graph.graphiti')


def _make_azure_generic_client(config, client):
    """Return an OpenAIGenericClient subclass that uses max_completion_tokens
    instead of max_tokens — required by gpt-5 / o-series models on Azure."""
    from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
    import openai as _openai
    from graphiti_core.llm_client.errors import RateLimitError as _RateLimitError
    from pydantic import BaseModel as _BaseModel

    class _AzureGenericClient(OpenAIGenericClient):
        async def _generate_response(self, messages, response_model=None, max_tokens=None, model_size=None):
            from openai.types.chat import ChatCompletionMessageParam
            if max_tokens is None:
                max_tokens = self.max_tokens
            openai_messages: list[ChatCompletionMessageParam] = []
            for m in messages:
                if m.role == 'user':
                    openai_messages.append({'role': 'user', 'content': m.content})
                elif m.role == 'system':
                    openai_messages.append({'role': 'system', 'content': m.content})
            response_format: dict[str, Any] = {'type': 'json_object'}
            if response_model is not None:
                schema_name = getattr(response_model, '__name__', 'structured_response')
                response_format = {
                    'type': 'json_schema',
                    'json_schema': {
                        'name': schema_name,
                        'schema': response_model.model_json_schema(),
                    },
                }
            try:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=openai_messages,
                    temperature=self.temperature,
                    max_completion_tokens=max_tokens,
                    response_format=response_format,
                )
                return json.loads(response.choices[0].message.content or '{}')
            except _openai.RateLimitError as e:
                raise _RateLimitError from e

    return _AzureGenericClient(config=config, client=client)


def _run_async(coro, timeout=300):
    """Run an async coroutine from a sync context using a dedicated thread loop."""
    loop = _get_event_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=timeout)


_loop: Optional[asyncio.AbstractEventLoop] = None
_loop_thread: Optional[threading.Thread] = None
_loop_lock = threading.Lock()


def _get_event_loop() -> asyncio.AbstractEventLoop:
    global _loop, _loop_thread
    with _loop_lock:
        if _loop is None or not _loop.is_running():
            _loop = asyncio.new_event_loop()
            _loop_thread = threading.Thread(target=_loop.run_forever, daemon=True)
            _loop_thread.start()
    return _loop


class GraphitiBackend(GraphBackend):
    def __init__(
        self,
        uri: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self._uri = uri or Config.NEO4J_URI
        self._user = user or Config.NEO4J_USER
        self._password = password or Config.NEO4J_PASSWORD
        if not self._password:
            raise ValueError("NEO4J_PASSWORD is not configured")
        self._entity_types: Dict[str, Any] = {}
        self._edge_types: Dict[str, Any] = {}
        self._entity_defs: Dict[str, Any] = {}
        self._edge_defs: Dict[str, Any] = {}
        self._client = self._build_client()

    def _build_client(self):
        from graphiti_core import Graphiti
        from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
        from graphiti_core.llm_client.config import LLMConfig
        from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
        from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
        from openai import AsyncOpenAI

        llm_base_url, llm_query = parse_azure_url(Config.LLM_BASE_URL)
        small_base_url, small_query = parse_azure_url(Config.LLM_SMALL_BASE_URL)
        embed_base_url, embed_query = parse_azure_url(Config.LLM_EMBED_BASE_URL)

        # Pre-built async clients so api-version is passed as default_query (Azure requirement)
        async_llm_client = AsyncOpenAI(
            api_key=Config.LLM_API_KEY,
            base_url=llm_base_url,
            default_query=llm_query or None,
        )
        async_small_client = AsyncOpenAI(
            api_key=Config.LLM_SMALL_API_KEY,
            base_url=small_base_url,
            default_query=small_query or None,
        )
        async_embed_client = AsyncOpenAI(
            api_key=Config.LLM_EMBED_API_KEY,
            base_url=embed_base_url,
            default_query=embed_query or None,
        )

        llm_config = LLMConfig(
            api_key=Config.LLM_API_KEY,
            model=Config.LLM_MODEL_NAME,
            small_model=Config.LLM_SMALL_MODEL_NAME,
            base_url=llm_base_url,
        )
        llm_client = _make_azure_generic_client(config=llm_config, client=async_llm_client)
        embedder = OpenAIEmbedder(
            config=OpenAIEmbedderConfig(
                api_key=Config.LLM_EMBED_API_KEY,
                base_url=embed_base_url,
                embedding_model=Config.LLM_EMBED_MODEL_NAME,
            ),
            client=async_embed_client,
        )
        cross_encoder = OpenAIRerankerClient(config=llm_config, client=async_small_client)
        client = Graphiti(
            uri=self._uri,
            user=self._user,
            password=self._password,
            llm_client=llm_client,
            embedder=embedder,
            cross_encoder=cross_encoder,
        )
        self._patch_extract_entity_attributes()
        return client

    @staticmethod
    def _patch_extract_entity_attributes() -> None:
        """Monkey-patch graphiti internals to fix two LLM quirks:

        1. _extract_entity_attributes: some LLMs wrap attribute values in nested
           dicts ({"value": "CTTI"}). Neo4j rejects these — flatten them.
        2. _extract_nodes_single: some LLMs omit entity_type_id from extracted
           entities, causing a Pydantic ValidationError. Default missing IDs to 0
           (the generic "Entity" type) before validation runs.
        """
        import graphiti_core.utils.maintenance.node_operations as _node_ops

        # --- patch 1: attribute flattening ---
        original_attrs = _node_ops._extract_entity_attributes

        async def _patched_attrs(llm_client, node, episode, previous_episodes, entity_type):
            result = await original_attrs(llm_client, node, episode, previous_episodes, entity_type)
            return _flatten_attributes(result) if result else result

        _node_ops._extract_entity_attributes = _patched_attrs

        # --- patch 2: entity_type_id defaulting ---
        original_nodes = _node_ops._extract_nodes_single

        async def _patched_nodes(llm_client, episode, context):
            from graphiti_core.utils.maintenance.node_operations import ExtractedEntities
            # Call the LLM the normal way but catch the Pydantic validation error
            # that arises when the LLM forgets entity_type_id.
            try:
                return await original_nodes(llm_client, episode, context)
            except Exception as exc:
                # Only intercept Pydantic validation errors about entity_type_id
                if "entity_type_id" not in str(exc):
                    raise
                logger.warning(f"LLM omitted entity_type_id — defaulting to 0 and retrying validation: {exc}")
                # Re-run the LLM call via the internal helper to get the raw dict
                from graphiti_core.utils.maintenance.node_operations import _call_extraction_llm
                llm_response = await _call_extraction_llm(llm_client, episode, context)
                # Inject entity_type_id=0 for any entity that is missing it
                entities = llm_response.get("extracted_entities", [])
                for ent in entities:
                    if isinstance(ent, dict) and "entity_type_id" not in ent:
                        ent["entity_type_id"] = 0
                response_object = ExtractedEntities(**llm_response)
                return response_object.extracted_entities

        _node_ops._extract_nodes_single = _patched_nodes

    def create_graph(self, graph_id: str, name: str, description: str = "") -> None:
        logger.info(f"Graphiti graph namespace ready: {graph_id}")

    def set_ontology(self, graph_ids: List[str], entities: Dict[str, Any], edges: Dict[str, Any]) -> None:
        from pydantic import BaseModel as _BaseModel, Field as _Field

        def _make_model(name: str, type_def: Any) -> Any:
            if isinstance(type_def, dict):
                doc = type_def.get("description", "")
                attrs_defs = type_def.get("attributes", [])
            else:
                doc = getattr(type_def, "__doc__", "") or ""
                attrs_defs = []

            annotations: Dict[str, Any] = {}
            fields: Dict[str, Any] = {"__doc__": doc, "__annotations__": annotations}
            for attr in attrs_defs:
                attr_name = attr.get("name", "")
                attr_desc = attr.get("description", attr_name)
                if not attr_name:
                    continue
                annotations[attr_name] = Optional[str]
                fields[attr_name] = _Field(default=None, description=attr_desc)

            return type(name, (_BaseModel,), fields)

        self._entity_types: Dict[str, Any] = {
            name: _make_model(name, td) for name, td in (entities or {}).items()
        }
        self._edge_types: Dict[str, Any] = {
            name: _make_model(name, td) for name, td in (edges or {}).items()
        }
        # Keep a separate plain dict for use in extraction instructions
        self._entity_defs: Dict[str, Any] = dict(entities or {})
        self._edge_defs: Dict[str, Any] = dict(edges or {})
        if self._entity_types:
            logger.info(f"Graphiti entity types: {list(self._entity_types.keys())}")
        if self._edge_types:
            logger.info(f"Graphiti edge types: {list(self._edge_types.keys())}")

    def _build_extraction_instructions(self) -> Optional[str]:
        """Return custom instructions that constrain extraction to ontology types and attributes."""
        entity_defs = self._entity_defs or {}
        edge_defs = self._edge_defs or {}
        if not entity_defs and not edge_defs:
            return None

        parts = []

        if entity_defs:
            entity_lines = []
            for name, td in entity_defs.items():
                desc = td.get("description", "") if isinstance(td, dict) else ""
                attrs = td.get("attributes", []) if isinstance(td, dict) else []
                if attrs:
                    attr_str = ", ".join(
                        f"{a['name']} ({a.get('description', a['name'])})"
                        for a in attrs if a.get("name")
                    )
                    entity_lines.append(f"  - {name}: {desc} [attributes: {attr_str}]")
                else:
                    entity_lines.append(f"  - {name}: {desc}")
            parts.append(
                "Only classify entities using these types (use 'Entity' only if none fits):\n"
                + "\n".join(entity_lines)
                + "\nFor each entity, extract values for the listed attributes when present in the text."
            )

        if edge_defs:
            edge_names = list(edge_defs.keys())
            parts.append(
                f"Only use these relationship types: {', '.join(edge_names)}. "
                "Do not invent new relationship type names."
            )

        return "\n\n".join(parts)

    def add_batch(self, graph_id: str, episodes: List[Any]) -> List[str]:
        from graphiti_core.nodes import EpisodeType
        from datetime import datetime, timezone
        import time as _time

        entity_types = self._entity_types or None
        edge_types = self._edge_types or None
        instructions = self._build_extraction_instructions()
        ids = []

        for ep in episodes:
            data = ep["data"] if isinstance(ep, dict) else ep.data
            ep_id = str(uuid_mod.uuid4())
            ids.append(ep_id)

            last_exc = None
            for attempt in range(3):
                try:
                    _run_async(
                        self._client.add_episode(
                            name=ep_id,
                            episode_body=data,
                            source_description="MiroFish document chunk",
                            reference_time=datetime.now(timezone.utc),
                            source=EpisodeType.text,
                            group_id=graph_id,
                            entity_types=entity_types,
                            edge_types=edge_types,
                            custom_extraction_instructions=instructions,
                        ),
                        timeout=300,
                    )
                    last_exc = None
                    break
                except Exception as exc:
                    last_exc = exc
                    # "node not found" race condition — wait and retry
                    if "not found" in str(exc).lower() and attempt < 2:
                        logger.warning(f"Episode {ep_id} attempt {attempt + 1} failed ({exc}), retrying...")
                        _time.sleep(2 * (attempt + 1))
                    else:
                        raise

            if last_exc:
                raise last_exc

        return ids

    def get_episode(self, uuid_: str) -> Any:
        class _FakeEpisode:
            processed = True
        return _FakeEpisode()

    def get_all_nodes(self, graph_id: str) -> List[Dict[str, Any]]:
        results = _run_async(
            self._client.driver.execute_query(
                "MATCH (n:Entity {group_id: $gid}) RETURN n",
                params={"gid": graph_id},
            )
        )
        nodes = []
        for record in results.records:
            n = record["n"]
            nodes.append({
                "uuid": n.get("uuid", n.element_id),
                "name": n.get("name", ""),
                "labels": list(n.labels),
                "summary": n.get("summary", ""),
                "attributes": _neo4j_props(n),
                "created_at": str(n.get("created_at", "")),
            })
        return nodes

    def get_all_edges(self, graph_id: str, max_items: int = 5000) -> List[Dict[str, Any]]:
        results = _run_async(
            self._client.driver.execute_query(
                "MATCH (s)-[r]->(t) WHERE r.group_id = $gid RETURN s, r, t LIMIT $limit",
                params={"gid": graph_id, "limit": max_items},
            )
        )
        if len(results.records) >= max_items:
            logger.warning(
                f"get_all_edges: result truncated at {max_items} edges for graph {graph_id}"
            )
        edges = []
        for record in results.records:
            r = record["r"]
            edges.append({
                "uuid": r.get("uuid", r.element_id),
                "name": r.get("name", type(r).__name__),
                "fact": r.get("fact", ""),
                "source_node_uuid": record["s"].get("uuid", ""),
                "target_node_uuid": record["t"].get("uuid", ""),
                "fact_type": r.get("fact_type", ""),
                "attributes": _neo4j_props(r),
                "created_at": str(r.get("created_at", "")),
                "valid_at": str(r.get("valid_at", "")),
                "invalid_at": str(r.get("invalid_at", "")),
                "expired_at": str(r.get("expired_at", "")),
                "episodes": [],
            })
        return edges

    def get_node(self, uuid_: str) -> Dict[str, Any]:
        results = _run_async(
            self._client.driver.execute_query(
                "MATCH (n {uuid: $uuid}) RETURN n LIMIT 1",
                params={"uuid": uuid_},
            )
        )
        if not results.records:
            return {}
        n = results.records[0]["n"]
        return {
            "uuid": n.get("uuid", ""),
            "name": n.get("name", ""),
            "labels": list(n.labels),
            "summary": n.get("summary", ""),
            "attributes": _neo4j_props(n),
        }

    def get_node_edges(self, node_uuid: str) -> List[Dict[str, Any]]:
        results = _run_async(
            self._client.driver.execute_query(
                "MATCH (n {uuid: $uuid})-[r]->(t) RETURN r, t "
                "UNION MATCH (s)-[r]->(n {uuid: $uuid}) RETURN r, s as t",
                params={"uuid": node_uuid},
            )
        )
        edges = []
        for record in results.records:
            r = record["r"]
            edges.append({
                "uuid": r.get("uuid", r.element_id),
                "name": r.get("name", ""),
                "fact": r.get("fact", ""),
                "source_node_uuid": r.get("source_node_uuid", node_uuid),
                "target_node_uuid": r.get("target_node_uuid", ""),
            })
        return edges

    def search(self, graph_id: str, query: str, limit: int = 10, scope: str = "edges") -> Dict[str, Any]:
        max_retries = 3
        delay = 2.0
        last_exc = None
        for attempt in range(max_retries):
            try:
                results = _run_async(
                    self._client.search(query=query, group_ids=[graph_id], num_results=limit)
                )
                edges = [
                    {
                        "uuid": getattr(r, "uuid", ""),
                        "name": getattr(r, "name", ""),
                        "fact": getattr(r, "fact", ""),
                        "source_node_uuid": getattr(r, "source_node_uuid", ""),
                        "target_node_uuid": getattr(r, "target_node_uuid", ""),
                    }
                    for r in (results or [])
                ]
                return {"edges": edges, "nodes": []}
            except Exception as e:
                last_exc = e
                logger.debug(
                    f"Graphiti search attempt {attempt + 1}/{max_retries} failed: "
                    f"{type(e).__name__}: {e}"
                )
                if attempt < max_retries - 1:
                    import time as _time
                    _time.sleep(delay)
                    delay *= 2
                    # Reconnect in case the Neo4j TCP connection dropped
                    try:
                        self._client = self._build_client()
                    except Exception as rebuild_exc:
                        logger.warning(f"Graphiti client rebuild failed: {rebuild_exc}")
        import traceback as _tb
        logger.error(
            f"Graphiti search failed after {max_retries} attempts: "
            f"{type(last_exc).__name__}: {last_exc}\n{_tb.format_exc()}"
        )
        raise last_exc

    def add_text(self, graph_id: str, data: str) -> None:
        from graphiti_core.nodes import EpisodeType
        from datetime import datetime, timezone
        ep_id = str(uuid_mod.uuid4())
        _run_async(
            self._client.add_episode(
                name=ep_id,
                episode_body=data,
                source_description="MiroFish document chunk",
                reference_time=datetime.now(timezone.utc),
                source=EpisodeType.text,
                group_id=graph_id,
                entity_types=self._entity_types or None,
                edge_types=self._edge_types or None,
                custom_extraction_instructions=self._build_extraction_instructions(),
            )
        )

    async def _execute_neo4j_query(self, query: str, parameters: dict = None):
        """Execute a raw Cypher query against Neo4j via the sync driver in the shared event loop."""
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: self._client.driver.execute_query(query, **({"parameters_": parameters} if parameters else {}))
        )
        return result

    async def clone_graph(self, src_group_id: str, dst_group_id: str) -> None:
        """Clone all nodes and relationships from src_group_id to dst_group_id."""
        clone_nodes_query = """
            MATCH (n) WHERE n.group_id = $src
            WITH n, properties(n) AS props
            CREATE (m) SET m = props SET m.group_id = $dst
        """
        await self._execute_neo4j_query(clone_nodes_query, {"src": src_group_id, "dst": dst_group_id})

        clone_rels_query = """
            MATCH (n)-[r]->(m)
            WHERE n.group_id = $src AND m.group_id = $src
            MATCH (n2 {uuid: n.uuid, group_id: $dst})
            MATCH (m2 {uuid: m.uuid, group_id: $dst})
            CALL apoc.create.relationship(n2, type(r), properties(r), m2) YIELD rel
            SET rel.group_id = $dst
            RETURN rel
        """
        await self._execute_neo4j_query(clone_rels_query, {"src": src_group_id, "dst": dst_group_id})

    async def delete_graph_async(self, group_id: str) -> None:
        """Delete all nodes and relationships for a given group_id (async version)."""
        delete_query = "MATCH (n) WHERE n.group_id = $gid DETACH DELETE n"
        await self._execute_neo4j_query(delete_query, {"gid": group_id})

    def delete_graph(self, graph_id: str) -> None:
        _run_async(
            self._client.driver.execute_query(
                "MATCH (n {group_id: $gid}) DETACH DELETE n",
                params={"gid": graph_id},
            )
        )
