# My Own Researcher

**An independent fork of [MiroFish](https://github.com/666ghj/MiroFish), licensed under [AGPL-3.0](LICENSE).** This repository adapts MiroFish's document → graph → simulation → report workflow into a personal research workbench with selectable agent CLI inference and local Graphiti/Neo4j storage.

Upload source material, describe a question, explore how simulated agents respond, and download the resulting report. Use it to examine assumptions and possible scenarios; simulation output is generated evidence for exploration, not a guarantee of real-world predictions.

## What this fork adds

- **Your own Codex login:** use the ChatGPT-authenticated Codex CLI and your account's available allowance. No LLM API key is required in local mode, and there is no automatic paid API fallback.
- **More agent providers:** select any of the 14 additional agent CLIs below for inference, and generate provider-specific MCP connection settings.
- **Local graph storage:** Graphiti and Neo4j replace the subset of Zep operations this application uses. Local mode needs no Zep account or key.
- **English interface:** English is the default, with the inherited language selector available.
- **Recovery checkpoints:** resume unfinished graph ingestion, agent preparation, memory saving, and report sections while retaining completed work. Simulation process restarts begin at round 1; they do not resume an interrupted OASIS process mid-round.
- **Visible retries:** supported workflow failures receive up to three automatic retries after the initial failure, delayed by 2, 5, and 10 seconds while the browser page is open. Manual recovery remains available.
- **Simulation effort:** Quick uses 25% of planned rounds, Moderate 50%, and Full 100%. Full is the default; the interface shows the round count before starting.
- **Stop and report:** a confirmation warns before stopping a simulation. Saved actions can support a clearly labeled partial report after graph memory finishes saving.
- **PDF download:** download the saved report from the report or final interaction view without another AI call.
- **MCP for research agents:** use the same projects, graphs, simulations, and reports through local Streamable HTTP or stdio tools. Run the workflow without opening a browser.

**Local storage does not mean offline AI.** Document text, extracted content, and simulation conversations go to the selected CLI's configured model service (OpenAI in the default Codex setup). Its authentication, billing, and account/model limits apply; this is not free or unlimited inference. Graph finalization and report generation also make AI calls and can take time after you stop a simulation.

## Compared with the inherited MiroFish setup

This comparison describes the upstream baseline inherited by this fork, not a claim about every current upstream release.

| Area | Inherited MiroFish baseline | This fork's local setup |
| --- | --- | --- |
| Research workflow | Source documents, graph, OASIS simulation, report, interaction | Retains that workflow |
| Language inference | OpenAI-compatible API configuration | Codex or another supported agent CLI; optional API mode retained |
| Graph service | Zep Cloud credentials | Local Graphiti + Neo4j; no Zep account required |
| Interface | Upstream multilingual interface | English default and fork identity |
| Interrupted work | Existing task and run handling | Additional checkpoints, visible retries, and manual recovery |
| Run controls | Planned simulation rounds | Quick/Moderate/Full budgets and warned early stop with partial reports |
| Report export | Markdown report download | Adds locally rendered PDF download |

## Install and run

Use macOS, Linux, or WSL with Node.js 22.12+, Python 3.11–3.12, [uv](https://docs.astral.sh/uv/), Docker with Compose, and your selected agent CLI. The quickstart below uses the [official Codex CLI](https://learn.chatgpt.com/docs/cli) and your ChatGPT login. For another provider, replace the configuration and login steps using [Choose your inference provider](#choose-your-inference-provider). Docker must be running.

```sh
git clone https://github.com/Handriantog/My-Own-Researcher.git
cd My-Own-Researcher
npm ci
npm ci --prefix frontend
uv sync --project backend --frozen
uv sync --project graph_platform --frozen
python3 scripts/configure_local_graph.py
codex login
npm run graph:up
npm run dev
```

Open **http://localhost:4317/?lang=en** and wait for graph readiness before uploading. The first graph-service start downloads the local embedding and reranking models. MCP is available at **http://127.0.0.1:4318/mcp**.

The commented [`.env.example`](.env.example) explains provider settings, local credentials, and timeouts. The configuration helper defaults to `LLM_PROVIDER=codex`, preserves an existing selection, accepts `--provider`, and selects `GRAPH_PROVIDER=graphiti`. It creates private credentials in the ignored `.env` and preserves existing secrets. Each CLI owns its login credentials; do not copy them into `.env`.

Docker runs Neo4j. The frontend, backend, graph service, MCP adapter, and selected agent CLI run on the host. `npm run graph:up` uses `compose.local-graph.yml` for Neo4j only; run the application and CLI natively on the host.

For subsequent starts, run `npm run graph:up` and `npm run dev`. Stop the app with Ctrl+C; `npm run graph:down` stops Neo4j while retaining its data.

The homepage **Demo** tab opens a self-contained LoopLunch walkthrough at `/demo`: source brief, knowledge graph, generated personas, recorded discussion and the saved report. It uses bundled fictional example data and makes no backend or AI requests. To explore only the demo, run `npm run frontend` after installing frontend dependencies. The example run stopped early at round 37 of 336, with 102 recorded actions; its report describes that partial coverage.

## Choose your inference provider

Install and sign in to the CLI you have access to, under the same OS user who runs the app. Use the provider ID below for both `LLM_PROVIDER` and the MCP configuration generator. **Inference and MCP are independent:** for example, Cursor can drive research through MCP while Claude Code performs the underlying inference.

| Agent | Provider ID | Inference executable | MCP configuration destination |
| --- | --- | --- | --- |
| Codex | `codex` | `codex` | `~/.codex/config.toml` |
| Claude Code | `claude-code` | `claude` | `.mcp.json` |
| Antigravity | `antigravity` | `agy` (CLI required) | `.agents/mcp_config.json` |
| Cursor | `cursor` | `agent` | `.cursor/mcp.json` |
| Devin CLI | `devin` | `devin` | `.devin/mcp_config.json` |
| Factory Droid | `factory-droid` | `droid` | `.factory/mcp.json` |
| Gemini CLI | `gemini` | `gemini` | `.gemini/settings.json` |
| GitHub Copilot CLI | `copilot` | `copilot` | `~/.copilot/mcp-config.json` |
| Grok Build CLI | `grok` | `grok` | `~/.grok/config.toml` |
| Kimi Code | `kimi` | `kimi` (current Node.js CLI) | `.kimi-code/mcp.json` |
| OpenCode | `opencode` | `opencode` (v2) | `opencode.json` |
| Pi | `pi` | `pi` (current native MCP release) | `.pi/mcp.json` |
| Qwen Code | `qwen` | `qwen` | `.qwen/settings.json` |
| Hermes Agent | `hermes` | `hermes` | `~/.hermes/config.yaml` |
| Muse | `muse` | `muse` (Meta Muse Code) | `~/.config/muse/settings.json` |

For example, after installing and signing in to Claude Code:

```sh
python3 scripts/configure_local_graph.py --provider claude-code
uv run --project backend python backend/scripts/check_agent.py --provider claude-code
```

The second command checks configuration and executable availability **without running inference**. To verify login, text/JSON output, simulation actions, and graph response compatibility, opt into a small live check that uses your account allowance:

```sh
uv run --project backend python backend/scripts/check_agent.py --provider claude-code --live
# Optional: also exercise two agents in a temporary OASIS simulation
uv run --project backend python backend/scripts/check_agent.py --provider claude-code --live --oasis
```

Replace `claude-code` with your provider ID. In the root `.env`, optional settings for non-Codex agents are:

```dotenv
LLM_PROVIDER=claude-code
GRAPH_PROVIDER=graphiti
# AGENT_BIN=/absolute/path/to/claude
# AGENT_MODEL=an-exact-model-id-available-to-your-account
AGENT_TIMEOUT_SECONDS=600
AGENT_QUEUE_TIMEOUT_SECONDS=600
```

Restart the application after changes. Document analysis, personas, configuration, simulations, reports, and interviews use this selection. **Local Graphiti extraction follows it too**, so another CLI provider does not require a Codex login. `GRAPH_LLM_PROVIDER` can explicitly select a different graph CLI; when `LLM_PROVIDER=openai`, graph extraction keeps its existing Codex default unless overridden. `AGENT_MODEL` applies to non-Codex CLI requests; Codex retains its `CODEX_*` settings. API and boost keys never select an automatic fallback.

The new native presets are **experimental and version-sensitive**. Their command construction, parsers, and routing are tested with local fake executables; live account compatibility must be checked on your installation. CLI tool restrictions vary and are not an OS sandbox: some clients retain native tools, user configuration, hooks, or MCP discovery. See the [provider setup guide](docs/agent-providers.md) for official install/login references, exact version requirements, tool-control limitations, and the `AGENT_COMMAND_JSON` wrapper option for a different CLI version or a controlled runtime.

## Use it from another AI agent

Complete the installation above once. For research without the browser UI:

```sh
npm run graph:up
npm run dev:agent
```

This starts the backend, the configured local graph service, and MCP. Connect your agent's MCP client with **Streamable HTTP**, URL **`http://127.0.0.1:4318/mcp`**, and a **tool timeout of at least 900 seconds**. If `npm run dev` is already running, MCP is already available; do not start another backend. `npm run mcp` starts only the adapter when the backend/graph services are already running separately.

Generate the correct configuration for your client, using its provider ID from the table above:

```sh
python3 scripts/agent_mcp.py --provider claude-code
python3 scripts/agent_mcp.py --provider gemini
python3 scripts/agent_mcp.py --provider cursor --transport stdio
python3 scripts/agent_mcp.py --list
```

The generator prints configuration only. Merge its `my-own-researcher` entry into the destination listed above, preserving your other servers and settings, then restart or reload the agent. Use `--url http://127.0.0.1:YOUR_PORT/mcp` for a custom port; stdio automatically uses absolute checkout paths and resolves `uv` when available. Ask the agent to call `get_status` to verify the connection without inference. The [per-agent MCP guide](docs/agent-mcp.md) includes global locations, client-specific schemas, timeout units, and compatibility notes. Use stdio for Hermes when calls can exceed its HTTP idle limit.

For other clients that accept generic **stdio** settings, use this configuration, replacing both `/absolute/path/My-Own-Researcher` paths with your checkout:

```json
{
  "mcpServers": {
    "my-own-researcher": {
      "command": "uv",
      "args": [
        "run", "--project", "/absolute/path/My-Own-Researcher/backend", "--frozen",
        "python", "/absolute/path/My-Own-Researcher/backend/mcp_server.py"
      ]
    }
  }
}
```

Stdio launches an adapter, so the backend and graph services must still be running. Use an absolute path to `uv` if your agent's environment does not have it on `PATH`. Set the client's tool timeout separately; its configuration field varies by client.

The server advertises typed tools and a `research://workflow` resource. An agent can call `get_status`, submit text/Markdown using `create_project`, build and search the graph, prepare and run simulations, poll progress, and retrieve a report's Markdown with `get_report`. Browser-uploaded projects, including PDFs, are also available. For example, give your agent:

> Use the my-own-researcher MCP tools to research the supplied sources. Check readiness, create a project with a unique upload_id, build its graph, and prepare a Reddit-only simulation. Run a two-round pilot, wait for simulation and memory saving to finish, then generate and retrieve the report. Preserve evidence and coverage limitations. Read research://workflow for the call sequence and recovery rules.

See the **[MCP guide](docs/mcp.md)** for tool names, example inputs, polling, retries, and access from another machine through SSH. Inference tools use your configured provider and account allowance. Defaults are web **4317**, MCP **4318**, backend **5001**, and graph **5002**; override `FRONTEND_PORT`, `MCP_PORT`, or `FLASK_PORT` in the root `.env`. The web server fails clearly if its port is occupied instead of silently choosing another.

## Start a research run

1. Upload a short PDF, Markdown, or text file and describe the question you want to explore.
2. Build the graph and prepare the simulation's agents and configuration.
3. Review the round budget and choose Quick, Moderate, or Full before starting.
4. Let the simulation finish, or use **Stop simulation** and confirm the warning. Keep the services running while saved activity is added to graph memory.
5. Generate the report, inspect its evidence and coverage notes, and use **Download PDF**. Continue with agent or report interaction when available.

Start with a small source and a few agents. CLI requests are serialized, so larger graphs, more agents, and additional rounds can take substantial time and allowance. Effort percentages scale round counts, not total runtime or token consumption.

## Storage and operating limits

This is a **single-user local application**. Keep services on loopback and run one backend process; multiple backend workers and shared public hosting are unsupported. Local files and graph storage remain on your machine, but inference content goes to your CLI's configured model provider.

Projects and checkpoints live in `backend/uploads/`; Neo4j data lives in its Docker volume. Back up both together. The graph compatibility layer implements the operations this app needs, not the complete Zep product. Existing projects retain their graph provider; changing configuration does not migrate their data.

See [setup, storage, and recovery](docs/my-own-researcher.md) and the [Codex provider guide](docs/codex-provider.md) for configuration, diagnostics, and limitations.

## Attribution and license

My Own Researcher builds on **[MiroFish](https://github.com/666ghj/MiroFish)** by the MiroFish team. The upstream project and its contributors deserve credit for the original interface and research simulation workflow. This fork retains the [GNU Affero General Public License v3.0](LICENSE).

The simulation engine uses **[OASIS](https://github.com/camel-ai/oasis)** from CAMEL-AI. Local graph processing uses **[Graphiti](https://github.com/getzep/graphiti)** and **[Neo4j](https://github.com/neo4j/neo4j)**. Dependencies and models retain their respective licenses. This fork is independently maintained and does not imply endorsement by those projects or OpenAI.

[中文说明](README-ZH.md) · [Upstream MiroFish documentation](https://github.com/666ghj/MiroFish#readme)
