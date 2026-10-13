import json

import pytest


@pytest.mark.parametrize('kind,wire', [
    ('result', {'type': 'result', 'is_error': False, 'result': '{"content":"hi","tool_calls":[]}'}),
    ('response', {'response': '{"content":"hi","tool_calls":[]}'}),
    ('antigravity', {'event': 'result', 'result': {'status': 'SUCCESS', 'response': '{"content":"hi","tool_calls":[]}'}}),
    ('grok', {'text': '{"content":"hi","tool_calls":[]}', 'stopReason': 'end_turn'}),
    ('qwen', [{'type': 'system'}, {'type': 'result', 'is_error': False, 'result': '{"content":"hi","tool_calls":[]}'}]),
    ('kimi', {'role': 'assistant', 'content': '{"content":"hi","tool_calls":[]}'}),
    ('opencode', {'type': 'text', 'part': {'type': 'text', 'text': '{"content":"hi","tool_calls":[]}'}}),
    ('hermes', {'type': 'result', 'exit_code': 0, 'text': '{"content":"hi","tool_calls":[]}'}),
])
def test_documented_final_output_formats(kind, wire):
    from research_agents.transport import parse_output
    result, usage = parse_output(json.dumps(wire), kind)
    assert result == {'content': 'hi', 'tool_calls': []}


@pytest.mark.parametrize('kind,wire', [
    ('result', {'is_error': True, 'result': '{"content":"hi","tool_calls":[]}'}),
    ('response', {'error': {'message': 'private-secret'}, 'response': '{}'}),
    ('antigravity', {'event': 'result', 'result': {'status': 'ERROR', 'response': '{}'}}),
    ('qwen', [{'type': 'result', 'is_error': True, 'result': '{}'}]),
    ('kimi', {'role': 'assistant', 'content': '{}', 'tool_calls': [{'id': '1'}]}),
    ('opencode', {'type': 'tool_use', 'part': {'text': '{}'}}),
    ('hermes', {'type': 'result', 'exit_code': 1, 'text': '{}', 'error': 'private-secret'}),
])
def test_provider_error_records_never_become_success(kind, wire):
    from research_agents import ProviderError
    from research_agents.transport import parse_output
    with pytest.raises(ProviderError) as error:
        parse_output(json.dumps(wire), kind)
    assert 'private-secret' not in str(error.value)


def test_opencode_concatenates_text_events_and_rejects_late_errors():
    from research_agents import ProviderError
    from research_agents.transport import parse_output
    lines = '\n'.join(json.dumps(event) for event in [
        {'type': 'step_start'}, {'type': 'reasoning', 'part': {'text': 'hidden'}},
        {'type': 'text', 'part': {'text': '{"json":'}},
        {'type': 'text', 'part': {'text': '"{}"}'}}, {'type': 'step_finish'},
    ])
    assert parse_output(lines, 'opencode')[0] == {'json': '{}'}
    with pytest.raises(ProviderError):
        parse_output(lines + '\n{"type":"error","error":"private-secret"}', 'opencode')


