---
name: executar-qa
description: Validates feature implementation against PRD, Tech Spec, and Tasks through E2E testing with Playwright MCP, accessibility verification (WCAG 2.2), and visual analysis. Documents all bugs found with screenshot evidence and generates a comprehensive QA report. Use when the user asks to run QA, validate a feature, or test implementation completeness. Do not use for code review, bug fixing, or task implementation.
---

# QA Execution

## SDD Interop (conditional — skip entirely in standalone projects)

If BOTH `docs/.spec-system.json` AND `docs/RULES.md` exist at the project root, the project is governed by the SDD spec system. In that case, and ONLY then:

1. **Workspace**: resolve the feature workspace directory from the SDD manifest/active SPEC. Every reference in this skill to `./tasks/prd-[feature-slug]/` means that resolved directory.
2. **Slug**: if a slug/workspace is provided by the caller or manifest, use it verbatim — never derive a new one.
3. **Requirements equivalence**: where a prerequisite requires `prd.md` and it does not exist, accept the SPEC's `main.md` as the equivalent requirements document.
4. **Interview dedupe**: before asking any clarification question, read the SPEC's `main.md` and journal; ask ONLY what is not already answered there, and record inferred answers with their source in the generated document.
5. **Approvals**: plan/list presentations become informative (record in the journal and proceed) — EXCEPT decisions that change the SPEC's acceptance criteria or scope, which ALWAYS require explicit user approval.
6. **Commands**: use the command labels from the SDD manifest (`commands: {test, typecheck, lint, dev, e2e}`) instead of any hardcoded or detected command.
7. **Memory feedback (mandatory final step)**: after this skill's last step, append a dated summary of decisions, deviations, and learnings to the active SPEC's journal, and update the artifact pointers in the SPEC's `main.md`. When a verified requirement maps to an acceptance criterion in `main.md`, mark that criterion with a timestamp and a link to the evidence.

If the manifest is absent, ignore this section completely — the standalone behavior below is unchanged.

## Procedures

**Step 0: Resolve Project Commands (Mandatory)**
1. If the SDD manifest exists (`docs/.spec-system.json`), use its command labels (`commands: {test, typecheck, lint, dev, e2e}`) and skip detection.
2. Otherwise detect once: package manager by lockfile (`bun.lockb`→bun, `pnpm-lock.yaml`→pnpm, `yarn.lock`→yarn, `package-lock.json`→npm) and scripts from `package.json`. Non-Node stacks by marker: `pyproject.toml`→`pytest`; `go.mod`→`go test ./...`; `Cargo.toml`→`cargo test`.
3. If nothing resolves, ask the user once and reuse the answer.
4. Below, `<test>`, `<dev>` and `<e2e>` mean the resolved commands. A command that does not exist in the project is a tooling limitation — report it, never treat it as a failure of the feature.

**Step 1: Documentation Analysis (Mandatory)**
1. Read the PRD at `./tasks/prd-[feature-slug]/prd.md` and extract ALL numbered functional requirements.
2. Read the Tech Spec at `./tasks/prd-[feature-slug]/techspec.md` and verify implemented technical decisions.
3. Read Tasks at `./tasks/prd-[feature-slug]/tasks.md` and verify completion status of each task.
4. Create a verification checklist based on the requirements.
5. Do NOT skip this step — understanding requirements is fundamental for QA.

