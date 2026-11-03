import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask

from app import create_app
from app.utils.locale import (
    get_language_instruction,
    get_locale,
    get_output_language,
    resolve_locale,
    set_locale,
    t,
)
from scripts.simulation_locale import apply_output_language, interview_prompt


@pytest.fixture(autouse=True)
def restore_thread_locale():
    previous = get_locale()
    yield
    set_locale(previous)


def flatten(value, prefix=''):
    if isinstance(value, dict):
        return {key: text for name, child in value.items()
                for key, text in flatten(child, f'{prefix}.{name}').items()}
    if isinstance(value, list):
        return {key: text for index, child in enumerate(value)
                for key, text in flatten(child, f'{prefix}.{index}').items()}
    return {prefix: value}


def test_brazilian_catalog_has_all_keys_and_interpolation_parameters():
    directory = Path(__file__).resolve().parents[2] / 'locales'
    catalogs = {language: flatten(json.loads((directory / f'{language}.json').read_text(encoding='utf-8')))
                for language in ('en', 'zh', 'pt-BR')}
    assert catalogs['en'].keys() == catalogs['zh'].keys() == catalogs['pt-BR'].keys()
    for key, translated in catalogs['pt-BR'].items():
        assert isinstance(translated, str) and translated.strip(), key
        parameters = lambda text: sorted(re.findall(r'\{\w+\}', text))
        assert parameters(translated) == parameters(catalogs['en'][key]), key
        assert not re.search(r'[\u3400-\u9fff]', translated), key


@pytest.mark.parametrize('tag', ['pt-BR', 'pt-br', 'PT_br', 'pt', 'pt-PT'])
def test_portuguese_tags_resolve_to_the_installed_brazilian_catalog(tag):
    assert resolve_locale(tag) == 'pt-BR'


@pytest.mark.parametrize(('header', 'expected'), [
    ('pt-BR,pt;q=0.9,en;q=0.8', 'pt-BR'),
    ('fr-FR;q=1,pt-BR;q=0.8,en;q=0.5', 'pt-BR'),
    ('pt-BR;q=0,en-US;q=0.9', 'en'),
    ('en;q=0.5,pt-BR;q=0.9', 'pt-BR'),
    ('en-US', 'en'),
    ('zh-CN', 'zh'),
    ('de-DE', 'zh'),
    ('', 'zh'),
])
def test_accept_language_negotiates_available_catalogs(header, expected):
    with Flask(__name__).test_request_context(headers={'Accept-Language': header}):
        assert get_locale() == expected


def test_background_tasks_use_brazilian_messages_and_ai_instructions():
    set_locale('pt-BR')
    assert t('log.prepareComplete') == '✓ Preparação concluída'
    assert t('api.projectNotFound', id='example') == 'Projeto não encontrado: example'
    assert 'português do Brasil' in get_language_instruction()
    assert 'chaves JSON' in get_language_instruction()
    assert get_output_language() == 'Brazilian Portuguese'


def test_api_validation_is_localized_without_changing_status_or_fields():
    app = create_app()
    client = app.test_client()
    response = client.post('/api/simulation/create', json={}, headers={'Accept-Language': 'pt-BR,pt;q=0.9'})
    assert response.status_code == 400
    assert response.json['success'] is False
    assert response.json['error'] == 'Informe o identificador do projeto (project_id)'


def test_new_oasis_agents_receive_the_requested_output_language(monkeypatch):
    agents = [SimpleNamespace(output_language=None), SimpleNamespace(output_language=None)]
    graph = SimpleNamespace(get_agents=lambda: enumerate(agents))
    monkeypatch.setenv('MIROFISH_OUTPUT_LANGUAGE', 'Brazilian Portuguese')
    apply_output_language(graph)
    assert all(agent.output_language == 'Brazilian Portuguese' for agent in agents)


def test_unconfigured_output_language_preserves_existing_agent_behavior(monkeypatch):
    agent = SimpleNamespace(output_language='existing')
    graph = SimpleNamespace(get_agents=lambda: [(0, agent)])
    monkeypatch.delenv('MIROFISH_OUTPUT_LANGUAGE', raising=False)
    apply_output_language(graph)
    assert agent.output_language == 'existing'


def test_interviews_retain_the_question_and_request_brazilian_portuguese(monkeypatch):
    monkeypatch.setenv('MIROFISH_OUTPUT_LANGUAGE', 'Brazilian Portuguese')
    assert interview_prompt('What changed?') == 'What changed?\n\nRespond in Brazilian Portuguese.'


def test_unconfigured_interviews_preserve_the_original_prompt(monkeypatch):
    monkeypatch.delenv('MIROFISH_OUTPUT_LANGUAGE', raising=False)
    assert interview_prompt('Original question') == 'Original question'
