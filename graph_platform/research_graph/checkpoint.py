"""Atomic ingestion receipts for the pinned Graphiti 0.30.2 Neo4j writer."""

from graphiti_core import Graphiti
from graphiti_core.utils.bulk_utils import add_nodes_and_edges_bulk_tx
from graphiti_core.utils.maintenance.edge_operations import build_episodic_edges


async def save_with_checkpoint(tx, episodes, episodic_edges, nodes, edges, embedder, *, driver):
    await add_nodes_and_edges_bulk_tx(
        tx, episodes, episodic_edges, nodes, edges, embedder, driver=driver)
    # The receipt commits with all extracted entities/edges, including an empty
    # extraction. A lost commit response must never trigger another extraction.
    await tx.run(
        'UNWIND $episodes AS item '
        'MATCH (e:Episodic {uuid: item.uuid, group_id: item.group_id}) '
        'SET e.research_ingestion_complete = true',
        episodes=[{'uuid': ep.uuid, 'group_id': ep.group_id} for ep in episodes],
    )


class CheckpointGraphiti(Graphiti):
    async def _process_episode_data(
        self, episode, nodes, entity_edges, now, group_id, saga=None,
        saga_previous_episode_uuid=None, node_episode_index_map=None, clients=None,
    ):
        # This application does not use sagas or community updates. Refuse new
        # unsupported modes rather than silently bypassing their persistence.
        if saga is not None or saga_previous_episode_uuid is not None:
            raise ValueError('Checkpoint ingestion does not support sagas')
        clients = clients or self.clients
        episodes = episode if isinstance(episode, list) else [episode]
        episodic_edges = build_episodic_edges(
            nodes, [ep.uuid for ep in episodes], now, node_episode_index_map)
        for ep in episodes:
            ep.entity_edges = [edge.uuid for edge in entity_edges]
            if not self.store_raw_episode_content:
                ep.content = ''
        session = clients.driver.session()
        try:
            await session.execute_write(
                save_with_checkpoint, episodes, episodic_edges, nodes,
                entity_edges, clients.embedder, driver=clients.driver)
        finally:
            await session.close()
        return episodic_edges, episodes[0]
