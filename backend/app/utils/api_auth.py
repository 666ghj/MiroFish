"""
Optional shared-secret API token for /api routes (mitigates R-003).

When the MIROFISH_API_TOKEN environment variable is set (non-empty) at app
creation, every request whose path starts with /api/ must carry a matching
X-API-Token header, otherwise it is rejected with HTTP 401. CORS preflight
(OPTIONS) and /health are always allowed. When the variable is unset or
empty, no hook is registered and behaviour is unchanged.

Note: the frontend sends this token from its build-time env (VITE_API_TOKEN),
so it ends up in the browser bundle. It gates casual network callers, not
users who can load the UI.
"""

import hmac
import os

from flask import Flask, jsonify, request

API_TOKEN_ENV = 'MIROFISH_API_TOKEN'
API_TOKEN_HEADER = 'X-API-Token'


def register_api_auth(app: Flask) -> None:
    """Register a before_request hook enforcing the API token, if configured."""
    expected = os.environ.get(API_TOKEN_ENV, '').strip()
    if not expected:
        return

    expected_bytes = expected.encode('utf-8')

    @app.before_request
    def require_api_token():
        if request.method == 'OPTIONS':
            return None
        if not request.path.startswith('/api/'):
            return None
        provided = request.headers.get(API_TOKEN_HEADER, '')
        if hmac.compare_digest(provided.encode('utf-8'), expected_bytes):
            return None
        return jsonify({
            'success': False,
            'error': f'Missing or invalid {API_TOKEN_HEADER} header',
        }), 401
