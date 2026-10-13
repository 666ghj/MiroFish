"""Graphiti and Neo4j operations, with explicit model clients and graph scoping."""

import asyncio
from copy import deepcopy
from datetime import datetime
import os

from .models import create_graph_client, LocalEmbedder, LocalReranker, EMBED_MODEL, EMBED_REVISION
from .checkpoint import CheckpointGraphiti
from graphiti_core.nodes import EntityNode, EpisodicNode, EpisodeType
from graphiti_core.edges import EntityEdge
from graphiti_core.errors import NodeNotFoundError
from graphiti_core.search.search_config_recipes import COMBINED_HYBRID_SEARCH_CROSS_ENCODER, COMBINED_HYBRID_SEARCH_RRF
from graphiti_core.search.search_filters import SearchFilters
from pydantic import create_model, Field


def compile_ontology(ontology):
    def compile_types(definitions):
        result = {}
        for name, definition in definitions.items():
            fields = {key: (str | None, Field(default=None, description=description))
                      for key, description in definition.get('attributes', {}).items()}
            result[name] = create_model(name, __doc__=definition.get('description', name), **fields)
        return result
    entities = compile_types(ontology.get('entities', {}))
    edges = compile_types(ontology.get('edges', {}))
    mapping = {}
    for name, definition in ontology.get('edges', {}).items():
        for pair in definition.get('source_targets', []):
            mapping.setdefault((pair['source'], pair['target']), []).append(name)
    return entities, edges, mapping


def normalized(model):
    value = model.model_dump(mode='json', exclude={'name_embedding', 'fact_embedding', 'embedding'})
    value['uuid_'] = value['uuid']
    value.setdefault('attributes', {})
    return value


