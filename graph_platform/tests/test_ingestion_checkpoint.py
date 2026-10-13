from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_committed_episode_is_not_extracted_again():
    from research_graph.engine import GraphEngine
    engine = GraphEngine(None)
    engine.graphiti = SimpleNamespace(driver=SimpleNamespace(
        execute_query=AsyncMock(return_value=([{'completed': True}], None, None))),
        add_episode=AsyncMock())
    await engine.ingest({'uuid': 'episode-1', 'graph_id': 'g1'}, {})
    engine.graphiti.add_episode.assert_not_called()
    assert engine.graphiti.driver.execute_query.call_args.kwargs['group_id'] == 'g1'


@pytest.mark.asyncio
async def test_checkpoint_and_graph_writes_share_the_same_transaction(monkeypatch):
    from research_graph import checkpoint
    events = []
    tx = SimpleNamespace(run=AsyncMock(side_effect=lambda *a, **k: events.append('checkpoint')))
    async def save(tx_arg, *args, **kwargs):
        assert tx_arg is tx
        events.append('graph')
    monkeypatch.setattr(checkpoint, 'add_nodes_and_edges_bulk_tx', save)
    episode = SimpleNamespace(uuid='ep1', group_id='g1', entity_edges=[])
    await checkpoint.save_with_checkpoint(tx, [episode], [], [], [], None, driver=None)
    assert events == ['graph', 'checkpoint']
    assert tx.run.call_args.kwargs['episodes'] == [{'uuid': 'ep1', 'group_id': 'g1'}]


@pytest.mark.asyncio
async def test_failed_graph_write_cannot_publish_a_completion_receipt(monkeypatch):
    from research_graph import checkpoint
    tx = SimpleNamespace(run=AsyncMock())
    monkeypatch.setattr(checkpoint, 'add_nodes_and_edges_bulk_tx', AsyncMock(side_effect=RuntimeError('Failed transaction')))
    with pytest.raises(RuntimeError, match='Failed transaction'):
        await checkpoint.save_with_checkpoint(tx, [], [], [], [], None, driver=None)
    tx.run.assert_not_called()
