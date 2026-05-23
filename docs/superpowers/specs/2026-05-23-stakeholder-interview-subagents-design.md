# Stakeholder Interview Subagents — Design Spec

- **Date:** 2026-05-23
- **Project:** MiroFish (multi-agent simulation engine for German fisheries discourse)
- **Author:** Christian Möllmann (with Claude Code)
- **Status:** Approved design — pending implementation plan

## 1. Purpose

After the OASIS Twitter + Reddit simulation produces a population of in-character stakeholder agents (fishers, NGOs, policy actors, scientists, consumers, etc.) grounded in a German fisheries discourse knowledge graph, we want to interrogate each agent individually with a structured questionnaire about the future of German fisheries.

Four methodologies run as independent subagents over the same agent population:

1. **Longitudinal** — pre/post Likert to measure opinion drift induced by simulated peer interaction
2. **Diversity** — Q-sort + multi-dim Likert to map the value space and derive a stakeholder typology
3. **Delphi** — three-round consensus probing to identify where stakeholder views converge vs. stay polarised
4. **Scenario** — rating of 4 pre-defined 2040 scenarios on desirability, plausibility, group-impact, fairness

A synthesiser combines the four outputs into a single cross-method report.

## 2. Non-goals (v1)

- Real-time WebSocket streaming of interview progress (polling suffices)
- Adaptive instruments / IRT calibration
- Web UI for editing instruments (YAML + restart is fine)
- Cross-simulation comparison endpoints (CSV exports support this externally)
- Multi-language support beyond DE / EN

## 3. Architectural approach

**Chosen approach: Deterministic instrument runners.** Each subagent is a fixed protocol, not a ReACT loop. Rationale: fisheries futures methodology favours instrument fidelity (every stakeholder sees the same scale) over agent autonomy; results must be directly tabularisable for downstream analysis in pandas/R.

Rejected:
- *ReACT-style subagents* — non-deterministic, ~3–10× cost, can't guarantee every agent answered every item
- *Single InterviewService with mode enum* — couples four distinct methodologies (especially multi-round Delphi and two-phase Longitudinal) into one growing class

## 4. System architecture

```
                    InterviewOrchestrator
                          │
   ┌──────────────┬───────┴───────┬──────────────┐
   ▼              ▼               ▼              ▼
Longitudinal   Diversity        Delphi       Scenario
Subagent       Subagent         Subagent     Subagent
   │              │               │              │
   └──────────────┴──────┬────────┴──────────────┘
                         ▼
              StakeholderInterviewer (base)
                         │
       ┌─────────────────┼─────────────────┐
       ▼                 ▼                 ▼
   LLMClient        ZepEntityReader   ProfileLoader
   (in-character)   (memory digest)   (reddit/twitter)
                         │
                         ▼
       uploads/.../interviews/    +    Zep episodes
```

### 4.1 New files

| Path | Purpose |
|---|---|
| `backend/app/services/interviews/base.py` | `StakeholderInterviewer` — persona+memory loading, in-character prompting, retry/validation |
| `backend/app/services/interviews/longitudinal.py` | Pre/post Likert |
| `backend/app/services/interviews/diversity.py` | Q-sort + multi-dim value-space mapping |
| `backend/app/services/interviews/delphi.py` | Three-round consensus |
| `backend/app/services/interviews/scenario.py` | Scenario rating |
| `backend/app/services/interview_orchestrator.py` | Fan-out, parallel execution, two-phase lifecycle |
| `backend/app/services/interview_synthesizer.py` | Cross-method narrative report |
| `backend/app/api/interview.py` | New Flask blueprint `/api/interview/*` |
| `backend/app/models/interview.py` | Pydantic schemas for instruments + responses |
| `backend/scripts/instruments/*.yaml` | Editable instrument definitions (one YAML per subagent) |
| `frontend/src/components/Step4bInterviews.vue` | Four tabs + synthesis tab |
| `backend/tests/interviews/` | Unit tests per subagent + base + orchestrator + synthesiser |
| `tests/integration/test_interview_pipeline.py` | End-to-end with stub LLM + disposable Zep graph |

