"""Backward-compatible Codex CAMEL model."""
from .agent_model import AgentModel
from .codex_provider import CodexClient


class CodexModel(AgentModel):
    def __init__(self):
        super().__init__('codex')
        self.client = CodexClient()
