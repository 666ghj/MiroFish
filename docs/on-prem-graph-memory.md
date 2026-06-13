# On-Premise Graph Memory

Mirofish now uses a graph-memory adapter layer. The default backend remains Zep Cloud, so existing behavior does not change unless the backend is explicitly switched.

## Default: Zep Cloud

```env
GRAPH_MEMORY_BACKEND=zep_cloud
ZEP_API_KEY=...
```

## On-premise: Graphiti Bridge + FalkorDB

Start the local graph-memory services:

```bash
docker compose --profile graphiti up -d graphiti-falkordb graphiti-bridge
```

Switch Mirofish to the on-premise backend:

```env
GRAPH_MEMORY_BACKEND=graphiti_bridge
GRAPHITI_BRIDGE_URL=http://graphiti-bridge:8008
GRAPHITI_MODEL_NAME=gpt-5.4-mini
GRAPHITI_EMBEDDING_MODEL_NAME=text-embedding-3-small
```

Then rebuild/restart Mirofish:

```bash
docker compose build mirofish
docker compose up -d mirofish
```

The Graphiti bridge runs in a separate container so its dependencies do not conflict with OASIS. FalkorDB data is stored in the `graphiti_falkordb_data` Docker volume.

Health checks:

```bash
curl http://127.0.0.1:8008/health
curl http://localhost:5001/health
```
