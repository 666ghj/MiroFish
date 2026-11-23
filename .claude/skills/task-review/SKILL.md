---
name: task-review
description: Reviews completed task implementations against project code standards, type checks, and test suites. Classifies issues by severity (critical, major, minor, positive) and generates a structured review artifact. Use when a task has been completed and needs quality validation before proceeding. Do not use for full code review of branches, QA testing, or bug fixing.
---

# Task Review

## SDD Interop (conditional — skip entirely in standalone projects)

If BOTH `docs/.spec-system.json` AND `docs/RULES.md` exist at the project root, the project is governed by the SDD spec system. In that case, and ONLY then:

1. **Workspace**: resolve the feature workspace directory from the SDD manifest/active SPEC. Every reference in this skill to task file locations means that resolved directory's `tasks/` subfolder first.
2. **Slug**: if a slug/workspace and task number are provided by the caller, use them verbatim — never guess by recency.
3. **Requirements equivalence**: where a prerequisite requires `prd.md` and it does not exist, accept the SPEC's `main.md` as the equivalent requirements document.
4. **Interview dedupe**: before asking any clarification question, read the SPEC's `main.md` and journal; ask ONLY what is not already answered there.
5. **Approvals**: findings are recorded and reported — decisions that change the SPEC's acceptance criteria or scope ALWAYS require explicit user approval.
6. **Commands**: use the command labels from the SDD manifest (`commands: {test, typecheck, lint, dev, e2e}`) instead of any hardcoded or detected command.
7. **Memory feedback (mandatory final step)**: after this skill's last step, append CRITICAL/MAJOR findings as dated notes to the active SPEC's journal (gotcha candidates for the touched features).

If the manifest is absent, ignore this section completely — the standalone behavior below is unchanged.

## Procedures

**Step 0: Resolve Project Commands (Mandatory)**
1. If the SDD manifest exists (`docs/.spec-system.json`), use its command labels (`commands: {test, typecheck, lint, dev, e2e}`) and skip detection.
2. Otherwise detect once: package manager by lockfile (`bun.lockb`→bun, `pnpm-lock.yaml`→pnpm, `yarn.lock`→yarn, `package-lock.json`→npm) and scripts from `package.json`; if a `typecheck` script is missing in a TypeScript project, use `tsc --noEmit` via the detected package manager. Non-Node stacks by marker: `pyproject.toml`→`pytest`/`mypy`; `go.mod`→`go test ./...`/`go vet ./...`; `Cargo.toml`→`cargo test`/`cargo check`.
3. If nothing resolves, ask the user once and reuse the answer.
4. Below, `<test>`, `<typecheck>`, `<dev>` and `<e2e>` mean the resolved commands. CRITICAL: a command that does not exist in the project is a tooling limitation — report it as such; NEVER treat the absence of a command as failing tests or as a critical issue of the reviewed code.

**Step 1: Identify the Task**
1. Search for task files matching the pattern `*_task.md` in the project (check `tasks/`, `.claude/tasks/`, `docs/tasks/`, or the project root).
2. If a task number is provided, find the specific `[num]_task.md` file.
3. If no task number is provided, find the most recent task file.
4. Read and understand the task requirements completely.

**Step 2: Identify Changed Files**
1. Use `git diff` and `git log` to identify files changed as part of this task.
2. Review each changed file carefully.
3. Read the full context of modified files, not just the diffs.

**Step 3: Conduct the Review**
1. Read `references/code-standards.md` for the complete standards checklist.
2. Review the code against ALL criteria:
   - **Language**: All code in English (variables, functions, classes, comments).
   - **Naming**: camelCase for methods/functions/variables, PascalCase for classes/interfaces, kebab-case for files/directories.
   - **Clear naming**: No abbreviations, no names over 30 characters.
   - **Constants**: No magic numbers — use named constants.
   - **Functions**: Start with a verb, perform a single clear action.
   - **Parameters**: Maximum 3 parameters (use objects for more).
   - **Side effects**: Functions must do mutation OR query, never both.
   - **Conditionals**: Maximum 2 nesting levels, prefer early returns.
   - **Flag parameters**: Never use boolean flags to toggle behavior.
   - **Method size**: Maximum 50 lines per method.
   - **Class size**: Maximum 300 lines per class.
   - **Formatting**: No blank lines within methods/functions.
   - **Comments**: Avoid comments — code should be self-explanatory.
   - **Variable declarations**: One variable per line, declare close to usage.
3. Verify compliance with CLAUDE.md and applicable skills.

**Step 4: Classify Issues**
1. For each issue found, classify as:
   - **CRITICAL**: Bugs, security issues, broken functionality, unsafe/dynamic types where the stack offers typing (e.g. `any` in TypeScript), missing error handling.
   - **MAJOR**: Project code standard violations, missing tests, bad naming.
   - **MINOR**: Style suggestions, minor improvements, optional optimizations.
   - **POSITIVE**: Well-done things that should be recognized.

**Step 5: Validate Tests and Types**
1. Run the resolved `<typecheck>` command to verify type/compilation checks (when the stack has them).
2. Run the resolved `<test>` command to verify all tests pass.

**Step 6: Generate Review Artifact**
1. Read the template at `assets/review-artifact-template.md`.
2. Create the file `[num]_task_review.md` in the SAME directory as the `[num]_task.md` file.
3. Apply status criteria:
   - **APPROVED**: No critical or major issues. Production-ready.
   - **APPROVED WITH OBSERVATIONS**: No critical issues, minor or few non-blocking major issues.
   - **CHANGES REQUESTED**: Critical issues found OR multiple major issues that must be resolved.

## Guidelines
- Be thorough but fair: review every changed file, but acknowledge good work.
- Be specific: always reference the exact file and line number for issues.
- Provide solutions: suggest fixes with code examples, not just problems.
- Write the review artifact in Brazilian Portuguese. Code examples remain in English.

## Error Handling
- If no task file is found, report to the user and ask for the task number.
- If git diff shows no changes, report that there is nothing to review.
- If typecheck or tests fail, include failures in the review artifact as critical issues.
