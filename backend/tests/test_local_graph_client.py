import json
from types import SimpleNamespace

import httpx
import pytest


def test_graph_pages_preserve_sdk_shape_and_opaque_cursors():
    from app.local_graph.client import LocalGraphClient
    from app.utils.zep_paging import fetch_all_nodes
    def respond(request):
        body = json.loads(request.content)
        assert request.headers['X-Research-Token'] == 'test-token'
        assert body['operation'] == 'graph.page'
        params = body['params']
        assert params['graph_id'] == 'g1'
        if params.get('cursor') is None:
            return httpx.Response(200, json={'data': [{'uuid_': 'n2', 'name': 'Alice', 'attributes': {'role': 'CEO'}}], 'next_cursor': 'n2'})
        assert params['cursor'] == 'n2'
        return httpx.Response(200, json={'data': [{'uuid_': 'n1', 'name': 'Bob'}], 'next_cursor': None})
    client = LocalGraphClient('http://127.0.0.1:5002', 'test-token', transport=httpx.MockTransport(respond))
    nodes = fetch_all_nodes(client, 'g1')
    assert [n.name for n in nodes] == ['Alice', 'Bob']
    assert nodes[0].attributes == {'role': 'CEO'}


def test_batch_metadata_stays_mapping_and_progress_is_accessible():
    from app.local_graph.client import LocalGraphClient
    def respond(request):
        return httpx.Response(200, json={'batches': [{'batch_id': 'b1', 'metadata': {'graph_id': 'g1'},
            'progress': {'succeeded_items': 2}}], 'next_cursor': None})
    client = LocalGraphClient('http://localhost:5002', 'test', transport=httpx.MockTransport(respond))
    page = client.batch.list()
    assert page.batches[0].metadata.get('graph_id') == 'g1'
    assert page.batches[0].progress.succeeded_items == 2


def test_missing_graph_uses_existing_not_found_contract():
    from app.local_graph.client import LocalGraphClient
    from zep_cloud import NotFoundError
    client = LocalGraphClient('http://localhost:5002', 'test', transport=httpx.MockTransport(
        lambda request: httpx.Response(404, json={'error': 'Graph not found'})))
    with pytest.raises(NotFoundError):
        client.graph.get('missing')


def test_local_provider_works_without_zep_key(monkeypatch):
    from app.config import Config
    from app.utils.zep import get_zep_client
    monkeypatch.setattr(Config, 'GRAPH_PROVIDER', 'graphiti', raising=False)
    monkeypatch.setattr(Config, 'ZEP_API_KEY', None)
    monkeypatch.setattr(Config, 'LOCAL_GRAPH_TOKEN', 'test-token', raising=False)
    monkeypatch.delenv('ZEP_API_URL', raising=False)
    from app.services.graph_builder import GraphBuilderService
    from app.services.zep_entity_reader import ZepEntityReader
    from app.services.zep_tools import ZepToolsService
    for service in [GraphBuilderService, ZepEntityReader, ZepToolsService]:
        assert service().client.provider == 'graphiti'
    assert get_zep_client().provider == 'graphiti'
    assert not any('ZEP_API_KEY' in error for error in Config.validate())


def test_project_remembers_provider_and_legacy_projects_remain_cloud(monkeypatch, tmp_path):
    from app.config import Config
    from app.models.project import Project, ProjectManager
    monkeypatch.setattr(Config, 'GRAPH_PROVIDER', 'graphiti')
    monkeypatch.setattr(ProjectManager, 'PROJECTS_DIR', str(tmp_path))
    project = ProjectManager.create_project('Local research')
    assert ProjectManager.get_project(project.project_id).graph_provider == 'graphiti'
    old = project.to_dict()
    del old['graph_provider']
    assert Project.from_dict(old).graph_provider == 'zep'


def test_api_rejects_project_provider_mismatch_before_mutating(monkeypatch, tmp_path):
    from app import create_app
    from app.config import Config
    from app.models.project import ProjectManager
    monkeypatch.setattr(ProjectManager, 'PROJECTS_DIR', str(tmp_path))
    monkeypatch.setattr(Config, 'GRAPH_PROVIDER', 'zep')
    project = ProjectManager.create_project('Cloud research')
    monkeypatch.setattr(Config, 'GRAPH_PROVIDER', 'graphiti')
    client = create_app().test_client()
    response = client.post('/api/graph/build', json={'project_id': project.project_id})
    assert response.status_code == 409
    assert 'provider' in response.json['error'].lower()


def test_ingestion_timeout_follows_current_provider(monkeypatch):
    from app.config import Config
    from app.utils.zep import get_ingestion_wait_timeout, ZEP_INGESTION_WAIT_TIMEOUT_SECONDS
    assert ZEP_INGESTION_WAIT_TIMEOUT_SECONDS == 600
    monkeypatch.setattr(Config, 'GRAPH_PROVIDER', 'zep')
    assert get_ingestion_wait_timeout() == 600
    monkeypatch.setenv('LOCAL_GRAPH_WAIT_SECONDS', '900')
    monkeypatch.setattr(Config, 'GRAPH_PROVIDER', 'graphiti')
    assert get_ingestion_wait_timeout() == 900
