from flask import request, jsonify
from ..config import Config
from .logger import get_logger

logger = get_logger('mirofish.auth')

_SKIP_PATHS = {'/health'}


def check_api_key():
    """Flask before_request handler — enforces X-Api-Key when API_KEY is configured."""
    if not Config.API_KEY:
        return  # API key auth is disabled; log a warning once at startup instead

    if request.path in _SKIP_PATHS:
        return

    provided = request.headers.get('X-Api-Key', '')
    if not provided or provided != Config.API_KEY:
        logger.warning(f"Unauthorized request to {request.method} {request.path}")
        return jsonify({"success": False, "error": "Unauthorized"}), 401
