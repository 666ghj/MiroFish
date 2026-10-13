# Agent connections and inference providers

The user requests Claude Code, Antigravity, Cursor, Devin CLI, Factory Droid,
Gemini CLI, GitHub Copilot CLI, Grok Build CLI, Kimi Code, OpenCode, Pi, Qwen Code,
Hermes Agent, and Muse integrations, and explicitly confirmed both MCP connections
and replacing Codex for inference are in scope.

Keep one research MCP server and document each client's supported configuration.
Introduce a shared CLI provider registry/transport used by backend services,
CAMEL/OASIS runners, and Graphiti. Preserve Codex behavior and existing API mode.
Use documented noninteractive CLI presets where available; otherwise require an
explicit command wrapper and explain the limitation. Do not invent provider flags.
Allow command overrides as JSON argv, never shell strings, with prompts on stdin.
Validate response envelopes and simulation arguments before any action executes.
Retain bounded queues, process cleanup, cancellation, and sanitized errors.
Do not silently fall back to another provider or a paid API. Keep account login
owned by the selected CLI. Document that native agents may read user configuration
and that tool restrictions are not an OS sandbox.

Provider selection must cover graph extraction too. Existing openai backend mode
may retain Codex graph inference unless a graph inference provider is explicitly
selected. Configuration helpers must preserve an existing provider selection.
Ship non-live diagnostics and opt-in live checks, provider-specific README setup,
and automated subprocess/routing/structured-output regression coverage. Tests must
not consume paid inference or modify the user's agent configuration or credentials.
