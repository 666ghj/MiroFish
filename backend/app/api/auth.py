"""
Autenticació bàsica: POST /api/auth/login
Retorna JWT HS256 amb 24h d'expiració.
Si DEMO_PASSWORD és buida (no configurada), sempre retorna 401.
"""
import jwt
import datetime
from flask import request, jsonify, current_app
from . import auth_bp


@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    username = data.get('username', '')
    password = data.get('password', '')

    expected = current_app.config.get('DEMO_PASSWORD', '')
    if username != 'demo' or not expected or password != expected:
        return jsonify({'success': False, 'error': 'Invalid credentials'}), 401

    payload = {
        'sub': username,
        'iat': datetime.datetime.utcnow(),
        'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=24),
    }
    token = jwt.encode(payload, current_app.config['SECRET_KEY'], algorithm='HS256')
    return jsonify({'success': True, 'token': token})
