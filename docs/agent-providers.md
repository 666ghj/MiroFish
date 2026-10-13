# Agent CLI inference providers

MiroFish can use an installed agent CLI for backend research, simulation decisions,
and local graph extraction. Connecting an agent to MiroFish's MCP server is a
separate setting: MCP lets that agent call research tools; `LLM_PROVIDER` selects
the process MiroFish calls for inference. See [agent MCP setup](agent-mcp.md) for
the client connection instructions.

The fourteen additional native presets are experimental and depend on the
installed CLI version. The integration does not install CLIs, create accounts,
sign in, or grant model access. No real inference calls for these providers were
tested as part of this implementation. Official interfaces were checked on
2026-10-13; use the linked documentation and the checks below after an upgrade.

## Select a provider

Install and authenticate one CLI from the table below, then edit the repository's
`.env`. For example:

```dotenv
LLM_PROVIDER=gemini
AGENT_TIMEOUT_SECONDS=180
AGENT_QUEUE_TIMEOUT_SECONDS=600

# Optional: use these only when the CLI's defaults are unsuitable.
# AGENT_BIN=/absolute/path/to/gemini
# AGENT_MODEL=an-exact-model-id-available-to-your-account
# AGENT_LOCK_PATH=/absolute/path/to/mirofish-agent.lock
```

Restart the backend and graph service after changing their environment. A desktop
app's terminal and a background service can have different `PATH` values; set an
absolute `AGENT_BIN` when the service cannot find the executable.

| Setting | Meaning |
| --- | --- |
| `LLM_PROVIDER` | A provider ID below, existing `codex`, or existing `openai` API mode. |
| `AGENT_BIN` | Executable override for a non-Codex native preset. It is one executable path, not a shell command with flags. |
| `AGENT_MODEL` | Optional model ID forwarded to the selected CLI. Omit it to use that CLI's configured default. Model IDs and account access are provider-specific. |
| `AGENT_TIMEOUT_SECONDS` | Maximum execution time per inference process; default `180`. |
| `AGENT_QUEUE_TIMEOUT_SECONDS` | Maximum wait for the shared inference slot; default `600`. |
| `AGENT_LOCK_PATH` | Optional absolute path to the lock shared by cooperating inference processes. |
| `GRAPH_LLM_PROVIDER` | Optional graph provider override. Otherwise graph extraction inherits `LLM_PROVIDER`; `LLM_PROVIDER=openai` retains the existing Codex graph default. |
| `AGENT_COMMAND_JSON` | Optional JSON argv array replacing the non-Codex native command with a wrapper implementing the protocol below. |
| `AGENT_ENV_PASSTHROUGH` | Comma-separated names of environment variables explicitly forwarded to the agent process. |

Codex continues to use its existing `CODEX_*` settings. `AGENT_*` settings apply to
the additional providers; changing `AGENT_BIN` does not change Codex. When graph
and backend use different non-Codex providers, they share the `AGENT_*` settings.
Use the wrapper's `MIROFISH_AGENT_PROVIDER` value to dispatch different commands
if one executable/model setting cannot serve both.

MiroFish does not silently switch providers or fall back to a paid API when an
agent fails. The selected CLI still applies its own account limits and billing.

## Install and sign in

Follow the official installer for your operating system. Run the CLI's login
flow manually under the same operating-system account that runs MiroFish, then
check the listed command. Installation and login are setup actions for you to
perform; the commands below have not been run by this integration. MiroFish's
agent subprocess transport currently requires macOS, Linux, or WSL; native
Windows is not supported.

