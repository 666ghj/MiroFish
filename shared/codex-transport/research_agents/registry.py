"""Stable provider IDs shared by backend, simulation workers, and graph service."""
from dataclasses import dataclass
import os

from research_codex.transport import CodexProviderError as ProviderError


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    executable: str


PROVIDERS = {p.id: p for p in [
    Provider('codex', 'Codex', 'codex'),
    Provider('claude-code', 'Claude Code', 'claude'),
    Provider('antigravity', 'Antigravity', 'agy'),
    Provider('cursor', 'Cursor', 'agent'),
    Provider('devin', 'Devin CLI', 'devin'),
    Provider('factory-droid', 'Factory Droid', 'droid'),
    Provider('gemini', 'Gemini CLI', 'gemini'),
    Provider('copilot', 'GitHub Copilot CLI', 'copilot'),
    Provider('grok', 'Grok Build CLI', 'grok'),
    Provider('kimi', 'Kimi Code', 'kimi'),
    Provider('opencode', 'OpenCode', 'opencode'),
    Provider('pi', 'Pi', 'pi'),
    Provider('qwen', 'Qwen Code', 'qwen'),
    Provider('hermes', 'Hermes Agent', 'hermes'),
    Provider('muse', 'Muse', 'muse'),
]}

ALIASES = {'claude': 'claude-code', 'droid': 'factory-droid', 'gemini-cli': 'gemini',
           'github-copilot': 'copilot', 'github-copilot-cli': 'copilot',
           'devin-cli': 'devin', 'grok-build': 'grok', 'grok-build-cli': 'grok',
           'kimi-code': 'kimi', 'qwen-code': 'qwen', 'hermes-agent': 'hermes'}


def get_provider(value=None) -> Provider:
    key = (value if value is not None else os.environ.get('LLM_PROVIDER', 'codex')).strip().lower()
    key = ALIASES.get(key, key)
    if key not in PROVIDERS:
        raise ProviderError('Unknown agent provider. Choose one of: ' + ', '.join(PROVIDERS))
    return PROVIDERS[key]


def is_agent_provider(value: str) -> bool:
    return ALIASES.get(value.strip().lower(), value.strip().lower()) in PROVIDERS


def model_name(provider=None) -> str:
    selected = get_provider(provider)
    key = 'CODEX_MODEL' if selected.id == 'codex' else 'AGENT_MODEL'
    return os.environ.get(key, '').strip() or selected.id + '-default'


def graph_provider() -> str:
    # Preserve the existing openai-backend/Codex-graph arrangement unless overridden.
    selected = os.environ.get('GRAPH_LLM_PROVIDER', '').strip()
    if not selected:
        selected = os.environ.get('LLM_PROVIDER', 'codex').strip().lower()
        if selected == 'openai':
            selected = 'codex'
    return get_provider(selected).id
