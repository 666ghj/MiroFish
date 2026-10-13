"""Exercise the adapter through real subprocesses, without paid inference."""

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


@pytest.fixture
def fake_codex(tmp_path, monkeypatch):
    executable = tmp_path / 'codex'
    state = tmp_path / 'state.json'
    state.write_text(json.dumps({'content': 'Hello', 'tool_calls': []}))
    executable.write_text(f'''#!{sys.executable}
import json, os, pathlib, sys, time
args = sys.argv[1:]
state = json.loads(pathlib.Path({str(state)!r}).read_text())
if 'login' in args:
    print(state.get('login', 'Logged in using ChatGPT'), file=sys.stderr)
    sys.exit(0)
assert 'OPENAI_API_KEY' not in os.environ
assert 'CODEX_API_KEY' not in os.environ
assert 'ZEP_API_KEY' not in os.environ
assert '--ignore-user-config' in args and '--ephemeral' in args
assert '--no-daemon' in args
assert args[args.index('--sandbox') + 1] == 'read-only'
assert 'forced_login_method="chatgpt"' in args
assert 'model_provider="openai"' in args
assert 'features.shell_tool=false' in args
assert 'features.plugins=false' in args
assert 'features.hooks=false' in args
assert 'features.code_mode_host=false' in args
prompt = sys.stdin.read()
if state.get('pid_file'):
    pathlib.Path(state['pid_file']).write_text(str(os.getpid()))
if state.get('sleep'):
    time.sleep(state['sleep'])
if state.get('fail'):
    print('API_KEY=private-secret ' + state['fail'], file=sys.stderr)
    sys.exit(1)
answer = {{'content': state.get('content', ''), 'tool_calls': state.get('tool_calls', [])}}
if state.get('echo'):
    answer['content'] = prompt
output = pathlib.Path(args[args.index('-o') + 1])
output.write_text(state.get('raw', json.dumps(answer)))
print(json.dumps({{'type': 'turn.completed', 'usage': {{'input_tokens': 13, 'output_tokens': 7}}}}))
''')
    executable.chmod(0o700)
    monkeypatch.setenv('CODEX_BIN', str(executable))
    monkeypatch.setenv('CODEX_LOCK_PATH', str(tmp_path / 'request.lock'))
    monkeypatch.setenv('OPENAI_API_KEY', 'must-not-inherit')
    monkeypatch.setenv('CODEX_API_KEY', 'must-not-inherit')
    monkeypatch.setenv('ZEP_API_KEY', 'must-not-inherit')
    monkeypatch.delenv('CODEX_MODEL', raising=False)
    return state


def complete(**kwargs):
    from app.utils.codex_provider import CodexClient
    return CodexClient().chat.completions.create(
        model='ignored-api-model', messages=[{'role': 'user', 'content': 'Hello'}], **kwargs
    )


def test_plain_completion_is_sdk_compatible_and_uses_clean_environment(fake_codex):
    response = complete()
    assert response.choices[0].message.content == 'Hello'
    assert response.choices[0].finish_reason == 'stop'
    assert response.usage.total_tokens == 20


def test_json_mode_rejects_non_object_output(fake_codex):
    from app.utils.codex_provider import CodexProviderError
    fake_codex.write_text(json.dumps({'content': '[1,2]'}))
    with pytest.raises(CodexProviderError, match='JSON object'):
        complete(response_format={'type': 'json_object'})


TOOL = {'type': 'function', 'function': {
    'name': 'create_post', 'description': 'Post to the simulated network',
    'parameters': {'type': 'object', 'properties': {'content': {'type': 'string'}},
                   'required': ['content'], 'additionalProperties': False},
}}


def test_tool_decision_returns_callable_arguments_and_id(fake_codex):
    fake_codex.write_text(json.dumps({'content': '', 'tool_calls': [
        {'name': 'create_post', 'arguments': '{"content":"你好"}'}]}))
    response = complete(tools=[TOOL], tool_choice='required')
    choice = response.choices[0]
    assert choice.finish_reason == 'tool_calls'
    tool = choice.message.tool_calls[0]
    assert tool.id.startswith('call_')
    assert tool.function.name == 'create_post'
    assert json.loads(tool.function.arguments) == {'content': '你好'}


@pytest.mark.parametrize('call', [
    {'name': 'delete_everything', 'arguments': '{}'},
    {'name': 'create_post', 'arguments': '{"content":42}'},
    {'name': 'create_post', 'arguments': 'broken json'},
])
def test_invalid_actions_never_reach_oasis(fake_codex, call):
    from app.utils.codex_provider import CodexProviderError
    fake_codex.write_text(json.dumps({'content': '', 'tool_calls': [call]}))
    with pytest.raises(CodexProviderError):
        complete(tools=[TOOL])


def test_required_tool_choice_cannot_silently_return_text(fake_codex):
    from app.utils.codex_provider import CodexProviderError
    with pytest.raises(CodexProviderError, match='required'):
        complete(tools=[TOOL], tool_choice='required')


