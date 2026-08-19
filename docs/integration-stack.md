# MiroFish Integration Stack

## Goal

Use **MiroFish** as the prediction engine and simulation brain, with:

- **Codex** as the builder and operator
- **Claude** as the reasoning and synthesis layer
- **n8n** as the automation layer
- **MCP** as the shared tool access layer

## Recommended Architecture

```text
Codex / Claude
      |
      v
  MCP tools
      |
      v
MiroFish backend API
      |
      +--> graph build
      +--> simulation lifecycle
      +--> interviews with agents
      +--> report generation and chat
      |
      v
  MiroFish frontend

n8n
  |
  +--> calls MiroFish backend directly over HTTP
  +--> or invokes the same lifecycle through the MCP server
```

## Roles

### Codex

- builds workflow glue, prompts, and wrappers
- drives MiroFish through MCP tools
- prepares projects, simulations, and reports

### Claude

- consumes simulation outputs and reports
- performs deeper reasoning on what the simulation means
- uses the same MCP tools so it sees the same state as Codex

### n8n

- schedules or triggers prediction runs
- polls preparation/report task status
- routes outputs to Slack, email, dashboards, or databases

### MCP

- standardizes access to MiroFish
- gives Codex and Claude a stable tool layer
- avoids coupling every agent directly to raw REST details

## Added in This Setup

- MCP server: [`integrations/mcp/mirofish_mcp_server.py`](/Users/al/Documents/CODEX/MiroFish/integrations/mcp/mirofish_mcp_server.py)
- start scripts:
  - [`scripts/start_mirofish_mcp_stdio.sh`](/Users/al/Documents/CODEX/MiroFish/scripts/start_mirofish_mcp_stdio.sh)
  - [`scripts/start_mirofish_mcp_http.sh`](/Users/al/Documents/CODEX/MiroFish/scripts/start_mirofish_mcp_http.sh)
- Codex and Claude setup guide:
  - [`docs/codex-claude-mcp-setup.md`](/Users/al/Documents/CODEX/MiroFish/docs/codex-claude-mcp-setup.md)
- n8n workflow template:
  - [`integrations/n8n/mirofish_prediction_pipeline.json`](/Users/al/Documents/CODEX/MiroFish/integrations/n8n/mirofish_prediction_pipeline.json)
- npm scripts:
  - `npm run mcp:stdio`
  - `npm run mcp:http`

## MCP Tools Exposed

- health
- project list
- project detail
- graph build
- graph task status
- simulation create
- simulation prepare
- simulation prepare status
- simulation start
- simulation stop
- simulation run status
- simulation timeline
- batch interviews
- report generate
- report generate status
- report fetch
- report fetch by simulation
- report chat

## n8n Automation Pattern

Use HTTP Request nodes against the backend:

1. `POST /api/graph/build`
2. poll `GET /api/graph/task/{task_id}`
3. `POST /api/simulation/create`
4. `POST /api/simulation/prepare`
5. poll `POST /api/simulation/prepare/status`
6. `POST /api/simulation/start`
7. poll `GET /api/simulation/{simulation_id}/run-status`
8. `POST /api/report/generate`
9. poll `POST /api/report/generate/status`
10. `GET /api/report/by-simulation/{simulation_id}`

An importable starter workflow is included at
[`integrations/n8n/mirofish_prediction_pipeline.json`](/Users/al/Documents/CODEX/MiroFish/integrations/n8n/mirofish_prediction_pipeline.json).

## Suggested Operating Mode

- Let Codex build and evolve the simulation workflow.
- Let Claude reason over the generated report and interview outputs.
- Let n8n handle timed or event-driven execution.
- Treat MiroFish as the core prediction substrate, not the orchestration system.

## Notes

- Real simulation quality depends on valid `LLM_API_KEY` and `ZEP_API_KEY`.
- Local boot verification can use placeholder values, but real runs cannot.
- Python 3.12 is required for this repo on this Mac.
