---
name: executar-bugfix
description: Reads documented bugs from bugs.md, analyzes root causes, implements fixes with regression tests, and validates the full test suite. Prioritizes fixes by severity (high to low). Updates bugs.md with correction status and generates a final bugfix report. Use when the user asks to fix bugs, resolve issues, or run the bugfix workflow for a feature. Do not use for new feature implementation, code review, or QA testing.
---

# Bug Fix Execution

## SDD Interop (conditional — skip entirely in standalone projects)

If BOTH `docs/.spec-system.json` AND `docs/RULES.md` exist at the project root, the project is governed by the SDD spec system. In that case, and ONLY then:

1. **Workspace**: resolve the feature workspace directory from the SDD manifest/active SPEC. Every reference in this skill to `./tasks/prd-[feature-slug]/` means that resolved directory.
2. **Slug**: if a slug/workspace is provided by the caller or manifest, use it verbatim — never derive a new one.
3. **Requirements equivalence**: where a prerequisite requires `prd.md` and it does not exist, accept the SPEC's `main.md` as the equivalent requirements document.
4. **Interview dedupe**: before asking any clarification question, read the SPEC's `main.md` and journal; ask ONLY what is not already answered there, and record inferred answers with their source in the generated document.
5. **Approvals**: implementation proceeds autonomously — EXCEPT when a fix changes the SPEC's acceptance criteria or contracted scope: in that case, ALWAYS ask the user first (one question per affected criterion).
6. **Commands**: use the command labels from the SDD manifest (`commands: {test, typecheck, lint, dev, e2e}`) instead of any hardcoded or detected command.
7. **Memory feedback (mandatory final step)**: after this skill's last step, append a dated summary of root causes, decisions, and learnings to the active SPEC's journal (root causes are gotcha candidates for the touched features), and update the artifact pointers in the SPEC's `main.md`.

If the manifest is absent, ignore this section completely — the standalone behavior below is unchanged.

## Procedures

**Step 0: Resolve Project Commands (Mandatory)**
1. If the SDD manifest exists (`docs/.spec-system.json`), use its command labels (`commands: {test, typecheck, lint, dev, e2e}`) and skip detection.
2. Otherwise detect once: package manager by lockfile (`bun.lockb`→bun, `pnpm-lock.yaml`→pnpm, `yarn.lock`→yarn, `package-lock.json`→npm) and scripts from `package.json`; if a `typecheck` script is missing in a TypeScript project, use `tsc --noEmit` via the detected package manager. Non-Node stacks by marker: `pyproject.toml`→`pytest`/`mypy`; `go.mod`→`go test ./...`/`go vet ./...`; `Cargo.toml`→`cargo test`/`cargo check`.
3. If nothing resolves, ask the user once and reuse the answer.
4. Below, `<test>` and `<typecheck>` mean the resolved commands. A command that does not exist in the project is a tooling limitation — report it, never treat it as failing tests.

**Step 1: Context Analysis (Mandatory)**
1. Read the bugs file at `./tasks/prd-[feature-slug]/bugs.md` and extract ALL documented bugs. Work ONLY on bugs with Status `Aberto` or `Reaberto`; skip bugs with Status `Corrigido`, `Verificado`, or `Não reproduzível`.
2. Read the PRD at `./tasks/prd-[feature-slug]/prd.md` to understand affected requirements.
3. Read the Tech Spec at `./tasks/prd-[feature-slug]/techspec.md` to understand relevant technical decisions.
4. Review project rules for compliance in fixes.
5. Do NOT skip this step — full context understanding is fundamental for quality fixes.

**Step 2: Plan Fixes (Mandatory)**
1. For each bug, generate a planning summary:
   - Bug ID, Severity (Alta/Média/Baixa), Affected Requirement (RF-XX), Affected Component.
   - Root Cause analysis.
   - Files to modify.
   - Fix strategy description.
   - Planned regression tests (unit, integration, E2E).
2. Use Context7 MCP to analyze documentation of involved languages, frameworks, and libraries.

**Step 3: Implement Fixes (Mandatory)**
1. After planning, begin implementation immediately without waiting for approval (bugs were already triaged by QA). Exception: in SDD mode, if a fix changes contracted acceptance criteria, ask first (see SDD Interop item 5).
2. Fix bugs in severity order: Alta first, then Média, then Baixa.
3. For each bug follow this sequence:
   a. Locate and read the affected code.
   b. Reason about the flow causing the bug.
   c. Implement the root-cause fix — no superficial workarounds.
   d. Run the resolved `<typecheck>` command after each fix (when the stack has one).
   e. Run existing tests to ensure no regressions.

**Step 4: Create Regression Tests (Mandatory)**
1. For each fixed bug, create tests that:
   - Simulate the original bug scenario (test must fail if the fix is reverted).
   - Validate the correct behavior with the fix applied.
   - Cover related edge cases.
2. Choose test type based on bug nature:
   - **Unit test**: Bug in isolated function/method logic.
   - **Integration test**: Bug in module communication (e.g., controller + service).
   - **E2E test**: Bug visible in the UI or full flow.

**Step 5: Visual Validation with Playwright MCP (Mandatory for frontend bugs)**
1. For bugs affecting the UI:
   a. Use `browser_navigate` to access the application.
   b. Use `browser_snapshot` to verify page state.
   c. Reproduce the flow that caused the bug.
   d. Use `browser_take_screenshot` to capture evidence of the fix: raw captures go to `./tasks/prd-[feature-slug]/tmp/`; copy the citable evidence to `./tasks/prd-[feature-slug]/evidence/` named `BUG-NN-fixed.png` and reference the relative path in bugs.md.

**Step 6: Final Test Execution (Mandatory)**
1. Run ALL project tests with the resolved `<test>` command.
2. Verify ALL pass with 100% success.
3. Run type checking with the resolved `<typecheck>` command (when the stack has one).
4. The task is NOT complete if any executed test fails. The absence of a test command is a tooling limitation to report.

**Step 7: Update bugs.md (Mandatory)**
1. For each fixed bug, update its entry (never rewrite other entries — bugs.md is append-only per `executar-qa/assets/bugs-template.md`):
   - **Status:** Corrigido.
   - **Correção aplicada:** Brief description (+ commit hash when available).
   - **Testes de regressão:** List of created tests.
2. If a bug cannot be reproduced, set its Status to `Não reproduzível` with a short justification instead of guessing a fix.

**Step 8: Generate Final Report**
1. Read the report template at `assets/bugfix-report-template.md`.
2. Fill in all sections with actual results.
3. Save the report to `./tasks/prd-[feature-slug]/bugfix-report.md` (sequential suffix on re-runs: `bugfix-report-02.md`) and report the final path.

**Step 9: Recommend Re-validation**
1. Recommend re-running the `executar-qa` skill to re-validate the fixes end-to-end — fixed bugs are only closed as `Verificado` by a QA re-run.

## Error Handling
- If bugs.md does not exist, halt and report to the user.
- If a bug requires significant architectural changes, document the justification before proceeding.
- If new bugs are discovered during fixes, document them in bugs.md.
- If the Context7 MCP is unavailable, proceed using Web Search and local project documentation — do not halt.
- If Playwright MCP is unavailable for frontend fix validation (Step 5), validate by creating/running an automated E2E test of the project (resolved `<e2e>` command) or request manual verification from the user, recording the limitation in the final report.