| `LLM_PROVIDER` | Executable | Official setup and authentication | Inspect the installed interface |
| --- | --- | --- | --- |
| `claude-code` | `claude` | [Install and authenticate Claude Code](https://code.claude.com/docs/en/setup). Start `claude` and complete browser login. | `claude --help` |
| `antigravity` | `agy` | [Antigravity CLI setup](https://www.antigravity.google/docs/cli/overview/). Install the actual CLI and complete its account sign-in. | `agy --help` |
| `cursor` | `agent` | [Install Cursor CLI](https://cursor.com/docs/cli/installation), then run `agent login`. The current executable is `agent`. | `agent --help` |
| `devin` | `devin` | [Install Devin CLI](https://docs.devin.ai/cli), then run [`devin auth login`](https://docs.devin.ai/cli/reference/commands). | `devin --help` |
| `factory-droid` | `droid` | [Factory Droid installation and headless authentication](https://docs.factory.com/droid-exec/overview). Complete account authentication before a headless run. | `droid exec --help` |
| `gemini` | `gemini` | [Install](https://geminicli.com/docs/get-started/installation/): `npm install -g @google/gemini-cli`. Start `gemini` and follow [authentication setup](https://geminicli.com/docs/get-started/authentication/). | `gemini --help` |
| `copilot` | `copilot` | [Install and authenticate](https://docs.github.com/en/copilot/how-tos/copilot-cli/set-up-copilot-cli/install-copilot-cli): `npm install -g @github/copilot`, then start `copilot` and use `/login`. | `copilot help` |
| `grok` | `grok` | [Grok Build installer and first-run login](https://docs.x.ai/build/overview). `grok login` is also documented. | `grok --help` |
| `kimi` | `kimi` | [Current Kimi Code installation](https://www.kimi.com/code/docs/en/kimi-code-cli/guides/getting-started): `npm install -g @moonshot-ai/kimi-code`. Run `kimi login`, or `/login` in the UI. | `kimi --help` |
| `opencode` | `opencode` | [OpenCode V2 installation](https://opencode.ai/v2/docs/): `npm install -g @opencode/cli`. Use [`opencode auth login PROVIDER`](https://opencode.ai/v2/docs/cli/commands/#auth) for your chosen model provider. | `opencode run --help` |
| `pi` | `pi` | [Pi installation and login](https://github.com/badlogic/pi-mono/tree/main/packages/coding-agent): `npm install -g --ignore-scripts @earendil-works/pi-coding-agent`, then `/login` in Pi. | `pi --help` |
| `qwen` | `qwen` | [Quickstart](https://qwenlm.github.io/qwen-code-docs/en/users/quickstart/): `npm install -g @qwen-code/qwen-code@latest`. Start `qwen` and use its first-run flow or [`/auth`](https://qwenlm.github.io/qwen-code-docs/en/users/configuration/auth/). | `qwen --help` |
| `hermes` | `hermes` | [Install Hermes](https://hermes-agent.nousresearch.com/docs/getting-started/installation), then `hermes setup` to configure the provider; `hermes setup --portal` selects the Nous Portal route. | `hermes chat --help` |
| `muse` | `muse` | [Install Meta Muse Code](https://dev.meta.ai/docs/muse-code), then start `muse` for [browser/API-key sign-in](https://dev.meta.ai/docs/muse-code/auth); `/login` reopens the choices. | `muse exec --help` |

This `muse` integration refers to **Meta Muse Code**. An unrelated executable with
the same name does not implement the expected interface. Likewise, Antigravity
uses `agy`, rather than assuming that an editor launcher accepts headless flags.
For an older Cursor installation named `cursor-agent`, use `AGENT_BIN` only if
its help output supports the preset's flags.

Authentication stored by a CLI remains owned by that CLI. MiroFish does not
implicitly forward API keys or application secrets. If your chosen login method
requires an environment credential, explicitly opt in to its name, for example:

```dotenv
LLM_PROVIDER=copilot
AGENT_ENV_PASSTHROUGH=COPILOT_GITHUB_TOKEN
```

Set that credential in the service's environment using your usual secret
management. The allowlist contains variable names, not values. A credential kept
in the CLI's own config or keychain may be available without this setting. A
custom CLI home directory can also require explicit passthrough of its location;
moving a home usually moves both configuration and authentication.

## Native commands and their limits

The commands here identify the upstream headless interfaces, not shell commands
you need to paste into `.env`. MiroFish builds argv directly, adds its inference
instructions, and decodes the selected output format. Use `AGENT_MODEL` for the
CLI's model option and `AGENT_COMMAND_JSON` for a different invocation. The exact
flags applied by this checkout are in
[`presets.py`](../shared/codex-transport/research_agents/presets.py).

Cursor and Kimi receive prompts as argv arguments. Very large requests can exceed
the operating system's argument limit, and the arguments may be visible in
process inspection. Devin and Muse receive temporary prompt files. The other
native presets use stdin (Antigravity uses a JSONL input message). Use a wrapper
when you need a different input channel; every wrapper receives stdin.

| Provider | Documented headless interface | Output/controls to account for |
| --- | --- | --- |
| Claude Code | `claude -p --output-format json` | JSON result/structured output. `--safe-mode` retains subscription authentication; `--bare` changes authentication to API-only. CLI flags can suppress tools, MCP, hooks, and other ambient features. [Reference](https://code.claude.com/docs/en/cli-reference), [headless](https://code.claude.com/docs/en/headless). |
| Antigravity | `agy -p PROMPT --output-format json` | Extract `response`. Permission configuration can deny named action categories; no universal per-run hooks/config-off switch was established. [Headless](https://www.antigravity.google/docs/cli/headless/), [permissions](https://www.antigravity.google/docs/permissions/). |
| Cursor | `agent -p PROMPT --output-format json --mode ask` | Ask mode may still read files and use tools. It is not a no-tools mode. [Parameters](https://cursor.com/docs/cli/reference/parameters), [output](https://cursor.com/docs/cli/reference/output-format). |
| Devin | `devin -p PROMPT --model MODEL` | Plain response; prompt files are supported. The reference does not document `--output-format json`. Config and workspace-trust controls require the current interface. [Commands](https://docs.devin.ai/cli/reference/commands), [permissions](https://docs.devin.ai/cli/reference/permissions). |
| Factory Droid | `droid exec -o json` | Reads prompt stdin; extract `result`. Native tool allowlists/denylists and `hooksDisabled` exist, but a settings override merges normal config. [Exec](https://docs.factory.com/droid-exec/overview), [settings](https://docs.factory.com/droid-cli/settings). |
| Gemini | `gemini -p PROMPT --output-format json -e none` | Extract `response`. Stdin supplements `-p`. Extensions can be disabled; tool policy and settings control native tools, hooks, skills, and MCP. `--allowed-tools` grants approval, not an exclusive tool list. [Headless](https://geminicli.com/docs/cli/headless/), [policy](https://geminicli.com/docs/reference/policy-engine/). |
| Copilot | `copilot -p PROMPT --silent --output-format text` | Silent text avoids an undocumented full prompt-event schema. JSON mode is JSONL. Stdin supplies the prompt only without `-p`; custom agents can specify `tools: []`. Built-in MCPs and custom instructions have separate disabling flags. [Programmatic use](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-programmatic-reference), [agents](https://docs.github.com/en/copilot/reference/custom-agents-configuration). |
| Grok | `grok -p PROMPT --output-format json` | Extract `text`. Built-in tool allowlist and denylist run in sequence; MCP permission denial is separate. `--no-subagents`, `--no-memory`, and `--disable-web-search` restrict named features. [Headless](https://docs.x.ai/build/cli/headless-scripting), [flags](https://docs.x.ai/build/cli/reference). |
| Kimi | `kimi -p PROMPT --output-format stream-json` | Current Node.js CLI emits assistant/tool messages as JSONL. `-p` automatically uses unattended permissions and cannot combine with `--auto`, `--yolo`, or `--plan`. An explicit Markdown agent with `tools: []` disables tools. [Commands](https://www.kimi.com/code/docs/en/kimi-code-cli/reference/kimi-command.html), [agents](https://www.kimi.com/code/docs/en/kimi-code-cli/customization/agents.html). |
| OpenCode | `opencode run --standalone --format json PROMPT` | V2 JSONL text events carry `part.text`. Use the selected agent's `permissions` array to deny actions; agent rules can override global rules. [Commands](https://opencode.ai/v2/docs/cli/commands/), [agents](https://opencode.ai/v2/docs/agents). |
| Pi | `pi --print --mode text` | Reads prompt stdin. Documented `--no-tools`, `--no-extensions`, `--no-skills`, `--no-prompt-templates`, `--no-context-files`, and `--no-session` offer explicit controls. [CLI reference](https://pi.dev/docs/latest/cli). |
| Qwen | `qwen --safe-mode --output-format json` | Reads prompt stdin. JSON output is an array with a terminal result, not Gemini's object format. Safe mode does not establish that every native tool is disabled. `--allowed-tools` grants approvals. [Headless](https://qwenlm.github.io/qwen-code-docs/en/users/features/headless/), [settings](https://qwenlm.github.io/qwen-code-docs/en/users/configuration/settings/). |
| Hermes | `hermes chat --oneshot --quiet --ignore-rules --query-file - --format stream-json` | Preserves the configured model/provider. Ignores injected rules, memory, and preloaded skills; native tools, plugins, hooks, and MCP may remain active. An empty toolsets argument is not a documented disable-all value. [CLI reference](https://hermes-agent.nousresearch.com/docs/reference/cli-commands). |
| Muse | `muse exec --prompt-file FILE --no-session-log` | Plain output avoids relying on an undocumented JSON event schema. Prompt-file input is documented; stdin `-` and blanket no-tools behavior were not established. [Configuration](https://dev.meta.ai/docs/muse-code/configuration), [extensions](https://dev.meta.ai/docs/muse-code/extending). |

**These controls are not an operating-system sandbox.** A temporary working
directory and a filtered environment do not block a native agent from reading
its user configuration, loading configured hooks/plugins, or accessing files and
networks with the service account's authority. A read-only/ask mode can still
execute reads or other allowed tools. MiroFish asks for text-only inference and
validates returned simulation actions before dispatching them, but output
validation cannot undo a native tool that already ran. Use a restricted wrapper
or container if your deployment requires stronger isolation, particularly for
providers without a documented no-tools mode.

Native presets do not add force, YOLO, or allow-all flags. Some upstream headless
modes are automatically permissive nonetheless, as noted for Kimi. Review the
installed CLI's effective configuration before enabling live research workloads.

In this checkout, Claude and Pi use explicit tool-disabling flags; Kimi and
OpenCode receive temporary restricted agent profiles. Gemini receives an admin
deny policy and project settings disabling hooks and skills; existing managed
policies can take precedence. Grok receives a built-in allowlist followed by a
matching denylist and a separate MCP denial. Copilot denies shell, read, write,
URL, and memory permissions, but only its built-in MCP servers are disabled by
the preset. Devin receives a temporary permissions/config override, Cursor uses
ask mode, and Droid disables hooks. Antigravity uses its existing permission
configuration. Qwen uses its documented safe mode. Hermes uses `--ignore-rules`
to suppress injected rules, memory, and preloaded skills while preserving its
configured model/provider; its safe mode would discard that provider configuration.
Hermes user plugins, hooks, MCP servers, and native tools may therefore remain active.
Muse uses
`--no-session-log`; that option does not disable tools. These differences are why
the native presets remain experimental.

### Kimi and OpenCode version boundaries

The `kimi` preset targets the Node.js `@moonshot-ai/kimi-code` generation with
`~/.kimi-code` storage and Markdown agent profiles. Legacy Python `kimi-cli` uses
`~/.kimi`, `--print`, and different profile/options semantics. Do not mix their
flags or files. Follow the [official migration guide](https://www.kimi.com/code/docs/en/kimi-code-cli/guides/migration.html)
or use a wrapper for the legacy CLI.

The `opencode` preset targets V2 (`@opencode/cli`). Its configuration uses
`agents`, `permissions` arrays, and `mcp.servers`. V1 uses `agent`, `permission`,
and a flat `mcp` map, with different timeout meanings. A V1 installation needs a
wrapper or an upgrade; a successful executable lookup alone does not establish
V2 compatibility. See [V2 configuration](https://opencode.ai/v2/docs/config/).

## Use a custom wrapper

`AGENT_COMMAND_JSON` replaces the selected non-Codex preset. This is the escape
hatch for a pinned older CLI, an enterprise launcher, provider-specific isolation,
or a different machine protocol:

```dotenv
LLM_PROVIDER=hermes
AGENT_COMMAND_JSON=["/absolute/path/to/mirofish-inference-wrapper","--profile","research"]
AGENT_TIMEOUT_SECONDS=180
```

The value must be a nonempty JSON array of nonempty string arguments. MiroFish
does not run a shell, expand shell variables in those arguments, interpolate a
prompt placeholder, or append native CLI flags. Use absolute paths because the
wrapper runs in a temporary working directory.

The wrapper contract is:

1. Read the full UTF-8 prompt from stdin until EOF. It includes the required JSON
   Schema and conversation. Do not depend on terminal input or an approval prompt.
2. Read `MIROFISH_AGENT_PROVIDER` and `MIROFISH_AGENT_MODEL` if needed; the latter
   is empty when no `AGENT_MODEL` is set. Explicitly selected environment names
   in `AGENT_ENV_PASSTHROUGH` are also available.
3. Call your selected provider and normalize its result. Write exactly one raw
   JSON object matching the supplied schema to stdout. Send logs to stderr.
4. Exit nonzero on authentication, quota, model, transport, or decoding failure.
   Do not silently return a fabricated answer or change providers.

A normal assistant response has this envelope:

```json
{"content":"The requested answer.","tool_calls":[]}
```

When the supplied conversation permits a simulation action, its representation
is data for MiroFish to validate and execute:

```json
{"content":"","tool_calls":[{"name":"an_allowed_function","arguments":"{\"example\":\"value\"}"}]}
```

`arguments` is a JSON-encoded **string**. Function names and argument schemas must
match those supplied for that request. Do not execute these simulation actions
through the native CLI. The wrapper must also support graph requests, whose
envelope is different:

```json
{"json":"{\"field_required_by_this_request\":\"value\"}"}
```

The inner `json` string must contain JSON matching the graph request's schema.
The examples show structure only; they are not valid answers for every request.
Do not add a provider's outer `result`/`response` envelope, Markdown fences, usage
reports, or JSONL events to wrapper stdout.

## Check the connection

Run checks from the repository root, substituting any provider ID from the table:

```sh
uv run --project backend python backend/scripts/check_agent.py --provider gemini
```

The default check validates local configuration and executable availability. It
does not establish that login, quota, model access, version-specific options, or
real model output work. Opt in to a real inference check after completing login:

```sh
uv run --project backend python backend/scripts/check_agent.py --provider gemini --live
uv run --project backend python backend/scripts/check_agent.py --provider gemini --live --oasis
```

Live checks use the chosen account and can consume quota or incur charges. Check
each selected provider separately, including a `GRAPH_LLM_PROVIDER` override.
A basic live check does not validate an entire research run. The OASIS check
creates a temporary local two-agent simulation and checks that both agents
recorded posts. The basic live check covers text, JSON, a validated simulation
action, and a graph extraction envelope without requiring a graph database.

If a command is missing, confirm the executable name and service `PATH`. If a
flag is rejected or output cannot be decoded, compare installed help with the
linked reference and use a version-appropriate wrapper. For login/model/quota
errors, repair the selected CLI's own setup; there is no automatic provider
fallback. Increase execution and queue timeouts independently when a legitimate
request or queue needs longer, and keep all cooperating processes on the same
absolute lock path when overriding it.
