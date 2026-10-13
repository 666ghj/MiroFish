# Agent Providers Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans for implementation; independent provider documentation research may run in parallel.

**Goal:** Connect the requested agents through MCP and use their headless interfaces for research inference.

**Architecture:** A shared provider registry and supervised transport normalize CLI output. Existing completion validation and CAMEL interfaces remain shared, while Graphiti selects the same provider. Providers without a verified unattended interface use an explicit wrapper contract.

**Tech Stack:** Python, subprocess, JSON Schema, existing MCP SDK and pytest.

**Spec:** ../specs/2026-10-13-agent-providers.md

## Global Constraints

- Preserve Codex and explicit OpenAI-compatible API configuration.
- No shell interpolation, automatic paid fallback, or live inference in tests.
- Credentials remain owned by the selected CLI; configuration is opt-in.
- All inference routes and local graph extraction honor provider selection.

## Review Focus

- Unknown providers and malformed command settings fail before spawning.
- CLI errors, malformed envelopes, and invalid simulation actions cannot become successful output.
- Timeout, cancellation, and parent exit terminate request processes and release locks.
- Graph, backend, and simulation subprocesses select the same requested provider.
- Client schemas differ; do not label unverified native interfaces as supported.

## Tasks

- [x] Add failing real-subprocess tests for provider selection, command overrides, output parsing, lifecycle, and validation.
- [x] Implement shared registry, documented CLI presets, wrapper protocol, and supervised transport.
- [x] Generalize completion/CAMEL adapters and route services, runners, and Graphiti; add routing regression tests.
- [x] Add configuration/diagnostic commands and MCP configuration generation, with tests for generated schemas and paths.
- [x] Update README, environment example, and detailed guides for all requested providers, with source links and limitations.
- [x] Run backend and graph suites, configuration checks, and independent diff review; fix material findings.

## Verification and review

- Backend suite: `uv run --project backend --frozen pytest backend/tests -q` — 493 passed.
- Graph suite: `uv run --project graph_platform --frozen pytest graph_platform/tests -q` — 38 passed.
- Generated HTTP/stdio configuration and dry provider diagnostics checked; no live inference or user configuration edits.
- Independent review found dotenv assignment preservation and Hermes safe-mode provider-selection issues. Both were reproduced with failing tests and fixed; Hermes now preserves inference configuration with `--ignore-rules`.
- CLI presets remain experimental and version-sensitive; limitations and account setup are documented.
