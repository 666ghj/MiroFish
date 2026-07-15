# Stock Swarm throughput PoC

This CLI assigns one stock to each agent.

Round 1 creates independent opinions. Later rounds give every agent its own prior opinion plus the prior opinions of fixed, directed peers. One LLM request runs per agent per round.

## Dry run

```bash
cd backend
uv run python scripts/run_stock_swarm.py \
  --dry-run --agents 8 --rounds 3 --peers 2 --concurrency 4 \
  --output ../artifacts/dry-run.json
```

## Live run

Set secrets in the environment. Do not add them to `.env` in Git.

```bash
export CLICKHOUSE_URL=https://clickhouse.example:8443
export CLICKHOUSE_USER='<clickhouse-user>'
export CLICKHOUSE_PASSWORD=...
export CLICKHOUSE_DATABASE=fundamentals
export LLM_BASE_URL=http://openai-compatible-endpoint:8080/v1
export LLM_API_KEY=...
export LLM_MODEL_NAME=glm-5.2-fp8

cd backend
uv run python scripts/run_stock_swarm.py \
  --agents 128 --rounds 2 --peers 3 --concurrency 128 \
  --max-tokens 512 --opinion-words 80 --reasoning-effort none \
  --output ../artifacts/live.json
```

`reasoning-effort none` is important on Taurus-style GLM endpoints. Otherwise a short token budget can be consumed entirely by `reasoning_content` before the JSON opinion appears.

## Data

- `backend/sql/ticker_universe.sql` selects active Mid, Large, and Mega companies.
- `backend/sql/holding_quarter.sql` finds the latest globally complete 13F quarter.
- `backend/sql/dossier.sql` deduplicates restatements by `datekey`, keeps MRY annual values separate from MRT trailing values, computes conventional sector percentiles, and adds quarterly and ownership trends.

ClickHouse preparation is timed separately from LLM execution. Dossiers load with at most 16 concurrent ClickHouse queries.

## Metrics

All token counts come from `response.usage`.

- `input_tokens_per_sec`: prompt tokens divided by round wall time.
- `output_tokens_per_sec`: completion tokens divided by round wall time.
- `transport_successes`: HTTP/API calls that returned successfully.
- `valid_opinions`: responses containing a parsed opinion with a `view`.
- `successes` and `failures`: valid and invalid opinions, not merely HTTP status.
- `latency_ms`: end-to-end request latency, including local semaphore wait and retries.
- `metrics.setup`: ClickHouse preparation time and selected 13F quarter.
- `metrics.rounds`: isolated metrics for each P2P round.
- `metrics.total`: all LLM rounds combined. It excludes ClickHouse preparation.

The output JSON contains metrics, topology, opinions, parse failures, and request failures. Hosts are redacted by default. Use `--include-hosts` only for local evidence. Credentials are never written.

## Tests

```bash
cd backend
uv run pytest -q
```
