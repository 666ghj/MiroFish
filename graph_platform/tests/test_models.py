import json

from pydantic import BaseModel
import pytest


class Facts(BaseModel):
    facts: list[str]


@pytest.mark.asyncio
async def test_graphiti_adapter_validates_structured_codex_output(monkeypatch):
    from research_graph import models
    from graphiti_core.prompts.models import Message
    def completion(prompt, schema, cancel_event=None):
        assert 'Alice' in prompt
        return {'json': json.dumps({'facts': ['Alice founded Acme.']})}, {}
    monkeypatch.setattr(models, 'run_codex', completion)
    llm = models.CodexGraphClient()
    result = await llm.generate_response([Message(role='user', content='Alice founded Acme.')], Facts)
    assert result == {'facts': ['Alice founded Acme.']}
    monkeypatch.setattr(models, 'run_codex', lambda *a, **kw: ({'json': '{"facts": 42}'}, {}))
    with pytest.raises(ValueError):
        await llm.generate_response([Message(role='user', content='Alice')], Facts)


def test_ontology_compilation_preserves_types_and_source_target_mapping():
    from research_graph.engine import compile_ontology
    entities, edges, mapping = compile_ontology({
        'entities': {'Person': {'description': 'A person', 'attributes': {'role': 'Job title'}}},
        'edges': {'WORKS_AT': {'description': 'Employment', 'attributes': {},
                              'source_targets': [{'source': 'Person', 'target': 'Entity'}]}}
    })
    assert entities['Person'](role='Engineer').model_dump() == {'role': 'Engineer'}
    assert entities['Person'].__doc__ == 'A person'
    assert mapping == {('Person', 'Entity'): ['WORKS_AT']}
    assert 'WORKS_AT' in edges


@pytest.mark.asyncio
async def test_new_episode_is_saved_before_graphiti_receives_explicit_uuid(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from research_graph.engine import GraphEngine
    from research_graph.store import GraphStore
    from graphiti_core.nodes import EpisodicNode
    store = GraphStore(tmp_path / 'jobs.db')
    store.create_graph('g1', 'one', '')
    job = store.add_episode('g1', 'text', 'Alice founded Acme.')
    saved = {}
    async def save(episode, driver):
        saved[episode.uuid] = episode
    async def retrieve(*args, **kwargs):
        return []
    async def add(**kwargs):
        assert kwargs['uuid'] in saved
        assert kwargs['previous_episode_uuids'] == []
        assert saved[kwargs['uuid']].content == 'Alice founded Acme.'
        return SimpleNamespace(episode=saved[kwargs['uuid']])
    monkeypatch.setattr(EpisodicNode, 'save', save)
    engine = GraphEngine(store)
    from unittest.mock import AsyncMock
    driver = SimpleNamespace(execute_query=AsyncMock(return_value=([], None, None)))
    engine.graphiti = SimpleNamespace(driver=driver, retrieve_episodes=retrieve, add_episode=add)
    result = await engine.ingest(job, {})
    assert result.episode.uuid == job['uuid']


def test_local_reranker_normalizes_logits_for_graphiti_score_threshold():
    import threading
    from types import SimpleNamespace
    from research_graph.models import LocalReranker
    reranker = object.__new__(LocalReranker)
    reranker.lock = threading.Lock()
    reranker.model = SimpleNamespace(predict=lambda *a, **kw: [-8.0, 4.0])
    ranked = reranker._rank('research director', ['Bob', 'Alice'])
    assert [name for name, score in ranked] == ['Alice', 'Bob']
    # Graphiti's default cutoff is zero; raw negative logits discard valid candidates.
    assert all(0 < score < 1 for name, score in ranked)
