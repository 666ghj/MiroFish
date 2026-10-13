#!/usr/bin/env python3
"""Print an agent's MCP configuration fragment; never modify its settings files."""
from __future__ import annotations

import argparse
import ipaddress
import json
from pathlib import Path
import shutil
from urllib.parse import urlsplit


SERVER_NAME = "my-own-researcher"
DEFAULT_URL = "http://127.0.0.1:4318/mcp"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

# These are destinations for merging the printed fragment, not files to overwrite.
# Current Kimi Code (Node.js), OpenCode v2 and Pi with native MCP are required.
PROVIDERS = {
    "codex": ("toml", ["~/.codex/config.toml", ".codex/config.toml"]),
    "claude-code": ("json", [".mcp.json"]),
    "antigravity": ("json", [".agents/mcp_config.json", "~/.gemini/config/mcp_config.json"]),
    "cursor": ("json", [".cursor/mcp.json", "~/.cursor/mcp.json"]),
    "devin": ("json", [".devin/mcp_config.json"]),
    "factory-droid": ("json", [".factory/mcp.json", "~/.factory/mcp.json"]),
    "gemini": ("json", [".gemini/settings.json", "~/.gemini/settings.json"]),
    "copilot": ("json", ["~/.copilot/mcp-config.json", ".mcp.json"]),
    "grok": ("toml", ["~/.grok/config.toml"]),
    "kimi": ("json", [".kimi-code/mcp.json", "~/.kimi-code/mcp.json"]),
    "opencode": ("json", ["opencode.json", "~/.config/opencode/opencode.json"]),
    "pi": ("json", [".pi/mcp.json", "~/.pi/agent/mcp.json"]),
    "qwen": ("json", [".qwen/settings.json", "~/.qwen/settings.json"]),
    "hermes": ("yaml", ["~/.hermes/config.yaml"]),
    "muse": ("json", ["~/.config/muse/settings.json"]),
}


def loopback_url(value: str) -> str:
    """Match the local adapter's trust boundary, including SSH-forwarded ports."""
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        is_loopback = host == "localhost" or bool(host and ipaddress.ip_address(host).is_loopback)
        port = parsed.port
    except ValueError:
        raise argparse.ArgumentTypeError("--url must be a valid loopback HTTP URL") from None
    if (parsed.scheme != "http" or not is_loopback or parsed.username is not None
            or parsed.password is not None or parsed.fragment or port == 0):
        raise argparse.ArgumentTypeError("--url must be a loopback HTTP URL without credentials or fragments")
    return value


def stdio_command(root: Path, uv: str) -> tuple[str, list[str]]:
    candidate = Path(uv).expanduser()
    if candidate.is_absolute() or "/" in uv or "\\" in uv:
        executable = str(candidate.resolve())
    else:
        executable = shutil.which(uv) or uv
    backend = root.expanduser().resolve() / "backend"
    return executable, ["run", "--project", str(backend), "--frozen",
                        "python", str(backend / "mcp_server.py")]


def build_config(provider: str, transport: str, url: str, root: Path, uv: str) -> dict:
    command, args = stdio_command(root, uv)
    entry = {"url": url} if transport == "http" else {"command": command, "args": args}

    if provider in {"codex", "grok"}:
        entry["tool_timeout_sec"] = 900
        return {"mcp_servers": {SERVER_NAME: entry}}
    if provider == "hermes":
        entry["timeout"] = 900
        return {"mcp_servers": {SERVER_NAME: entry}}
    if provider == "muse":
        entry.update(transport="streamable_http" if transport == "http" else "stdio",
                     enabled=True, mode="required")
        return {"schema_version": 1, "mcp_servers": {SERVER_NAME: entry}}
    if provider == "opencode":
        entry = ({"type": "remote", "url": url} if transport == "http"
                 else {"type": "local", "command": [command, *args]})
        entry["timeout"] = {"execution": 900000}
        return {"mcp": {"servers": {SERVER_NAME: entry}}}

    if provider in {"claude-code", "factory-droid", "copilot"}:
        entry.update(type=transport, timeout=900000)
    if provider == "copilot":
        entry["tools"] = ["*"]
    if provider == "antigravity" and transport == "http":
        entry = {"serverUrl": url}
    if provider == "devin" and transport == "http":
        entry["transport"] = transport
    if provider in {"gemini", "qwen"}:
        if transport == "http":
            entry = {"httpUrl": url}
        entry["timeout"] = 900000
    if provider == "kimi":
        entry["toolTimeoutMs"] = 900000
    if provider == "pi":
        entry["timeout"] = 900
    result = {"mcpServers": {SERVER_NAME: entry}}
    if provider == "qwen":
        result["mcp"] = {"toolIdleTimeoutMs": 900000}
    return result


def render_config(provider: str, config: dict) -> str:
    if PROVIDERS[provider][0] == "toml":
        entry = config["mcp_servers"][SERVER_NAME]
        lines = [f'[mcp_servers."{SERVER_NAME}"]']
        for key, value in entry.items():
            lines.append(f"{key} = {json.dumps(value, ensure_ascii=False)}")
        return "\n".join(lines)
    # JSON is also valid YAML 1.2 for Hermes, with no third-party dependency.
    return json.dumps(config, indent=2, ensure_ascii=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--provider", choices=PROVIDERS)
    selection.add_argument("--list", action="store_true", help="Print supported clients and config destinations as JSON")
    parser.add_argument("--transport", choices=("http", "stdio"), default="http")
    parser.add_argument("--url", type=loopback_url, default=DEFAULT_URL, help="Streamable HTTP URL (loopback only)")
    parser.add_argument("--root", type=Path, default=REPOSITORY_ROOT, help="Repository path for stdio; converted to an absolute path")
    parser.add_argument("--uv", default=shutil.which("uv") or "uv", help="uv executable for stdio")
    args = parser.parse_args()
    if not args.uv.strip():
        parser.error("--uv must name an executable")
    if args.list:
        print(json.dumps({name: {"format": format_, "config_paths": paths,
                                 "transports": ["http", "stdio"]}
                          for name, (format_, paths) in PROVIDERS.items()}, indent=2))
        return
    print(render_config(args.provider, build_config(args.provider, args.transport,
                                                   args.url, args.root, args.uv)))


if __name__ == "__main__":
    main()
