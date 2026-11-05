import logging
import os
import stat

import pytest
from dotenv import dotenv_values

from app import create_app
from app.config import Config
from app.services import ai_settings


@pytest.fixture
def setup(tmp_path, monkeypatch):
    for name, value in {'LLM_API_KEY': None, 'ZEP_API_KEY': None, 'LLM_BASE_URL': 'https://api.example.org/v1', 'LLM_MODEL_NAME': 'example-model'}.items():
        monkeypatch.setattr(Config, name, value)
        monkeypatch.setenv(name, value or '')
    monkeypatch.delenv('ZEP_API_URL', raising=False)
    monkeypatch.setattr(ai_settings, 'ENV_FILE', tmp_path / '.env')
    app = create_app()
    app.config.update(TESTING=True)
    client = app.test_client()
    response = client.get('/api/settings/ai', headers={'Accept-Language': 'en'})
    return client, response.json['data']['setup_token'], tmp_path / '.env'


def payload():
    return {'llm_api_key': 'unit-test-llm-key', 'llm_base_url': 'https://api.example.org/v1', 'llm_model_name': 'unit-test-model', 'zep_api_key': 'unit-test-zep-key'}


def post(client, token, data=None, **kwargs):
    headers = {'X-MiroFish-Setup': token, 'Accept-Language': 'en', **kwargs.pop('headers', {})}
    return client.post('/api/settings/ai', json=payload() if data is None else data, headers=headers, **kwargs)


def test_save_applies_and_persists_without_exposing_keys(setup):
    client, token, path = setup
    path.write_text('# Keep unrelated configuration\nOASIS_DEFAULT_MAX_ROUNDS=4\n')
    response = post(client, token)
    assert response.status_code == 200
    assert response.json['data']['llm_configured'] is True
    assert response.json['data']['zep_configured'] is True
    assert Config.LLM_API_KEY == 'unit-test-llm-key'
    assert os.environ['LLM_MODEL_NAME'] == 'unit-test-model'
    values = dotenv_values(path)
    assert values['LLM_API_KEY'] == 'unit-test-llm-key'
    assert values['ZEP_API_KEY'] == 'unit-test-zep-key'
    assert values['OASIS_DEFAULT_MAX_ROUNDS'] == '4'
    assert '# Keep unrelated configuration' in path.read_text()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert 'unit-test-llm-key' not in response.get_data(as_text=True)
    assert 'unit-test-zep-key' not in client.get('/api/settings/ai').get_data(as_text=True)


def test_blank_keys_keep_existing_configuration(setup):
    client, token, path = setup
    assert post(client, token).status_code == 200
    data = payload()
    data.update(llm_api_key='', zep_api_key='', llm_model_name='updated-model')
    assert post(client, token, data).status_code == 200
    assert Config.LLM_API_KEY == 'unit-test-llm-key'
    assert Config.ZEP_API_KEY == 'unit-test-zep-key'
    assert Config.LLM_MODEL_NAME == 'updated-model'


def test_changing_provider_requires_a_new_key(setup):
    client, token, path = setup
    post(client, token)
    original = path.read_text()
    data = payload()
    data.update(llm_api_key='', llm_base_url='https://different.example.org/v1')
    response = post(client, token, data)
    assert response.status_code == 400
    assert path.read_text() == original
    assert Config.LLM_BASE_URL == 'https://api.example.org/v1'


@pytest.mark.parametrize('origin', ['https://evil.example', 'null', 'http://localhost.evil.example', 'file://localhost'])
def test_foreign_origins_cannot_read_token_or_write(setup, origin):
    client, token, path = setup
    assert client.get('/api/settings/ai', headers={'Origin': origin}).status_code == 403
    assert post(client, token, headers={'Origin': origin}).status_code == 403
    assert not path.exists()


@pytest.mark.parametrize('overrides', [{'REMOTE_ADDR': '192.0.2.10'}, {'HTTP_HOST': 'evil.example'}, {'HTTP_HOST': 'localhost.evil.example'}])
def test_remote_clients_and_rebinding_hosts_are_blocked(setup, overrides):
    client, token, path = setup
    assert client.get('/api/settings/ai', environ_overrides=overrides).status_code == 403
    assert post(client, token, environ_overrides=overrides).status_code == 403
    assert not path.exists()


@pytest.mark.parametrize('token', ['', 'incorrect', 'wrong-ñ'])
def test_write_requires_local_setup_token(setup, token):
    client, _, path = setup
    assert post(client, token).status_code == 403
    assert not path.exists()


@pytest.mark.parametrize('update', [
    {'llm_base_url': 'http://api.example.org/v1'},
    {'llm_base_url': 'https://user:secret@api.example.org/v1'},
    {'llm_base_url': 'https://api.example.org/v1?key=secret'},
    {'llm_base_url': 'https://api.example.org:8443/v1'},
    {'llm_api_key': 'bad\nkey'},
    {'llm_api_key': '${UNRELATED_SECRET}'},
    {'zep_api_key': ''},
    {'llm_model_name': ''},
    {'llm_model_name': 42},
    {'unexpected': 'field'},
])
def test_invalid_config_does_not_change_disk_or_runtime(setup, update):
    client, token, path = setup
    response = post(client, token, {**payload(), **update})
    assert response.status_code == 400
    assert not path.exists()
    assert Config.LLM_API_KEY is None
    assert 'unit-test-llm-key' not in response.get_data(as_text=True)


