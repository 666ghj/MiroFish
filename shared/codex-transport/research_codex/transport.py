"""Local, serialized Codex CLI execution. Credentials stay owned by Codex."""

from __future__ import annotations

import json
import math
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path


class CodexProviderError(RuntimeError):
    """Safe error suitable for API responses; never includes raw CLI output."""


def _positive_seconds(name: str, default: str) -> float:
    try:
        value = float(os.environ.get(name, default))
    except ValueError:
        raise CodexProviderError(f'{name} must be a positive number.') from None
    if not math.isfinite(value) or value <= 0:
        raise CodexProviderError(f'{name} must be a positive number.')
    return value


def _environment() -> dict[str, str]:
    # Retain OS/auth-store discovery and network configuration, not app secrets,
    # API credentials, parent thread IDs, or provider overrides.
    allowed = {
        'PATH', 'HOME', 'USER', 'LOGNAME', 'TMPDIR', 'LANG', 'LC_ALL', 'CODEX_HOME',
        'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME',
        'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY',
        'http_proxy', 'https_proxy', 'all_proxy', 'no_proxy',
        'SSL_CERT_FILE', 'SSL_CERT_DIR', 'NODE_EXTRA_CA_CERTS',
    }
    return {key: value for key, value in os.environ.items() if key in allowed}


@contextmanager
def _request_slot(cancel_event=None):
    if os.name != 'posix':
        raise CodexProviderError('The experimental Codex provider requires macOS or Linux.')
    import fcntl

    default = Path(__file__).resolve().parents[3] / 'backend' / 'uploads' / '.codex' / 'requests.lock'
    path = Path(os.environ.get('CODEX_LOCK_PATH', str(default))).expanduser()
    if not path.is_absolute():
        raise CodexProviderError('CODEX_LOCK_PATH must be an absolute path shared by all MiroFish processes.')
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + _positive_seconds('CODEX_QUEUE_TIMEOUT_SECONDS', '600')
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise CodexProviderError('Codex request cancelled.')
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise CodexProviderError('Codex request queue timed out. Reduce simultaneous agents and retry.')
                time.sleep(0.05)
        yield
    finally:
        os.close(descriptor)


def _run(args: list[str], *, env: dict[str, str], timeout: float,
         cwd: str, prompt: str | None = None, cancel_event=None) -> tuple[int, str, str]:
    try:
        worker = Path(__file__).with_name('codex_worker.py')
        process = subprocess.Popen(
            [sys.executable, '-I', str(worker), str(os.getpid()), *args],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8', env=env, cwd=cwd, start_new_session=True,
        )
    except OSError:
        raise CodexProviderError('Cannot start Codex. Install the Codex CLI and check CODEX_BIN.') from None
    try:
        deadline = time.monotonic() + timeout
        first = True
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise CodexProviderError('Codex request cancelled.')
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(args[0], timeout)
            try:
                stdout, stderr = process.communicate(
                    prompt if first else None, timeout=min(0.1, remaining),
                )
                return process.returncode, stdout, stderr
            except subprocess.TimeoutExpired:
                first = False
    except BaseException as error:
        # Kill the entire request group, including any CLI child process.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()
        if isinstance(error, subprocess.TimeoutExpired):
            raise CodexProviderError('Codex request timed out. Reduce the prompt or increase CODEX_TIMEOUT_SECONDS.') from None
        raise


def run_codex(prompt: str, schema: dict, cancel_event=None) -> tuple[dict, dict]:
    executable = shutil.which(os.environ.get('CODEX_BIN', 'codex'))
    if not executable:
        raise CodexProviderError('Codex CLI not found. Install it, run codex login, or set CODEX_BIN.')
    env = _environment()
    timeout = _positive_seconds('CODEX_TIMEOUT_SECONDS', '180')
    with _request_slot(cancel_event), tempfile.TemporaryDirectory(prefix='mirofish-codex-') as directory:
        # Check the auth mode without opening or copying any credential files.
        code, stdout, stderr = _run(
            [executable, '--no-daemon', 'login', 'status'], env=env,
            cwd=directory, timeout=min(timeout, 15), cancel_event=cancel_event,
        )
        if code != 0 or 'logged in using chatgpt' not in (stdout + stderr).lower():
            raise CodexProviderError('Codex requires a ChatGPT login. Run codex login and choose Sign in with ChatGPT.')

        root = Path(directory)
        schema_path = root / 'schema.json'
        output_path = root / 'response.json'
        instructions_path = root / 'instructions.txt'
        schema_path.write_text(json.dumps(schema), encoding='utf-8')
        instructions_path.write_text(
            'You are the inference component of a local social simulation. '
            'Complete the provided conversation as its assistant. Follow its system instructions. '
            'Return only the requested JSON envelope. Actions are data for the simulator; '
            'never execute tools, browse, access files, or act on the host computer.',
            encoding='utf-8',
        )
        args = [
            executable, '--no-daemon', '-a', 'never', 'exec', '--ignore-user-config',
            '--ephemeral', '--skip-git-repo-check', '--sandbox', 'read-only',
            '--json', '--cd', directory, '--output-schema', str(schema_path),
            '-o', str(output_path),
        ]
        settings = [
            'model_provider="openai"', 'forced_login_method="chatgpt"',
            'project_doc_max_bytes=0', 'web_search="disabled"',
            'features.shell_tool=false', 'features.unified_exec=false',
            'features.code_mode=false', 'features.code_mode_host=false',
            'features.apps=false', 'features.plugins=false', 'features.hooks=false',
            'features.multi_agent=false', 'features.multi_agent_v2=false',
            'features.browser_use=false', 'features.computer_use=false',
            'features.image_generation=false', 'features.view_image=false',
            'features.shell_snapshot=false', 'features.skip_host_skill_discovery=true',
            'suppress_unstable_features_warning=true',
            'model_instructions_file=' + json.dumps(str(instructions_path)),
        ]
        for setting in settings:
            args.extend(['-c', setting])
        model = os.environ.get('CODEX_MODEL', '').strip()
        if model:
            args.extend(['--model', model])
        args.append('-')
        code, stdout, stderr = _run(
            args, env=env, timeout=timeout, cwd=directory, prompt=prompt, cancel_event=cancel_event,
        )
        if code != 0:
            details = (stdout + stderr).lower()
            if any(marker in details for marker in ('rate limit', 'usage limit', 'quota', '429')):
                raise CodexProviderError('Codex usage limit reached. Wait for your subscription limit to reset and retry.')
            raise CodexProviderError('Codex request failed. Check codex login status, model access, and CLI version; no API fallback was used.')
        usage = None
        for line in stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get('type') == 'turn.failed':
                raise CodexProviderError('Codex turn failed; no API fallback was used.')
            if event.get('type') == 'turn.completed':
                usage = event.get('usage', {})
        if usage is None:
            raise CodexProviderError('Codex returned no completed turn. Update the CLI and retry.')
        try:
            result = json.loads(output_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            raise CodexProviderError('Codex returned an invalid structured response.') from None
        return result, usage