def test_history_preserves_roles_tool_ids_and_results(fake_codex):
    from app.utils.codex_provider import CodexClient
    fake_codex.write_text(json.dumps({'echo': True}))
    messages = [
        {'role': 'system', 'content': 'You are Alice.'},
        {'role': 'assistant', 'content': None, 'tool_calls': [
            {'id': 'call_abc', 'type': 'function', 'function': {
                'name': 'create_post', 'arguments': '{"content":"Hello"}'}}]},
        {'role': 'tool', 'tool_call_id': 'call_abc', 'content': '{"post_id":19}'},
    ]
    result = CodexClient().chat.completions.create(model='unused', messages=messages)
    prompt = result.choices[0].message.content
    assert json.dumps(messages, ensure_ascii=False) in prompt


def test_api_key_login_is_rejected(fake_codex):
    from app.utils.codex_provider import CodexProviderError
    fake_codex.write_text(json.dumps({'login': 'Logged in using an API key'}))
    with pytest.raises(CodexProviderError, match='ChatGPT'):
        complete()


def test_provider_failure_does_not_expose_raw_output(fake_codex):
    from app.utils.codex_provider import CodexProviderError
    fake_codex.write_text(json.dumps({'fail': 'rate limit exceeded'}))
    with pytest.raises(CodexProviderError, match='limit') as error:
        complete()
    assert 'private-secret' not in str(error.value)


def test_timeout_terminates_request_and_releases_lock(fake_codex, monkeypatch):
    from app.utils.codex_provider import CodexProviderError
    monkeypatch.setenv('CODEX_TIMEOUT_SECONDS', '0.2')
    fake_codex.write_text(json.dumps({'sleep': 5}))
    start = time.monotonic()
    with pytest.raises(CodexProviderError, match='timed out'):
        complete()
    assert time.monotonic() - start < 3
    fake_codex.write_text(json.dumps({'content': 'recovered'}))
    monkeypatch.setenv('CODEX_TIMEOUT_SECONDS', '5')
    assert complete().choices[0].message.content == 'recovered'


def test_malformed_envelope_fails_cleanly(fake_codex):
    from app.utils.codex_provider import CodexProviderError
    fake_codex.write_text(json.dumps({'raw': 'not json'}))
    with pytest.raises(CodexProviderError, match='invalid'):
        complete()


def test_streaming_is_explicitly_unsupported(fake_codex):
    with pytest.raises(ValueError, match='stream'):
        complete(stream=True)


def test_requests_are_serialized_across_clients(fake_codex):
    fake_codex.write_text(json.dumps({'sleep': 0.25, 'content': 'ok'}))
    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: complete(), range(2)))
    assert all(r.choices[0].message.content == 'ok' for r in results)
    assert time.monotonic() - start >= 0.5


def test_lock_held_by_other_process_has_bounded_wait(fake_codex, monkeypatch):
    import subprocess
    from app.utils.codex_provider import CodexProviderError
    lock_path = os.environ['CODEX_LOCK_PATH']
    child = subprocess.Popen([sys.executable, '-c',
        'import fcntl,sys,time; f=open(sys.argv[1],"a"); '
        'fcntl.flock(f,fcntl.LOCK_EX); print("ready",flush=True); time.sleep(10)', lock_path],
        stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == 'ready'
        monkeypatch.setenv('CODEX_QUEUE_TIMEOUT_SECONDS', '0.15')
        with pytest.raises(CodexProviderError, match='queue'):
            complete()
    finally:
        child.terminate()
        child.wait(timeout=3)


def test_relative_lock_override_is_rejected(fake_codex, monkeypatch, tmp_path):
    from app.utils.codex_provider import CodexProviderError
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('CODEX_LOCK_PATH', 'requests.lock')
    with pytest.raises(CodexProviderError, match='absolute'):
        complete()
    assert not (tmp_path / 'requests.lock').exists()


def test_parent_exit_does_not_leave_codex_running(fake_codex, tmp_path):
    import subprocess
    import psutil
    pid_file = tmp_path / 'codex.pid'
    fake_codex.write_text(json.dumps({'sleep': 8, 'pid_file': str(pid_file)}))
    parent = subprocess.Popen([sys.executable, '-c',
        'from app.utils.codex_provider import CodexClient; '
        'CodexClient().create(messages=[{"role":"user","content":"hi"}])'],
        cwd=Path(__file__).resolve().parents[1], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    pid = None
    try:
        deadline = time.monotonic() + 4
        while not pid_file.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert pid_file.exists()
        pid = int(pid_file.read_text())
        parent.terminate()
        parent.wait(timeout=2)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if not psutil.pid_exists(pid) or psutil.Process(pid).status() == psutil.STATUS_ZOMBIE:
                break
            time.sleep(0.05)
        else:
            pytest.fail('Codex inference survived its parent process')
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait()
        if pid and psutil.pid_exists(pid):
            psutil.Process(pid).kill()