def test_failed_disk_write_does_not_apply_runtime_values(setup, monkeypatch):
    client, token, path = setup

    def fail(*args):
        raise PermissionError('must not leak file details')

    monkeypatch.setattr(ai_settings.os, 'replace', fail)
    response = post(client, token)
    assert response.status_code == 500
    assert Config.LLM_API_KEY is None
    assert not path.exists()
    assert not list(path.parent.glob('.mirofish-ai-*'))
    assert 'must not leak' not in response.get_data(as_text=True)


def test_request_logging_never_records_settings_body(setup, caplog):
    client, token, _ = setup
    logger = logging.getLogger('mirofish.request')
    logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.DEBUG, logger='mirofish.request'):
            assert post(client, token).status_code == 200
    finally:
        logger.removeHandler(caplog.handler)
    assert '/api/settings/ai' in caplog.text
    assert 'unit-test-llm-key' not in caplog.text
    assert 'unit-test-zep-key' not in caplog.text


def test_quoted_key_survives_dotenv_roundtrip(setup):
    client, token, path = setup
    data = payload()
    data['llm_api_key'] = "test-only-'quote$and#hash"
    assert post(client, token, data).status_code == 200
    assert dotenv_values(path)['LLM_API_KEY'] == data['llm_api_key']


def test_setup_start_allows_missing_keys_but_keeps_other_validation(setup, monkeypatch):
    assert Config.validate()
    assert Config.validate(allow_missing_keys=True) == []
    monkeypatch.setenv('ZEP_API_URL', 'https://unsupported.example.org')
    assert Config.validate(allow_missing_keys=True)


def test_new_clients_use_saved_values_without_provider_calls(setup, monkeypatch):
    from app.utils.llm_client import LLMClient
    from app.utils import zep

    client, token, _ = setup
    assert post(client, token).status_code == 200
    llm = LLMClient()
    assert llm.api_key == 'unit-test-llm-key'
    assert llm.model == 'unit-test-model'
    assert llm.base_url == 'https://api.example.org/v1'
    monkeypatch.setattr(zep, '_cached_zep_client', lambda key, timeout: key)
    assert zep.get_zep_client() == 'unit-test-zep-key'
    assert client.get('/api/settings/ai').headers['Cache-Control'] == 'no-store'


@pytest.mark.parametrize('kind,key', [('m_plan', 'sk-cp-test-only-key'), ('api', 'standard-test-only-key')])
def test_minimax_key_type_is_explicit_and_reopens_without_revealing_key(setup, kind, key):
    client, token, _ = setup
    data = {**payload(), 'llm_base_url': 'https://api.minimax.io/v1', 'llm_api_key': key, 'minimax_key_type': kind}
    response = post(client, token, data)
    assert response.status_code == 200
    assert response.json['data']['minimax_key_type'] == kind
    assert key not in response.get_data(as_text=True)
    assert client.get('/api/settings/ai').json['data']['minimax_key_type'] == kind


@pytest.mark.parametrize('kind,key', [('api', 'sk-cp-test-only-key'), ('m_plan', 'standard-test-only-key')])
def test_mismatched_minimax_key_type_cannot_change_billing_configuration(setup, kind, key):
    client, token, path = setup
    response = post(client, token, {**payload(), 'llm_base_url': 'https://api.minimax.io/v1', 'llm_api_key': key, 'minimax_key_type': kind})
    assert response.status_code == 400
    assert not path.exists()
    assert Config.LLM_API_KEY is None


@pytest.mark.parametrize('zep_key', ['unit-test-llm-key', 'sk-cp-wrong-provider-test-only'])
def test_llm_credentials_cannot_be_saved_as_zep_keys(setup, zep_key):
    client, token, path = setup
    response = post(client, token, {**payload(), 'zep_api_key': zep_key})
    assert response.status_code == 400
    assert 'Zep Cloud' in response.json['error']
    assert not path.exists()
    assert Config.ZEP_API_KEY is None
    assert zep_key not in response.get_data(as_text=True)


def test_saved_cross_provider_key_is_flagged_without_returning_it(setup, monkeypatch):
    client, _, _ = setup
    monkeypatch.setattr(Config, 'LLM_API_KEY', 'sk-cp-test-only-same-key')
    monkeypatch.setattr(Config, 'ZEP_API_KEY', 'sk-cp-test-only-same-key')
    response = client.get('/api/settings/ai')
    assert response.json['data']['zep_key_misplaced'] is True
    assert 'sk-cp-test-only-same-key' not in response.get_data(as_text=True)


def test_misplaced_zep_key_blocks_ontology_before_project_or_llm_work(setup, monkeypatch, tmp_path):
    import io
    from app.api import graph
    from app.models.project import ProjectManager

    client, _, _ = setup
    monkeypatch.setattr(Config, 'LLM_API_KEY', 'sk-cp-test-only-same-key')
    monkeypatch.setattr(Config, 'ZEP_API_KEY', 'sk-cp-test-only-same-key')
    monkeypatch.setattr(ProjectManager, 'PROJECTS_DIR', str(tmp_path / 'projects'))
    monkeypatch.setattr(graph, 'OntologyGenerator', lambda: pytest.fail('Do not consume LLM tokens for this configuration mistake'))
    response = client.post('/api/graph/ontology/generate', data={
        'simulation_requirement': 'Test question',
        'files': (io.BytesIO(b'Test article.'), 'source.txt'),
    }, headers={'Accept-Language': 'en'})
    assert response.status_code == 400
    assert 'Zep Cloud' in response.json['error']
    assert ProjectManager.list_projects() == []
