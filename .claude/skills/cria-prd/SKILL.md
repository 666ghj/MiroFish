---
name: cria-prd
description: Creates Product Requirements Documents (PRDs) from feature requests following a structured workflow of clarification, planning, and drafting. Outputs a standardized PRD to the project tasks directory. Use when the user asks to create a PRD, define requirements, or document a new feature. Do not use for technical specifications, task breakdowns, or implementation planning.
---

# PRD Creation

## SDD Interop (conditional — skip entirely in standalone projects)

If BOTH `docs/.spec-system.json` AND `docs/RULES.md` exist at the project root, the project is governed by the SDD spec system. In that case, and ONLY then:

1. **Workspace**: resolve the feature workspace directory from the SDD manifest/active SPEC. Every reference in this skill to `./tasks/prd-[feature-slug]/` means that resolved directory.
2. **Slug**: if a slug/workspace is provided by the caller or manifest, use it verbatim — never derive a new one.
3. **Requirements equivalence**: where a prerequisite requires `prd.md` and it does not exist, accept the SPEC's `main.md` as the equivalent requirements document.
4. **Interview dedupe**: before asking any clarification question, read the SPEC's `main.md` and journal; ask ONLY what is not already answered there, and record inferred answers with their source in the generated document.
5. **Approvals**: governed by the execution mode chosen at the SPEC checkpoint and recorded in the journal (`autônomo | com gates`; no recorded mode → assume `com gates`, fail-safe). In `com gates`: after generating the PRD, present the RF summary and STOP for explicit user approval (AskUserQuestion) before handing off to the next phase. In `autônomo`: plan/list presentations become informative (record in the journal and proceed). In BOTH modes, decisions that change the SPEC's acceptance criteria or scope ALWAYS require explicit user approval.
6. **Commands**: use the command labels from the SDD manifest (`commands: {test, typecheck, lint, dev, e2e}`) instead of any hardcoded or detected command.
7. **Memory feedback (mandatory final step)**: after this skill's last step, append a dated summary of decisions, deviations, and learnings to the active SPEC's journal, and update the artifact pointers in the SPEC's `main.md`.
8. **RF altitude**: an RF names the capability and the service (WHAT), never the mechanism (HOW — transport, endpoint, header name, library). Mechanism belongs to the tech spec (e.g., "Slack (OUTPUT)", not "Slack incoming-webhook") — RFs stay stable when implementation decisions evolve.

If the manifest is absent, ignore this section completely — the standalone behavior below is unchanged.

## Procedures

**Step 1: Validate Prerequisites**
1. Confirm the feature name or description has been provided by the user.
2. If a slug or workspace directory is provided by the caller (or by the SDD manifest), use it verbatim; otherwise derive the slug in kebab-case. Output directory: `./tasks/prd-[feature-slug]/`.

**Step 2: Clarify Requirements (Mandatory)**
1. Ask the user clarification questions using the AskUserQuestion tool before generating any content.
2. Cover all areas from the clarification checklist:
   - **Problem and Objectives**: What problem to solve, measurable goals.
   - **Users and Stories**: Primary users, user stories, main flows.
   - **Core Functionality**: Data inputs/outputs, actions.
   - **Scope and Planning**: What is NOT included, dependencies.
   - **Design and Experience**: UI/UX guidelines and accessibility.
3. Do NOT proceed to Step 3 until clarification answers are received.

**Step 3: Plan the PRD (Mandatory)**
1. Create a development plan including:
   - Section-by-section approach.
   - Areas requiring research (use Web Search for business rules).
   - Assumptions and dependencies.
2. Present the plan to the user for alignment.

**Step 4: Draft the PRD (Mandatory)**
1. Read the template at `assets/prd-template.md`.
2. Focus on WHAT and WHY, never on HOW (implementation belongs in Tech Spec).
3. Include numbered functional requirements.
4. Keep the document under 2,000 words.
5. Do NOT deviate from the template structure.

**Step 5: Save the PRD (Mandatory)**
1. Create the directory: `./tasks/prd-[feature-slug]/`.
2. Save the PRD to: `./tasks/prd-[feature-slug]/prd.md`.

**Step 6: Report Results**
1. Provide the final file path.
2. Provide a brief summary of the PRD outcome.

## Core Principles
- Clarify before planning; plan before drafting.
- Minimize ambiguity; prefer measurable statements.
- PRD defines outcomes and constraints, NOT implementation.
- Always consider usability and accessibility.

## Quality Checklist
- [ ] Clarification questions completed and answered.
- [ ] Detailed plan created.
- [ ] PRD generated using the template.
- [ ] Numbered functional requirements included.
- [ ] File saved to `./tasks/prd-[feature-slug]/prd.md`.
- [ ] Final path provided.

## Error Handling
- If the user provides insufficient context, ask follow-up clarification questions before proceeding.
- If the template file is missing, report the error and halt — do not generate a PRD without the template.
- If the output directory already exists, confirm with the user before overwriting.
