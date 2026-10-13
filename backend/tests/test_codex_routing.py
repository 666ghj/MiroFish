from unittest.mock import patch

import pytest

from app.config import Config


@pytest.fixture
def codex_mode(monkeypatch):
    monkeypatch.setattr(Config, 'LLM_PROVIDER', 'codex', raising=False)
    monkeypatch.setattr(Config, 'LLM_API_KEY', None)
    monkeypatch.setattr(Config, 'ZEP_API_KEY', None)


def test_codex_config_does_not_require_llm_key(codex_mode):
    assert 'LLM_API_KEY 未配置' not in Config.validate()
    assert 'ZEP_API_KEY 未配置' in Config.validate()


def test_api_config_still_requires_llm_key(monkeypatch):
    monkeypatch.setattr(Config, 'LLM_PROVIDER', 'openai', raising=False)
    monkeypatch.setattr(Config, 'LLM_API_KEY', None)
    assert 'LLM_API_KEY 未配置' in Config.validate()


def test_unknown_provider_is_rejected(monkeypatch):
    monkeypatch.setattr(Config, 'LLM_PROVIDER', 'typo', raising=False)
    assert any('LLM_PROVIDER' in error for error in Config.validate())


@pytest.mark.parametrize('module_name, class_name', [
    ('app.utils.llm_client', 'LLMClient'),
    ('app.services.oasis_profile_generator', 'OasisProfileGenerator'),
    ('app.services.simulation_config_generator', 'SimulationConfigGenerator'),
])
def test_backend_services_use_codex_without_creating_api_client(codex_mode, module_name, class_name):
    import importlib
    from app.utils.codex_provider import CodexClient
    module = importlib.import_module(module_name)
    with patch.object(module, 'OpenAI', side_effect=AssertionError('Paid API client created')):
        service = getattr(module, class_name)()
    assert isinstance(service.client, CodexClient)


@pytest.mark.parametrize('operation', ['time', 'event', 'agents', 'profiles'])
def test_provider_errors_are_not_replaced_with_default_simulation_data(codex_mode, monkeypatch, operation):
    from types import SimpleNamespace
    from app.utils.codex_transport import CodexProviderError
    from app.services import simulation_config_generator as config_module
    from app.services import oasis_profile_generator as profile_module

    def fail(*args, **kwargs):
        raise CodexProviderError('Codex usage limit reached')

    monkeypatch.setattr(config_module, 'create_chat_completion', fail)
    monkeypatch.setattr(profile_module, 'create_chat_completion', fail)
    monkeypatch.setattr('time.sleep', lambda _: None)
    entity = SimpleNamespace(name='Alice', summary='A participant', uuid='alice',
                             attributes={}, related_edges=[], related_nodes=[],
                             get_entity_type=lambda: 'Person')
    generator = config_module.SimulationConfigGenerator()
    with pytest.raises(CodexProviderError, match='usage limit'):
        if operation == 'time':
            generator._generate_time_config('A discussion', 1)
        elif operation == 'event':
            generator._generate_event_config('A discussion', 'Discuss a library', [entity])
        elif operation == 'agents':
            generator._generate_agent_configs_batch('A discussion', [entity], 0, 'Discuss a library')
        else:
            profile_module.OasisProfileGenerator().generate_profiles_from_entities(
                [entity], use_llm=True, parallel_count=1,
            )
