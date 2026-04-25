# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MiroFish is an AI-powered multi-agent simulation platform. It extracts entities from user-provided documents (PDF/MD/TXT), builds a knowledge graph (via Zep Cloud), generates agent personas, runs social interaction simulations (via OASIS/CAMEL-AI), and produces analytical reports.

## Commands

### Setup
```bash
cp .env.example .env          # Configure API keys before first run
npm run setup:all             # Install Node + Python dependencies (root, frontend, backend)
npm run setup                 # Node deps only
npm run setup:backend         # Python deps only (uv venv)
```

### Development
```bash
npm run dev                   # Start both frontend (port 3000) & backend (port 5001) concurrently
npm run frontend              # Frontend only
npm run backend               # Backend only (uv run python run.py)
```

### Build
```bash
npm run build                 # Vite production build of frontend
```

### Testing
```bash
pytest                        # Run Python tests (pytest + pytest-asyncio available in venv)
```

Python 3.11–3.12 required (strict constraint). Node 18+ required.

## Architecture

### Overview
Full-stack monorepo: **Vue 3 SPA** (frontend, port 3000) + **Flask API** (backend, port 5001). Vite proxies all `/api/*` requests to the backend.

### 5-Step Workflow Pipeline
1. **Graph Build** — Upload seed documents → entity/relationship extraction via LLM → Zep Cloud knowledge graph
2. **Environment Setup** — Agent persona generation (OASIS profiles) from the graph
3. **Simulation** — OASIS multi-agent simulation (Twitter + Reddit platforms) run as a subprocess
4. **Report** — ReportAgent (LLM with tool calling) analyzes simulation output
5. **Interaction** — Live chat with simulated agents

### Key Backend Patterns
- **`models/project.py`** — `ProjectManager` singleton. Projects persist as `uploads/projects/{uuid}/project.json` + files. The server is the source of truth; frontend only holds a `projectId`.
- **`models/task.py`** — `TaskManager` singleton. In-memory async task tracking (PENDING → PROCESSING → COMPLETED|FAILED). Frontend polls `GET /api/.../task/{taskId}`.
- **`services/simulation_runner.py`** — Spawns OASIS as a subprocess. Communicates via IPC files at `/tmp/mirofish_sim_{id}_*.json`. Atexit cleanup registered.
- **`services/report_agent.py`** — Multi-turn LLM agent with tool use (Zep queries). Max 5 tool calls, 2 reflection rounds.
- **`utils/locale.py`** — Thread-local locale storage. Reads `Accept-Language` header from requests; falls back to thread-local for background workers (default: `zh`).

### Key Frontend Patterns
- **`api/index.js`** — Axios instance with retry (`requestWithRetry`, 3 attempts, exponential backoff) and response interceptor. Auto-injects `Accept-Language` header from current locale.
- **`store/pendingUpload.js`** — Lightweight reactive state (no Vuex/Pinia) for deferred file uploads between views.
- Views are self-contained; no shared state beyond `projectId` in the URL route.

### i18n
Translation files at `/locales/{en,zh}.json` are shared by both frontend and backend. The frontend uses `vue-i18n` v11 with `localStorage` persistence. The backend reads the `Accept-Language` header. `/locales/languages.json` also contains per-language LLM prompt instructions (to force LLM output language).

### Configuration (`backend/app/config.py`)
Required environment variables (from `.env`):
- `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL_NAME` — any OpenAI-compatible API (default: Qwen-plus via Alibaba Bailian)
- `ZEP_API_KEY` — Zep Cloud memory graph
- Optional: `LLM_BOOST_API_KEY`, `LLM_BOOST_BASE_URL`, `LLM_BOOST_MODEL_NAME` — faster secondary LLM

## Git Remotes
- `origin` — this fork: `https://github.com/jaumemir/MiroFish`
- `upstream` — original project: `https://github.com/666ghj/MiroFish`

To cherry-pick from upstream branches or PRs:
```bash
git fetch upstream
git cherry-pick <commit-sha>
# or: git merge upstream/<branch-name>
```
