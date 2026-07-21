# On-Premise Graph Memory

This document describes the intended on-premise graph-memory setup for MiroFish. The goal is to keep the default Zep Cloud setup unchanged while allowing operators to run graph memory locally with Graphiti in a separate Docker service.

## Target architecture

MiroFish should not vendor or fork Graphiti. Graphiti stays an external service and is consumed through the graph-memory adapter layer.

```text
MiroFish application
  -> graph-memory adapter
      -> Zep Cloud adapter, default
      -> Graphiti bridge adapter, optional on-premise mode
          -> Graphiti bridge container
              -> Graphiti Core from the public Graphiti package
              -> FalkorDB container for graph storage
```

This separation keeps the MiroFish codebase small, avoids dependency conflicts with the existing backend, and makes the deployment model explicit. The Graphiti bridge container owns the Graphiti Python dependencies. MiroFish only calls the bridge through HTTP.

## Repository responsibilities

The MiroFish repository contains:

- the graph-memory provider interface;
- the default Zep Cloud implementation;
- the optional Graphiti bridge implementation;
- the `graphiti_bridge` service wrapper;
- Docker Compose wiring for the bridge and FalkorDB;
- environment variables selecting the active backend.

The MiroFish repository does not contain:

- a copied Graphiti source tree;
- local modifications to the Graphiti upstream project;
- a hard dependency on on-premise graph memory for default users.

## Backend selection

Zep Cloud remains the default backend. Existing installations continue to work with the current configuration.

```env
GRAPH_MEMORY_BACKEND=zep_cloud
ZEP_API_KEY=your_zep_api_key_here
```

On-premise mode is enabled explicitly:

```env
GRAPH_MEMORY_BACKEND=graphiti_bridge
GRAPHITI_BRIDGE_URL=http://graphiti-bridge:8008
GRAPHITI_MODEL_NAME=gpt-5.4-mini
GRAPHITI_EMBEDDING_MODEL_NAME=text-embedding-3-small
```

The bridge receives the LLM credentials through the existing OpenAI-compatible variables:

```env
LLM_API_KEY=your_api_key_here
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL_NAME=gpt-5.4-mini
```

## Docker services

The on-premise graph-memory stack uses two additional services:

| Service | Purpose |
| --- | --- |
| `graphiti-bridge` | HTTP compatibility layer used by MiroFish. It imports `graphiti-core` and translates MiroFish graph-memory calls to Graphiti operations. |
| `graphiti-falkordb` | Local graph database used by Graphiti. Data is persisted in the `graphiti_falkordb_data` Docker volume. |

Start the graph-memory services with the `graphiti` profile:

```bash
docker compose --profile graphiti up -d graphiti-falkordb graphiti-bridge
```

Then start or restart MiroFish:

```bash
docker compose build mirofish
docker compose up -d mirofish
```

For a full local stack, run:

```bash
docker compose --profile graphiti up -d
```

## Expected runtime URLs

Inside Docker Compose:

```text
MiroFish backend -> http://graphiti-bridge:8008
Graphiti bridge -> graphiti-falkordb:6379
```

From the host machine:

```text
MiroFish frontend: http://localhost:3000
MiroFish backend:  http://localhost:5001
Graphiti bridge:   http://127.0.0.1:8008
```

The bridge is bound to `127.0.0.1` on the host so it is not exposed on the network by default.

## Health checks

Check the bridge:

```bash
curl http://127.0.0.1:8008/health
```

Check the MiroFish backend:

```bash
curl http://localhost:5001/health
```

Expected bridge response:

```json
{
  "service": "graphiti-bridge",
  "status": "ok"
}
```

## Smoke-test flow

After startup, verify the complete path through the application rather than only checking container health.

1. Open `http://localhost:3000`.
2. Create a new project.
3. Add a small but meaningful source document with several named actors and relationships.
4. Generate the ontology.
5. Build the graph.
6. Confirm that the graph contains more than placeholder nodes and edges.
7. Create a simulation.
8. Run at least one round.
9. Confirm that the simulation can read from graph memory and complete without a Zep Cloud key.

