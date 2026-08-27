"""模型配置中心 API。"""

from dataclasses import asdict
from enum import Enum
import json
import os
import urllib.error
import urllib.request

from flask import jsonify, request

from . import model_settings_bp
from ..services.model_config_service import ModelConfigService
from ..services.model_connection_tester import ModelConnectionTester
from ..services.model_discovery import ModelDiscovery
from ..models.model_config import ModelRole


def _json(value):
    if isinstance(value, Enum): return value.value
    if isinstance(value, dict): return {str(k.value if isinstance(k, Enum) else k): _json(v) for k, v in value.items()}
    if isinstance(value, list): return [_json(v) for v in value]
    return value


def _service():
    service = ModelConfigService()
    service.initialize_from_environment()
    return service


def _gateway_request(path, method='GET'):
    base_url = os.environ.get('DIRECT_OAUTH_GATEWAY_URL', 'http://direct-oauth-gateway:8090')
    token = os.environ.get('DIRECT_GATEWAY_TOKEN', '')
    request_value = urllib.request.Request(base_url + path, data=b'{}' if method == 'POST' else None, method=method, headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request_value, timeout=20) as response:
            return json.load(response), response.status
    except urllib.error.HTTPError as error:
        return json.load(error), error.code


@model_settings_bp.get('/connections')
def list_connections():
    return jsonify({"success": True, "data": [_json(asdict(item)) for item in _service().store.list_connections()]})


@model_settings_bp.post('/connections')
def create_connection():
    data = request.get_json() or {}
    try:
        item = _service().store.create_connection(data["name"], data["connection_type"], data["base_url"], data.get("api_key", ""), data.get("is_local", False))
        return jsonify({"success": True, "data": _json(asdict(item))}), 201
    except (KeyError, ValueError) as error:
        return jsonify({"success": False, "error": str(error)}), 400


@model_settings_bp.patch('/connections/<connection_id>')
def update_connection(connection_id):
    return jsonify({"success": True, "data": _json(asdict(_service().store.update_connection(connection_id, **(request.get_json() or {}))))})


@model_settings_bp.delete('/connections/<connection_id>')
def delete_connection(connection_id):
    try:
        _service().store.delete_connection(connection_id)
        return jsonify({"success": True})
    except ValueError as error:
        return jsonify({"success": False, "error": str(error)}), 409


@model_settings_bp.route('/draft', methods=['GET', 'PUT'])
def draft():
    service = _service()
    if request.method == 'PUT':
        try: service.save_draft(request.get_json() or {})
        except ValueError as error: return jsonify({"success": False, "error": str(error)}), 400
    return jsonify({"success": True, "data": _json(service.store.get_draft())})


@model_settings_bp.post('/apply')
def apply():
    try: version = _service().apply_draft()
    except ValueError as error: return jsonify({"success": False, "error": str(error)}), 400
    return jsonify({"success": True, "data": _json(asdict(version))})


@model_settings_bp.post('/test')
def test_connection():
    connection_id = (request.get_json() or {}).get('connection_id')
    if not connection_id:
        return jsonify({"success": False, "error": "缺少 connection_id"}), 400
    result = ModelConnectionTester(_service().store).test(connection_id)
    return jsonify({"success": result["status"] == "passed", "data": result, "error": None if result["status"] == "passed" else "连接测试失败"}), 200 if result["status"] == "passed" else 422


@model_settings_bp.get('/connections/<connection_id>/models')
def connection_models(connection_id):
    try:
        service = _service()
        role = ModelRole(request.args.get('role', 'high_capability'))
        connection = service.store.get_connection(connection_id)
        models = ModelDiscovery().list_models(connection, service.store.get_connection_secret(connection_id), role)
        return jsonify({"success": True, "data": models})
    except (KeyError, ValueError) as error:
        return jsonify({"success": False, "error": str(error)}), 400
    except Exception as error:
        return jsonify({"success": False, "error": "无法获取模型列表", "error_code": type(error).__name__}), 502


@model_settings_bp.get('/active')
def active():
    value = _service().store.get_active_version()
    return jsonify({"success": True, "data": _json(asdict(value)) if value else None})


@model_settings_bp.get('/oauth/account')
def oauth_account():
    data, status = _gateway_request('/account')
    return jsonify({"success": status < 400, "data": data}), status


@model_settings_bp.post('/oauth/device/start')
def oauth_device_start():
    data, status = _gateway_request('/oauth/device/start', 'POST')
    return jsonify({"success": status < 400, "data": data}), status


@model_settings_bp.get('/oauth/device/<login_id>')
def oauth_device_status(login_id):
    data, status = _gateway_request(f'/oauth/device/{login_id}')
    return jsonify({"success": status < 400, "data": data}), status


@model_settings_bp.post('/oauth/device/<login_id>/cancel')
def oauth_device_cancel(login_id):
    data, status = _gateway_request(f'/oauth/device/{login_id}/cancel', 'POST')
    return jsonify({"success": status < 400, "data": data}), status


@model_settings_bp.post('/oauth/logout')
def oauth_logout():
    data, status = _gateway_request('/oauth/logout', 'POST')
    return jsonify({"success": status < 400, "data": data}), status
