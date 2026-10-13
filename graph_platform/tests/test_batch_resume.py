import pytest

from research_graph.store import GraphStore


def failed_batch(tmp_path):
    store = GraphStore(tmp_path / 'journal.db')
    store.create_graph('g1', 'Research', '')
    bid = store.create_batch({'graph_id': 'g1', 'mirofish_operation_id': 'op1', 'chunk_count': 3})['batch_id']
    items = store.add_items(bid, [{'graph_id': 'g1', 'data': str(i)} for i in range(3)])
    store.process_batch(bid)
    store.finish(store.claim_next()['uuid'])
    store.finish(store.claim_next()['uuid'], error='Quota exceeded')
    return store, bid, items


def test_resume_preserves_succeeded_items_and_requeues_only_unfinished(tmp_path):
    store, bid, items = failed_batch(tmp_path)
    store.resume_batch(bid, operation_id='op1')
    assert store.graph('g1')['state'] == 'active'
    assert store.episode(items[0]['uuid'])['status'] == 'succeeded'
    assert store.batch(bid)['progress']['succeeded_items'] == 1
    assert store.claim_next()['uuid'] == items[1]['uuid']
    store.finish(items[1]['uuid'])
    assert store.claim_next()['uuid'] == items[2]['uuid']
    store.finish(items[2]['uuid'])
    assert store.batch(bid)['status'] == 'succeeded'
    store.resume_batch(bid, operation_id='op1')
    assert store.claim_next() is None


def test_resume_rejects_changed_identity_and_deletion(tmp_path):
    store, bid, items = failed_batch(tmp_path)
    with pytest.raises(ValueError, match='operation'):
        store.resume_batch(bid, operation_id='wrong')
    assert store.graph('g1')['state'] == 'failed'
    store.reserve_delete('g1')
    with pytest.raises(RuntimeError, match='delet'):
        store.resume_batch(bid, operation_id='op1')
    assert store.episode(items[1]['uuid'])['status'] == 'failed'


def test_resume_draft_requires_complete_validated_chunk_count(tmp_path):
    store = GraphStore(tmp_path / 'journal.db')
    store.create_graph('g1', 'Research', '')
    bid = store.create_batch({'graph_id': 'g1', 'mirofish_operation_id': 'op1', 'chunk_count': 2})['batch_id']
    store.add_items(bid, [{'graph_id': 'g1', 'data': 'One'}])
    with pytest.raises(ValueError, match='count'):
        store.resume_batch(bid, operation_id='op1')
    assert store.claim_next() is None


def test_partial_draft_resume_atomically_appends_only_missing_chunks(tmp_path):
    import hashlib
    store = GraphStore(tmp_path / 'journal.db')
    store.create_graph('g1', 'Research', '')
    chunks = ['One', 'Two']
    digest = hashlib.sha256('\0'.join(chunks).encode()).hexdigest()
    operation = hashlib.sha256(f'g1:{digest}'.encode()).hexdigest()
    bid = store.create_batch({'graph_id': 'g1', 'mirofish_operation_id': operation, 'chunk_count': 2})['batch_id']
    first = store.add_items(bid, [{'graph_id': 'g1', 'data': 'One'}])[0]
    store.resume_batch(bid, operation_id=operation, chunks=chunks)
    assert len(store.episodes(batch_id=bid)) == 2
    assert store.claim_next()['uuid'] == first['uuid']
    store.finish(first['uuid'])
    second = store.claim_next()
    store.finish(second['uuid'])
    store.resume_batch(bid, operation_id=operation, chunks=chunks)
    assert store.batch(bid)['status'] == 'succeeded'
    assert len(store.episodes(batch_id=bid)) == 2
    assert store.claim_next() is None


@pytest.mark.asyncio
async def test_worker_resume_retries_failed_episode_and_keeps_completed_work(tmp_path):
    import asyncio
    from research_graph.runtime import GraphRuntime
    store, bid, items = failed_batch(tmp_path)
    seen = []
    class Engine:
        async def ingest(self, job, ontology):
            seen.append(job['uuid'])
        async def close(self):
            pass
    runtime = GraphRuntime(store, Engine())
    await runtime.start()
    try:
        store.resume_batch(bid, operation_id='op1')
        for _ in range(100):
            if store.batch(bid)['status'] == 'succeeded':
                break
            await asyncio.sleep(0.01)
        assert store.batch(bid)['status'] == 'succeeded'
        assert seen == [items[1]['uuid'], items[2]['uuid']]
    finally:
        await runtime.close()
