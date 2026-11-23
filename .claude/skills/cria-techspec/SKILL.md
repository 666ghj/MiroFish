---
name: cria-techspec
description: Creates Technical Specifications from existing PRDs, translating product requirements into architectural decisions and implementation guidance. Performs deep project analysis, uses Context7 MCP for technical research and Web Search for business rules. Use when the user asks to create a tech spec, define architecture, or plan implementation for a feature with an existing PRD. Do not use for PRD creation, task breakdowns, or direct code implementation.
---

# Tech Spec Creation

## SDD Interop (conditional — skip entirely in standalone projects)

If BOTH `docs/.spec-system.json` AND `docs/RULES.md` exist at the project root, the project is governed by the SDD spec system. In that case, and ONLY then:

1. **Workspace**: resolve the feature workspace directory from the SDD manifest/active SPEC. Every reference in this skill to `./tasks/prd-[feature-slug]/` (or `tasks/prd-[feature-slug]/`) means that resolved directory.
2. **Slug**: if a slug/workspace is provided by the caller or manifest, use it verbatim — never derive a new one.
3. **Requirements equivalence**: where a prerequisite requires `prd.md` and it does not exist, accept the SPEC's `main.md` as the equivalent requirements document.
4. **Interview dedupe**: before asking any clarification question, read the SPEC's `main.md` and journal; ask ONLY what is not already answered there, and record inferred answers with their source in the generated document.
5. **Approvals**: governed by the execution mode chosen at the SPEC checkpoint and recorded in the journal (`autônomo | com gates`; no recorded mode → assume `com gates`, fail-safe). In `com gates`: after generating the tech spec, present the key design decisions and STOP for explicit user approval (AskUserQuestion) before handing off to the next phase. In `autônomo`: plan/list presentations become informative (record in the journal and proceed). In BOTH modes, decisions that change the SPEC's acceptance criteria or scope ALWAYS require explicit user approval.
6. **Commands**: use the command labels from the SDD manifest (`commands: {test, typecheck, lint, dev, e2e}`) instead of any hardcoded or detected command.
7. **Memory feedback (mandatory final step)**: after this skill's last step, append the key technical decisions (with trade-offs) as dated entries to the active SPEC's journal, and update the artifact pointers in the SPEC's `main.md`.

If the manifest is absent, ignore this section completely — the standalone behavior below is unchanged.

## Procedures

**Step 1: Validate Prerequisites**
1. Confirm the feature slug has been provided.
2. Verify the PRD exists at `tasks/prd-[feature-slug]/prd.md`. If missing, halt and report.

**Step 2: Analyze PRD (Mandatory)**
1. Read the PRD completely — do NOT skip this step.
2. Identify technical content, constraints, and success metrics.
3. Extract core requirements for architectural consideration.

**Step 3: Deep Project Analysis (Mandatory)**
1. Explore the codebase to discover files, modules, interfaces, and integration points.
2. Map symbols, dependencies, and critical paths.
3. Analyze: callers/callees, configs, middleware, persistence, concurrency, error handling, tests, infra.
4. Explore solution strategies, patterns, risks, and alternatives.

**Step 4: Research (Mandatory)**
1. Use Context7 MCP to resolve technical questions about frameworks and libraries.
2. Perform at least 3 Web Searches to gather business rules and general information.
3. Complete all research BEFORE asking clarification questions.

**Step 5: Technical Clarifications (Mandatory)**
1. Explore the project BEFORE asking questions.
2. Ask focused clarification questions using the AskUserQuestion tool covering:
   - Domain positioning.
   - Data flow.
   - External dependencies.
   - Key interfaces.
   - Test scenarios.
3. Do NOT proceed until answers are received.

**Step 6: Standards Compliance Mapping (Mandatory)**
1. Identify applicable skills: project skills in `.claude/skills/` and applicable user-level skills (e.g., frontend-design for UI features).
2. Highlight deviations with justification and compliant alternatives.

**Step 7: Generate Tech Spec (Mandatory)**
1. Read the template at `assets/techspec-template.md`.
2. Provide: architecture overview, component design, interfaces, data models, endpoints, integration points, impact analysis, test strategy, observability.
3. Focus on HOW, not WHAT (the PRD owns what/why).
4. Avoid repeating functional requirements from the PRD.
5. The spec is about specification, NOT detailed implementation code.
6. Keep under ~2,000 words.
7. Do NOT deviate from the template structure.
8. Prefer existing libraries over custom development.

**Step 8: Save Tech Spec (Mandatory)**
1. Save to: `tasks/prd-[feature-slug]/techspec.md`.
2. Confirm the write operation and path.

## Core Principles
- Tech Spec focuses on HOW, not WHAT (PRD owns the what/why).
- Prefer simple, evolutionary architecture with clear interfaces.
- Provide testability and observability considerations upfront.
- Prefer existing libraries over custom solutions.

## Quality Checklist
- [ ] PRD reviewed.
- [ ] Deep repository analysis completed.
- [ ] Key technical clarifications answered.
- [ ] Tech Spec generated using the template.
- [ ] Project skills verified for compliance.
- [ ] File written to `./tasks/prd-[feature-slug]/techspec.md`.
- [ ] Final output path provided and confirmed.

## Error Handling
- If the PRD does not exist at the expected path, halt and ask the user to create it first via the `cria-prd` skill.
- If Context7 MCP is unavailable, fall back to Web Search for technical documentation.
- If the output file already exists, confirm with the user before overwriting.
