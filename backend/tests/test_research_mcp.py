"""Agent-facing contracts: exercise real MCP sessions and the Flask upload route."""
import json
from contextlib import asynccontextmanager

import httpx
import pytest
from flask import Flask
from mcp.shared.memory import create_connected_server_and_client_session

from research_mcp.client import BackendClient
from research_mcp.server import create_server


@asynccontextmanager
async def session_for(handler):
    client = BackendClient(transport=httpx.MockTransport(handler))
    async with create_connected_server_and_client_session(create_server(client)) as session:
        yield session


@pytest.mark.asyncio
async def test_discovery_includes_workflow_and_typed_tools():
    async with session_for(lambda r: httpx.Response(200, json={'success': True})) as session:
        tools = {tool.name: tool for tool in (await session.list_tools()).tools}
        assert {'create_project', 'build_graph', 'prepare_simulation', 'start_simulation',
                'generate_report', 'get_report', 'search_graph', 'get_status'} <= tools.keys()
        assert tools['get_status'].annotations.readOnlyHint is True
        assert tools['create_project'].annotations.readOnlyHint is False
        schema = tools['create_project'].inputSchema
        assert {'documents', 'simulation_requirement', 'upload_id'} <= set(schema['required'])
        assert 'enum' in tools['start_simulation'].inputSchema['properties']['platform']
        resource = await session.read_resource('research://workflow')
        assert 'get_preparation_status' in resource.contents[0].text
        assert 'allowance' in resource.contents[0].text


@pytest.mark.asyncio
async def test_text_upload_retries_reuse_real_backend_project(monkeypatch, tmp_path):
    from app.api import graph
    from app.models.project import ProjectManager

    monkeypatch.setattr(ProjectManager, 'PROJECTS_DIR', str(tmp_path / 'projects'))
    calls = []

    def generate(self, **kwargs):
        calls.append(kwargs)
        return {'entity_types': [], 'edge_types': []}

    monkeypatch.setattr(graph.OntologyGenerator, 'generate', generate)
    app = Flask(__name__)
    app.register_blueprint(graph.graph_bp, url_prefix='/api/graph')

    def backend(request):
        with app.test_client() as flask_client:
            response = flask_client.open(request.url.raw_path.decode(), method=request.method,
                                         headers=dict(request.headers), data=request.read())
        return httpx.Response(response.status_code, content=response.data,
                              headers=dict(response.headers))

    arguments = {'documents': [{'filename': 'evidence.md', 'content': 'Alice supports a small café pilot.'},
                               {'filename': 'notes.txt', 'content': 'Bob asks for independent review.'}],
                 'simulation_requirement': 'Explore their agreement.', 'upload_id': 'research-test-1',
                 'project_name': 'Agent research'}
    async with session_for(backend) as session:
        first = await session.call_tool('create_project', arguments)
        second = await session.call_tool('create_project', arguments)
        assert not first.isError, first.content
        assert not second.isError, second.content
        pid = first.structuredContent['data']['project_id']
        assert second.structuredContent['data']['project_id'] == pid
        assert second.structuredContent['data']['reused'] is True
        project = await session.call_tool('get_project', {'project_id': pid})
        assert project.structuredContent['data']['name'] == 'Agent research'
    assert len(ProjectManager.list_projects()) == 1
    assert len(calls) == 1
    text = ProjectManager.get_extracted_text(pid)
    assert 'café pilot' in text and 'independent review' in text