### 4.2 Lifecycle integration

Two hooks added to `backend/app/services/simulation_manager.py`:

- `on_ready()` — automatically triggers Longitudinal T0 (pre-simulation baseline)
- `on_completed()` — queues a `task_id` running Longitudinal T1 + Diversity + Delphi + Scenario in parallel, then Synthesiser

The two-phase split is **non-negotiable**: Longitudinal needs T0 captured before OASIS exposes agents to peer-generated content, otherwise drift is unmeasurable.

## 5. Instrument design

All instruments live in `backend/scripts/instruments/*.yaml` so content is editable without redeploying. Items default to German, translatable via existing locale system.

### 5.1 Longitudinal — opinion drift

- 12–15 item 5-point Likert ("lehne stark ab" → "stimme stark zu")
- Administered at T0 (post-persona, pre-OASIS) and T1 (post-OASIS)
- Item families (3–4 each): stock status & recovery; governance & CFP; market & MSC; climate & adaptation
- Per-agent output: response value + LLM self-reported confidence per item + one open comment
- Aggregate: Δ-matrix (N × M items), per-item Wilcoxon signed-rank, per-agent total drift magnitude

### 5.2 Diversity — typology mapping

- One-shot, post-simulation only
- **Part A (Q-sort lite):** 24 statements sorted onto forced quasi-normal distribution from −3 to +3
- **Part B:** 6 multi-dim Likert axes (preservation↔extraction, local↔EU, science-led↔tradition-led, individual↔collective, short-term↔long-term, market↔regulation)
- Per-agent output: vector ∈ ℝ^30
- Aggregate: PCA + k-means → 3–5 stakeholder clusters with archetype descriptions + cluster-membership probabilities

### 5.3 Delphi — consensus probing

- Three rounds, fully automated
- **R1 (open):** 4 open questions; LLM extracts thematic codes from responses
- **R2 (rate):** Agent sees anonymised list of all unique themes; rates each on importance (1–5) + plausibility (1–5)
- **R3 (revise):** Agent sees group median + IQR per theme; can revise own ratings; free-text justification
- Aggregate: per-theme convergence (Δ-IQR R2→R3), persistent disagreements (IQR > 2), ranked consensus statements

### 5.4 Scenario — futures evaluation

Four 2040 scenarios (YAML-editable):

- **S1 "Erholung"** — cod and herring recover, MSC ubiquitous, small-scale fleet stabilises
- **S2 "Kollaps"** — both stocks collapse, fleet halved, aquaculture dominant
- **S3 "Festung Europa"** — protectionist EU policy, MPAs cover 30%, recreational fishing curtailed
- **S4 "Privatisierung"** — ITQs, consolidation, large operators only

Each agent rates each scenario on 4 dimensions (1–7 Likert): desirability, plausibility, impact-on-my-group, fairness. Plus one open question per scenario: "If you woke up in this 2040, what would you do?"

Aggregate: 4 × 4 per-agent matrix + open-text corpus → polarity charts (desirability × plausibility by stakeholder type), narrative themes.

### 5.5 Cross-cutting

**In-character prompting.** Every LLM call uses a system prompt of the form:

> You are [persona_text]. You are answering a survey about the future of German fisheries. Answer strictly in character based on your background, values, and what you experienced during the simulated social media discourse summarised below: [Zep memory digest]. Return JSON only.

Memory digest comes from `ZepEntityReader.get_entity_with_context()`.

**Structured output enforced.** Every response goes through `LLMClient.chat_json()` with a per-instrument JSON schema. One auto-retry on schema violation; agent flagged in audit log on second failure.

**Cost guardrails.** Longitudinal × 2 phases + Delphi × 3 rounds is heaviest. For N=50 agents and ~100 LLM calls per agent across all 4 subagents, budget ~5k calls / 5–10M tokens per simulation. Persona system prompts stay constant within a subagent run → cacheable.

## 6. Data flow and storage

### 6.1 Storage layout

