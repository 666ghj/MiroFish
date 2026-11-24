# Phase Plan

## Phase 0: Repo Audit + Documentation
**Goal:** Establish implementation foundation; document intent and architecture.
**Files affected:** `docs/` (new), `CLAUDE.md` (new)
**Acceptance criteria:**
- All docs created
- CLAUDE.md at repo root
- Existing app still runs unchanged
- Repo audit summary exists
**Do not:** Touch any existing Vue, Python, or config files.

---

## Phase 1: Rebrand and Copy Cleanup
**Goal:** Replace MiroFish identity with GTM Simulation Lab identity throughout the UI.
**Files likely affected:**
- `frontend/src/views/Home.vue`
- `frontend/index.html`
- `locales/en.json`
- `README.md`
- `package.json` (name/description)
**Acceptance criteria:**
- All visible UI text reflects GTM Simulation Lab branding
- "MiroFish", "swarm intelligence", "parallel digital world" copy replaced
- No functional code changes
**Do not:** Change routing, component structure, or backend.

---

## Phase 2: GTM Input Form
**Goal:** Replace the Step 1 file-upload flow with a structured GTM Brief input form.
**Files likely affected:**
- `frontend/src/components/Step1GraphBuild.vue` (replace upload with form)
- `frontend/src/views/Home.vue` (new hero CTA)
- `frontend/src/api/graph.js` (add `/api/gtm/brief` endpoint)
- `backend/app/api/gtm.py` (new blueprint, POST `/api/gtm/brief`)
- `locales/en.json` (new form field keys)

**Input fields:**
`product_description`, `icp`, `pricing`, `target_market`, `sales_channel`,
`main_pain_point`, `competitors`, `gtm_goal`

**Acceptance criteria:**
- User can fill form and submit
- Brief is stored as project context (file-system)
- Graph Build step replaced by Brief Review step
**Do not:** Remove the existing graph building logic - keep it intact alongside the new flow.

---

## Phase 3: Persona Generation
**Goal:** Generate 12 buyer persona types from the GTM brief.
**Files likely affected:**
- `backend/app/services/gtm_persona_generator.py` (new, adapts `oasis_profile_generator.py`)
- `backend/app/api/gtm.py` (add POST `/api/gtm/personas`)
- `frontend/src/components/Step2EnvSetup.vue` (show persona cards)
- `locales/en.json`
**Acceptance criteria:**
- 12 buyer personas generated with name, role, company size, pain point, skepticism level
- Personas displayed in Step 2 as review cards
- Fallback mock personas available if LLM unavailable
**Do not:** Change the existing OASIS profile format - add a GTM variant alongside it.

---

## Phase 4: Message Testing
**Goal:** Generate 3 outreach message variants and simulate buyer reactions per persona.
**Files likely affected:**
- `backend/app/services/gtm_message_generator.py` (new)
- `backend/app/services/gtm_reaction_simulator.py` (new)
- `backend/app/api/gtm.py` (add POST `/api/gtm/messages`, POST `/api/gtm/simulate`)
- `frontend/src/components/Step3Simulation.vue` (show message × persona matrix)
- `locales/en.json`
**Acceptance criteria:**
- 3 message angles: pain-led, ROI-led, social-proof-led
- Each persona reacts: interested / neutral / objection
- Objections captured as strings
- Matrix displayed in Step 3
**Do not:** Run OASIS social simulation - pure LLM generation is sufficient for MVP.

---

## Phase 5: Simulation Results
**Goal:** Surface aggregated results - response rates, top objections, segment readiness.
**Files likely affected:**
- `backend/app/api/gtm.py` (add GET `/api/gtm/results/<id>`)
- `frontend/src/views/SimulationRunView.vue` (replace action log with results dashboard)
- `locales/en.json`
**Acceptance criteria:**
- Estimated open/reply rate per message angle
- Top 3 objections ranked by frequency
- Segment readiness score (0–100) per persona group
- Data is JSON-first; UI renders from JSON
**Do not:** Add charts or data visualization libraries in this phase.

---

