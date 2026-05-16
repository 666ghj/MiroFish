"""
Autenticació real: login bcrypt+JWT, refresh, logout, me,
forgot-password, reset-password, invitation, set-password.
"""
import logging
from flask import request, jsonify, current_app
from flask_jwt_extended import (
    create_access_token, create_refresh_token,
    set_refresh_cookies, unset_jwt_cookies,
    jwt_required, get_jwt_identity
)
from . import auth_bp
from ..db import get_session
from ..models.db_models import UserModel
from ..services.auth_service import (
    verify_password, get_user_by_email, _DUMMY_HASH,
    create_invitation_token, get_user_by_invitation_token, consume_invitation_token,
    create_reset_token, get_user_by_reset_token, consume_reset_token
)

logger = logging.getLogger('mirofish.auth')


def _user_dto(user: UserModel) -> dict:
    return {'id': user.id, 'email': user.email, 'name': user.name, 'role': user.role}


@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')

    user = get_user_by_email(email)
    candidate_hash = user.password_hash if (user and user.password_hash) else _DUMMY_HASH
    valid = verify_password(password, candidate_hash)

    if not valid or not user or user.status != 'active':
        return jsonify({'success': False, 'error': 'Invalid credentials'}), 401

    access_token = create_access_token(
        identity=user.id,
        additional_claims={'role': user.role, 'email': user.email}
    )
    refresh_token = create_refresh_token(identity=user.id)
    response = jsonify({'success': True, 'token': access_token, 'user': _user_dto(user)})
    set_refresh_cookies(response, refresh_token)
    return response


@auth_bp.route('/refresh', methods=['POST'])
@jwt_required(refresh=True)
def refresh():
    user_id = get_jwt_identity()
    with get_session() as db:
        user = db.get(UserModel, user_id)
        if not user or user.status != 'active':
            return jsonify({'success': False, 'error': 'User not active'}), 401
        db.expunge(user)
    access_token = create_access_token(
        identity=user.id,
        additional_claims={'role': user.role, 'email': user.email}
    )
    return jsonify({'success': True, 'token': access_token, 'user': _user_dto(user)})


@auth_bp.route('/logout', methods=['POST'])
def logout():
    response = jsonify({'success': True})
    unset_jwt_cookies(response)
    return response


@auth_bp.route('/me', methods=['GET'])
def me():
    from .. import get_current_user
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    return jsonify({'success': True, 'data': _user_dto(user)})


@auth_bp.route('/forgot-password', methods=['POST'])
def forgot_password():
    data = request.get_json(silent=True) or {}
    email = data.get('email', '').strip().lower()
    user = get_user_by_email(email)
    if user and user.status == 'active':
        ttl = current_app.config.get('ACS_RESET_PASSWORD_TTL_HOURS', 1)
        token = create_reset_token(user.id, ttl_hours=ttl)
        reset_url = f"{request.host_url.rstrip('/')}/reset-password/{token}"
        from ..services.email_service import send_reset_password_email
        send_reset_password_email(user.email, reset_url)
    return jsonify({'success': True, 'message': 'If the email exists, a reset link has been sent'}), 202


@auth_bp.route('/reset-password/<token>', methods=['GET'])
def get_reset_token(token):
    user = get_user_by_reset_token(token)
    if not user:
        return jsonify({'success': False, 'error': 'Invalid or expired token'}), 404
    return jsonify({'success': True, 'data': {'email': user.email}})


@auth_bp.route('/reset-password', methods=['POST'])
def reset_password():
    data = request.get_json(silent=True) or {}
    token = data.get('token', '')
    password = data.get('password', '')
    if len(password) < 8:
        return jsonify({'success': False, 'error': 'Password must be at least 8 characters'}), 400
    user = get_user_by_reset_token(token)
    if not user:
        return jsonify({'success': False, 'error': 'Invalid or expired token'}), 404
    consume_reset_token(token, password)
    return jsonify({'success': True})


@auth_bp.route('/invitation/<token>', methods=['GET'])
def get_invitation(token):
    user = get_user_by_invitation_token(token)
    if not user:
        return jsonify({'success': False, 'error': 'Invalid or expired token'}), 404
    return jsonify({'success': True, 'data': {'email': user.email, 'name': user.name}})


@auth_bp.route('/set-password', methods=['POST'])
def set_password():
    data = request.get_json(silent=True) or {}
    token = data.get('token', '')
    password = data.get('password', '')
    if len(password) < 8:
        return jsonify({'success': False, 'error': 'Password must be at least 8 characters'}), 400
    user = get_user_by_invitation_token(token)
    if not user:
        return jsonify({'success': False, 'error': 'Invalid or expired token'}), 404
    consume_invitation_token(token, password)
    return jsonify({'success': True})