```
uploads/simulations/{sim_id}/interviews/
├── instruments_used.json          # frozen snapshot of YAML at run-time
├── T0/
│   └── longitudinal/
│       ├── responses.jsonl
│       ├── audit.jsonl            # raw LLM I/O, retries, validation failures
│       └── aggregate.json
├── T1/
│   ├── longitudinal/{same structure}
│   ├── diversity/
│   │   ├── responses.jsonl
│   │   ├── typology.json
│   │   └── pca.json
│   ├── delphi/
│   │   ├── round1_themes.jsonl
│   │   ├── round2_ratings.jsonl
│   │   ├── round3_revisions.jsonl
│   │   └── convergence.json
│   └── scenario/
│       ├── responses.jsonl
│       └── polarity_matrix.json
└── synthesis/
    ├── report.md
    └── exports/
        ├── all_responses.csv      # tidy long format
        └── codebook.json
```

JSONL for raw responses (append-safe, streams cleanly); JSON for aggregates; CSV for analysis hand-off. `instruments_used.json` snapshot is critical for reproducibility when YAML is later edited.

### 6.2 Zep integration

Two write patterns, both reusing `ZepGraphMemoryUpdater.add_activity()`:

- **Per-agent episode** — after each subagent finishes for an agent, write one episode: `"Agent {name} (interview/{subagent}/{phase}): {short summary of stance}"`. The existing ReportAgent can retrieve interview content via its current `panorama_search` / `insight_forge` tools without changes.
- **Aggregate episodes** — after each subagent's aggregate step, write one summary episode per cluster / theme / scenario.

No new Zep schemas. No new entity types. Interviews are just more episodes — append-only, safe.

### 6.3 API surface

