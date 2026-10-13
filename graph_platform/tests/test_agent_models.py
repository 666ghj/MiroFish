"""Graph extraction follows the selected CLI and exposes the actual inference route."""
import asyncio
import json
import threading

import pytest
from fastapi.testclient import TestClient
from graphiti_core.prompts.models import Message
from pydantic import BaseModel
from research_agents import ProviderError


class Facts(BaseModel):
    facts: list[str]


@pytest.fixture(autouse=True)
def no_external_inference(monkeypatch):
    from research_graph import models

    def unexpected(*args, **kwargs):
        raise AssertionError('Unexpected Codex inference')

    monkeypatch.setattr(models, 'run_codex', unexpected)


@pytest.mark.asyncio
@pytest.mark.parametrize('backend,override,expected', [
    ('claude-code', None, 'claude-code'),
    ('cursor', 'gemini', 'gemini'),
    ('openai', None, 'codex'),
    ('codex', None, 'codex'),
])
async def test_engine_routes_extraction_to_selected_provider(monkeypatch, backend, override, expected):
    from research_graph import models
    from research_graph.engine import GraphEngine
    monkeypatch.setenv('LLM_PROVIDER', backend)
    if override:
        monkeypatch.setenv('GRAPH_LLM_PROVIDER', override)
    else:
        monkeypatch.delenv('GRAPH_LLM_PROVIDER', raising=False)

    def completion(prompt, schema, cancel_event=None, *, provider='codex'):
        return {'json': json.dumps({'facts': [provider]})}, {}

    monkeypatch.setattr(models, 'run_codex', completion)
    monkeypatch.setattr(models, 'run_agent', completion, raising=False)
    engine = GraphEngine(None)
    result = await engine.llm.generate_response([Message(role='user', content='Extract facts')], Facts)
    assert result == {'facts': [expected]}
    assert engine.llm.calls == 1
    if expected == 'codex':
        assert isinstance(engine.llm, models.CodexGraphClient)


def test_unknown_graph_provider_fails_before_initialization(monkeypatch):
    from research_graph.engine import GraphEngine
    monkeypatch.setenv('GRAPH_LLM_PROVIDER', 'typo-provider')
    with pytest.raises(ProviderError, match='Unknown'):
        GraphEngine(None)


@pytest.mark.asyncio
async def test_agent_extraction_validates_inner_schema_and_propagates_failures(monkeypatch):
    from research_graph import models
    from research_graph.engine import GraphEngine
    monkeypatch.setenv('GRAPH_LLM_PROVIDER', 'claude-code')
    monkeypatch.setattr(models, 'run_agent', lambda *a, **kw: ({'json': '{"facts":42}'}, {}), raising=False)
    llm = GraphEngine(None).llm
    with pytest.raises(ValueError):
        await llm._generate_response([Message(role='user', content='Extract facts')], Facts)

    def failure(*args, **kwargs):
        raise ProviderError('Provider quota reached')

    monkeypatch.setattr(models, 'run_agent', failure)
    with pytest.raises(ProviderError, match='quota'):
        await llm._generate_response([Message(role='user', content='Extract facts')], Facts)


@pytest.mark.asyncio
async def test_canceling_graph_extraction_signals_and_joins_agent_transport(monkeypatch):
    from research_graph import models
    from research_graph.engine import GraphEngine
    monkeypatch.setenv('GRAPH_LLM_PROVIDER', 'claude-code')
    started, stopped = threading.Event(), threading.Event()

    def blocked(prompt, schema, cancel_event=None, *, provider=None):
        started.set()
        assert cancel_event.wait(2)
        stopped.set()
        raise ProviderError('Canceled')

    monkeypatch.setattr(models, 'run_agent', blocked, raising=False)
    task = asyncio.create_task(GraphEngine(None).llm._generate_response([Message(role='user', content='Extract')]))
    try:
        assert await asyncio.to_thread(started.wait, 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stopped.is_set()
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_health_reports_engine_provider_even_if_environment_changes(tmp_path, monkeypatch):
    from research_graph.engine import GraphEngine
    from research_graph.server import create_app
    from research_graph.store import GraphStore
    monkeypatch.setenv('GRAPH_LLM_PROVIDER', 'claude-code')
    engine = GraphEngine(GraphStore(tmp_path / 'jobs.db'))

    async def ready():
        pass

    engine.initialize = engine.health = engine.close = ready
    monkeypatch.setenv('GRAPH_LLM_PROVIDER', 'gemini')
    with TestClient(create_app(engine.store, engine, 'test-token-at-least-20-characters')) as client:
        assert client.get('/health').json()['inference'] == 'claude-code'
