"""Backward-compatible Codex client using the shared completion validation."""
from .agent_provider import AgentClient
from .codex_transport import CodexProviderError, run_codex


class CodexClient(AgentClient):
    def __init__(self):
        super().__init__('codex')

    def _infer(self, prompt, schema, cancel_event=None):
        return run_codex(prompt, schema, cancel_event=cancel_event)
