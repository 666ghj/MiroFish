# Connect your agent through MCP

Use an agent's MCP client to operate My Own Researcher: submit source text, build the graph, run a simulation, and retrieve its report. This connection is separate from the agent selected as the workbench's inference provider. See [the MCP workflow](mcp.md) for tools, readiness checks, and recovery.

Start the application from the repository:

```sh
npm run graph:up
npm run dev:agent
```

The HTTP endpoint is `http://127.0.0.1:4318/mcp`. The backend and graph service must remain running. `npm run dev` also starts the browser interface; choose one application command.

## Generate settings

The generator uses Python's standard library. It prints a configuration fragment and never opens, merges, or writes an agent's configuration files:

```sh
python3 scripts/agent_mcp.py --list
python3 scripts/agent_mcp.py --provider claude-code
python3 scripts/agent_mcp.py --provider cursor --transport stdio
python3 scripts/agent_mcp.py --provider codex
```

`--provider` accepts the IDs in the table below. HTTP is the default. `--list` prints JSON containing supported transports, native format, and configuration destinations. Codex and Grok receive TOML; the other clients receive JSON. Hermes receives JSON compatible with its YAML configuration format.

Copy the generated server entry named `my-own-researcher` into the appropriate existing configuration. Preserve other servers, settings, credentials, and comments. Do **not** redirect a generated fragment over an existing settings file. For TOML, merge the named `[mcp_servers."my-own-researcher"]` table rather than adding a duplicate table. For Hermes YAML, translate the printed object's keys into the existing YAML mapping; the whole JSON object can also be used as a new YAML file. Muse requires `schema_version: 1` at the top level.

| Provider ID | Configuration destination | Official reference |
| --- | --- | --- |
| `codex` | `~/.codex/config.toml`; trusted project `.codex/config.toml` | [Codex MCP](https://developers.openai.com/codex/mcp/) |
| `claude-code` | Project `.mcp.json` | [Claude Code MCP](https://code.claude.com/docs/en/mcp) |
| `antigravity` | Project `.agents/mcp_config.json`; user `~/.gemini/config/mcp_config.json` | [Antigravity MCP](https://www.antigravity.google/docs/mcp/) |
| `cursor` | Project `.cursor/mcp.json`; user `~/.cursor/mcp.json` | [Cursor MCP](https://cursor.com/docs/mcp) |
| `devin` | Project `.devin/mcp_config.json` | [Devin CLI MCP](https://docs.devin.ai/cli/extensibility/mcp/configuration) |
| `factory-droid` | Project `.factory/mcp.json`; user `~/.factory/mcp.json` | [Factory MCP](https://docs.factory.com/harness/mcp) |
| `gemini` | Project `.gemini/settings.json`; user `~/.gemini/settings.json` | [Gemini CLI MCP](https://geminicli.com/docs/tools/mcp-server/) |
| `copilot` | User `~/.copilot/mcp-config.json`; project `.mcp.json` | [Copilot CLI MCP](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference#mcp-server-configuration) |
| `grok` | `~/.grok/config.toml` | [Grok MCP](https://docs.x.ai/build/features/mcp-servers) |
| `kimi` | Project `.kimi-code/mcp.json`; user `~/.kimi-code/mcp.json` | [Kimi Code MCP](https://www.kimi.com/code/docs/en/kimi-code-cli/customization/mcp.html) |
| `opencode` | Project `opencode.json` or `opencode.jsonc`; user `~/.config/opencode/opencode.json` or `.jsonc` | [OpenCode v2 MCP](https://opencode.ai/v2/docs/mcp-servers/) |
| `pi` | Project `.pi/mcp.json`; user `~/.pi/agent/mcp.json` | [Pi MCP](https://pi.dev/docs/latest/mcp) |
| `qwen` | Project `.qwen/settings.json`; user `~/.qwen/settings.json` | [Qwen Code MCP](https://qwenlm.github.io/qwen-code-docs/en/users/features/mcp/) |
| `hermes` | `~/.hermes/config.yaml` | [Hermes MCP](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp) |
| `muse` | `~/.config/muse/settings.json` | [Meta Muse Code MCP](https://dev.meta.ai/docs/muse-code/extending#mcp) |

These templates target the current documented clients, checked on 2026-10-13. `kimi` means the current Node.js Kimi Code CLI, whose `.kimi-code` configuration differs from the older Python `kimi-cli`. `opencode` uses the **v2** `mcp.servers` schema; v1's flat `mcp` mapping is incompatible. `pi` requires a release with native MCP support; older releases used extensions with their own settings. `muse` means Meta Muse Code. These are configuration examples, not a claim that every client has been installed and connected in this workspace.

## HTTP and stdio

The generator uses each client's documented HTTP field: `httpUrl` for Gemini/Qwen, `serverUrl` for Antigravity, and the corresponding `url` and transport fields for other clients. In Gemini/Qwen, `url` alone selects legacy SSE, so do not substitute it for `httpUrl`.

For another local port or an SSH tunnel:

```sh
python3 scripts/agent_mcp.py --provider gemini --url http://localhost:5432/mcp
```

`--url` accepts loopback HTTP addresses without credentials. A cloud agent's localhost refers to its own machine; use the [SSH tunnel instructions](mcp.md#agent-on-another-machine) when the agent and workbench run on different machines.

Stdio makes the client launch its own adapter. The generated argument list is equivalent to:

```text
/absolute/path/to/uv run --project /absolute/path/to/repository/backend --frozen python /absolute/path/to/repository/backend/mcp_server.py
```

Repository paths are absolute even when the generator runs from another directory. `uv` is resolved from `PATH` when available, with `uv` as the fallback executable name. You can override both locations:

```sh
python3 scripts/agent_mcp.py --provider opencode --transport stdio \
  --root "/path/to/My Own Researcher" --uv /path/to/uv
```

Paths containing spaces remain individual arguments. The generator never launches `uv` or an agent. Stdio starts only the adapter; the research backend must already be running. Do not replace this command with `npm run`: npm's banners would interfere with the stdio protocol.

## Timeouts and connection checks

Research calls can take minutes. The generator sets a 900-second tool timeout wherever the documented schema supports it:

| Clients | Generated timeout |
| --- | --- |
| Claude Code, Factory Droid, Gemini CLI, Copilot CLI, Qwen Code | `timeout: 900000` milliseconds |
| Kimi Code | `toolTimeoutMs: 900000` |
| OpenCode v2 | `timeout: {execution: 900000}` |
| Codex, Grok | `tool_timeout_sec = 900` |
| Pi, Hermes | `timeout: 900` seconds |
| Antigravity, Cursor, Devin CLI, Muse Code | No verified timeout key; configure the client's supported limit separately if available |

Qwen also receives `mcp.toolIdleTimeoutMs: 900000`; its separate idle limit otherwise can expire first. Hermes supports the per-tool timeout, but its [current HTTP transport](https://github.com/NousResearch/hermes-agent/blob/main/tools/mcp_tool_transport.py) has a 300-second read idle timeout. The current research adapter does not promise progress during synchronous calls, so use **stdio for Hermes** when calls may exceed five minutes. The workbench's own `MCP_REQUEST_TIMEOUT_SECONDS` defaults to 900; changing a client timeout does not change this backend-request limit.

Restart or reload the client after merging its configuration, and grant project trust when the client requires it. Ask it to call `get_status` before submitting research. This checks the connection without invoking inference. Once ready, read `research://workflow` or follow the [documented research sequence](mcp.md#research-sequence). If a long call times out, inspect saved project or simulation state before repeating a mutation.
