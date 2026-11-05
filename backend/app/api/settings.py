"""Local-only provider setup. Never return or log stored API keys."""
import hmac
import ipaddress
import secrets
from urllib.parse import urlsplit

from flask import Blueprint, current_app, jsonify, request

from ..services.ai_settings import SettingsError, public_settings, save_settings
from ..utils.locale import t

settings_bp = Blueprint('settings', __name__)


def _local_host(host):
    if host == 'localhost':
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@settings_bp.before_request
def require_local_setup():
    try:
        peer = ipaddress.ip_address(request.remote_addr or '')
        host = urlsplit(request.host_url).hostname
        origin = request.headers.get('Origin')
        origin_parts = urlsplit(origin) if origin else None
        if not peer.is_loopback or not _local_host(host) or (origin_parts and (
            origin_parts.scheme not in ('http', 'https') or not _local_host(origin_parts.hostname)
        )):
            raise ValueError()
    except (ValueError, TypeError):
        return jsonify(success=False, error=t('aiSettings.localOnly')), 403
    if request.method == 'POST':
        token = request.headers.get('X-MiroFish-Setup', '')
        if not hmac.compare_digest(token.encode('utf-8'), current_app.config['AI_SETUP_TOKEN'].encode('ascii')):
            return jsonify(success=False, error=t('aiSettings.reload')), 403
        if not request.is_json or request.content_length is None or request.content_length > 16_384:
            return jsonify(success=False, error=t('aiSettings.invalid')), 400


@settings_bp.after_request
def disable_settings_cache(response):
    response.headers['Cache-Control'] = 'no-store'
    return response


@settings_bp.route('/ai', methods=['GET'])
def get_ai_settings():
    return jsonify(success=True, data={**public_settings(), 'setup_token': current_app.config['AI_SETUP_TOKEN']})


@settings_bp.route('/ai', methods=['POST'])
def update_ai_settings():
    try:
        save_settings(request.get_json(silent=True))
        return jsonify(success=True, data=public_settings())
    except SettingsError as error:
        return jsonify(success=False, error=t(f'aiSettings.{error.code}')), 400
    except OSError:
        return jsonify(success=False, error=t('aiSettings.saveFailed')), 500


def register_settings(app):
    app.config['AI_SETUP_TOKEN'] = secrets.token_urlsafe(32)
    app.register_blueprint(settings_bp, url_prefix='/api/settings')