**Step 2: Environment Preparation (Mandatory)**
1. Create the artifact directories if missing: `./tasks/prd-[feature-slug]/tmp/` (temporary/raw outputs — screenshots as captured, dumps, traces; ensure this pattern is covered by .gitignore, adding `tasks/**/tmp/` if missing) and `./tasks/prd-[feature-slug]/evidence/` (persistent evidence referenced by reports — versioned).
2. Determine from the Tech Spec whether the feature has a web UI surface. If it does NOT: skip the browser-based steps (rest of Step 2, Steps 3-5) and validate each PRD requirement via integration/API tests, direct HTTP calls, or CLI execution (using the resolved project commands), with command outputs saved to `evidence/` as evidence in place of screenshots; accessibility does not apply.
3. Resolve the base URL — never assume a port: Playwright config (`baseURL`), `.env` (`PORT`), the framework's default, or ask the user.
4. Verify the application responds at the base URL. If it does not: resolve the project's `<dev>` command, offer to start it in background, poll the URL until ready (60s timeout), and retry; if it still fails, halt reporting the command attempted and the error.
5. Use `browser_navigate` from Playwright MCP to access the application.
6. Confirm the page loaded correctly with `browser_snapshot`.

**Step 3: E2E Tests with Playwright MCP (Mandatory)**
1. Read `references/playwright-tools.md` for the available tools reference.
2. For each functional requirement from the PRD:
   a. Navigate to the feature.
   b. Execute the expected flow.
   c. Verify the result.
   d. Capture screenshot evidence into `tmp/`; when a screenshot supports a requirement verdict or a bug, copy it to `evidence/` named `RF-XX-[label].png` and reference that relative path in the report.
   e. Mark as PASSED or FAILED.
3. Always use `browser_snapshot` before interacting to understand current page state.
4. Check browser console for JavaScript errors with `browser_console_messages`.
5. Verify API calls with `browser_network_requests`.

**Step 4: Accessibility Verification (Mandatory)**
1. Verify for each screen/component:
   - Keyboard navigation works (Tab, Enter, Escape).
   - Interactive elements have descriptive labels.
   - Images have appropriate alt text.
   - Color contrast is adequate (verify via `browser_take_screenshot` + explicit visual analysis — the accessibility tree alone does not expose colors; if visual analysis is not possible, mark as "verificação limitada").
   - Forms have labels associated to inputs.
   - Error messages are clear and accessible.
2. Use `browser_press_key` to test keyboard navigation.
3. Use `browser_snapshot` to verify labels and semantic structure.
4. Follow WCAG 2.2 standard.

**Step 5: Visual Verification (Mandatory)**
1. Capture screenshots of main screens with `browser_take_screenshot` into `tmp/`; promote the ones cited in the report to `evidence/` with descriptive names.
2. Verify layouts in different states (empty, with data, error).
3. Document visual inconsistencies found.
4. Verify responsiveness if applicable.

**Step 6: Bug Documentation**
1. Read the template at `assets/bugs-template.md` and document each bug following it exactly: ID `BUG-NN`, affected requirement `RF-XX`, description, reproduction steps, expected vs. observed behavior, evidence path in `evidence/`, Severidade (Alta/Média/Baixa), Status (Aberto).
2. Save bugs to `./tasks/prd-[feature-slug]/bugs.md`. If `bugs.md` already exists (QA re-run after fixes):
   a. Read ALL existing bugs before writing anything.
   b. Re-execute the scenario of each bug with Status `Corrigido` and update its Status to `Verificado` (fix confirmed) or `Reaberto` (still failing).
   c. Number new bugs continuing from the highest existing ID.
   d. NEVER overwrite or delete existing entries — only append new bugs and update Status fields.
3. If a blocking bug is found, document and report immediately.

**Step 7: Generate QA Report (Mandatory)**
1. Read the report template at `assets/qa-report-template.md`.
2. Fill in all sections with actual results.
3. Set status to APPROVED only when ALL PRD requirements are verified and functioning.
4. Save the report to `./tasks/prd-[feature-slug]/qa-report.md` (sequential suffix on re-runs: `qa-report-02.md`) and report the final path.

## Error Handling
- If the application is not running, resolve the project's `<dev>` command and follow Step 2.4 (offer to start in background and poll) before asking the user to intervene.
- If Playwright MCP is unavailable, report the error and suggest running the project's E2E suite via the resolved `<e2e>` command (or manual verification, recording the limitation in the report).
- If a blocking bug prevents testing subsequent features, document it and continue with testable areas.
