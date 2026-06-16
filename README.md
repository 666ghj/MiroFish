# MiroFish Neo4j Edition

English | [中文](./README-ZH.md)

This project is a secondary development based on the original open-source repository [666ghj/MiroFish](https://github.com/666ghj/MiroFish).

The main change in this edition is replacing the Zep Cloud graph-memory dependency with a local Neo4j backend, so the project can run with local graph storage and local graph search while keeping the original MiroFish multi-agent simulation workflow.

The project follows the same source license as the original repository: **AGPL-3.0**.

## What Changed

- Replaced Zep Cloud graph storage/search with local Neo4j adapters.
- Added Neo4j graph builder, entity reader, memory updater, and search service.
- Added local graph service factory for switching graph backends.
- Improved report-agent search tool output for:
  - Deep Insight
  - Panorama Search
  - Quick Search
- Added LLM 429 rate-limit waiting and retry logic.
- Added deterministic football score probability reporting for football simulation scenarios.
- Added local Neo4j Docker Compose configuration.

## Features

- Upload seed documents and build a graph from extracted entities and relations.
- Generate simulation agents and social behavior profiles.
- Run dual-platform social simulation.
- Generate prediction reports with graph search tools.
- Use local Neo4j as the default graph backend.
- Produce football score probabilities when the scenario contains football/score/Poisson/lambda signals.

## Architecture

```text
frontend/                 Vue + Vite frontend
backend/                  Flask backend
backend/app/services/     Simulation, report, graph, and adapter services
backend/app/services/adapters/
                           Neo4j graph adapter implementation
backend/app/utils/neo4j/  Neo4j driver and schema helpers
locales/                  i18n text
static/                   Static images
```

## Requirements

- Node.js 18+
- Python 3.11 - 3.12
- uv
- Docker, if you want to run Neo4j with Docker Compose
- An OpenAI-compatible LLM API key

## Environment Configuration

Copy the example environment file:

```bash
cp .env.example .env
```

Minimal local configuration:

```env
LLM_API_KEY=your_api_key_here
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL_NAME=qwen-plus

GRAPH_BACKEND=neo4j
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=password
NEO4J_DATABASE=neo4j
```

Optional LLM rate-limit settings:

```env
LLM_RATE_LIMIT_MAX_ATTEMPTS=20
LLM_RATE_LIMIT_INITIAL_DELAY=30
LLM_RATE_LIMIT_MAX_DELAY=180
LLM_RATE_LIMIT_BACKOFF_FACTOR=1.5
```

## Start Neo4j

Use the included local Neo4j Compose file:

```bash
docker compose -f docker-compose.neo4j.yml up -d
```

Default endpoints:

- Neo4j Browser: `http://localhost:7474`
- Bolt URI: `bolt://localhost:7687`
- Default account: `neo4j / password`

Make sure the password matches `NEO4J_PASSWORD` in `.env`.

## Install Dependencies

Install frontend and backend dependencies:

```bash
npm run setup:all
```

Or install them separately:

```bash
npm run setup
npm run setup:backend
```

## Run the Project

Run frontend and backend together:

```bash
npm run dev
```

Service URLs:

- Frontend: `http://localhost:3000`
- Backend API: `http://localhost:5001`

Run services separately:

```bash
npm run backend
npm run frontend
```

## Docker

The root `docker-compose.yml` can start the app container. For local graph storage, start Neo4j separately with:

```bash
docker compose -f docker-compose.neo4j.yml up -d
```

Then run the application:

```bash
docker compose up -d
```

## Basic Workflow

1. Start Neo4j.
2. Start the backend and frontend.
3. Open `http://localhost:3000`.
4. Create or open a project.
5. Upload seed documents.
6. Build the graph.
7. Generate simulation configuration.
8. Run simulation.
9. Generate the prediction report.

## Report Search Tools

The report agent can call several graph-search tools:

- **Deep Insight**: decomposes a question and gathers supporting graph facts.
- **Panorama Search**: returns a broad view of graph entities and facts.
- **Quick Search**: performs lightweight keyword search over graph facts and nodes.
- **Interview Agents**: uses simulation/graph context for agent-oriented responses.

In the Neo4j edition, tool outputs are rendered in the text format expected by the frontend, so the report timeline can display facts, entities, and relation chains directly.

## Football Score Probability

For football simulation prompts, the backend can extract usable signals such as `lambda_home`, `lambda_away`, xG, or prose score priors from simulation config/actions and generate:

- Home/draw/away probabilities
- Top scorelines
- Expected goals
- Score distribution matrix

This is injected into the report as a deterministic computed section so the report does not depend only on LLM prose.

## Logs

Common local log files:

```text
log/backend-restart.out.log
log/backend-restart.err.log
log/frontend-direct.out.log
log/frontend-direct.err.log
backend/uploads/reports/<report_id>/agent_log.jsonl
backend/uploads/reports/<report_id>/console_log.txt
```

## Troubleshooting

### Neo4j connection failed

Check that Neo4j is running and the `.env` values match the Docker Compose credentials.

```bash
docker compose -f docker-compose.neo4j.yml ps
```

### LLM returns 429

The backend includes rate-limit retry logic. It will sleep and retry according to the `LLM_RATE_LIMIT_*` settings.

### Search tools return empty results

Make sure the project has built a graph successfully. The Neo4j search tools search graph facts, node names, and node summaries.

### Football report has no score prediction

Make sure the simulation requirement or seed data includes football-related terms and usable scoring priors such as `lambda_home`, `lambda_away`, xG, or expected goals.

## License

This project follows the original repository license: **AGPL-3.0**.

If you deploy, distribute, or provide this software over a network, please comply with the AGPL-3.0 requirements.

## Acknowledgements

This project is based on the original [666ghj/MiroFish](https://github.com/666ghj/MiroFish). Thanks to the original authors and contributors for their open-source work.
