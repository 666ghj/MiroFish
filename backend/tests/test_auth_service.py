"""Tests unitaris per a AuthService."""
import pytest
from datetime import datetime, timezone, timedelta


@pytest.fixture(autouse=True)
def _db(in_memory_db):
    pass


def test_hash_and_verify_password():
    from backend.app.services.auth_service import hash_password, verify_password
    h = hash_password("secret123")
    assert h != "secret123"
    assert verify_password("secret123", h) is True
    assert verify_password("wrong", h) is False


def test_verify_wrong_hash_returns_false():
    from backend.app.services.auth_service import verify_password
    assert verify_password("any", "not-a-valid-hash") is False


def test_create_invitation_token(in_memory_db):
    from backend.app.services.auth_service import create_invitation_token
    from backend.app.models.db_models import UserModel
    from backend.app.db import get_session

    with get_session() as db:
        user = UserModel(email="test@example.com", name="Test", role="user", status="pending")
        db.add(user)
        db.commit()
        user_id = user.id

    token = create_invitation_token(user_id, ttl_hours=1)
    assert len(token) == 36  # UUID


def test_verify_valid_invitation_token(in_memory_db):
    from backend.app.services.auth_service import create_invitation_token, get_user_by_invitation_token
    from backend.app.models.db_models import UserModel
    from backend.app.db import get_session

    with get_session() as db:
        user = UserModel(email="invite@example.com", name="Inv", role="user", status="pending")
        db.add(user)
        db.commit()
        user_id = user.id

    token = create_invitation_token(user_id, ttl_hours=1)
    result = get_user_by_invitation_token(token)
    assert result is not None
    assert result.id == user_id


def test_verify_expired_invitation_token(in_memory_db):
    from backend.app.services.auth_service import get_user_by_invitation_token
    from backend.app.models.db_models import UserModel, InvitationTokenModel
    from backend.app.db import get_session
    import uuid

    with get_session() as db:
        user = UserModel(email="exp@example.com", name="Exp", role="user", status="pending")
        db.add(user)
        db.commit()
        tok = InvitationTokenModel(
            token=str(uuid.uuid4()),
            user_id=user.id,
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1)
        )
        db.add(tok)
        db.commit()
        token_val = tok.token

    result = get_user_by_invitation_token(token_val)
    assert result is None


def test_create_and_verify_reset_token(in_memory_db):
    from backend.app.services.auth_service import (
        create_reset_token, get_user_by_reset_token, consume_reset_token
    )
    from backend.app.models.db_models import UserModel
    from backend.app.db import get_session

    with get_session() as db:
        user = UserModel(email="reset@example.com", name="Reset", role="user", status="active",
                         password_hash="x")
        db.add(user)
        db.commit()
        user_id = user.id

    token = create_reset_token(user_id, ttl_hours=1)
    u = get_user_by_reset_token(token)
    assert u is not None
    assert u.id == user_id

    consume_reset_token(token, "newpassword123")
    assert get_user_by_reset_token(token) is None


def test_set_password_activates_user(in_memory_db):
    from backend.app.services.auth_service import (
        create_invitation_token, consume_invitation_token
    )
    from backend.app.models.db_models import UserModel
    from backend.app.db import get_session

    with get_session() as db:
        user = UserModel(email="act@example.com", name="Act", role="user", status="pending")
        db.add(user)
        db.commit()
        user_id = user.id

    token = create_invitation_token(user_id, ttl_hours=1)
    consume_invitation_token(token, "mypassword")

    with get_session() as db:
        u = db.get(UserModel, user_id)
        assert u.status == "active"
        from backend.app.services.auth_service import verify_password
        assert verify_password("mypassword", u.password_hash) is True