class GraphEngine:
    def __init__(self, store):
        self.store = store
        self.graphiti = None
        self.llm = create_graph_client()
        self.lock = asyncio.Lock()

    async def initialize(self):
        if self.graphiti is not None:
            return
        async with self.lock:
            if self.graphiti is not None:
                return
            password = os.environ.get('LOCAL_NEO4J_PASSWORD')
            if not password:
                raise ValueError('LOCAL_NEO4J_PASSWORD is required')
            self.store.check_setting('embedding', f'{EMBED_MODEL}@{EMBED_REVISION}:384')
            embedder = await asyncio.to_thread(LocalEmbedder)
            reranker = await asyncio.to_thread(LocalReranker)
            graphiti = CheckpointGraphiti(os.environ.get('LOCAL_NEO4J_URI', 'bolt://127.0.0.1:7687'),
                                'neo4j', password, llm_client=self.llm,
                                embedder=embedder, cross_encoder=reranker, max_coroutines=1)
            try:
                await graphiti.driver.health_check()
                # The pinned Neo4j driver schedules index creation in its constructor.
                # Await it rather than racing a second creation pass.
                if graphiti.driver._init_task is not None:
                    await graphiti.driver._init_task
                else:
                    await graphiti.build_indices_and_constraints()
            except BaseException:
                await graphiti.close()
                raise
            self.graphiti = graphiti

    async def health(self):
        if self.graphiti is None:
            raise RuntimeError("Graph engine is not initialized")
        await self.graphiti.driver.health_check()

    async def ingest(self, job, ontology):
        await self.initialize()
        records, _, _ = await self.graphiti.driver.execute_query(
            'MATCH (e:Episodic {uuid: $uuid, group_id: $group_id}) '
            'RETURN coalesce(e.research_ingestion_complete, false) '
            'OR size(coalesce(e.entity_edges, [])) > 0 '
            'OR EXISTS { MATCH (e)-[:MENTIONS]->(:Entity) } AS completed',
            uuid=job['uuid'], group_id=job['graph_id'], routing_='r')
        # Legacy ingestions without a receipt can also be reconciled when their
        # final atomic write left mentions/edges. Legacy empty results are safe
        # to extract again because they contributed no graph entities or edges.
        if records and records[0]['completed']:
            return
        entities, edges, mapping = compile_ontology(ontology)
        kind = job.get('data_type') or job.get('type', 'text')
        source = {'json': EpisodeType.json, 'message': EpisodeType.message}.get(kind, EpisodeType.text)
        timestamp = datetime.fromisoformat(job['created_at'].replace('Z', '+00:00'))
        if timestamp.tzinfo is None:
            raise ValueError('Episode reference time must include a timezone')
        previous = await self.graphiti.retrieve_episodes(
            timestamp, last_n=3, group_ids=[job['graph_id']], source=source)
        # Graphiti 0.30.2 interprets a supplied UUID as an existing episode.
        # Persist the source first; the journal still reports running until extraction ends.
        episode = EpisodicNode(uuid=job['uuid'], name=job['uuid'], group_id=job['graph_id'],
                              labels=[], source=source, content=job['data'],
                              source_description=job.get('source_description') or 'My Own Researcher document',
                              valid_at=timestamp)
        await episode.save(self.graphiti.driver)
        return await self.graphiti.add_episode(
            uuid=job['uuid'], name=job['uuid'], group_id=job['graph_id'],
            episode_body=job['data'], source=source,
            source_description=job.get('source_description') or 'My Own Researcher document',
            reference_time=timestamp, entity_types=entities or None, edge_types=edges or None,
            edge_type_map=mapping or None, update_communities=False,
            previous_episode_uuids=[episode.uuid for episode in previous if episode.uuid != job['uuid']],
            custom_extraction_instructions='Write extracted summaries and facts in English. Preserve proper names.',
        )

    async def page(self, graph_id, kind, limit=100, cursor=None):
        self.store.graph(graph_id)
        if kind not in {'nodes', 'edges'} or not 1 <= limit <= 100:
            raise ValueError('Invalid graph page request')
        await self.initialize()
        model = EntityNode if kind == 'nodes' else EntityEdge
        rows = await model.get_by_group_ids(self.graphiti.driver, [graph_id], limit=limit + 1, uuid_cursor=cursor)
        return {'data': [normalized(row) for row in rows[:limit]],
                'next_cursor': rows[limit - 1].uuid if len(rows) > limit else None}

    async def node(self, node_id):
        await self.initialize()
        try:
            node = await EntityNode.get_by_uuid(self.graphiti.driver, node_id)
        except NodeNotFoundError:
            raise LookupError('Local node not found') from None
        self.store.graph(node.group_id)
        return normalized(node)

    async def node_edges(self, node_id):
        node = await self.node(node_id)
        edges = await EntityEdge.get_by_node_uuid(self.graphiti.driver, node_id)
        return [normalized(edge) for edge in edges if edge.group_id == node['group_id']]

    async def search(self, graph_id, query, scope='edges', limit=10, reranker='cross_encoder', search_filters=None):
        self.store.graph(graph_id)
        if scope not in {'nodes', 'edges'} or reranker not in {'cross_encoder', 'rrf'}:
            raise ValueError('Local search supports nodes/edges with cross_encoder or rrf ranking')
        if not isinstance(query, str) or not query.strip() or not 1 <= limit <= 50:
            raise ValueError('Search requires a query and a limit between 1 and 50')
        await self.initialize()
        config = deepcopy(COMBINED_HYBRID_SEARCH_CROSS_ENCODER if reranker == 'cross_encoder' else COMBINED_HYBRID_SEARCH_RRF)
        config.limit = limit
        config.community_config = None
        config.episode_config = None
        if scope == 'edges':
            config.node_config = None
        else:
            config.edge_config = None
        filters = SearchFilters(**(search_filters or {}))
        result = await self.graphiti.search_(query, config=config, group_ids=[graph_id], search_filter=filters)
        return {'nodes': [normalized(node) for node in result.nodes],
                'edges': [normalized(edge) for edge in result.edges]}

    async def delete(self, graph_id):
        self.store.reserve_delete(graph_id)
        await self.initialize()
        # Group filter is mandatory. Never call Graphiti clear_data() here.
        await self.graphiti.driver.execute_query(
            'MATCH (n {group_id: $group_id}) DETACH DELETE n', group_id=graph_id)
        self.store.delete_graph(graph_id)

    async def close(self):
        if self.graphiti is not None:
            await self.graphiti.close()
            self.graphiti = None
