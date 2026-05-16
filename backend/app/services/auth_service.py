"""Auth service: password hashing, token CRUD."""
import uuid
import bcrypt
from datetime import datetime, timezone, timedelta
from typing import Optional

from ..db import get_session
from ..models.db_models import UserModel, InvitationTokenModel, PasswordResetTokenModel

# Timing-safe: dummy hash prevents timing attacks when user not found
_DUMMY_HASH = bcrypt.hashpw(b'dummy', bcrypt.gensalt(12)).decode('utf-8')


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt(12)).decode('utf-8')


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8'))
    except Exception:
        return False


def get_user_by_email(email: str) -> Optional[UserModel]:
    from sqlalchemy import select
    with get_session() as db:
        user = db.execute(
            select(UserModel).where(UserModel.email == email.strip().lower())
        ).scalar_one_or_none()
        if user:
            db.expunge(user)
        return user


def create_invitation_token(user_id: str, ttl_hours: int = 48) -> str:
    token = str(uuid.uuid4())
    expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
    with get_session() as db:
        db.add(InvitationTokenModel(token=token, user_id=user_id, expires_at=expires_at))
        db.commit()
    return token


def get_user_by_invitation_token(token: str) -> Optional[UserModel]:
    with get_session() as db:
        rec = db.get(InvitationTokenModel, token)
        if rec is None or rec.used_at is not None:
            return None
        expires = rec.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires < datetime.now(timezone.utc):
            return None
        user = db.get(UserModel, rec.user_id)
        if user:
            db.expunge(user)
        return user


def consume_invitation_token(token: str, password: str) -> None:
    """Marca el token com usat, estableix contrasenya i activa l'usuari."""
    with get_session() as db:
        rec = db.get(InvitationTokenModel, token)
        if rec is None:
            return
        rec.used_at = datetime.now(timezone.utc)
        user = db.get(UserModel, rec.user_id)
        if user:
            user.password_hash = hash_password(password)
            user.status = 'active'
        db.commit()


def create_reset_token(user_id: str, ttl_hours: int = 1) -> str:
    token = str(uuid.uuid4())
    expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
    with get_session() as db:
        db.add(PasswordResetTokenModel(token=token, user_id=user_id, expires_at=expires_at))
        db.commit()
    return token


def get_user_by_reset_token(token: str) -> Optional[UserModel]:
    with get_session() as db:
        rec = db.get(PasswordResetTokenModel, token)
        if rec is None or rec.used_at is not None:
            return None
        expires = rec.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires < datetime.now(timezone.utc):
            return None
        user = db.get(UserModel, rec.user_id)
        if user:
            db.expunge(user)
        return user


def consume_reset_token(token: str, new_password: str) -> None:
    """Marca el token com usat i actualitza la contrasenya."""
    with get_session() as db:
        rec = db.get(PasswordResetTokenModel, token)
        if rec is None:
            return
        rec.used_at = datetime.now(timezone.utc)
        user = db.get(UserModel, rec.user_id)
        if user:
            user.password_hash = hash_password(new_password)
        db.commit()
