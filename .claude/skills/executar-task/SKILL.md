---
name: executar-task
description: Implements feature tasks by loading required skills, reading PRD/TechSpec context, analyzing dependencies, and executing the implementation with tests. Marks tasks as complete in tasks.md and triggers the task-reviewer agent upon completion. Use when the user asks to implement a task, execute a task, or start working on a specific task number. Do not use for creating tasks, running QA, code review, or bug fixing.
---

# Task Execution

## SDD Interop (conditional — skip entirely in standalone projects)

If BOTH `docs/.spec-system.json` AND `docs/RULES.md` exist at the project root, the project is governed by the SDD spec system. In that case, and ONLY then:

1. **Workspace**: resolve the feature workspace directory from the SDD manifest/active SPEC. Every reference in this skill to `./tasks/prd-[feature-slug]/` means that resolved directory.
2. **Slug**: if a slug/workspace is provided by the caller or manifest, use it verbatim — never derive a new one.
3. **Requirements equivalence**: where a prerequisite requires `prd.md` and it does not exist, accept the SPEC's `main.md` as the equivalent requirements document.
4. **Interview dedupe**: before asking any clarification question, read the SPEC's `main.md` and journal; ask ONLY what is not already answered there, and record inferred answers with their source in the generated document.
5. **Approvals**: governed by the execution mode chosen at the SPEC checkpoint and recorded in the journal (`autônomo | com gates`; no recorded mode → assume `com gates`, fail-safe). In `com gates`: BEFORE starting each task, present a short summary (task number, RFs covered, planned files) and STOP for explicit user approval (AskUserQuestion). In `autônomo`: plan/list presentations become informative (record in the journal and proceed). In BOTH modes, decisions that change the SPEC's acceptance criteria or scope ALWAYS require explicit user approval.
6. **Commands**: use the command labels from the SDD manifest (`commands: {test, typecheck, lint, dev, e2e}`) instead of any hardcoded or detected command.
7. **Memory feedback (mandatory final step)**: after this skill's last step, append a dated summary of decisions, deviations, and learnings to the active SPEC's journal, and update the artifact pointers in the SPEC's `main.md`.

If the manifest is absent, ignore this section completely — the standalone behavior below is unchanged.

## Procedures

**Step 1: Pre-Task Configuration (Mandatory)**
1. Read the task definition file at `./tasks/prd-[feature-slug]/[num]_task.md`.
2. Read the PRD at `./tasks/prd-[feature-slug]/prd.md` for context.
3. Read the Tech Spec at `./tasks/prd-[feature-slug]/techspec.md` for technical requirements.
4. Identify dependencies from previous tasks and verify they are complete.
5. Do NOT skip any of these reads.

**Step 2: Load Required Skills**
1. Identify the technologies involved in the task (frameworks and libraries detected in the project).
2. Load the corresponding skills based on technologies used (check the project's `.claude/skills/` first, then applicable user-level skills).
3. If the task involves UI (components, pages, styling), also load and apply the `frontend-design` skill and follow its aesthetic guidelines.
4. Use Context7 MCP to analyze documentation of involved languages, frameworks, and libraries.

**Step 3: Task Analysis (Mandatory)**
1. Analyze the task considering:
   - Main objectives.
   - How the task fits into the project context.
   - Alignment with project rules and standards.
   - Possible approaches or solutions.
2. Generate a task summary:
   - Task ID and Name.
   - PRD Context (main points).
   - Tech Spec Requirements (key technical requirements).
   - Dependencies.
   - Main Objectives.
   - Risks/Challenges.

**Step 4: Approach Plan (Mandatory)**
1. Define a numbered step-by-step approach.
2. Do NOT skip any step.

**Step 5: Implementation (Mandatory)**
1. Begin implementation immediately after planning.
2. Follow all project standards established in CLAUDE.md and project rules.
3. Implement solutions without workarounds.
4. Create and run all task tests before considering the task finished.
5. Any temporary/scratch artifacts generated during implementation (logs, dumps, screenshots, generated test outputs) go to `./tasks/prd-[feature-slug]/tmp/` — never scattered elsewhere in the repository.

**Step 6: Review (Mandatory)**
1. Review the implementation following the `task-review` skill (via the `task-reviewer` agent if available; otherwise apply the `task-review` skill procedures directly in this session). Pass the feature slug and task number explicitly to the review.
2. Address any issues identified by the review and re-run the review after fixes.
3. Limit to 3 review cycles; if issues persist after the third cycle, stop and escalate to the user.

**Step 7: Mark Task Complete (Mandatory)**
1. Mark the task as complete in `tasks.md` ONLY when the review status is APROVADO or APROVADO COM OBSERVAÇÕES.
2. If the review status is MUDANÇAS SOLICITADAS, do NOT mark the task as complete (and revert the mark if it was already set) until the issues are resolved and a new review passes.
3. Also mark the completed subtask and test checkboxes in the task's own `[num]_task.md` file.

## Error Handling
- If the task file does not exist, halt and report to the user.
- If dependencies are not complete, warn the user and ask whether to proceed.
- If the Context7 MCP is unavailable, proceed using Web Search and local project documentation — do not halt.
- If tests fail, fix the issues before marking the task as complete.
- If the review identifies critical issues, address them before marking the task as complete.
