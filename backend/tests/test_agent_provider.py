"""CLI integration boundaries, exercised without provider accounts or inference."""
import asyncio
import json
import os
import sys
from pathlib import Path

import pytest


PROVIDERS = ['claude-code', 'antigravity', 'cursor', 'devin', 'factory-droid',
             'gemini', 'copilot', 'grok', 'kimi', 'opencode', 'pi', 'qwen', 'hermes', 'muse']


@pytest.fixture
def fake_agent(tmp_path, monkeypatch):
    state = tmp_path / 'state.json'
    state.write_text(json.dumps({'content': 'Hello', 'tool_calls': []}))
    executable = tmp_path / 'agent with spaces.py'
    executable.write_text('''import json, os, pathlib, sys, time
state = json.loads(pathlib.Path(sys.argv[1]).read_text())
assert 'ZEP_API_KEY' not in os.environ
assert 'LOCAL_GRAPH_TOKEN' not in os.environ
assert 'LLM_API_KEY' not in os.environ
prompt = sys.stdin.read()
if state.get('pid_file'):
    pathlib.Path(state['pid_file']).write_text(str(os.getpid()))
if state.get('sleep'):
    time.sleep(state['sleep'])
if state.get('fail'):
    print('private-secret ' + state['fail'], file=sys.stderr)
    sys.exit(1)
if state.get('echo'):
    state = {'content': prompt, 'tool_calls': []}
print(state.get('raw', json.dumps(state)))
''')
    monkeypatch.setenv('AGENT_COMMAND_JSON', json.dumps([sys.executable, str(executable), str(state)]))
    monkeypatch.setenv('AGENT_LOCK_PATH', str(tmp_path / 'requests.lock'))
    monkeypatch.setenv('LOCAL_GRAPH_TOKEN', 'private-secret')
    monkeypatch.setenv('ZEP_API_KEY', 'private-secret')
    monkeypatch.setenv('LLM_API_KEY', 'private-secret')
    return state


def complete(provider='claude-code', **kwargs):
    from app.utils.agent_provider import AgentClient
    return AgentClient(provider).create(messages=[{'role': 'user', 'content': 'Hello'}], **kwargs)


@pytest.mark.parametrize('provider', PROVIDERS)
def test_every_provider_can_use_explicit_stdin_wrapper(fake_agent, provider):
    response = complete(provider)
    assert response.choices[0].message.content == 'Hello'
    assert provider in response.model


def test_prompt_contains_schema_and_preserves_history(fake_agent):
    fake_agent.write_text(json.dumps({'echo': True}))
    content = complete().choices[0].message.content
    assert 'Hello' in content and 'JSON' in content and 'tool_calls' in content


@pytest.mark.parametrize('raw', ['not json', '[1]', '{"content":"secret"}',
                               '{"content":"","tool_calls":[]}',
                               '{"content":"ok","tool_calls":[]} trailing'])
def test_invalid_output_is_rejected_without_raw_output(fake_agent, raw):
    from research_agents import ProviderError
    fake_agent.write_text(json.dumps({'raw': raw}))
    with pytest.raises(ProviderError) as error:
        complete()
    assert raw not in str(error.value)


def test_invalid_action_cannot_reach_simulation(fake_agent):
    from research_agents import ProviderError
    fake_agent.write_text(json.dumps({'content': '', 'tool_calls': [
        {'name': 'create_post', 'arguments': '{"content":42}'}]}))
    with pytest.raises(ProviderError, match='arguments'):
        complete(tools=[{'type': 'function', 'function': {'name': 'create_post', 'parameters': {
            'type': 'object', 'properties': {'content': {'type': 'string'}}, 'required': ['content']}}}])


def test_provider_error_never_becomes_fallback_content(fake_agent):
    from research_agents import ProviderError
    fake_agent.write_text(json.dumps({'fail': 'quota exceeded'}))
    with pytest.raises(ProviderError, match='limit|quota') as error:
        complete()
    assert 'private-secret' not in str(error.value)


def test_timeout_releases_request_slot(fake_agent, monkeypatch):
    from research_agents import ProviderError
    fake_agent.write_text(json.dumps({'sleep': 5}))
    monkeypatch.setenv('AGENT_TIMEOUT_SECONDS', '0.2')
    with pytest.raises(ProviderError, match='timed out'):
        complete()
    fake_agent.write_text(json.dumps({'content': 'Recovered', 'tool_calls': []}))
    monkeypatch.setenv('AGENT_TIMEOUT_SECONDS', '5')
    assert complete().choices[0].message.content == 'Recovered'


def test_cancellation_stops_agent(fake_agent, tmp_path):
    from app.utils.agent_model import AgentModel
    pid_file = tmp_path / 'pid'
    fake_agent.write_text(json.dumps({'sleep': 5, 'pid_file': str(pid_file)}))

    async def scenario():
        task = asyncio.create_task(AgentModel('claude-code').arun([{'role': 'user', 'content': 'Hi'}]))
        for _ in range(100):
            if pid_file.exists():
                break
            await asyncio.sleep(0.02)
        assert pid_file.exists()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(ProcessLookupError):
            os.kill(int(pid_file.read_text()), 0)

    asyncio.run(scenario())


@pytest.mark.parametrize('command', ['echo hello', '[]', '[42]', '[""]', '{}'])
def test_command_must_be_nonempty_json_argv(fake_agent, monkeypatch, command):
    from research_agents import ProviderError
    monkeypatch.setenv('AGENT_COMMAND_JSON', command)
    with pytest.raises(ProviderError, match='AGENT_COMMAND_JSON'):
        complete()


def test_unknown_provider_fails_even_with_wrapper(fake_agent):
    from research_agents import ProviderError
    with pytest.raises(ProviderError, match='provider'):
        complete('typo')


def test_unusable_usage_is_a_sanitized_provider_error(monkeypatch):
    from app.utils.agent_provider import AgentClient
    from research_agents import ProviderError
    monkeypatch.setattr(AgentClient, '_infer', lambda *a, **kw: (
        {'content': 'Hello', 'tool_calls': []}, {'input_tokens': 'private-secret'},
    ))
    with pytest.raises(ProviderError) as error:
        complete()
    assert 'private-secret' not in str(error.value)
