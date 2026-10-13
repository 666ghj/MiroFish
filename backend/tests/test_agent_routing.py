"""Agent selections must reach services and workers without API fallback."""
import asyncio
import importlib
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.config import Config
from research_agents import PROVIDERS, ProviderError


AGENTS = [name for name in PROVIDERS if name != 'codex']
SERVICES = [
    ('app.utils.llm_client', 'LLMClient'),
    ('app.services.oasis_profile_generator', 'OasisProfileGenerator'),
    ('app.services.simulation_config_generator', 'SimulationConfigGenerator'),
]


@pytest.mark.parametrize('provider', AGENTS)
def test_config_accepts_agent_without_paid_api_key(monkeypatch, provider):
    monkeypatch.setattr(Config, 'LLM_PROVIDER', provider)
    monkeypatch.setattr(Config, 'LLM_API_KEY', None)
    monkeypatch.setattr(Config, 'ZEP_API_KEY', 'test')
    monkeypatch.setenv('AGENT_BIN', sys.executable)
    monkeypatch.delenv('AGENT_COMMAND_JSON', raising=False)
    assert Config.validate() == []


@pytest.mark.parametrize('provider', AGENTS)
@pytest.mark.parametrize('module_name,class_name', SERVICES)
def test_services_route_to_selected_agent_without_api_client(monkeypatch, provider, module_name, class_name):
    monkeypatch.setattr(Config, 'LLM_PROVIDER', provider)
    monkeypatch.setattr(Config, 'LLM_API_KEY', None)
    monkeypatch.setattr(Config, 'ZEP_API_KEY', None)
    module = importlib.import_module(module_name)

    def completion(prompt, schema, cancel_event=None, *, provider=None):
        return {'content': f'Answer from {provider}', 'tool_calls': []}, {}

    monkeypatch.setattr('app.utils.agent_provider.run_agent', completion)
    with patch.object(module, 'OpenAI', side_effect=AssertionError('API fallback')):
        service = getattr(module, class_name)()
        response = service.client.chat.completions.create(messages=[{'role': 'user', 'content': 'Hello'}])
    assert response.choices[0].message.content == f'Answer from {provider}'


@pytest.mark.parametrize('module_name,class_name', SERVICES)
def test_unknown_provider_rejected_before_api_client(monkeypatch, module_name, class_name):
    monkeypatch.setattr(Config, 'LLM_PROVIDER', 'typo-provider')
    monkeypatch.setattr(Config, 'LLM_API_KEY', 'would-enable-api-fallback')
    module = importlib.import_module(module_name)
    with patch.object(module, 'OpenAI', side_effect=AssertionError('API fallback')):
        with pytest.raises(ProviderError, match='Unknown'):
            getattr(module, class_name)()


@pytest.mark.parametrize('provider', ['claude-code', 'cursor', 'muse'])
@pytest.mark.parametrize('runner', ['twitter', 'reddit', 'parallel', 'parallel_boost'])
def test_simulation_workers_route_to_selected_agent(monkeypatch, provider, runner):
    monkeypatch.setenv('LLM_PROVIDER', provider)
    monkeypatch.setenv('LLM_API_KEY', '')
    monkeypatch.setenv('OPENAI_API_KEY', '')
    monkeypatch.setenv('LLM_BOOST_API_KEY', 'must-not-select-api')

    def completion(prompt, schema, cancel_event=None, *, provider=None):
        return {'content': f'Answer from {provider}', 'tool_calls': []}, {}

    monkeypatch.setattr('app.utils.agent_provider.run_agent', completion)
    if runner.startswith('parallel'):
        module = importlib.import_module('scripts.run_parallel_simulation')
        model = module.create_model({}, use_boost=runner.endswith('boost'))
    else:
        module = importlib.import_module(f'scripts.run_{runner}_simulation')
        instance = object.__new__(getattr(module, f'{runner.title()}SimulationRunner'))
        instance.config = {}
        model = instance._create_model()
    response = model.run([{'role': 'user', 'content': 'Hello'}])
    assert response.choices[0].message.content == f'Answer from {provider}'


def test_simulation_env_preserves_agent_failure(monkeypatch):
    from app.utils.simulation_env import make_simulation_env
    from oasis.environment.env import OasisEnv

    monkeypatch.setenv('LLM_PROVIDER', 'claude-code')
    # Construction normally opens simulation databases; the action dispatch is real.
    monkeypatch.setattr(OasisEnv, '__init__', lambda self: None)
    env = make_simulation_env()
    env.llm_semaphore = asyncio.Semaphore(1)

    async def failure():
        return ProviderError('Provider quota reached')

    with pytest.raises(ProviderError, match='quota'):
        asyncio.run(env._perform_llm_action(SimpleNamespace(perform_action_by_llm=failure)))


@pytest.mark.parametrize('operation', ['time', 'event', 'agents', 'profiles'])
def test_agent_failures_are_not_replaced_with_generated_defaults(monkeypatch, operation):
    from app.services import simulation_config_generator as config_module
    from app.services import oasis_profile_generator as profile_module
    monkeypatch.setattr(Config, 'LLM_PROVIDER', 'claude-code')
    monkeypatch.setattr(Config, 'LLM_API_KEY', None)
    monkeypatch.setattr(Config, 'ZEP_API_KEY', None)

    def failure(*args, **kwargs):
        raise ProviderError('Provider quota reached')

    monkeypatch.setattr('app.utils.agent_provider.run_agent', failure)
    entity = SimpleNamespace(name='Alice', summary='A participant', uuid='alice',
                             attributes={}, related_edges=[], related_nodes=[],
                             get_entity_type=lambda: 'Person')
    generator = config_module.SimulationConfigGenerator()
    with pytest.raises(ProviderError, match='quota'):
        if operation == 'time':
            generator._generate_time_config('Discussion', 1)
        elif operation == 'event':
            generator._generate_event_config('Discussion', 'A library', [entity])
        elif operation == 'agents':
            generator._generate_agent_configs_batch('Discussion', [entity], 0, 'A library')
        else:
            profile_module.OasisProfileGenerator().generate_profiles_from_entities(
                [entity], use_llm=True, parallel_count=1,
            )
