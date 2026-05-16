"""Tests d'integració per als endpoints d'autenticació."""
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def app(in_memory_db):
    import backend.app.db as db_module
    saved_engine = db_module._engine
    saved_session = db_module._SessionLocal

    def _noop_init_db(url):
        db_module._engine = saved_engine
        db_module._SessionLocal = saved_session

    with patch('backend.app.db.init_db', side_effect=_noop_init_db):
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


@pytest.fixture
def active_user(in_memory_db):
    from backend.app.models.db_models import UserModel
    from backend.app.services.auth_service import hash_password
    from backend.app.db import get_session
    with get_session() as db:
        user = UserModel(
            email="user@example.com",
            name="Test User",
            role="user",
            status="active",
            password_hash=hash_password("password123")
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        user_id = user.id
    return user_id


def test_login_success(client, active_user):
    res = client.post('/api/auth/login', json={
        'email': 'user@example.com',
        'password': 'password123'
    })
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert 'token' in data
    assert data['user']['email'] == 'user@example.com'


def test_login_wrong_password(client, active_user):
    res = client.post('/api/auth/login', json={
        'email': 'user@example.com',
        'password': 'wrongpassword'
    })
    assert res.status_code == 401
    assert res.get_json()['success'] is False


def test_login_nonexistent_user(client, in_memory_db):
    res = client.post('/api/auth/login', json={
        'email': 'nobody@example.com',
        'password': 'password123'
    })
    assert res.status_code == 401


def test_login_pending_user_rejected(client, in_memory_db):
    from backend.app.models.db_models import UserModel
    from backend.app.services.auth_service import hash_password
    from backend.app.db import get_session
    with get_session() as db:
        user = UserModel(
            email="pending@example.com", name="P", role="user", status="pending",
            password_hash=hash_password("pass")
        )
        db.add(user)
        db.commit()
    res = client.post('/api/auth/login', json={'email': 'pending@example.com', 'password': 'pass'})
    assert res.status_code == 401


def test_forgot_password_always_202(client, in_memory_db):
    res = client.post('/api/auth/forgot-password', json={'email': 'notexists@example.com'})
    assert res.status_code == 202
    res2 = client.post('/api/auth/forgot-password', json={'email': 'alsonotexists@example.com'})
    assert res2.status_code == 202


def test_get_invitation_token_valid(client, in_memory_db):
    from backend.app.models.db_models import UserModel
    from backend.app.services.auth_service import create_invitation_token
    from backend.app.db import get_session
    with get_session() as db:
        user = UserModel(email="inv@example.com", name="Inv", role="user", status="pending")
        db.add(user)
        db.commit()
        user_id = user.id
    token = create_invitation_token(user_id, ttl_hours=24)
    res = client.get(f'/api/auth/invitation/{token}')
    assert res.status_code == 200
    assert res.get_json()['data']['email'] == 'inv@example.com'


def test_get_invitation_token_invalid(client, in_memory_db):
    res = client.get('/api/auth/invitation/non-existent-token')
    assert res.status_code == 404


def test_set_password_activates_user(client, in_memory_db):
    from backend.app.models.db_models import UserModel
    from backend.app.services.auth_service import create_invitation_token
    from backend.app.db import get_session
    with get_session() as db:
        user = UserModel(email="setpwd@example.com", name="S", role="user", status="pending")
        db.add(user)
        db.commit()
        user_id = user.id
    token = create_invitation_token(user_id, ttl_hours=24)
    res = client.post('/api/auth/set-password', json={'token': token, 'password': 'newpass123'})
    assert res.status_code == 200
    with get_session() as db:
        u = db.get(UserModel, user_id)
        assert u.status == 'active'


def test_reset_password_flow(client, in_memory_db):
    from backend.app.models.db_models import UserModel
    from backend.app.services.auth_service import hash_password, create_reset_token
    from backend.app.db import get_session
    with get_session() as db:
        user = UserModel(
            email="reset@example.com", name="R", role="user", status="active",
            password_hash=hash_password("oldpass")
        )
        db.add(user)
        db.commit()
        user_id = user.id
    token = create_reset_token(user_id, ttl_hours=1)

    res = client.get(f'/api/auth/reset-password/{token}')
    assert res.status_code == 200
    assert res.get_json()['data']['email'] == 'reset@example.com'

    res2 = client.post('/api/auth/reset-password', json={'token': token, 'password': 'newpass456'})
    assert res2.status_code == 200

    res3 = client.get(f'/api/auth/reset-password/{token}')
    assert res3.status_code == 404
