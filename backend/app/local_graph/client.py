"""Internal Zep-shaped facade for My Own Researcher's local graph API."""

from types import SimpleNamespace
from urllib.parse import urlparse

import httpx
from zep_cloud import NotFoundError


def record(value):
    if isinstance(value, list):
        return [record(item) for item in value]
    if isinstance(value, dict):
        # Metadata and graph attributes must remain dictionaries for SDK consumers.
        return SimpleNamespace(**{key: record(item) if isinstance(item, list) or key == 'progress' else item
                                  for key, item in value.items()})
    return value


class LocalGraphClient:
    provider = 'graphiti'

    def __init__(self, url, token, timeout=60, *, transport=None):
        parsed = urlparse(url)
        if parsed.scheme != 'http' or parsed.hostname not in {'localhost', '127.0.0.1', '::1'} or parsed.username:
            raise ValueError('LOCAL_GRAPH_URL must be an HTTP loopback address')
        if not token:
            raise ValueError('LOCAL_GRAPH_TOKEN is required for the local graph platform')
        self.http = httpx.Client(base_url=url, headers={'X-Research-Token': token},
                                 timeout=timeout, transport=transport, trust_env=False)
        self.graph = Graph(self)
        self.batch = Batch(self)

    def call(self, operation, **params):
        response = self.http.post('/v1/rpc', json={'operation': operation, 'params': params})
        if response.status_code == 404:
            raise NotFoundError(body=response.json())
        if response.is_error:
            message = response.json().get('error') or response.json().get('detail') or 'Local graph request failed'
            raise RuntimeError(str(message))
        return record(response.json())

    def health(self):
        response = self.http.get('/health')
        response.raise_for_status()
        return response.json()


class Graph:
    def __init__(self, client):
        self.client = client
        self.node = Nodes(client)
        self.edge = Edges(client)
        self.episode = Episodes(client)

    def create(self, graph_id, name='', description=''):
        return self.client.call('graph.create', graph_id=graph_id, name=name, description=description)

    def get(self, graph_id):
        return self.client.call('graph.get', graph_id=graph_id)

    def delete(self, graph_id):
        return self.client.call('graph.delete', graph_id=graph_id)

    def add(self, **kwargs):
        return self.client.call('graph.add', **kwargs)

    def resume_simulation(self, *, graph_id, simulation_id):
        return self.client.call('simulation.resume', graph_id=graph_id, simulation_id=simulation_id)

    def search(self, **kwargs):
        return self.client.call('graph.search', **kwargs)

    def set_ontology(self, *, graph_ids, entities, edges=None):
        def definition(model):
            return {'description': model.__doc__ or '',
                    'attributes': {name: field.description or name for name, field in model.model_fields.items()}}
        ontology = {'entities': {name: definition(model) for name, model in entities.items()}, 'edges': {}}
        for name, (model, pairs) in (edges or {}).items():
            ontology['edges'][name] = {**definition(model), 'source_targets':
                                      [{'source': pair.source, 'target': pair.target} for pair in pairs]}
        for graph_id in graph_ids:
            self.client.call('graph.set_ontology', graph_id=graph_id, ontology=ontology)


class Pages:
    kind = None
    def __init__(self, client):
        self.client = client
        self.with_raw_response = self

    def get_by_graph_id(self, graph_id, limit=100, cursor=None):
        result = self.client.call('graph.page', graph_id=graph_id, kind=self.kind, limit=limit, cursor=cursor)
        return SimpleNamespace(data=result.data, headers={'zep-next-cursor': result.next_cursor} if result.next_cursor else {})


class Nodes(Pages):
    kind = 'nodes'
    def get(self, uuid_):
        return self.client.call('node.get', uuid_=uuid_)

    def get_edges(self, node_uuid):
        return self.client.call('node.edges', node_uuid=node_uuid)


class Edges(Pages):
    kind = 'edges'


class Episodes:
    def __init__(self, client):
        self.client = client

    def get(self, uuid_):
        value = self.client.call('episode.get', uuid_=uuid_)
        value.uuid_ = value.uuid
        return value

    def get_by_graph_id(self, graph_id, lastn=50):
        return self.client.call('episode.list', graph_id=graph_id, lastn=lastn)


class Batch:
    def __init__(self, client):
        self.client = client

    def create(self, *, metadata):
        return self.client.call('batch.create', metadata=metadata)

    def add(self, *, batch_id, items):
        return self.client.call('batch.add', batch_id=batch_id,
                                items=[item.model_dump(mode='json', exclude_none=True) if hasattr(item, 'model_dump') else item for item in items])

    def process(self, *, batch_id):
        return self.client.call('batch.process', batch_id=batch_id)

    def resume(self, *, batch_id, operation_id, chunks):
        return self.client.call('batch.resume', batch_id=batch_id, operation_id=operation_id, chunks=chunks)

    def get(self, *, batch_id):
        return self.client.call('batch.get', batch_id=batch_id)

    def list(self, *, limit=100, cursor=None):
        return self.client.call('batch.list', limit=limit, cursor=cursor)

    def list_items(self, *, batch_id, limit=100, cursor=None):
        return self.client.call('batch.list_items', batch_id=batch_id, limit=limit, cursor=cursor)
