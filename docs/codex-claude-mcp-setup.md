# Codex and Claude MCP Setup

## Goal

Use MiroFish as a shared prediction engine through one MCP server so:

- Codex can build and operate simulation flows
- Claude can reason over the same simulation and report state
- both tools stay aligned on one backend

## Recommended Shape

- Run the MiroFish backend locally
- Run one MCP server against that backend
- Point Codex and Claude at the same MCP server

```text
Codex ----\
           >---- MiroFish MCP ---- MiroFish backend
Claude ---/
```

## Start Order

From [`/Users/al/Documents/CODEX/MiroFish`](/Users/al/Documents/CODEX/MiroFish):

```bash
npm run backend
```

In another terminal:

```bash
npm run mcp:stdio
```

If you prefer HTTP transport instead of stdio:

```bash
MIROFISH_BASE_URL=http://127.0.0.1:5001 npm run mcp:http
```

## Codex Connection

Register the MCP server in Codex using the command below as the server command:

```bash
cd /Users/al/Documents/CODEX/MiroFish/backend && uv run python ../integrations/mcp/mirofish_mcp_server.py --transport stdio
```

Recommended environment:

```text
MIROFISH_BASE_URL=http://127.0.0.1:5001
MIROFISH_HTTP_TIMEOUT=60
```

Use stdio for local Codex work unless you specifically need HTTP transport for shared remote access.

## Claude Connection

Register the same MCP server command in Claude's MCP settings:

```bash
cd /Users/al/Documents/CODEX/MiroFish/backend && uv run python ../integrations/mcp/mirofish_mcp_server.py --transport stdio
```

Use the same environment values:

```text
MIROFISH_BASE_URL=http://127.0.0.1:5001
MIROFISH_HTTP_TIMEOUT=60
```

This keeps Codex and Claude on one shared tool surface and avoids separate wrapper logic.

## MCP Tools You Can Rely On

- `mirofish_health`
- `mirofish_list_projects`
- `mirofish_get_project`
- `mirofish_build_graph`
- `mirofish_get_graph_task`
- `mirofish_create_simulation`
- `mirofish_prepare_simulation`
- `mirofish_prepare_status`
- `mirofish_start_simulation`
- `mirofish_stop_simulation`
- `mirofish_simulation_status`
- `mirofish_simulation_timeline`
- `mirofish_interview_agents`
- `mirofish_generate_report`
- `mirofish_report_status`
- `mirofish_get_report`
- `mirofish_get_report_by_simulation`
- `mirofish_chat_report`

## Recommended Operator Flow

1. Confirm backend health with `mirofish_health`.
2. Choose an existing project with `mirofish_list_projects`.
3. Build or rebuild the graph with `mirofish_build_graph`.
4. Poll graph completion with `mirofish_get_graph_task`.
5. Create a simulation with `mirofish_create_simulation`.
6. Prepare the simulation with `mirofish_prepare_simulation`.
7. Poll readiness with `mirofish_prepare_status`.
8. Start the run with `mirofish_start_simulation`.
9. Poll runtime with `mirofish_simulation_status`.
10. Generate the report with `mirofish_generate_report`.
11. Fetch the final output with `mirofish_get_report_by_simulation`.
12. Ask follow-up questions with `mirofish_chat_report`.

## Notes

- Real simulation runs still require valid `LLM_API_KEY` and `ZEP_API_KEY`.
- The MCP server is a control layer, not a replacement for the MiroFish backend.
- n8n should call the backend directly for scheduled runs unless you explicitly want agent-mediated orchestration.
