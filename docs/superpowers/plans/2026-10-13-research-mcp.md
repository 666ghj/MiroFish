# Research MCP Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the existing local research workflow usable by MCP agents and document operation on distinct local ports.

**Architecture:** A separate MCP adapter proxies typed tools to the existing single Flask backend. Both HTTP and stdio use the same tool definitions and backend state.

**Tech Stack:** Python, official MCP Python SDK v1, httpx, pytest, Node/Vite.

**Spec:** `docs/superpowers/specs/2026-10-13-research-mcp-design.md`

## Global Constraints

- Preserve Python 3.11–3.12 and the existing local/Codex/Graphiti architecture.
- Web port 4317; MCP loopback HTTP port 4318; existing backend and graph ports remain 5001/5002.
- No automatic mutation retries, shell tools, arbitrary file reads, or duplicate Flask instances.
- Synchronous inference tools allow 900 seconds; polling uses existing backend job IDs.

## Review Focus

- Timeout after upload: reuse upload ID and preserve backend error metadata.
- Invalid IDs: reject traversal and URL delimiters before HTTP requests.
- Interrupted preparation: omit unspecified fields so stored options survive retries.
- Stdio launch from any directory: resolve root configuration and emit protocol only on stdout.
- Service unavailable or invalid JSON: produce actionable MCP errors, not false success.

### Task 1: Adapter and workflow tools

**Files:** Create `backend/research_mcp/{__init__,client,server}.py`, `backend/mcp_server.py`, `backend/tests/test_research_mcp.py`; update backend dependency manifests and lock.

**Interfaces:** `create_server(client=None, port=4318) -> FastMCP`; `BackendClient.request(method, path, **kwargs) -> dict` preserves API envelopes. CLI defaults to stdio and accepts `--transport streamable-http`.

- [x] Write failing protocol and integration tests for submission, error handling, input validation, recovery, and workflow tool mapping.
- [x] Implement the adapter, typed tools, workflow resource, and CLI with loopback transport protection.
- [x] Run `uv run --project backend pytest backend/tests/test_research_mcp.py -q`; expect all tests passing.

### Task 2: Launch and documentation

**Files:** Update `package.json`, `scripts/dev.mjs`, `frontend/vite.config.js`, `.env.example`, `README.md`, `README-ZH.md`, `docs/my-own-researcher.md`; add `docs/mcp.md`.

**Interfaces:** `npm run dev` and `npm run dev:agent` include HTTP MCP; standalone stdio uses absolute uv project and script paths.

- [x] Integrate launch scripts and port overrides; document HTTP/stdio configuration, polling, timeout recovery, and remote SSH access.
- [x] Verify actual SDK handshakes for HTTP and stdio, backend/frontend tests, production build, and `git diff --check`.
- [x] Review complete diff against the spec and report verification boundaries.

## Verification results

Implemented in the existing clean checkout.

- Backend: 296 tests passed, including 30 MCP behavior/integration cases and two executable transport checks.
- Graph service: 30 tests passed. Frontend: 48 tests passed; production build passed.
- Actual `npm run dev:agent`: HTTP SDK client discovered 26 tools and reported Graphiti/Neo4j ready with zero inference calls.
- Actual Vite server: port 4317 returned HTTP 200, proxied API readiness successfully, and rejected a second listener on the occupied port.
- Lockfile consistency and whitespace checks passed. Independent read-only review found no blocking issues.
- Test application processes were stopped after verification; existing Neo4j was left running.
- Existing dependency deprecation warnings and the frontend bundle-size warning remain. No new full live inference run or remote SSH connection was attempted; ontology integration used the real upload/persistence route with inference stubbed.
