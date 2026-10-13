# Codex inference in My Own Researcher

This MiroFish fork can use your **ChatGPT-authenticated Codex CLI** for document analysis, graph extraction, persona/configuration generation, simulation decisions, reports, and interviews. The local setup combines this adapter with Graphiti/Neo4j and needs **no LLM API key or Zep account**. See the [complete setup guide](my-own-researcher.md).

The CLI runs locally, but inference runs through OpenAI. Source text and simulation conversations are sent to OpenAI and use your account's available allowance. Account and model limits still apply; this is neither offline nor unlimited inference. There is no automatic fallback to a paid LLM API.

## Setup

Install the [official Codex CLI](https://learn.chatgpt.com/docs/cli), then run:

```sh
codex login
codex login status
```

Choose **Sign in with ChatGPT**. This adapter requires the status to report `Logged in using ChatGPT`; API-key-only login is rejected. See the [official authentication guide](https://learn.chatgpt.com/docs/auth). Codex manages credentials and refresh; do not copy its authentication tokens into the app's `.env`.

For the normal local setup, run `python3 scripts/configure_local_graph.py` from the repository root. It selects:

```dotenv
LLM_PROVIDER=codex
GRAPH_PROVIDER=graphiti
```

It also generates the private local graph token and Neo4j password. Start Neo4j with `npm run graph:up`, then start the application with `npm run dev`.

Optionally set `CODEX_MODEL` to a model available to your account. If omitted, the CLI's built-in default is used. User Codex configuration is intentionally ignored for these inference jobs. `LLM_MODEL_NAME` and the API/boost keys do not choose the model in Codex mode. Restart the app after configuration changes.

The adapter uses POSIX process and locking APIs and targets macOS/Linux. Native Windows and a full-application Docker deployment are unsupported for this provider; use a Linux environment such as WSL on Windows. The CLI and ChatGPT login must belong to the same OS user who runs the application.

## Verify the adapter

From the repository root:

```sh
uv run --project backend python backend/scripts/check_codex.py --live --oasis
```

This uses your account's allowance. It checks text, JSON, and two agents creating posts in a temporary OASIS Reddit database without requiring Zep. Passing verifies the model/action integration, not the complete source-to-report workflow. The [workbench guide](my-own-researcher.md#diagnostics) describes the separate local graph and end-to-end checks.

## How requests run

The adapter passes the per-agent conversation through stdin to an ephemeral `codex exec` session, with a JSON Schema for the response envelope. Simulation function decisions are validated against the available action schemas and returned to CAMEL, which executes them in OASIS. This compatibility adapter is not native Chat Completions transport; agent behavior can differ from the API provider.

Requests run in temporary directories with user/project configuration, shell tools, plugins, hooks, browser access, and child agents disabled. The app checks Codex login status without reading its credential store. A process supervisor terminates a request if its parent disappears; execution timeouts and cancellation also terminate it. Temporary prompt/output artifacts are removed after each request.

A shared lock allows **one request at a time** across backend threads, graph work, and simulation processes. CLI startup and instruction overhead can make this slower and less allowance-efficient than direct API inference. Start with a short document, a few agents, and a small round budget. Quick/Moderate/Full changes simulation rounds, not Codex reasoning effort.

| Setting | Adapter default | Purpose |
| --- | --- | --- |
| `LLM_PROVIDER` | `openai` if unset; setup selects `codex` | Choose the inference adapter |
| `CODEX_BIN` | `codex` | Executable name or absolute path |
| `CODEX_MODEL` | Unset | CLI built-in default or an available explicit model |
| `CODEX_TIMEOUT_SECONDS` | `180` | Execution timeout per CLI command |
| `CODEX_QUEUE_TIMEOUT_SECONDS` | `600` | Maximum wait for the shared request lock |
| `CODEX_LOCK_PATH` | `<repository>/backend/uploads/.codex/requests.lock` | Absolute lock path shared by participating processes |

API temperature and output-token cap arguments are ignored by this adapter. Execution deadlines bound time, not tokens. Streaming and multiple completion choices are rejected. CAMEL history budgeting uses an approximate tokenizer with a conservative 32,768-token budget; this is an adapter budget, not a statement about the selected model's context capacity. Oversized requests fail instead of silently dropping conversation history.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| CLI not found | Install Codex or set `CODEX_BIN` to the executable visible to the backend |
| ChatGPT login required | Run `codex login` as the OS user who starts the app |
| Usage limit reached | Wait for allowance to reset or reduce workload; no paid API fallback occurs |
| Queue timeout | Reduce simultaneous work or increase `CODEX_QUEUE_TIMEOUT_SECONDS` |
| Request timeout | Shorten the input or increase `CODEX_TIMEOUT_SECONDS`, then restart the app |
| Invalid action or JSON | The adapter rejected unusable output; retry with a model available to your account that supports the needed structured response |
| Unsupported CLI option | Update the CLI and rerun the adapter check; this integration depends on CLI flags and output events |
| Graph unavailable | Check Docker, Neo4j, and the local graph service; Codex login does not start them |

Stopping a simulation does not eliminate all remaining model work: saving recorded actions into graph memory and generating a partial report can still require Codex requests. Wait for finalization before requesting the report.

## Optional API and Zep modes

To use an OpenAI-compatible API explicitly, set `LLM_PROVIDER=openai`, configure `LLM_API_KEY`, `LLM_BASE_URL`, and `LLM_MODEL_NAME`, and restart. Local graph extraction still uses its Codex transport, so Graphiti mode continues to require Codex login.

To use Zep Cloud explicitly, set `GRAPH_PROVIDER=zep` and provide `ZEP_API_KEY`. Codex can provide language inference alongside Zep, but Codex authentication does not authorize Zep. Existing projects retain their provider; switching configuration does not migrate graph data.

This adapter is for each user's own local installation. Keep services on loopback with one backend process; shared public hosting requires a separate design.