New blueprint `/api/interview`:

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/interview/{sim_id}/pre` | Trigger T0 longitudinal (auto on READY, manual for re-runs) |
| `POST` | `/api/interview/{sim_id}/post` | Trigger all 4 post-sim subagents; returns `task_id` |
| `GET`  | `/api/interview/{sim_id}/status?task_id=...` | Per-subagent progress |
| `GET`  | `/api/interview/{sim_id}/results/{subagent}` | Aggregate JSON for one subagent |
| `GET`  | `/api/interview/{sim_id}/results/synthesis` | Full synthesis report |
| `GET`  | `/api/interview/{sim_id}/export.csv` | Tidy long-format CSV across all 4 subagents |
| `POST` | `/api/interview/{sim_id}/rerun` | Re-run one subagent (e.g. after editing YAML) |

All responses follow the existing `{success, data, error}` envelope. Polling reuses `models/task.py`.

### 6.4 Parallelism

- Within a subagent: `ThreadPoolExecutor(max_workers=8)` for per-agent LLM calls
- Across the 4 post-sim subagents: parallel, except Delphi (sequential rounds internally)
- Synthesiser waits for all four
- Token budget guard: `Config.INTERVIEW_MAX_TOKENS_PER_RUN`; if projected cost exceeds, API returns 400 with dry-run estimate and `confirm=true` override

### 6.5 Frontend

New `Step4bInterviews.vue` between current Step4 (report) and Step5 (interaction). Four tabs (one per subagent) + a synthesis tab. Each tab shows progress bar during run, then results: Likert heatmap (longitudinal Δ), PCA scatter (diversity), convergence chart (Delphi), polarity quadrants (scenario). Download button per tab pulls the CSV export.

## 7. Error handling

**Per-agent failures are isolated.** If agent 17 times out or fails JSON validation twice, agent 17 is marked `failed` in `audit.jsonl`; the rest of the run continues. Aggregates report `n_responded` / `n_total` honestly.

| Failure | Handling |
|---|---|
| LLM timeout / 5xx | Exponential-backoff retry (3 attempts) via existing `LLMClient`; then mark agent failed |
| JSON schema violation | One auto-retry with explicit corrective instruction; then mark failed |
| Likert out-of-range / missing items | Re-ask only the bad items; if still bad, item-level missing |
| Zep memory fetch fails | Run without memory digest; flag in audit (`memory_available: false`); down-weight in drift analysis |
| Whole-subagent crash | Other 3 continue; synthesiser runs on what completed and flags the gap |
| Token budget exceeded | Pause, write partial results, return 503 with `resume_token` |

**Idempotency.** Every subagent run is keyed by `(sim_id, subagent, phase, run_id)`. Re-runs write a new `run_id` directory; never overwrite. A `latest.json` pointer tracks the canonical run.

## 8. Validation

Three layers:

1. **Schema validation** — pydantic models for every response; JSONL files validated on write
2. **Instrument validation** — `validate_instrument(yaml)` pre-flight: required fields, scale coherence, no duplicate item_ids, DE+EN both present if i18n enabled
3. **Plausibility checks** on aggregates (flag, don't kill):
   - Longitudinal: >80% zero drift on every item OR >80% flip — likely a prompting bug or acquiescence bias
   - Diversity: first two PCA components explain <30% of variance — instrument not discriminating
   - Delphi: R3 ratings identical to R2 for >90% of agents — no engagement with anonymised feedback
   - Scenario: all agents rate all scenarios identically on `desirability` — instrument failure

Flags surface in the synthesis report under "instrument health" so the user can decide whether data is publishable.

## 9. Testing

**Unit tests** (`backend/tests/interviews/`):

- `test_instruments.py` — every YAML parses and validates
- `test_base_interviewer.py` — persona+memory loading, in-character prompt construction, schema-retry logic (mock `LLMClient`)
- One file per subagent — happy path + each failure mode in §7
- `test_orchestrator.py` — fan-out, partial failures, two-phase ordering (T0 before T1)
- `test_synthesizer.py` — missing-subagent handling, stable output shape

**Integration test** (`tests/integration/test_interview_pipeline.py`):

End-to-end with N=5 agents against a recorded LLM cassette. Verifies T0 at READY, T1 + 3 others at COMPLETED, CSV export well-formed, Zep episodes written.

**Stub LLM mode** (`Config.LLM_STUB_MODE=true`) returns deterministic canned responses keyed by `(subagent, item_id, persona_hash)`. Full pipeline exercisable in CI for free.

**Zep**: disposable graph in integration tests (consistent with project conventions); unit tests stub.

## 10. Methodological caveats (auto-emitted in synthesis)

The synthesiser **always** emits a "Limitations" section, programmatically generated from run metadata:

- **Simulated, not real stakeholders.** Responses reflect how the seed-document discourse + LLM jointly encode each stakeholder type, not what actual fishers / NGO staff would say. The instrument measures the *model of the stakeholder*, not the stakeholder.
- **Memory digest is lossy.** Each agent's "experience" of OASIS is summarised to bounded length; agents do not have full episodic recall.
- **LLM acquiescence and centrality bias.** Likert with LLM respondents skews toward 3–4 of 5; per-item distribution shape statistics are reported.
- **N is what it is.** `n_total` and `n_responded` printed verbatim; no rounding, no smoothing.
- **Instrument provenance.** Hash of `instruments_used.json` printed so future-you can rebuild the exact instrument.

This section is load-bearing for any publication: it makes the system intellectually defensible rather than a black box.

## 11. Defaulted decisions (revisit later if needed)

- **N agents:** assumed 50, driven from existing simulation config; if you typically run more/fewer, cost guardrail threshold needs adjusting
- **Default instrument language:** German with English fallback in YAML
- **Delphi rounds = 3:** classic Delphi can run more; 3 is the methodological floor and the cost ceiling here

## 12. Open questions for implementation phase

- Whether to write a separate `instruments_changelog.md` per run, or embed change tracking in `instruments_used.json` metadata
- Whether the synthesiser should write into Zep as a single mega-episode or stay file-only (current design: file-only, plus the per-agent + per-aggregate episodes from each subagent)
- Whether `Step4bInterviews.vue` should sit strictly after Step4 (current design) or render in parallel — interviews depend on the simulation having reached `completed` (Step3 output) and on the `graph_id` (created in Step1); they do not depend on Step4's ReportAgent run, so a parallel layout is technically possible
