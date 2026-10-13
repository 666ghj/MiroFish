import pytest


@pytest.fixture
def store(tmp_path):
    from research_graph.store import GraphStore
    return GraphStore(tmp_path / 'journal.sqlite3')


def batch(store, graph='g1', operation='op1'):
    store.create_graph(graph, 'Research', '')
    b = store.create_batch({'graph_id': graph, 'mirofish_operation_id': operation})
    return b['batch_id']


def test_batch_jobs_are_durable_ordered_and_not_complete_before_extraction(store):
    bid = batch(store)
    items = store.add_items(bid, [{'graph_id': 'g1', 'data': 'Alice founded Acme.'},
                                  {'graph_id': 'g1', 'data': 'Bob joined Acme.'}])
    assert store.claim_next() is None
    store.process_batch(bid)
    job = store.claim_next()
    assert job['uuid'] == items[0]['episode_uuid']
    assert store.episode(job['uuid'])['processed'] is False
    store.finish(job['uuid'])
    assert store.batch(bid)['progress']['succeeded_items'] == 1
    assert store.claim_next()['uuid'] == items[1]['episode_uuid']
    store.finish(items[1]['episode_uuid'])
    assert store.batch(bid)['status'] == 'succeeded'
    from research_graph.store import GraphStore
    reopened = GraphStore(store.path)
    assert reopened.episode(job['uuid'])['processed'] is True


def test_failure_stops_later_items_and_exposes_error(store):
    bid = batch(store)
    items = store.add_items(bid, [{'graph_id': 'g1', 'data': 'One'}, {'graph_id': 'g1', 'data': 'Two'}])
    store.process_batch(bid)
    job = store.claim_next()
    store.finish(job['uuid'], error='Codex quota reached')
    assert store.batch(bid)['status'] == 'failed'
    assert store.episode(job['uuid'])['error'] == 'Codex quota reached'
    assert store.episode(items[1]['episode_uuid'])['status'] == 'canceled'
    assert store.claim_next() is None


def test_restart_never_replays_a_partially_written_episode(store):
    bid = batch(store)
    store.add_items(bid, [{'graph_id': 'g1', 'data': 'One'}])
    store.process_batch(bid)
    job = store.claim_next()
    store.recover_interrupted()
    assert store.episode(job['uuid'])['processed'] is False
    assert store.batch(bid)['status'] == 'failed'
    assert store.claim_next() is None


def test_operation_identity_and_graph_isolation(store):
    bid = batch(store)
    assert store.create_batch({'graph_id': 'g1', 'mirofish_operation_id': 'op1'})['batch_id'] == bid
    store.create_graph('g2', 'Other', '')
    with pytest.raises(ValueError, match='graph'):
        store.add_items(bid, [{'graph_id': 'g2', 'data': 'Wrong graph'}])
    store.reserve_delete('g1')
    store.delete_graph('g1')
    assert store.graph('g2')['name'] == 'Other'
    with pytest.raises(LookupError):
        store.graph('g1')


def test_delete_refuses_active_jobs_and_blocks_new_writes_when_reserved(store):
    batch(store)
    job = store.add_episode('g1', 'text', 'One')
    with pytest.raises(RuntimeError, match='active'):
        store.reserve_delete('g1')
    store.claim_next()
    store.finish(job['uuid'])
    store.reserve_delete('g1')
    with pytest.raises(RuntimeError, match='delet'):
        store.add_episode('g1', 'text', 'Two')


def test_claim_is_atomic_across_connections(store):
    from concurrent.futures import ThreadPoolExecutor
    batch(store)
    store.add_episode('g1', 'text', 'One')
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: store.claim_next(), range(4)))
    assert sum(job is not None for job in results) == 1


def test_duplicate_graph_creation_does_not_overwrite_ontology(store):
    batch(store)
    store.set_ontology('g1', {'entities': {'Person': {'description': 'A person'}}})
    store.create_graph('g1', 'Research', '')
    assert 'Person' in store.graph('g1')['ontology']['entities']
