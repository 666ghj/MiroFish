# Architecture Notes

## Current Architecture Summary

### Frontend (Vue 3 SPA)
- Entry: `frontend/src/main.js` → Vue Router + Vue i18n + Pinia
- 7 views, 9 components, 4 API modules
- State: `store/pendingUpload.js` (Pinia, lightweight)
- i18n: `locales/en.json` + `locales/zh.json`

### Backend (Flask)
- Entry: `backend/run.py` → `backend/app/__init__.py` (Flask app factory)
- 3 API blueprints: `/api/graph`, `/api/simulation`, `/api/report`
- Config: `backend/app/config.py` (reads `.env`)
- Services: 12 modules, cleanly separated from API layer

### External Dependencies
- **Zep Cloud SDK**: graph memory (entity storage, retrieval, episode writing)
- **OASIS framework**: multi-agent social simulation (Twitter + Reddit)
- **LLM**: OpenAI-compatible API (configurable via `.env`)

### Data Persistence
- File-system based: uploads in `backend/uploads/`
- Simulation data: `backend/uploads/simulations/<id>/`
- Report data: `backend/uploads/reports/<id>/`
- No relational database

---

## Existing Engine Pieces to Reuse for GTM

| Existing Module | GTM Reuse |
|----------------|-----------|
| `ontology_generator.py` | Extract ICP entity types from product brief |
| `oasis_profile_generator.py` | Pattern for generating buyer persona profiles |
| `simulation_config_generator.py` | Pattern for LLM-driven parameter generation |
| `simulation_runner.py` | Background task execution pattern |
| `report_agent.py` | GTM recommendation report (ReACT + reflection loops) |
| `zep_tools.py` | InsightForge / PanoramaSearch retrieval tools |
| `llm_client.py` | All LLM calls (unified OpenAI-compatible wrapper) |
| `retry.py` | Resilient API calls |
| `file_parser.py` | Could parse uploaded competitor docs or briefs |
| `text_processor.py` | Chunking for brief processing |
| `models/task.py` | Background task tracking (async persona gen, report gen) |
| `models/project.py` | GTM brief stored as a "project" context |

---

## Proposed GTM Simulation Architecture

### Data Flow

```
User GTM Brief (8 fields)
       ↓
[Brief Processor]                     ← reuse text_processor.py
       ↓
[ICP Extractor / Persona Generator]   ← new: gtm_persona_generator.py
       ↓                                (adapts oasis_profile_generator.py patterns)
[Message Generator]                   ← new: gtm_message_generator.py
       ↓
[Buyer Reaction Simulator]            ← new: gtm_reaction_simulator.py
       ↓                                (LLM call per persona × message angle)
[GTM Analyst]                         ← adapt report_agent.py (new GTM prompt mode)
       ↓
[Report UI + Download]                ← reuse Step4Report.vue + report routes
```

---

### New Files to Create (Phases 2–6)

**Backend services:**
- `backend/app/services/gtm_persona_generator.py`
- `backend/app/services/gtm_message_generator.py`
- `backend/app/services/gtm_reaction_simulator.py`

**Backend API:**
- `backend/app/api/gtm.py` — new Flask blueprint at `/api/gtm/...`

**Backend models:**
- `backend/app/models/gtm_brief.py`

**Frontend components:**
- `frontend/src/components/GTMBriefForm.vue`
- `frontend/src/components/PersonaGrid.vue`
- `frontend/src/components/MessageMatrix.vue`

**Mock data:**
- `backend/mock_data/gtm_personas.json`
- `backend/mock_data/gtm_reactions.json`
- `backend/mock_data/gtm_report.json`

---

### Existing Files to Modify (Phases 1–6)

| File | Phase | Change |
|------|-------|--------|
| `frontend/src/views/Home.vue` | 1 + 2 | Rebrand copy; add GTM CTA |
| `frontend/index.html` | 1 | Update page title |
| `locales/en.json` | 1–6 | Add GTM UI keys progressively |
| `README.md` | 1 + 7 | Update description and quickstart |
| `package.json` | 1 | Update name/description |
| `frontend/src/components/Step1GraphBuild.vue` | 2 | Add GTM brief form mode |
| `frontend/src/components/Step2EnvSetup.vue` | 3 | Show persona cards |
| `frontend/src/components/Step3Simulation.vue` | 4 | Show message × persona matrix |
| `frontend/src/views/SimulationRunView.vue` | 5 | Replace action log with results |
| `frontend/src/components/Step4Report.vue` | 6 | GTM report section layout |
| `backend/app/__init__.py` | 2 | Register `/api/gtm` blueprint |

---

## API Route Suggestions (GTM-specific)

```
POST   /api/gtm/brief                → store brief; return brief_id + project_id
POST   /api/gtm/personas             → generate 12 buyer personas (async task)
GET    /api/gtm/personas/<id>        → retrieve generated personas
POST   /api/gtm/messages             → generate 3 message variants
POST   /api/gtm/simulate             → run reaction simulation (async task)
GET    /api/gtm/results/<id>         → get aggregated simulation results
POST   /api/gtm/report               → generate GTM report (async task)
GET    /api/gtm/report/<id>          → retrieve report JSON
GET    /api/gtm/report/<id>/download → download as Markdown
```

All endpoints support `?mock=true` to return pre-built mock data without LLM calls.

---

## State Management Notes
- Keep Pinia minimal: one store (`store/gtmSession.js`) for GTM brief session state
- Do not add Vuex or complex state libraries
- Use Vue Router params/query for step navigation (existing pattern)
- All simulation data fetched from API; do not store large payloads in frontend state

---

## Mock Mode Notes
- Add `MOCK_MODE=true` to `.env.example`
- Each GTM service checks `Config.MOCK_MODE` before calling LLM or Zep
- Mock data stored in `backend/mock_data/*.json` (checked into repo)
- `?mock=true` query param overrides per-request for individual calls
- Mock data must be realistic enough for a live demo without visible placeholders