For API-level validation, the same flow should cover ontology generation, graph build, simulation creation, simulation start, simulation status, graph readback, and report generation.

## Operational notes

- Use Zep Cloud for the default upstream-compatible mode.
- Use `graphiti_bridge` for local, no-cloud graph memory.
- Keep Graphiti isolated in its own container to avoid dependency conflicts.
- Keep the bridge API narrow and aligned with the MiroFish graph-memory adapter interface.
- Store graph data in the Docker volume `graphiti_falkordb_data`.
- Remove the volume only when local graph-memory data should be discarded.
- Do not expose the bridge port publicly unless an operator has added authentication and network controls.

## Fresh MacBook installation notes

For a clean on-premise installation on a new MacBook, the operator should install Docker Desktop, clone the MiroFish fork or the target branch, create `.env`, select `GRAPH_MEMORY_BACKEND=graphiti_bridge`, and start the Compose stack with the `graphiti` profile.

The installation should not require a Zep Cloud account in on-premise mode. It still requires an OpenAI-compatible LLM endpoint because Graphiti extraction and embeddings use model calls.

Recommended `.env` shape for on-premise testing:

```env
LLM_API_KEY=your_api_key_here
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL_NAME=gpt-5.4-mini

GRAPH_MEMORY_BACKEND=graphiti_bridge
GRAPHITI_BRIDGE_URL=http://graphiti-bridge:8008
GRAPHITI_MODEL_NAME=gpt-5.4-mini
GRAPHITI_EMBEDDING_MODEL_NAME=text-embedding-3-small
```

## Instructions for an AI installation agent

Use this section as the direct installation brief for an automated coding or operations agent.

Objective: install and verify MiroFish with local on-premise graph memory. Do not use Zep Cloud. Do not copy Graphiti source code into MiroFish. Run Graphiti through the existing `graphiti_bridge` Docker service and persist graph data in FalkorDB.

Steps:

1. Confirm Docker Desktop or Docker Engine is installed and running.
2. Clone the target MiroFish repository and checkout the on-premise graph-memory branch.
3. Create `.env` from `.env.example`.
4. Set `GRAPH_MEMORY_BACKEND=graphiti_bridge`.
5. Set `GRAPHITI_BRIDGE_URL=http://graphiti-bridge:8008`.
6. Set `LLM_API_KEY`, `LLM_BASE_URL`, and `LLM_MODEL_NAME` to an OpenAI-compatible model endpoint.
7. Set `GRAPHITI_MODEL_NAME` and `GRAPHITI_EMBEDDING_MODEL_NAME` if different from the defaults.
8. Start the stack with `docker compose --profile graphiti up -d --build`.
9. Verify `http://127.0.0.1:8008/health` returns status `ok`.
10. Verify `http://localhost:5001/health` returns successfully.
11. Open `http://localhost:3000` and run a complete graph-build and simulation smoke test.
12. Inspect the graph result and reject the installation if only placeholder or generic nodes are created from a rich source document.
13. Record the tested commit, `.env` backend mode, container status, and smoke-test result.

Acceptance criteria:

- The application starts from Docker Compose.
- No Zep Cloud API key is required in `graphiti_bridge` mode.
- The bridge health check succeeds.
- A project can build a graph from source documents.
- Graph nodes and edges reflect the document content.
- A simulation can be created and started against the local graph memory.
- The setup remains compatible with the default Zep Cloud mode when `GRAPH_MEMORY_BACKEND=zep_cloud` is selected.

Do not mark the installation complete if the graph build produces only a few generic nodes from a rich source document, if the simulation fails during startup, or if the application still requires `ZEP_API_KEY` while `GRAPH_MEMORY_BACKEND=graphiti_bridge` is selected.
