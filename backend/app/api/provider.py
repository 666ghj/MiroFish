"""Local-only provider controls. No account tokens are returned to clients."""

from flask import jsonify, request
from markupsafe import escape

from . import provider_bp
from ..services import local_codex_provider
from ..services import chatgpt_signin, chatgpt_compat


@provider_bp.get("/status")
def provider_status():
    if not _local_only():
        return jsonify({"success": False, "error": "Solo se permite desde este equipo"}), 403
    return jsonify({"success": True, "data": {**local_codex_provider.status(), "chatgpt": chatgpt_signin.status()}})


def _local_only():
    return local_codex_provider.is_local_request(request.remote_addr, request.headers.get("Origin"))


@provider_bp.post("/chatgpt/start")
def start_chatgpt():
    if not _local_only():
        return jsonify({"success": False, "error": "Solo se permite desde este equipo"}), 403
    try:
        return jsonify({"success": True, "data": {"url": chatgpt_signin.start(account_key=(request.get_json(silent=True) or {}).get("account_key"))}})
    except (ValueError, RuntimeError) as error:
        return jsonify({"success": False, "error": str(error)}), 400


@provider_bp.get("/auth/callback")
def chatgpt_callback():
    if not _local_only():
        return "Solicitud no permitida", 403
    try:
        chatgpt_signin.finish(request.args)
        return "<h1>ChatGPT autorizado</h1><p>Regresa a MiroFish para elegir el modelo.</p>"
    except (ValueError, RuntimeError, KeyError) as error:
        return f"<h1>No se completó la conexión</h1><p>{escape(str(error))}</p>", 400


@provider_bp.get("/chatgpt/models")
def chatgpt_models():
    if not _local_only():
        return jsonify({"success": False, "error": "Solo se permite desde este equipo"}), 403
    try:
        return jsonify({"success": True, "data": chatgpt_signin.list_models()})
    except RuntimeError as error:
        return jsonify({"success": False, "error": str(error)}), 503


@provider_bp.post("/chatgpt/activate")
def activate_chatgpt():
    if not _local_only():
        return jsonify({"success": False, "error": "Solo se permite desde este equipo"}), 403
    try:
        result = chatgpt_signin.activate((request.get_json(silent=True) or {}).get("model"))
        return jsonify({"success": True, "data": result})
    except (ValueError, RuntimeError) as error:
        return jsonify({"success": False, "error": str(error)}), 400


@provider_bp.post("/chatgpt/deactivate")
def deactivate_chatgpt():
    if not _local_only():
        return jsonify({"success": False, "error": "Solo se permite desde este equipo"}), 403
    return jsonify({"success": True, "data": chatgpt_signin.deactivate()})


@provider_bp.post("/compat/v1/chat/completions")
def chatgpt_chat_compat():
    if not _local_only() or not chatgpt_signin.check_bridge_token(request.headers.get("Authorization")):
        return jsonify({"error": {"message": "Unauthorized"}}), 401
    if request.content_length is None or request.content_length > 1024 * 1024:
        return jsonify({"error": {"message": "Request too large"}}), 413
    try:
        return jsonify(chatgpt_compat.complete(request.get_json()))
    except ValueError as error:
        return jsonify({"error": {"message": str(error)}}), 400
    except RuntimeError as error:
        return jsonify({"error": {"message": str(error)}}), 502


@provider_bp.post("/codex/activate")
def activate_codex():
    if not local_codex_provider.is_local_request(request.remote_addr, request.headers.get("Origin")):
        return jsonify({"success": False, "error": "Solo se permite desde este equipo"}), 403
    try:
        return jsonify({"success": True, "data": local_codex_provider.activate()})
    except RuntimeError as error:
        return jsonify({"success": False, "error": str(error)}), 503


@provider_bp.post("/codex/deactivate")
def deactivate_codex():
    if not local_codex_provider.is_local_request(request.remote_addr, request.headers.get("Origin")):
        return jsonify({"success": False, "error": "Solo se permite desde este equipo"}), 403
    return jsonify({"success": True, "data": local_codex_provider.deactivate()})