@pytest.mark.parametrize('provider,first,kind', [
    ('claude-code', ['claude', '-p'], 'result'),
    ('antigravity', ['agy', '--input-format', 'stream-json'], 'antigravity'),
    ('cursor', ['agent', '-p'], 'result'),
    ('devin', ['devin', '--config'], 'raw'),
    ('factory-droid', ['droid', 'exec'], 'result'),
    ('gemini', ['gemini', '--output-format', 'json'], 'response'),
    ('copilot', ['copilot', '--silent'], 'raw'),
    ('grok', ['grok', '--no-auto-update'], 'grok'),
    ('kimi', ['kimi', '-p'], 'kimi'),
    ('opencode', ['opencode', 'run'], 'opencode'),
    ('pi', ['pi', '--print'], 'raw'),
    ('qwen', ['qwen', '--safe-mode'], 'qwen'),
    ('hermes', ['hermes', 'chat'], 'hermes'),
    ('muse', ['muse', 'exec'], 'raw'),
])
def test_presets_deliver_prompt_and_explicit_model(tmp_path, monkeypatch, provider, first, kind):
    from research_agents.presets import build_command
    from research_agents.registry import get_provider
    monkeypatch.delenv('AGENT_BIN', raising=False)
    monkeypatch.setenv('AGENT_MODEL', 'chosen-model')
    args, parser, stdin = build_command(get_provider(provider), 'private prompt', {}, tmp_path, {})
    assert args[:len(first)] == first
    assert parser == kind and 'chosen-model' in args
    # Neither print-only argv nor stdin is silently discarded by the preset.
    files = [path.read_text() for path in tmp_path.rglob('*') if path.is_file()]
    assert any('private prompt' in text for text in [*args, stdin or '', *files])
    assert not any(arg in args for arg in ['--yolo', '--force', '--allow-all-tools', '--dangerously-skip-permissions'])


@pytest.mark.parametrize('provider', ['claude-code', 'antigravity', 'cursor', 'devin', 'factory-droid',
                                    'gemini', 'copilot', 'grok', 'kimi', 'opencode', 'pi', 'qwen', 'hermes', 'muse'])
def test_native_preset_round_trip_through_subprocess(tmp_path, monkeypatch, provider):
    import sys
    from app.utils.agent_provider import AgentClient
    executable = tmp_path / 'fake-cli'
    executable.write_text(f'''#!{sys.executable}
import json, pathlib, sys
provider = {provider!r}
args = sys.argv[1:]
if provider in ['cursor', 'kimi']:
    prompt = args[args.index('-p') + 1]
elif provider in ['devin', 'muse']:
    prompt = pathlib.Path(args[args.index('--prompt-file') + 1]).read_text()
else:
    prompt = sys.stdin.read()
if provider == 'antigravity':
    prompt = json.loads(prompt)['message']['content']
assert 'Hello from native' in prompt and 'Output JSON Schema' in prompt
answer = json.dumps({{'content': 'native result', 'tool_calls': []}})
wire = {{
    'claude-code': {{'type': 'result', 'is_error': False, 'result': answer}},
    'cursor': {{'type': 'result', 'is_error': False, 'result': answer}},
    'factory-droid': {{'type': 'result', 'is_error': False, 'result': answer}},
    'gemini': {{'response': answer}},
    'antigravity': {{'event': 'result', 'result': {{'status': 'SUCCESS', 'response': answer}}}},
    'qwen': [{{'type': 'result', 'result': answer, 'is_error': False}}],
    'kimi': {{'role': 'assistant', 'content': answer}},
    'opencode': {{'type': 'text', 'part': {{'text': answer}}}},
    'hermes': {{'type': 'result', 'text': answer, 'exit_code': 0}},
    'grok': {{'text': answer}},
}}
print(json.dumps(wire[provider]) if provider in wire else answer)
''')
    executable.chmod(0o700)
    monkeypatch.setenv('AGENT_BIN', str(executable))
    monkeypatch.setenv('AGENT_LOCK_PATH', str(tmp_path / 'requests.lock'))
    monkeypatch.delenv('AGENT_COMMAND_JSON', raising=False)
    result = AgentClient(provider).create(messages=[{'role': 'user', 'content': 'Hello from native'}])
    assert result.choices[0].message.content == 'native result'


def test_hermes_keeps_configured_model_provider(tmp_path, monkeypatch):
    from research_agents.presets import build_command
    from research_agents.registry import get_provider
    monkeypatch.delenv('AGENT_MODEL', raising=False)
    args, _, _ = build_command(get_provider('hermes'), 'Hello', {}, tmp_path, {})
    # These upstream modes discard provider/custom-endpoint settings while still
    # loading credentials, potentially selecting a different billed service.
    assert '--safe-mode' not in args and '--ignore-user-config' not in args
    assert '--ignore-rules' in args
