"""Exercise the public config-generator CLI without loading any agent or backend."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "agent_mcp.py"
NAME = "my-own-researcher"
URL = "http://127.0.0.1:4318/mcp"
PROVIDERS = {
    "codex", "claude-code", "antigravity", "cursor", "devin",
    "factory-droid", "gemini", "copilot", "grok", "kimi", "opencode",
    "pi", "qwen", "hermes", "muse",
}


def generate(tmp_path, *args):
    home = tmp_path / "empty-home"
    home.mkdir(exist_ok=True)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args], cwd=tmp_path,
        env={**os.environ, "HOME": str(home)}, text=True,
        capture_output=True, timeout=10,
    )
    assert list(home.iterdir()) == [], "The generator must never write user settings"
    return result


@pytest.mark.parametrize(("provider", "expected"), [
    ("claude-code", {"type": "http", "url": URL, "timeout": 900000}),
    ("antigravity", {"serverUrl": URL}),
    ("cursor", {"url": URL}),
    ("devin", {"url": URL, "transport": "http"}),
    ("factory-droid", {"type": "http", "url": URL, "timeout": 900000}),
    ("gemini", {"httpUrl": URL, "timeout": 900000}),
    ("copilot", {"type": "http", "url": URL, "tools": ["*"], "timeout": 900000}),
    ("kimi", {"url": URL, "toolTimeoutMs": 900000}),
    ("pi", {"url": URL, "timeout": 900}),
    ("qwen", {"httpUrl": URL, "timeout": 900000}),
])
def test_http_emits_each_clients_native_server_fields(tmp_path, provider, expected):
    result = generate(tmp_path, "--provider", provider)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    data = json.loads(result.stdout)
    assert data["mcpServers"] == {NAME: expected}
    if provider == "qwen":
        assert data["mcp"]["toolIdleTimeoutMs"] == 900000


@pytest.mark.parametrize(("provider", "expected"), [
    ("opencode", {"mcp": {"servers": {NAME: {
        "type": "remote", "url": URL, "timeout": {"execution": 900000},
    }}}}),
    ("hermes", {"mcp_servers": {NAME: {"url": URL, "timeout": 900}}}),
    ("muse", {"schema_version": 1, "mcp_servers": {NAME: {
        "transport": "streamable_http", "url": URL, "enabled": True, "mode": "required",
    }}}),
])
def test_http_preserves_nonstandard_top_level_schemas(tmp_path, provider, expected):
    result = generate(tmp_path, "--provider", provider)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == expected


@pytest.mark.parametrize(("provider", "timeout_key"), [
    ("codex", "tool_timeout_sec"), ("grok", "tool_timeout_sec"),
])
def test_toml_clients_receive_native_toml(tmp_path, provider, timeout_key):
    result = generate(tmp_path, "--provider", provider)
    assert result.returncode == 0, result.stderr
    assert tomllib.loads(result.stdout) == {
        "mcp_servers": {NAME: {"url": URL, timeout_key: 900}},
    }


@pytest.mark.parametrize("provider", sorted(PROVIDERS))
def test_stdio_launch_paths_are_absolute_and_arguments_preserve_spaces(tmp_path, provider):
    root = tmp_path / "research workspace"
    uv = tmp_path / 'bin with spaces' / 'u"v'
    result = generate(tmp_path, "--provider", provider, "--transport", "stdio",
                      "--root", str(root), "--uv", str(uv))
    assert result.returncode == 0, result.stderr
    data = tomllib.loads(result.stdout) if provider in {"codex", "grok"} else json.loads(result.stdout)
    if provider == "opencode":
        entry = data["mcp"]["servers"][NAME]
        argv = entry["command"]
        assert entry["type"] == "local"
    else:
        key = "mcp_servers" if provider in {"codex", "grok", "hermes", "muse"} else "mcpServers"
        entry = data[key][NAME]
        argv = [entry["command"], *entry["args"]]
    assert argv == [str(uv), "run", "--project", str(root / "backend"),
                    "--frozen", "python", str(root / "backend" / "mcp_server.py")]
    assert "url" not in entry and "httpUrl" not in entry and "serverUrl" not in entry
    if provider == "muse":
        assert entry["transport"] == "stdio"


def test_list_reports_destinations_formats_and_transports_without_provider(tmp_path):
    result = generate(tmp_path, "--list")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert set(data) == PROVIDERS
    for provider in data.values():
        assert provider["config_paths"]
        assert provider["format"] in {"json", "toml", "yaml"}
        assert provider["transports"] == ["http", "stdio"]


def test_default_root_uses_script_location_not_current_directory(tmp_path):
    result = generate(tmp_path, "--provider", "cursor", "--transport", "stdio", "--uv", "uv")
    assert result.returncode == 0, result.stderr
    args = json.loads(result.stdout)["mcpServers"][NAME]["args"]
    assert args[2] == str(SCRIPT.parents[1] / "backend")
    assert args[-1] == str(SCRIPT.parents[1] / "backend" / "mcp_server.py")


def test_relative_root_is_resolved_before_output(tmp_path):
    result = generate(tmp_path, "--provider", "cursor", "--transport", "stdio", "--root", "project")
    assert result.returncode == 0, result.stderr
    args = json.loads(result.stdout)["mcpServers"][NAME]["args"]
    assert args[2] == str(tmp_path / "project" / "backend")


@pytest.mark.parametrize("args", [
    [], ["--provider", "unknown"],
    ["--provider", "cursor", "--url", "https://example.org/mcp"],
    ["--provider", "cursor", "--url", "http://user:secret@127.0.0.1:4318/mcp"],
    ["--provider", "cursor", "--url", "http://127.0.0.1:99999/mcp"],
])
def test_invalid_options_fail_without_emitting_configuration(tmp_path, args):
    result = generate(tmp_path, *args)
    assert result.returncode == 2
    assert result.stdout == ""


def test_custom_loopback_url_is_preserved(tmp_path):
    url = "http://localhost:5432/mcp"
    result = generate(tmp_path, "--provider", "gemini", "--url", url)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["mcpServers"][NAME]["httpUrl"] == url