@pytest.mark.asyncio
@pytest.mark.parametrize(('name', 'arguments', 'method', 'path', 'payload'), [
    ('build_graph', {'project_id': 'proj_1'}, 'POST', '/api/graph/build', {'project_id': 'proj_1'}),
    ('prepare_simulation', {'simulation_id': 'sim_1'}, 'POST', '/api/simulation/prepare',
     {'simulation_id': 'sim_1', 'parallel_profile_count': 1}),
    ('get_preparation_status', {'simulation_id': 'sim_1', 'task_id': 'task_1'}, 'POST',
     '/api/simulation/prepare/status', {'simulation_id': 'sim_1', 'task_id': 'task_1'}),
    ('start_simulation', {'simulation_id': 'sim_1', 'platform': 'reddit', 'max_rounds': 2}, 'POST',
     '/api/simulation/start', {'simulation_id': 'sim_1', 'platform': 'reddit', 'max_rounds': 2,
                               'simulation_effort': 'full', 'enable_graph_memory_update': True, 'force': False}),
    ('stop_simulation', {'simulation_id': 'sim_1'}, 'POST', '/api/simulation/stop',
     {'simulation_id': 'sim_1', 'wait': False}),
    ('generate_report', {'simulation_id': 'sim_1'}, 'POST', '/api/report/generate',
     {'simulation_id': 'sim_1', 'resume': True}),
    ('get_report_status', {'task_id': 'task_1'}, 'POST', '/api/report/generate/status', {'task_id': 'task_1'}),
    ('search_graph', {'graph_id': 'graph_1', 'query': 'pilot'}, 'POST', '/api/report/tools/search',
     {'graph_id': 'graph_1', 'query': 'pilot', 'limit': 10}),
    ('get_simulation_status', {'simulation_id': 'sim_1'}, 'GET', '/api/simulation/sim_1/run-status', None),
])
async def test_workflow_preserves_backend_contract(name, arguments, method, path, payload):
    received = []

    def backend(request):
        received.append((request.method, request.url.path, json.loads(request.content) if request.content else None))
        assert request.headers['Accept-Language'] == 'en'
        return httpx.Response(200, json={'success': True, 'pending': True,
                                         'data': {'task_id': 'task_1', 'status': 'processing'}})

    async with session_for(backend) as session:
        result = await session.call_tool(name, arguments)
        assert not result.isError, result.content
        assert result.structuredContent['data']['task_id'] == 'task_1'
        assert result.structuredContent['pending'] is True
    assert received == [(method, path, payload)]


@pytest.mark.asyncio
@pytest.mark.parametrize(('name', 'arguments'), [
    ('get_project', {'project_id': '../secrets'}),
    ('get_report', {'report_id': 'report_1?format=pdf'}),
    ('get_task', {'task_id': 'task%2F1'}),
    ('get_simulation', {'simulation_id': '..'}),
    ('start_simulation', {'simulation_id': 'sim_1', 'max_rounds': 0}),
    ('start_simulation', {'simulation_id': 'sim_1', 'platform': 'unknown'}),
    ('get_actions', {'simulation_id': 'sim_1', 'limit': -1}),
    ('create_simulation', {'project_id': 'proj_1', 'enable_twitter': False, 'enable_reddit': False}),
    ('create_project', {'documents': [], 'simulation_requirement': 'Research', 'upload_id': 'u1'}),
    ('create_project', {'documents': [{'filename': '../secret.txt', 'content': 'text'}],
                        'simulation_requirement': 'Research', 'upload_id': 'u1'}),
    ('create_project', {'documents': [{'filename': 'test.pdf', 'content': 'not a PDF'}],
                        'simulation_requirement': 'Research', 'upload_id': 'u1'}),
    ('create_project', {'documents': [{'filename': 'test.txt', 'content': '   '}],
                        'simulation_requirement': 'Research', 'upload_id': 'u1'}),
])
async def test_bad_input_fails_before_backend_call(name, arguments):
    requests = []

    def backend(request):
        requests.append(request)
        return httpx.Response(200, json={'success': True})

    async with session_for(backend) as session:
        result = await session.call_tool(name, arguments)
        assert result.isError
    assert requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [200, 409, 500])
async def test_api_errors_are_mcp_errors_and_keep_recovery_metadata(status):
    async with session_for(lambda r: httpx.Response(status, json={
        'success': False, 'error': 'Resume saved ontology', 'data': {'project_id': 'proj_saved'},
        'resumable': True, 'traceback': 'internal stack',
    })) as session:
        result = await session.call_tool('resume_ontology', {'project_id': 'proj_saved'})
        assert result.isError
        message = result.content[0].text
        assert 'proj_saved' in message and 'resumable' in message
        assert 'internal stack' not in message


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['connect', 'timeout', 'html', 'redirect'])
async def test_transport_failures_are_actionable_and_never_retried(failure):
    calls = []

    def backend(request):
        calls.append(request)
        if failure == 'connect':
            raise httpx.ConnectError('refused', request=request)
        if failure == 'timeout':
            raise httpx.ReadTimeout('late', request=request)
        if failure == 'redirect':
            return httpx.Response(302, headers={'Location': 'https://example.org'})
        return httpx.Response(502, text='<html>bad gateway</html>')

    async with session_for(backend) as session:
        result = await session.call_tool('get_status', {})
        assert result.isError
        message = result.content[0].text.lower()
        assert {'connect': 'npm run dev', 'timeout': 'may still be running',
                'html': 'non-json', 'redirect': 'redirect'}[failure] in message
    assert len(calls) == 1
