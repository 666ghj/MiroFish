import pytest
from research_graph.store import GraphStore


def broken_simulation(tmp_path):
    store = GraphStore(tmp_path / 'journal.db')
    store.create_graph('g1', 'Research', '')
    items = [store.add_episode('g1', 'text', str(i), metadata={
        'source': 'mirofish_simulation', 'simulation_id': 'sim1'}) for i in range(3)]
    store.finish(store.claim_next()['uuid'])
    store.finish(store.claim_next()['uuid'], error='Codex request timed out')
    return store, items


def test_resume_simulation_requeues_only_its_unfinished_episodes(tmp_path):
    store, items = broken_simulation(tmp_path)
    result = store.resume_simulation('g1', 'sim1')
    assert result['episode_uuids'] == [items[1]['uuid'], items[2]['uuid']]
    assert store.episode(items[0]['uuid'])['status'] == 'succeeded'
    assert store.claim_next()['uuid'] == items[1]['uuid']
    # An overlapping retry attaches to the running request rather than requeues it.
    assert store.resume_simulation('g1', 'sim1')['episode_uuids'] == result['episode_uuids']
    store.finish(items[1]['uuid'])
    assert store.claim_next()['uuid'] == items[2]['uuid']
    store.finish(items[2]['uuid'])
    assert store.resume_simulation('g1', 'sim1')['episode_uuids'] == []
    assert len(store.episodes(graph_id='g1')) == 3


def test_resume_simulation_cannot_unlock_other_operations_or_deletion(tmp_path):
    store, items = broken_simulation(tmp_path)
    with pytest.raises((ValueError, RuntimeError), match='simulation|ingestion'):
        store.resume_simulation('g1', 'other')
    assert store.graph('g1')['state'] == 'failed'
    store.reserve_delete('g1')
    with pytest.raises(RuntimeError, match='delet'):
        store.resume_simulation('g1', 'sim1')


def test_resume_requires_entire_failed_scope_to_belong_to_simulation(tmp_path):
    store, items = broken_simulation(tmp_path)
    with store.connection(write=True) as db:
        db.execute("UPDATE episodes SET payload=json_set(payload, '$.metadata.simulation_id', 'other') WHERE id=?", (items[2]['uuid'],))
    with pytest.raises(RuntimeError, match='other'):
        store.resume_simulation('g1', 'sim1')
    assert store.episode(items[1]['uuid'])['status'] == 'failed'


def test_authenticated_api_exposes_simulation_resume(tmp_path):
    from fastapi.testclient import TestClient
    from research_graph.server import create_app
    store, items = broken_simulation(tmp_path)
    token = 'local-test-token-at-least-20-characters'
    client = TestClient(create_app(store, object(), token))
    request = {'operation': 'simulation.resume', 'params': {'graph_id': 'g1', 'simulation_id': 'sim1'}}
    assert client.post('/v1/rpc', json=request).status_code == 401
    response = client.post('/v1/rpc', json=request, headers={'X-Research-Token': token})
    assert response.status_code == 200
    assert response.json()['episode_uuids'] == [items[1]['uuid'], items[2]['uuid']]
