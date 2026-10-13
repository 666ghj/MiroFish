"""Serialized CLI requests with JSON validation, cancellation, and no API fallback."""
import json
import os
from pathlib import Path
import shutil
import tempfile

import jsonschema

from research_codex.transport import (
    CodexProviderError as ProviderError, _environment, _positive_seconds,
    _request_slot, _run, run_codex,
)
from .registry import get_provider


def _command_override():
    raw = os.environ.get('AGENT_COMMAND_JSON')
    if raw is None:
        return None
    try:
        command = json.loads(raw)
        if not isinstance(command, list) or not command or any(
            not isinstance(arg, str) or not arg or '\x00' in arg for arg in command
        ):
            raise ValueError()
    except (ValueError, TypeError):
        raise ProviderError('AGENT_COMMAND_JSON must be a nonempty JSON array of command arguments.') from None
    return command


def validate_provider(provider=None):
    selected = get_provider(provider)
    if os.name != 'posix':
        raise ProviderError('Agent CLI inference requires macOS, Linux, or WSL.')
    command = None if selected.id == 'codex' else _command_override()
    key = 'CODEX_BIN' if selected.id == 'codex' else 'AGENT_BIN'
    executable = command[0] if command else os.environ.get(key, selected.executable)
    if not shutil.which(executable):
        raise ProviderError(f'{selected.name} CLI not found. Install it or set {key}.')
    prefix = 'CODEX' if selected.id == 'codex' else 'AGENT'
    _positive_seconds(prefix + '_TIMEOUT_SECONDS', '180')
    _positive_seconds(prefix + '_QUEUE_TIMEOUT_SECONDS', '600')
    lock = os.environ.get(prefix + '_LOCK_PATH')
    if lock and not Path(lock).expanduser().is_absolute():
        raise ProviderError(f'{prefix}_LOCK_PATH must be an absolute path.')
    return selected


def _agent_environment():
    env = _environment()
    # Account/provider secrets are opt-in; app secrets are never implicitly inherited.
    for key in os.environ.get('AGENT_ENV_PASSTHROUGH', '').split(','):
        key = key.strip()
        if key and key in os.environ:
            env[key] = os.environ[key]
    return env


def parse_output(output: str, output_format: str) -> tuple[dict, dict]:
    """Decode only documented final-response fields, never arbitrary log fragments."""
    try:
        event_formats = {'antigravity', 'kimi', 'opencode', 'hermes'}
        if output_format in event_formats:
            events = [json.loads(line) for line in output.splitlines() if line.strip()]
            if not events or any(not isinstance(event, dict) for event in events):
                raise ValueError()
            if any(event.get('type') in {'error', 'tool_use', 'tool_result'} or event.get('error')
                   or event.get('tool_calls') or event.get('role') == 'tool' for event in events):
                raise ValueError()
            if output_format == 'antigravity':
                results = [e['result'] for e in events if e.get('event') == 'result']
                if len(results) != 1 or results[0].get('status') != 'SUCCESS':
                    raise ValueError()
                value = results[0]['response']
            elif output_format == 'kimi':
                replies = [e['content'] for e in events if e.get('role') == 'assistant']
                if not replies:
                    raise ValueError()
                value = replies[-1]
            elif output_format == 'opencode':
                value = ''.join(e['part']['text'] for e in events if e.get('type') == 'text')
            else:
                results = [e for e in events if e.get('type') == 'result']
                if len(results) != 1 or results[0].get('exit_code') != 0:
                    raise ValueError()
                value = results[0]['text']
        else:
            value = json.loads(output)
        usage = {}
        if output_format == 'qwen':
            if not isinstance(value, list) or any(not isinstance(e, dict) for e in value):
                raise ValueError()
            results = [e for e in value if e.get('type') == 'result']
            if len(results) != 1 or any(e.get('type') == 'error' for e in value):
                raise ValueError()
            value = results[0]
            output_format = 'result'
        if output_format == 'result':
            if not isinstance(value, dict) or value.get('is_error') or value.get('error'):
                raise ValueError()
            usage = value.get('usage') or {}
            value = value.get('structured_output') or value['result']
        elif output_format == 'response':
            if not isinstance(value, dict) or value.get('error'):
                raise ValueError()
            value = value['response']
        elif output_format == 'grok':
            if not isinstance(value, dict) or value.get('error'):
                raise ValueError()
            value = value['text']
        if isinstance(value, str):
            value = json.loads(value)
        if not isinstance(value, dict):
            raise ValueError()
        return value, usage if isinstance(usage, dict) else {}
    except (ValueError, KeyError, TypeError, AttributeError):
        raise ProviderError('Agent returned invalid structured output. Check CLI version and output format.') from None


def run_agent(prompt: str, schema: dict, cancel_event=None, *, provider=None) -> tuple[dict, dict]:
    selected = validate_provider(provider)
    if selected.id == 'codex':
        return run_codex(prompt, schema, cancel_event=cancel_event)
    jsonschema.Draft202012Validator.check_schema(schema)
    command = _command_override()
    timeout = _positive_seconds('AGENT_TIMEOUT_SECONDS', '180')
    instruction = (
        'You are a text inference component. Return only one JSON object matching the schema below. '
        'Do not execute tools, read files, browse, or take actions. Simulation actions are output data '
        'for the host application to validate and execute. Do not add Markdown fences or commentary.\n'
        'Output JSON Schema: ' + json.dumps(schema, ensure_ascii=False) + '\n\n' + prompt
    )
    with _request_slot(cancel_event, prefix='AGENT', label=selected.name), tempfile.TemporaryDirectory(
        prefix='mirofish-agent-'
    ) as directory:
        env = _agent_environment()
        if command:
            args, output_format, stdin = command, 'raw', instruction
            # A wrapper can read these without exposing prompts in the process list.
            env['MIROFISH_AGENT_PROVIDER'] = selected.id
            env['MIROFISH_AGENT_MODEL'] = os.environ.get('AGENT_MODEL', '')
        else:
            from .presets import build_command
            args, output_format, stdin = build_command(selected, instruction, schema, Path(directory), env)
        args[0] = shutil.which(args[0]) or args[0]
        code, stdout, stderr = _run(
            args, env=env, timeout=timeout, cwd=directory, prompt=stdin, cancel_event=cancel_event,
            label=selected.name, timeout_setting='AGENT_TIMEOUT_SECONDS',
        )
        if code:
            if any(marker in (stdout + stderr).lower() for marker in ('rate limit', 'usage limit', 'quota', '429')):
                raise ProviderError(f'{selected.name} usage limit or quota reached. Check your account allowance.')
            raise ProviderError(f'{selected.name} request failed. Check login, model access, and CLI version; no fallback was used.')
        result, usage = parse_output(stdout.strip(), output_format)
        try:
            jsonschema.validate(result, schema)
        except jsonschema.ValidationError:
            raise ProviderError(f'{selected.name} returned an invalid response envelope.') from None
        return result, usage
