# MiroFish deploy (agent.profikid.nl)

Single-host Docker deployment of the [MiroFish swarm-intelligence engine](https://github.com/666ghj/MiroFish) reforked to use **Graphiti + FalkorDB** instead of Zep Cloud.

## What you get

| URL | Service |
| --- | --- |
| `https://mirofish.agent.profikid.nl` | MiroFish web UI + API (frontend on :3000, Flask API on :5001, both inside the mirofish container) |
| `mirofish_net` (internal Docker network) | FalkorDB (in-memory graph store, port 6379) |

Traefik (running on the host as the `traefik` Docker network) auto-issues a Let's Encrypt cert for `mirofish.agent.profikid.nl`.

## Files

```
/docker/mirofish/                   <-- everything below lives here
├── docker-compose.yml              <-- mirofish + falkordb + e2e (opt-in)
├── secrets.env                     <-- LLM_API_KEY, FALKORDB creds
├── bootstrap.sh                    <-- one-time host checks
├── up.sh                           <-- build + bring up mirofish + falkordb
├── e2e.sh                          <-- run the in-container end-to-end test
├── health.sh                       <-- /health, container status, falkordb ping
├── Dockerfile.e2e                  <-- e2e test image (inherits mirofish:latest)
└── e2e_test.py                     <-- the test itself
```

## Companion: FalkorDB Browser

A separate stack at `/docker/falkordb-browser/` exposes the [FalkorDB Browser](https://github.com/FalkorDB/falkordb-browser) (v2.0.10) at **`https://falkor.agent.profikid.nl`**. It joins the same `mirofish_net` network as the sidecar so the browser UI can read every graph the MiroFish cron produces (MATCH queries, schema explorer, node editor).

To add the connection in the UI:

1. Open `https://falkor.agent.profikid.nl/`
2. On the login page, enter:
   - **Host:** `falkordb`
   - **Port:** `6379`
   - **Username / Password:** leave empty (the MiroFish FalkorDB runs without auth)
3. The browser will list all the `mirofish_*` graphs from the cron ingests.

The browser uses its own network connection (server-side) to dial `falkordb:6379`, so the host field is just an identifier — your browser doesn't need to be able to reach it.

## Deploy

```bash
ssh root@agent.profikid.nl
mkdir -p /docker/mirofish
cd /docker/mirofish
# Drop the contents of this directory here (or git clone the repo and copy deploy/ -> .)
./bootstrap.sh        # verifies docker / dns / file presence
./up.sh               # builds the image, brings up mirofish + falkordb
```

After ~90s (FalkorDB cold start + embedding model download on first build only), the URL `https://mirofish.agent.profikid.nl` should respond.

## E2E test

```bash
cd /docker/mirofish
./e2e.sh
```

This builds `mirofish-e2e:latest` (a thin layer on top of `mirofish:latest` that runs `e2e_test.py` as the entrypoint), then runs it as a one-shot container against the real `falkordb` sidecar. It:

1. Verifies FalkorDB is reachable (raw TCP probe)
2. Runs the real `GraphBuilderService` against the Iran/US/Israel OSINT briefing seed text
3. Reads back from FalkorDB via the adapter (`get_all_nodes`, `get_all_edges`)
4. Re-verifies with a raw `falkordb.FalkorDB` client (independent check)
5. Prints PASS / FAIL with node + edge counts

Expected on first run: **~8 entities, ~8 edges** in FalkorDB after the 2-chunk run (`E2E_MAX_CHUNKS=2`). Wall time ~3-4min on the first call (LLM is doing the extraction; reasoning tokens make M3 slow). Tune `E2E_MAX_CHUNKS` higher in `docker-compose.yml` to test with more seed text.

## How the refactor differs from upstream

Upstream MiroFish uses [Zep Cloud](https://www.getzep.com/) for the knowledge graph. This fork replaces it with [Graphiti](https://github.com/getzep/graphiti) (the open-source engine behind Zep) backed by [FalkorDB](https://www.falkordb.com/) (a Redis-protocol graph store). All graph operations go through a Zep-shaped facade in `backend/app/services/graphiti_service.py` so the rest of the MiroFish code (which still speaks Zep) didn't have to change.

Key wiring:

- `MinimaxLLMClient` — Graphiti's LLMClient ABC implemented against MiniMax M3 (`https://api.minimax.io/v1`). Uses the `tools` API for structured output because M3 ignores `response_format: json_object`.
- `M3RerankerClient` — chat-completion True/False reranker (M3 returns `logprobs: None`, so the stock OpenAI reranker that reads logprobs breaks).
- `HashEmbedder` — deterministic 384-dim embedder so the test image doesn't need to download the full `sentence-transformers` multilingual model. The production image still uses the real model (set `EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` in `secrets.env` to switch).
- `FalkorDriver` (from `graphiti-core[falkordb]>=0.20.0`) — the actual graph store. No Neo4j, no Bolt, just a Redis-protocol TCP socket to the sidecar.

## How to upgrade

```bash
cd /docker/mirofish
git pull                      # in the parent MiroFish repo
./up.sh --rebuild             # rebuild + restart
./e2e.sh                      # smoke-test
```

## Troubleshooting

- **FalkorDB healthcheck fails** — check `docker compose logs falkordb`. The `falkordb/falkordb:latest` image is small; first-pull can take a minute.
- **`/health` returns 200 but `/api/ontology/generate` times out** — the embedding model is downloading on first request. Wait, or run with a prebuilt `mirofish:latest` that has the model baked in (the `Dockerfile` already does this in step 4).
- **M3 returns 0 entities** — the M3 endpoint is shared; rate limiting or reasoning-token quirks can cause this. Check `docker compose logs mirofish | grep graphiti_service` and the raw LLM payloads.
- **Cert issuance stuck in Traefik** — confirm `TRAEFIK_HOST=agent.profikid.nl` and that the `traefik` Docker network exists. Traefik must be on the same network as the `mirofish` container.
