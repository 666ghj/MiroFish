# My Own Researcher: setup, storage, and recovery

My Own Researcher is an independent [MiroFish](https://github.com/666ghj/MiroFish) fork under [AGPL-3.0](../LICENSE). It retains MiroFish's source → graph → simulation → report → interaction workflow and adds a local Graphiti/Neo4j platform, Codex inference, and recovery controls. See the [README](../README.md) for an overview.

The graph database, ingestion journal, embeddings, and reranking run locally. Language inference uses your ChatGPT-authenticated Codex CLI and sends source and simulation text to OpenAI. It consumes your account's available allowance. Local mode needs neither a Zep account nor an LLM API key, but it still requires network access and is not unlimited inference.

## Installation

Requirements: macOS, Linux, or WSL, Node.js 22.12+, uv, Python 3.11–3.12, Docker with Compose, and an installed [Codex CLI](https://learn.chatgpt.com/docs/cli). Docker must be running. From a checkout of this repository:

```sh
npm ci
npm ci --prefix frontend
uv sync --project backend --frozen
uv sync --project graph_platform --frozen
python3 scripts/configure_local_graph.py
codex login
npm run graph:up
npm run dev
```

Choose **Sign in with ChatGPT** during Codex login. The CLI and login must be available to the same OS user who runs the app. See the [Codex provider guide](codex-provider.md) for adapter settings.

The configuration helper selects local/Codex mode and generates credentials in the ignored `.env` with owner-only permissions, preserving existing secrets. Keep the generated Neo4j password: changing it in `.env` does not change an initialized database's password.

Open **http://localhost:3000/?lang=en**. Wait for graph readiness before uploading; the first graph-service start downloads two pinned neural search models. Docker runs Neo4j, while the app, graph service, and Codex run on the host. Use `compose.local-graph.yml` for Neo4j; this setup does not provide a full-application container image.

For later starts, use `npm run graph:up` then `npm run dev`. Stop the app with Ctrl+C. `npm run graph:down` stops Neo4j while preserving its data. Keep the services running if active ingestion or memory saving needs to finish.

## Components and data

| Component | Address or location | Purpose |
| --- | --- | --- |
| Vue interface | `localhost:3000` | Upload, graph, simulation controls, reports, interaction |
| Flask/OASIS backend | `127.0.0.1:5001` | Projects, agents, simulation, and reports |
| Local graph service | `127.0.0.1:5002` | Compatibility API and durable ingestion |
| Neo4j Community 5.26 | `127.0.0.1:7687` / `127.0.0.1:7474` | Graphiti entities, temporal facts, and provenance |
| SQLite journal | `backend/uploads/local_graph/` | Graph identity, ontology, jobs, progress, and errors |
| Projects and runs | `backend/uploads/` | Documents, profiles, simulation state, checkpoints, and reports |
| Shared Codex transport | `shared/codex-transport/` | Cross-process request serialization and cancellation |

Graph API documentation is available at http://127.0.0.1:5002/docs; mutations require the private `X-Research-Token` header. Keep that token private.

Neo4j uses the `my-own-researcher_graph_data` Docker volume under the default Compose project name. Back up that volume **and** `backend/uploads/` while the app and database are stopped. Adding `-v` to a Compose shutdown deletes volumes and their graph data.

Graphiti has its own Python environment because its Neo4j dependency conflicts with the OASIS dependency pin. The backend facade supports the graph, ontology, batch, episode, node, edge, and search calls used by this app. It is not a complete implementation of Zep's commercial API or hosted platform.

Local search uses `all-MiniLM-L6-v2` (384 dimensions) and `cross-encoder/ms-marco-MiniLM-L6-v2`, with pinned revisions. These models target English text. Community generation and Graphiti telemetry are disabled. Embeddings and reranking have no cloud fallback; graph extraction still uses Codex inference.

## Effort, stopping, and reports

Step 3 offers **Quick (25%)**, **Moderate (50%)**, and **Full (100%)** of the configuration's planned rounds. Full is selected by default. Counts round up to at least one round and appear before starting. A previous explicit choice is remembered for that simulation. These percentages do not promise equivalent reductions in runtime or allowance: preparation, agents, model speed, and graph ingestion also affect the work.

**Stop simulation** opens a confirmation warning that an in-flight action may be interrupted. Saved actions remain available. Reporting becomes available only after the simulation process stops and graph memory finishes saving. **Finalization can still make AI calls and consume allowance**, so keep the services running and wait for it to complete. A deliberate stop is not automatically restarted as a failed run.

A partial report identifies the selected budget and recorded coverage. A zero-action run explicitly has no simulated evidence. Reports and simulated conversations are model-generated; evaluate their assumptions and source support before using their conclusions.

When a report is complete, use **Download PDF** below its title in Step 4 or the final interaction view. PDF rendering uses the saved report and runs locally without AI calls. Failed downloads expose an error and the same three-attempt recovery control. The Markdown download endpoint remains available.

## Recovery behavior

Supported workflow failures receive up to **three automatic retries after the initial failure**, with delays of **2, 5, and 10 seconds** while the page is open. The error and retry count remain visible, followed by a manual recovery control if retries are exhausted. Counts survive refresh within the same browser tab. Closing the page stops browser-driven retry scheduling; backend work may continue. Refresh restores saved state and reconnects to active work.

| Stage | What recovery preserves | Boundary |
| --- | --- | --- |
| Upload and document analysis | Upload retries reuse the project; ontology retries use the saved document | An invalid or unsupported source still requires correction |
| Local graph build | Existing graph, completed chunks, and extraction receipts | Resume retries unfinished chunks; terminal Zep Cloud batches do not support this local mechanism |
| Agent preparation | Generated personas, agent IDs, completed configuration, and frozen entity snapshot | Changed inputs or ambiguous older persona matches require explicit regeneration |
| Running simulation | Saved preparation; refresh reconnects to the current process | A failed process restart begins at round 1, not mid-round |
| Memory finalization | Episode IDs and completed graph receipts | Retry requeues failed/canceled local episodes; ambiguous failed uploads remain explicit errors |
| Report generation | Report ID, outline, and completed sections | Only unfinished sections are regenerated; an older run's report is not reused for a new run |
| Interaction | Successful responses and answered survey agents | A lost response may repeat a request on retry because completion is unknown |

Simulation restarts archive earlier runtime files under `backend/uploads/simulations/<id>/attempts/`. Graph memories already written by an earlier attempt remain in the graph. A durable memory checkpoint allows a fully uploaded run to finish finalization after an app restart; this does not restore the OASIS process itself.

Deletion is refused while graph ingestion or an app consumer is active. Finish or stop that work before resetting. Deleting a project deletes its own graph, without deleting other graphs. Existing projects retain their provider; changing `GRAPH_PROVIDER` does not migrate them. Create a new local project from the original document when switching from Zep Cloud.

## Diagnostics

A readiness check makes no Codex inference calls:

```sh
uv run --project backend python backend/scripts/check_local_graph.py
```

An optional live check creates and retains a small synthetic project, builds its graph, prepares agents, runs one Reddit round, interviews an agent, and generates a report. **It consumes Codex allowance.**

```sh
uv run --project backend python backend/scripts/check_local_graph.py --live
```

Progress is stored in `backend/uploads/local-graph-smoke.json`; rerunning resumes completed stages. Use `--state` with a separate local file for a separate check. These generated files are local runtime data, not published example results.

For development checks:

```sh
uv run --project backend python -m pytest backend/tests -q
uv run --project graph_platform python -m pytest graph_platform/tests -q
node --test frontend/tests/*.test.mjs
npm run build
```

If the graph is unavailable, check Docker, `npm run graph:up`, and the graph process's console output. `/api/system/status` reports readiness. If Codex fails, check `codex login status`, model access, and your allowance. Failures do not trigger a paid API fallback.

`CODEX_TIMEOUT_SECONDS` bounds each inference request; graph ingestion has its own overall wait. Increasing the request timeout can help slow requests but cannot remove quota limits or guarantee completion. Restart the app after changing `.env`.

## Operating scope

Keep this **single-user service on loopback**. Run one backend process: report and graph lifecycle claims are process-local, so multiple server workers are unsupported. The development servers are intended for local use. A public multi-user service would require a separate authentication, isolation, and deployment design.

Upstream credits and license information are in the [README](../README.md#attribution-and-license). Graphiti, Neo4j, OASIS, and the search models retain their respective licenses.
