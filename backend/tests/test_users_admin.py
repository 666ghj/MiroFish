"""Tests per a l'API d'administració d'usuaris."""
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


def test_list_users_empty(client, in_memory_db):
    res = client.get('/api/users/')
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert data['data'] == []


def test_create_user_sends_invitation(client, in_memory_db):
    with patch('backend.app.api.users.send_invitation_email', return_value=True) as mock_email:
        res = client.post('/api/users/', json={
            'email': 'newuser@example.com',
            'name': 'New User',
            'role': 'user'
        })
    assert res.status_code == 201
    data = res.get_json()
    assert data['success'] is True
    assert data['data']['email'] == 'newuser@example.com'
    assert data['data']['status'] == 'pending'
    mock_email.assert_called_once()


def test_create_user_duplicate_email(client, in_memory_db):
    with patch('backend.app.api.users.send_invitation_email', return_value=True):
        client.post('/api/users/', json={'email': 'dup@example.com', 'name': 'D', 'role': 'user'})
        res = client.post('/api/users/', json={'email': 'dup@example.com', 'name': 'D2', 'role': 'user'})
    assert res.status_code == 409


def test_get_user(client, in_memory_db):
    with patch('backend.app.api.users.send_invitation_email', return_value=True):
        create_res = client.post('/api/users/', json={'email': 'get@example.com', 'name': 'Get', 'role': 'user'})
    user_id = create_res.get_json()['data']['id']
    res = client.get(f'/api/users/{user_id}')
    assert res.status_code == 200
    assert res.get_json()['data']['email'] == 'get@example.com'


def test_patch_user_role(client, in_memory_db):
    with patch('backend.app.api.users.send_invitation_email', return_value=True):
        create_res = client.post('/api/users/', json={'email': 'patch@example.com', 'name': 'P', 'role': 'user'})
    user_id = create_res.get_json()['data']['id']
    res = client.patch(f'/api/users/{user_id}', json={'role': 'admin'})
    assert res.status_code == 200
    assert res.get_json()['data']['role'] == 'admin'


def test_soft_delete_user(client, in_memory_db):
    with patch('backend.app.api.users.send_invitation_email', return_value=True):
        create_res = client.post('/api/users/', json={'email': 'del@example.com', 'name': 'Del', 'role': 'user'})
    user_id = create_res.get_json()['data']['id']
    res = client.delete(f'/api/users/{user_id}')
    assert res.status_code == 200
    get_res = client.get(f'/api/users/{user_id}')
    assert get_res.get_json()['data']['status'] == 'disabled'


def test_reinvite_pending_user(client, in_memory_db):
    with patch('backend.app.api.users.send_invitation_email', return_value=True) as mock_email:
        create_res = client.post('/api/users/', json={'email': 'reinv@example.com', 'name': 'R', 'role': 'user'})
    user_id = create_res.get_json()['data']['id']
    with patch('backend.app.api.users.send_invitation_email', return_value=True) as mock_email2:
        res = client.post(f'/api/users/{user_id}/reinvite')
    assert res.status_code == 200
    mock_email2.assert_called_once()
