"""Provider-independent CLI inference; the distribution retains its legacy name."""
from research_codex.transport import CodexProviderError as ProviderError
from .registry import PROVIDERS, get_provider, is_agent_provider, model_name, graph_provider
from .transport import run_agent, validate_provider

__all__ = ['ProviderError', 'PROVIDERS', 'get_provider', 'is_agent_provider',
           'model_name', 'graph_provider', 'run_agent', 'validate_provider']
