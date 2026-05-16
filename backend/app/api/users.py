"""Users API: CRUD d'usuaris per a administradors."""
import logging
from flask import request, jsonify, current_app
from sqlalchemy import select
from . import users_bp
from .. import require_admin
from ..db import get_session
from ..models.db_models import UserModel
from ..services.auth_service import create_invitation_token
from ..services.email_service import send_invitation_email

logger = logging.getLogger('mirofish.users')


def _user_dto(user: UserModel) -> dict:
    return {
        'id': user.id, 'email': user.email, 'name': user.name,
        'role': user.role, 'status': user.status,
        'created_at': user.created_at.isoformat(),
    }


@users_bp.route('/', methods=['GET'])
@require_admin
def list_users():
    page = request.args.get('page', 1, type=int)
    page_size = request.args.get('pageSize', 20, type=int)
    offset = (page - 1) * page_size
    with get_session() as db:
        from sqlalchemy import func
        total = db.execute(select(func.count()).select_from(UserModel)).scalar()
        users = db.execute(
            select(UserModel).order_by(UserModel.created_at.desc())
            .offset(offset).limit(page_size)
        ).scalars().all()
        for u in users:
            db.expunge(u)
    return jsonify({'success': True, 'data': [_user_dto(u) for u in users],
                    'total': total, 'page': page, 'pageSize': page_size})


@users_bp.route('/', methods=['POST'])
@require_admin
def create_user():
    data = request.get_json(silent=True) or {}
    email = data.get('email', '').strip().lower()
    name = data.get('name', '').strip()
    role = data.get('role', 'user')
    if not email or not name:
        return jsonify({'success': False, 'error': 'email and name required'}), 400
    with get_session() as db:
        existing = db.execute(select(UserModel).where(UserModel.email == email)).scalar_one_or_none()
        if existing:
            return jsonify({'success': False, 'error': 'Email already registered'}), 409
        user = UserModel(email=email, name=name, role=role, status='pending')
        db.add(user)
        db.commit()
        db.refresh(user)
        db.expunge(user)

    ttl = current_app.config.get('ACS_INVITATION_TTL_HOURS', 48)
    token = create_invitation_token(user.id, ttl_hours=ttl)
    accept_url = f"{request.host_url.rstrip('/')}/accept-invite/{token}"
    send_invitation_email(user.email, user.name, accept_url)

    return jsonify({'success': True, 'data': _user_dto(user)}), 201


@users_bp.route('/<user_id>', methods=['GET'])
@require_admin
def get_user(user_id):
    with get_session() as db:
        user = db.get(UserModel, user_id)
        if not user:
            return jsonify({'success': False, 'error': 'User not found'}), 404
        db.expunge(user)
    return jsonify({'success': True, 'data': _user_dto(user)})


@users_bp.route('/<user_id>', methods=['PATCH'])
@require_admin
def patch_user(user_id):
    data = request.get_json(silent=True) or {}
    with get_session() as db:
        user = db.get(UserModel, user_id)
        if not user:
            return jsonify({'success': False, 'error': 'User not found'}), 404
        for field in ('name', 'role', 'status'):
            if field in data:
                setattr(user, field, data[field])
        db.commit()
        db.refresh(user)
        db.expunge(user)
    return jsonify({'success': True, 'data': _user_dto(user)})


@users_bp.route('/<user_id>', methods=['DELETE'])
@require_admin
def delete_user(user_id):
    """Soft delete: status = disabled."""
    with get_session() as db:
        user = db.get(UserModel, user_id)
        if not user:
            return jsonify({'success': False, 'error': 'User not found'}), 404
        user.status = 'disabled'
        db.commit()
    return jsonify({'success': True})


@users_bp.route('/<user_id>/purge', methods=['DELETE'])
@require_admin
def purge_user(user_id):
    """Hard delete: esborra usuari i projectes en cascada."""
    from .. import get_storage
    storage = get_storage()
    with get_session() as db:
        user = db.get(UserModel, user_id)
        if not user:
            return jsonify({'success': False, 'error': 'User not found'}), 404
        for proj in user.projects:
            try:
                storage.delete_prefix(f"projects/{proj.id}")
            except Exception:
                pass
        db.delete(user)
        db.commit()
    return jsonify({'success': True})


@users_bp.route('/<user_id>/reinvite', methods=['POST'])
@require_admin
def reinvite_user(user_id):
    with get_session() as db:
        user = db.get(UserModel, user_id)
        if not user:
            return jsonify({'success': False, 'error': 'User not found'}), 404
        if user.status != 'pending':
            return jsonify({'success': False, 'error': 'User is not pending'}), 400
        db.expunge(user)
    ttl = current_app.config.get('ACS_INVITATION_TTL_HOURS', 48)
    token = create_invitation_token(user.id, ttl_hours=ttl)
    accept_url = f"{request.host_url.rstrip('/')}/accept-invite/{token}"
    send_invitation_email(user.email, user.name, accept_url)
    return jsonify({'success': True})
