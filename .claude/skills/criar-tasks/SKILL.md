---
name: criar-tasks
description: Converts PRD and Tech Spec into a detailed, sequenced list of implementation tasks. Each task is a functional, incremental deliverable with its own test suite. Outputs tasks.md and individual task files. Use when the user asks to create tasks, break down work, or plan implementation from an existing PRD and Tech Spec. Do not use for PRD creation, tech spec creation, or actual code implementation.
---

# Task Creation

## SDD Interop (conditional — skip entirely in standalone projects)

If BOTH `docs/.spec-system.json` AND `docs/RULES.md` exist at the project root, the project is governed by the SDD spec system. In that case, and ONLY then:

1. **Workspace**: resolve the feature workspace directory from the SDD manifest/active SPEC. Every reference in this skill to `./tasks/prd-[feature-slug]/` means that resolved directory.
2. **Slug**: if a slug/workspace is provided by the caller or manifest, use it verbatim — never derive a new one.
3. **Requirements equivalence**: where a prerequisite requires `prd.md` and it does not exist, accept the SPEC's `main.md` as the equivalent requirements document.
4. **Interview dedupe**: before asking any clarification question, read the SPEC's `main.md` and journal; ask ONLY what is not already answered there, and record inferred answers with their source in the generated document.
5. **Approvals**: governed by the execution mode chosen at the SPEC checkpoint and recorded in the journal (`autônomo | com gates`; no recorded mode → assume `com gates`, fail-safe). In `com gates`: after generating `tasks.md`, present the task list and STOP for explicit user approval (AskUserQuestion) before any task execution begins. In `autônomo`: plan/list presentations become informative (record in the journal and proceed). In BOTH modes, decisions that change the SPEC's acceptance criteria or scope ALWAYS require explicit user approval.
6. **Commands**: use the command labels from the SDD manifest (`commands: {test, typecheck, lint, dev, e2e}`) instead of any hardcoded or detected command.
7. **Memory feedback (mandatory final step)**: after this skill's last step, record the task breakdown in the active SPEC's journal (phase table referencing task blocks), and update the artifact pointers in the SPEC's `main.md`.

If the manifest is absent, ignore this section completely — the standalone behavior below is unchanged.

## Procedures

**Step 1: Validate Prerequisites**
1. Confirm the feature slug has been provided.
2. Verify the PRD exists at `tasks/prd-[feature-slug]/prd.md`. If missing, halt.
3. Verify the Tech Spec exists at `tasks/prd-[feature-slug]/techspec.md`. If missing, halt.

**Step 2: Analyze PRD and Tech Spec (Mandatory)**
1. Read the PRD completely to extract requirements.
2. Read the Tech Spec completely to extract technical decisions.
3. Identify main components and their dependencies.

**Step 3: Generate High-Level Task List (Mandatory)**
1. Present the high-level task list to the user for approval BEFORE generating any files.
2. Organize tasks by logical deliverable.
3. Order tasks logically: dependencies before dependents (e.g., backend before frontend, both before E2E tests).
4. Each task MUST be a functional, incremental deliverable.
5. Each task MUST have its own set of unit and integration tests.
6. Limit to a maximum of 15 tasks (group as needed).
7. Wait for user approval before proceeding to Step 4.

**Step 4: Generate Task Files (Mandatory)**
1. Read the tasks summary template at `assets/tasks-template.md`.
2. Read the individual task template at `assets/task-template.md`.
3. Create the summary file: `./tasks/prd-[feature-slug]/tasks.md`.
4. Create individual task files: `./tasks/prd-[feature-slug]/[num]_task.md`.
5. Use format X.0 for main tasks, X.Y for subtasks.
6. Do NOT repeat implementation details already in the Tech Spec — reference it instead.

**Step 5: Report Results**
1. Present all generated files to the user.
2. Await confirmation before any implementation begins.

## Guidelines
- Assume the primary reader is a junior developer — be as clear as possible.
- Group tasks by logical deliverable.
- Make each main task independently completable.
- Define clear scope and deliverables for each task.
- Include tests as subtasks within each main task.
- Do NOT implement anything — focus solely on task listing and detailing.

## Quality Checklist
- [ ] PRD and Tech Spec analyzed.
- [ ] High-level task list approved by user.
- [ ] Task files generated using templates.
- [ ] Each task has unit and integration test subtasks.
- [ ] Files saved to `./tasks/prd-[feature-slug]/`.
- [ ] Results presented to user.

## Error Handling
- If the PRD or Tech Spec is missing, halt and direct the user to the `cria-prd` or `cria-techspec` skill.
- If the user rejects the high-level task list, revise based on feedback and re-present for approval.
- If the output directory already contains task files, confirm with the user before overwriting.
