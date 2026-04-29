# Memory backend abstraction

This package decouples MiroFish's simulation pipeline from any specific
graph-memory provider. Application code depends only on the abstract
`MemoryBackend` interface and the provider-neutral DTOs (`Episode`,
`Node`, `Edge`, `SearchResult`, `OntologySpec`). The concrete backend is
selected at runtime via the `MEMORY_BACKEND` environment variable.

## Available backends

| `MEMORY_BACKEND=` | Provider | Cost | Setup |
|---|---|---|---|
| `zep` *(default)* | [Zep Cloud](https://www.getzep.com/) | Free tier with quota; paid above | Just set `ZEP_API_KEY` |
| `graphiti` | [Graphiti](https://github.com/getzep/graphiti) on local Neo4j | Free, unlimited | `docker compose --profile graphiti up -d` |

The default is `zep` for backward compatibility — existing deployments
need no changes after this refactor lands.

## Switching to self-hosted Graphiti

```bash
# 1. Start Neo4j
docker compose --profile graphiti up -d

# 2. Configure the backend
echo "MEMORY_BACKEND=graphiti" >> .env
echo "NEO4J_URI=bolt://localhost:7687" >> .env
echo "NEO4J_USER=neo4j" >> .env
echo "NEO4J_PASSWORD=mirofish-local" >> .env

# 3. Restart the backend
npm run dev
```

Graphiti reuses your existing `LLM_API_KEY` / `LLM_BASE_URL` /
`LLM_MODEL_NAME` for entity extraction, so no extra LLM key is needed.
Override per-task via `GRAPHITI_LLM_*` env vars if you want a cheaper
model just for extraction.

## Architecture

```
backend/app/services/memory/
├── __init__.py             # public API surface
├── base.py                 # MemoryBackend ABC + DTOs
├── exceptions.py           # MemoryBackendError + typed subclasses
├── factory.py              # MEMORY_BACKEND env var → backend instance
├── zep_cloud_backend.py    # Zep Cloud implementation (default)
└── graphiti_backend.py     # Self-hosted Graphiti implementation
```

The abstraction follows SOLID:

- **S**ingle Responsibility — each backend file implements exactly one
  provider; the ABC carries only the contract.
- **O**pen/Closed — adding a new backend (Mem0, Memgraph, etc.) means
  dropping a new file and registering it in `factory.py`. Existing
  backends and consumers are unchanged.
- **L**iskov Substitution — both backends produce the same DTO types so
  consumers cannot tell them apart.
- **I**nterface Segregation — `MemoryBackend` exposes only the 11
  operations MiroFish actually uses, not the 50+ surface of the Zep SDK.
- **D**ependency Inversion — services like `GraphBuilderService`,
  `ZepGraphMemoryUpdater`, `ZepToolsService`, `ZepEntityReader`, and
  `OasisProfileGenerator` depend on the abstract `MemoryBackend`, not
  the concrete `Zep` SDK class.

## Adding a new backend

1. Create `app/services/memory/<provider>_backend.py`.
2. Subclass `MemoryBackend` and implement all abstract methods.
3. Translate provider exceptions into `MemoryBackendError` /
   `MemoryBackendRateLimited` / `MemoryBackendQuotaExceeded` so callers
   can handle them uniformly.
4. Register your loader in `factory._REGISTRY`.
5. Add the dep to `pyproject.toml` and document the env vars in
   `.env.example`.

That is the entire integration surface — no consumer-side changes.
