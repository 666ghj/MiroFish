"""Real SDK clients connect to the executable adapter over both supported transports."""
import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
import socket
import subprocess
import sys
import threading

import httpx
import pytest
from flask import Flask
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from werkzeug.serving import make_server

SCRIPT = Path(__file__).resolve().parents[1] / 'mcp_server.py'


@pytest.fixture
def backend_url():
    app = Flask(__name__)

    @app.get('/api/system/status')
    def status():
        return {'success': True, 'data': {'name': 'Transport test backend', 'graph': {'status': 'ready'}}}

    server = make_server('127.0.0.1', 0, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


@asynccontextmanager
async def http_adapter(tmp_path, backend_url):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    url = f'http://127.0.0.1:{port}/mcp'
    with (tmp_path / 'mcp.log').open('w') as log:
        process = subprocess.Popen([sys.executable, str(SCRIPT), '--transport', 'streamable-http',
                                    '--port', str(port), '--backend-url', backend_url],
                                   cwd=tmp_path, stdout=log, stderr=log)
        try:
            async with httpx.AsyncClient(trust_env=False, timeout=1) as client:
                for _ in range(200):
                    assert process.poll() is None, (tmp_path / 'mcp.log').read_text()
                    try:
                        await client.get(url)
                        break
                    except httpx.ConnectError:
                        await asyncio.sleep(0.05)
                else:
                    pytest.fail('MCP HTTP server did not start within 10 seconds')
            yield url
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


async def verify_session(read, write):
    async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=10)) as session:
        info = await session.initialize()
        assert info.serverInfo.name == 'My Own Researcher'
        assert 'get_status' in {tool.name for tool in (await session.list_tools()).tools}
        result = await session.call_tool('get_status', {})
        assert not result.isError, result.content
        assert result.structuredContent['data']['name'] == 'Transport test backend'
        workflow = await session.read_resource('research://workflow')
        assert 'upload_id' in workflow.contents[0].text


@pytest.mark.asyncio
async def test_stdio_launches_from_another_directory_without_stdout_noise(tmp_path, backend_url):
    params = StdioServerParameters(command=sys.executable,
                                   args=[str(SCRIPT), '--backend-url', backend_url], cwd=str(tmp_path))
    async with stdio_client(params) as (read, write):
        await verify_session(read, write)


@pytest.mark.asyncio
async def test_streamable_http_client_and_dns_rebinding_guard(tmp_path, backend_url):
    async with http_adapter(tmp_path, backend_url) as url:
        async with streamable_http_client(url) as (read, write, _):
            await verify_session(read, write)
        async with httpx.AsyncClient(trust_env=False) as client:
            response = await client.post(url, headers={'Host': 'attacker.example',
                                                       'Content-Type': 'application/json'}, json={})
            assert response.status_code == 421
            response = await client.post(url, headers={'Origin': 'https://attacker.example'}, json={})
            assert response.status_code == 403