## Phase 6: GTM Report
**Goal:** Use existing `report_agent.py` ReACT pattern to generate a structured GTM recommendation.
**Files likely affected:**
- `backend/app/services/report_agent.py` (add GTM report mode / new prompt)
- `backend/app/api/gtm.py` (add POST `/api/gtm/report`, GET `/api/gtm/report/<id>`)
- `frontend/src/components/Step4Report.vue` (GTM report layout)
- `locales/en.json`

**Output sections:**
1. ICP Validation
2. Best Message Angle
3. Top 3 Objections + Rebuttals
4. Segment Readiness Summary
5. 7-Day Outbound Experiment

**Acceptance criteria:**
- Report renders in Step 4
- Markdown download works (reuse existing `/api/report/<id>/download`)
- Report can be generated from mock data (no live simulation required)
**Do not:** Change the existing report agent's graph-retrieval tools.

---

## Phase 7: Demo Polish
**Goal:** Make the end-to-end demo clean, fast, and credible enough for a live founder pitch.
**Files likely affected:**
- `frontend/src/views/Home.vue` (demo CTA, social proof)
- All Step components (loading states, progress indicators)
- `README.md` (updated setup instructions)
- `locales/en.json`
**Acceptance criteria:**
- Full demo flow under 3 minutes
- Graceful fallback to mock data if APIs unavailable
- Mobile-readable (not necessarily responsive, just not broken)
- README updated with demo quickstart
**Do not:** Add auth, billing, database, or deployment config.

---

## Phase 8: Trustworthy Simulation and Audience (done)

| Sub | What shipped |
|-----|--------------|
| 8.1 | Labelled mock fallback, unbiased reaction prompt, 3 shuffled runs with win rate and stability |
| 8.2 | Synced upstream MiroFish fixes; translated new upstream text to English |
| 8.3 | True-black UI, neutral greys, unified blue accent |
| 8.4 | Site copy that matches the product; no em dashes; honest cost and time estimates |
| 8.5 | Landing page redesign with checkable metrics |
| 8.6 | Audience builder; buyers colored as an exact blend of three buying roles |
| 8.7 | Market intelligence per region (outreach rules, culture, fiscal timing, holidays, World Bank data, headlines) |
| 8.8 | Batched persona generation with honest `meta`; no silent padding |
| 8.9 | Idea Studio plumbing: streamed chat (SSE) and JSON session storage |
| 8.10 | Docs refresh; MOCK_MODE covers every GTM step and starts without a key |

---

## Phase 9: Idea Studio (MVP done)

**Goal:** An early founder talks an idea through with an AI co-founder. A live panel sharpens the idea every turn: clear one-line idea, problem and customer, what could work and what won't, "why hasn't this been built yet" with evidence, challenges, why now, riskiest assumptions and cheapest tests. One click turns a clear idea into a GTM brief.

**Inputs:** three deep-research reports (ChatGPT, Gemini, Claude) in `../deep_researchs/` (kept outside the repo). They decide the conversation strategy, the panel schema, the scoring rubric, the evidence sources, and the MVP scope.

**Already in place (8.9):** `/api/idea` sessions, streamed replies, `chat_stream()`, `frontend/src/api/idea.js`.

| Sub | What shipped |
|-----|--------------|
| 9.1 | Idea state, code-computed clarity, guarded patches |
| 9.2 | Turn pipeline: streamed co-founder + third-person analyst filling a fixed form |
| 9.3 | Evidence: Tavily, Exa, Hacker News, GitHub; research analyst pass; sourced competitors only |
| 9.4 | /studio page: chat, live panel, labels, edit and lock, browser storage |
| 9.5 | Handoff to the GTM simulation, entry points, privacy notes |
| 9.6 | Real-model quality suite (`backend/evals/idea_studio_eval.py`): 15/15 with gpt-4.1-mini analyst |

**Next candidates (from the research v2 lists):** promise assessment bands unlocked at clarity 60, turn-by-turn history scrubber, founder-uploaded interview notes as evidence, SEC EDGAR / Companies House checks, simulation results flowing back into what could and won't work.

**Do not:** add a database or accounts.

---

## Deferred

- `?mock=true` per-request mock flag (CLAUDE.md rule 7 originally asked for it; `MOCK_MODE` covers the need today)
- History view of past simulations
- Real reply ingestion to calibrate simulations
- Docker image is built from this repo but not covered by CI
