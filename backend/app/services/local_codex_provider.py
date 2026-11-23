"""Opt-in local Codex provider for future MiroFish LLM requests."""

from __future__ import annotations

import atexit
import ipaddress
import os
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from ..config import Config
from scripts.codex_chat_bridge import verify_chatgpt_login


_lock = threading.RLock()
_original = {
    "LLM_API_KEY": Config.LLM_API_KEY,
    "LLM_BASE_URL": Config.LLM_BASE_URL,
    "LLM_MODEL_NAME": Config.LLM_MODEL_NAME,
}
_original_env = {name: os.environ.get(name) for name in _original}
_boost_names = ("LLM_BOOST_API_KEY", "LLM_BOOST_BASE_URL", "LLM_BOOST_MODEL_NAME")
_original_boost_env = {name: os.environ.get(name) for name in _boost_names}
_bridge_process: subprocess.Popen | None = None
_bridge_port: int | None = None
_bridge_token: str | None = None
_active = False
_MODEL = "gpt-6-luna"


def _configured_provider() -> str:
    return "OpenRouter" if "openrouter.ai" in (_original["LLM_BASE_URL"] or "") else "API configurada"


def _bridge_ready() -> bool:
    if _bridge_process is None or _bridge_process.poll() is not None or _bridge_port is None:
        return False
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{_bridge_port}/health", timeout=1) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def status() -> dict:
    with _lock:
        return {
            "active_provider": "codex" if _active else "configured",
            "configured_provider": _configured_provider(),
            "codex_available": shutil.which("codex") is not None,
            "codex_connected": _active and _bridge_ready(),
            "codex_model": _MODEL,
        }


def _free_loopback_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _set_llm(api_key: str, base_url: str, model: str) -> None:
    Config.LLM_API_KEY = api_key
    Config.LLM_BASE_URL = base_url
    Config.LLM_MODEL_NAME = model
    os.environ.update({
        "LLM_API_KEY": api_key,
        "LLM_BASE_URL": base_url,
        "LLM_MODEL_NAME": model,
    })
    # A configured boost provider would otherwise take one OASIS platform.
    for name in _boost_names:
        os.environ[name] = ""


def activate() -> dict:
    global _active, _bridge_process, _bridge_port, _bridge_token
    with _lock:
        if _bridge_ready():
            _set_llm(_bridge_token, f"http://127.0.0.1:{_bridge_port}/v1", "codex-bridge")
            _active = True
            return status()

        codex_binary = shutil.which("codex")
        if not codex_binary:
            raise RuntimeError("Codex CLI no está instalado o no está en PATH")
        try:
            verify_chatgpt_login(codex_binary)
        except subprocess.TimeoutExpired as error:
            raise RuntimeError("La comprobación de la sesión de Codex agotó el tiempo") from error

        if _bridge_process is not None and _bridge_process.poll() is None:
            _bridge_process.terminate()

        port = _free_loopback_port()
        token = secrets.token_urlsafe(32)
        env = os.environ.copy()
        for name in (
            "OPENAI_API_KEY", "CODEX_API_KEY", "LLM_API_KEY", "LLM_BASE_URL",
            "ZEP_API_KEY", *_boost_names,
        ):
            env.pop(name, None)
        env["MIROFISH_CODEX_BRIDGE_TOKEN"] = token
        script = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "codex_chat_bridge.py")
        process = subprocess.Popen(
            [sys.executable, script, "--model", _MODEL, "--port", str(port)],
            cwd=os.path.dirname(script),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            _bridge_process, _bridge_port = process, port
            if _bridge_ready():
                _bridge_token = token
                _set_llm(token, f"http://127.0.0.1:{port}/v1", "codex-bridge")
                _active = True
                return status()
            if process.poll() is not None:
                break
            time.sleep(0.15)
        if process.poll() is None:
            process.terminate()
        _bridge_process, _bridge_port = None, None
        raise RuntimeError("El puente local de Codex no pudo iniciarse")


def deactivate() -> dict:
    global _active
    with _lock:
        for name, value in _original.items():
            setattr(Config, name, value)
            original_env = _original_env[name]
            if original_env is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = original_env
        for name, original_env in _original_boost_env.items():
            if original_env is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = original_env
        # Keep the bridge alive for simulations and reports already in progress.
        _active = False
        return status()


def is_local_request(remote_addr: str | None, origin: str | None) -> bool:
    try:
        if not ipaddress.ip_address(remote_addr or "").is_loopback:
            return False
    except ValueError:
        return False
    if not origin:
        return True
    parsed = urlparse(origin)
    return parsed.scheme in {"http", "https"} and parsed.hostname in {"localhost", "127.0.0.1", "::1"}


@atexit.register
def _cleanup() -> None:
    if _bridge_process is not None and _bridge_process.poll() is None:
        _bridge_process.terminate()
