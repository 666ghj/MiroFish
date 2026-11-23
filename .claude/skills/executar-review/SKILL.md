---
name: executar-review
description: Performs comprehensive code review by analyzing git diff, verifying conformance with project rules, validating test suites, and checking adherence to Tech Spec and Tasks. Generates a structured code review report with severity-classified findings. Use when the user asks for a code review, wants to validate code quality, or needs pre-merge verification. Do not use for QA testing, bug fixing, or task implementation.
---

# Code Review Execution

## SDD Interop (conditional — skip entirely in standalone projects)

If BOTH `docs/.spec-system.json` AND `docs/RULES.md` exist at the project root, the project is governed by the SDD spec system. In that case, and ONLY then:

1. **Workspace**: resolve the feature workspace directory from the SDD manifest/active SPEC. Every reference in this skill to `./tasks/prd-[feature-slug]/` means that resolved directory.
2. **Slug**: if a slug/workspace is provided by the caller or manifest, use it verbatim — never derive a new one.
3. **Requirements equivalence**: where a prerequisite requires `prd.md` and it does not exist, accept the SPEC's `main.md` as the equivalent requirements document.
4. **Interview dedupe**: before asking any clarification question, read the SPEC's `main.md` and journal; ask ONLY what is not already answered there, and record inferred answers with their source in the generated document.
5. **Approvals**: plan/list presentations become informative (record in the journal and proceed) — EXCEPT decisions that change the SPEC's acceptance criteria or scope, which ALWAYS require explicit user approval.
6. **Commands**: use the command labels from the SDD manifest (`commands: {test, typecheck, lint, dev, e2e}`) instead of any hardcoded or detected command.
7. **Memory feedback (mandatory final step)**: after this skill's last step, append a dated summary of decisions, deviations, and learnings to the active SPEC's journal, and update the artifact pointers in the SPEC's `main.md`.

If the manifest is absent, ignore this section completely — the standalone behavior below is unchanged.

## Procedures

**Step 0: Resolve Project Commands (Mandatory)**
1. If the SDD manifest exists (`docs/.spec-system.json`), use its command labels (`commands: {test, typecheck, lint, dev, e2e}`) and skip detection.
2. Otherwise detect once: package manager by lockfile (`bun.lockb`→bun, `pnpm-lock.yaml`→pnpm, `yarn.lock`→yarn, `package-lock.json`→npm) and scripts from `package.json`; if a `typecheck` script is missing in a TypeScript project, use `tsc --noEmit` via the detected package manager. Non-Node stacks by marker: `pyproject.toml`→`pytest`/`mypy`; `go.mod`→`go test ./...`/`go vet ./...`; `Cargo.toml`→`cargo test`/`cargo check`.
3. If nothing resolves, ask the user once and reuse the answer.
4. Below, `<test>`, `<typecheck>`, `<dev>` and `<e2e>` mean the resolved commands. CRITICAL: a command that does not exist in the project is a tooling limitation — report it as such; NEVER treat the absence of a command as failing tests or as a critical issue of the reviewed code.

**Step 1: Documentation Analysis (Mandatory)**
1. Read the Tech Spec at `./tasks/prd-[feature-slug]/techspec.md` to understand expected architectural decisions.
2. Read the Tasks at `./tasks/prd-[feature-slug]/tasks.md` to verify the scope implemented.
3. Read the project rules to know the required standards.
4. Do NOT skip this step — understanding context is fundamental for the review.

**Step 2: Code Change Analysis (Mandatory)**
1. Detect the repository's base branch first — never assume `main`: use the remote default branch (`git symbolic-ref refs/remotes/origin/HEAD --short` or `git remote show origin`); with no remote, use the local default branch (`main` or `master`, whichever exists; if ambiguous, ask the user). Refer to it as `<base>` below.
2. Run git commands to understand what changed:
   - `git status` to see modified files.
   - `git diff` and `git diff --staged` to see all changes.
   - If on a feature branch: `git log <base>..HEAD --oneline` to see branch commits and `git diff <base>...HEAD` for the full branch diff.
   - If currently ON the base branch: review the working tree changes plus the recent feature commits (identify their scope via `tasks.md` and `git log`, and confirm the commit range with the user).
3. For each modified file:
   a. Analyze changes line by line.
   b. Verify adherence to project standards.
   c. Identify potential issues.
4. Read the full context of modified files, not just the diff.

**Step 3: Rules Conformance Verification (Mandatory)**
1. For each code change, verify:
   - Naming conventions per project rules.
   - Project folder structure adherence.
   - Code standards (formatting, linting).
   - No unauthorized dependencies introduced.
   - Error handling patterns.
   - Language conventions (Portuguese/English as defined).

**Step 4: Tech Spec Adherence Verification (Mandatory)**
1. Compare implementation against the Tech Spec:
   - Architecture implemented as specified.
   - Components created as defined.
   - Interfaces and contracts follow specification.
   - Data models as documented.
   - Endpoints/APIs as specified.
   - Integrations implemented correctly.

**Step 5: Task Completeness Verification (Mandatory)**
1. For each task marked as complete:
   - Corresponding code was implemented.
   - Acceptance criteria were met.
   - Subtasks were all completed.
   - Task tests were implemented.

**Step 6: Test Execution (Mandatory)**
1. Run the test suite with the resolved `<test>` command.
2. Run type checking with the resolved `<typecheck>` command (when the stack has one).
3. Verify:
   - All tests pass.
   - New tests added for new code.
   - Coverage: if the project has a coverage script, run it and report the number — comparing against `./tasks/prd-[feature-slug]/coverage-baseline.json` when present (and updating it after the review); if there is no coverage tooling, omit the coverage field instead of inventing a number.
   - Tests are meaningful (not just for coverage).
4. The review CANNOT be approved if any executed test fails. The absence of a test/typecheck command is a tooling limitation to report, never an automatic rejection.

**Step 7: Code Quality Analysis (Mandatory)**
1. Read `references/code-quality-checklist.md` for the full checklist.
2. Assess: complexity, DRY, SOLID, naming, comments, error handling, security, performance.

**Step 8: Generate Review Report (Mandatory)**
1. Read the report template at `assets/review-report-template.md`.
2. Fill in all sections with actual findings.
3. Save the report to `./tasks/prd-[feature-slug]/review-report.md` (if it already exists from a previous round, use a sequential suffix: `review-report-02.md`) and report the final path.
4. Apply approval criteria:
   - **APPROVED**: All criteria met, tests passing, code conforms to rules and Tech Spec.
   - **APPROVED WITH OBSERVATIONS**: Main criteria met, minor or few non-blocking major issues.
   - **REJECTED**: Tests failing, severe rule violations, Tech Spec non-adherence, or security issues.

## Error Handling
- Only report that there is nothing to review after checking BOTH the working tree (`git diff`, `git diff --staged`) AND the branch commits against `<base>`; if either contains changes, review them.
- If tests fail, the review status MUST be REJECTED regardless of other findings.
- Check if there are files that SHOULD have been modified but were not.
- Be constructive in criticism — always suggest alternatives.
