"""Tests per a l'API d'administració."""
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def app(in_memory_db):
    import backend.app.db as db_module
    saved_engine = db_module._engine
    saved_session = db_module._SessionLocal

    def _noop(url):
        db_module._engine = saved_engine
        db_module._SessionLocal = saved_session

    with patch('backend.app.db.init_db', side_effect=_noop):
        from backend.app import create_app
        application = create_app()

    application.config['TESTING'] = True
    application.extensions['storage'] = MagicMock()
    db_module._engine = saved_engine
    db_module._SessionLocal = saved_session
    return application


@pytest.fixture
def client(app):
    with app.test_client() as c:
        yield c


def test_get_config_empty(client, in_memory_db):
    res = client.get('/api/admin/config')
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert isinstance(data['data'], list)


def test_patch_config(client, in_memory_db):
    from backend.app.models.db_models import SystemConfigModel
    from backend.app.db import get_session
    with get_session() as db:
        db.add(SystemConfigModel(
            key='llm.model_name', value='qwen-plus',
            value_type='string', group='llm',
            label='Model LLM', description='Nom del model LLM principal',
            is_secret=False
        ))
        db.commit()

    res = client.patch('/api/admin/config', json={'llm.model_name': 'gpt-4o'})
    assert res.status_code == 200

    res2 = client.get('/api/admin/config')
    entries = res2.get_json()['data']
    entry = next(e for e in entries if e['key'] == 'llm.model_name')
    assert entry['value'] == 'gpt-4o'


def test_get_executions_empty(client, in_memory_db):
    res = client.get('/api/admin/executions')
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert data['data'] == []
