from fastapi.testclient import TestClient
from research_graph.store import GraphStore


class Engine:
    graphiti = True
    async def initialize(self): pass
    async def health(self): pass
    async def close(self): pass
    async def ingest(self, job, ontology): pass
    async def delete(self, graph_id):
        self.store.reserve_delete(graph_id)
        self.store.delete_graph(graph_id)


def test_api_requires_token_and_persists_graph_lifecycle(tmp_path):
    from research_graph.server import create_app
    store = GraphStore(tmp_path / 'api.db')
    engine = Engine()
    engine.store = store
    token = 'local-test-token-at-least-20-characters'
    with TestClient(create_app(store, engine, token)) as client:
        assert client.get('/health').json()['status'] == 'ready'
        body = {'operation': 'graph.create', 'params': {'graph_id': 'g1', 'name': 'Research'}}
        assert client.post('/v1/rpc', json=body).status_code == 401
        headers = {'X-Research-Token': token}
        assert client.post('/v1/rpc', json=body, headers=headers).status_code == 200
        response = client.post('/v1/rpc', json={'operation': 'graph.get', 'params': {'graph_id': 'g1'}}, headers=headers)
        assert response.json()['name'] == 'Research'
        assert client.post('/v1/rpc', json={'operation': '__dict__', 'params': {}}, headers=headers).status_code == 400
        assert client.post('/v1/rpc', json={'operation': 'graph.delete', 'params': {'graph_id': 'g1'}}, headers=headers).status_code == 200
        assert client.post('/v1/rpc', json={'operation': 'graph.get', 'params': {'graph_id': 'g1'}}, headers=headers).status_code == 404


def test_health_detects_database_failure_after_startup(tmp_path):
    from research_graph.server import create_app
    engine = Engine()
    async def failed_health():
        raise ConnectionError('Database offline')
    engine.health = failed_health
    with TestClient(create_app(GraphStore(tmp_path / 'jobs.db'), engine, 'local-test-token-at-least-20-characters')) as client:
        assert client.get('/health').json()['status'] == 'unavailable'
