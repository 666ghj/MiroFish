# CLAUDE.md - GTM Simulation Lab

## Project Purpose
This is a fork of MiroFish adapted into a **GTM Simulation Lab**.
It helps founders and GTM teams simulate buyer reactions and outbound messaging
before launching real outreach.

**Working name:** GTM Simulation Lab
**Pitch:** *"Simulate your GTM before launching outreach."*

---

## Branding Rules
- Product name: **GTM Simulation Lab**
- Tagline: *"Simulate your GTM before launching outreach."*
- Do not imply external brand affiliations or endorsements
- Replace all MiroFish, "swarm intelligence", and "parallel digital world" copy with GTM-focused language
- Do not show "Built on MiroFish" or similar credits in the UI (the LICENSE file stays)
- No em dashes anywhere in UI copy, mock data, or generated text (LLM output is cleaned by `utils/text_style.py`)

---

## Coding Rules

1. **JSON-first output**: All simulation and report data must be structured JSON before rendering in UI. No hardcoded strings in simulation output.

2. **No overbuild**: Do not add complexity beyond the current phase's acceptance criteria. Three similar lines is better than a premature abstraction.

3. **No auth / database / billing**: File-system persistence only. No login required for the MVP. No Postgres, Redis, or external storage.

4. **Preserve existing structure**: Do not delete or rename existing working modules. Add new GTM modules alongside them. The original MiroFish simulation flow must remain runnable.

5. **Keep demo runnable**: The app must run end-to-end at all times. Never leave a broken import, missing route, or unhandled exception.

6. **Phase-locked development**: Only build what the current phase spec in `docs/PHASE_PLAN.md` requires. Document deferred work in that file rather than implementing it early.

7. **Mock mode required, and always labelled**: Every LLM-dependent feature must have a mock fallback. `MOCK_MODE=true` makes every GTM step serve sample data and lets the server start without a key. Mock or partial results must say so in the API response (`source`, `mock_reason`, counts) and in the UI; never silently pad real results with sample data. Mock data lives in `backend/mock_data/`. (`?mock=true` per request is not implemented.)

8. **English only**: All code comments, docstrings, log messages, and UI strings in English.

9. **No new dependencies** unless explicitly required by the phase spec and approved in the commit. Do not add npm or pip packages speculatively.

---

## Phase-by-Phase Development Rule

Read `docs/PHASE_PLAN.md` before starting any implementation.

Each phase has:
- A clear goal
- A list of files likely affected
- Acceptance criteria
- An explicit "do not" list

After completing each phase:
1. Run the full app and verify it works end-to-end
2. Run `grep -r '[一-鿿]' frontend/ backend/ --include='*.py' --include='*.vue' --include='*.js'` to confirm no Chinese text crept in
3. Commit with the format below
4. Stop and wait for the next phase instruction

**Last completed phase: Phase 9.6 (Idea Studio MVP and its quality suite)**
**Current phase: awaiting instruction. Focus is local quality; deployment is deferred.**

---

## Architecture Summary

See `docs/ARCHITECTURE_NOTES.md` for the full data flow and file map.

GTM flow modules (backend/app):
- `api/gtm.py`: all GTM routes (brief, market, personas, messages, reactions, report)
- `api/idea.py`: Idea Studio sessions and streamed chat (Server-Sent Events)
- `services/gtm_persona_generator.py`: batched persona generation with `meta` (source, counts)
- `services/gtm_reaction_simulator.py` + `gtm_aggregator.py`: 3 shuffled runs, win rate, stability
- `services/gtm_audience.py`: audience validation, prompt section, archetype_mix enrichment
- `services/gtm_market.py`: region profiles + live signals (World Bank, Nager.Date, Google News)
- `services/idea_state.py`: idea state, code-computed clarity, guarded JSON Patch validation
- `services/idea_studio.py`: turn pipeline, question router, co-founder and analyst prompts, brief handoff
- `services/idea_evidence.py`: Tavily, Exa, Hacker News, GitHub search and the research analyst pass
- `evals/idea_studio_eval.py`: real-model quality suite (run before changing Idea Studio prompts or models)
- `models/gtm_brief.py`, `models/idea_session.py`: JSON-on-disk persistence
- `utils/llm_client.py`: all LLM calls (`chat`, `chat_json`, `chat_stream`), OpenAI-compatible
- `utils/text_style.py`: strips em dashes from generated text

The legacy MiroFish modules (`oasis_profile_generator`, `report_agent`, `zep_*`, `simulation_*`)
belong to the original social-simulation flow and are not used by the GTM flow.

---

## Repository Structure (Key Paths)

```
frontend/src/
  views/          Home, SimulatePage, GTMPersonasView, GTMMessageTestingView, GTMReportView (+ legacy views)
  components/     GTMBriefForm, AudienceBuilder, MarketIntel, HeroViz, PersonaCard (+ legacy components)
  api/            gtm.js, idea.js (streaming), index.js (axios)
  store/          gtmSimulation.js (reactive singleton)
  utils/          audience.js, gtmFormatter.js, downloadMarkdown.js
  mock/           offline sample data

backend/app/      api/, services/, models/, utils/ (see above)
backend/tests/    pytest suite, no network, stubbed LLM
backend/mock_data/ sample JSON served in mock mode
locales/          en.json, zh.json (legacy i18n strings)
docs/             project documentation
```

---

## Commit Message Format

```
<phase>.<sub>: <one-line summary>

Changed files:
- path/to/file1: what changed
- path/to/file2: what changed

Next: Phase <N+1> - <goal>
```

Example:
```
2.1: add GTM brief API endpoint

Changed files:
- backend/app/api/gtm.py: new blueprint, POST /api/gtm/brief
- backend/app/__init__.py: register gtm blueprint

Next: Phase 2.2 - GTMBriefForm.vue frontend component
```

Use colons and hyphens, not em dashes. Run `cd backend && python -m pytest -q` and `cd frontend && npx vite build` before committing.
