"""
OrcaRouter provider blueprint.

Exposes the two credential choices (API key and OAuth 2.0 + PKCE), provider
status, and per-capability model discovery to the frontend. The API key
never lives in the browser: the backend holds it and returns only minimal,
redacted status to the frontend.
"""

import os

from flask import Blueprint, jsonify, request

from ..config import Config
from ..utils.orcarouter import (
    ApiKeyAdapter,
    ConnectManager,
    ExchangeFailedError,
    OrcaCredentialStore,
    OrcaEndpoints,
    OrcaModelCatalog,
    PKCEConnectError,
    ScopeDowngradeError,
    classify_relay_401,
    redact,
)

orca_bp = Blueprint("orcarouter", __name__)

# One shared connect manager per backend process. Attempts expire server side
# (10 minute TTL) so a leaked authorize URL cannot hang a fresh login.
connect_manager = ConnectManager()


def _store() -> OrcaCredentialStore:
    return OrcaCredentialStore()


def _credential():
    return _store().get()


def _redacted_status():
    credential = _credential()
    provider = os.environ.get("LLM_PROVIDER", "default")
    model = os.environ.get(OrcaCredentialStore.MODEL_VAR) or "orcarouter/auto"
    if credential is None:
        return {
            "configured": False,
            "provider": provider,
            "model": model if provider == "orcarouter" else None,
            "source": None,
            "key_preview": None,
            "scope": None,
            "user_id": None,
        }
    return {
        "configured": True,
        "provider": provider,
        "model": model if provider == "orcarouter" else None,
        "source": credential.source,
        "key_preview": redact(credential.key),
        "scope": credential.scope,
        "user_id": credential.user_id,
    }


@orca_bp.route("/api/orcarouter/status", methods=["GET"])
def status():
    """Provider status for the settings UI. Never returns the raw key."""
    return jsonify(_redacted_status())


@orca_bp.route("/api/orcarouter/models", methods=["GET"])
def models():
    """Per-capability model dropdowns from the live OrcaRouter catalog.

    Query params: ``capability`` = chat | embedding | image | video | rerank
    Response:
      ``{ "source": "live" | "seed", "degraded": bool, "models": [...] }``
    When live discovery fails or no credential is configured, the verified
    cold-start seed is returned with ``degraded=True``; the frontend shows
    it as degraded/refreshable rather than as free-text input.
    """
    capability = request.args.get("capability", "chat")
    if capability not in {"chat", "embedding", "image", "video", "rerank"}:
        return jsonify({"error": f"unsupported capability: {capability}"}), 400

    credential = _credential()
    catalog = OrcaModelCatalog(credential=credential)

    try:
        if credential is None or not credential.key:
            raise PKCEConnectError(
                "No OrcaRouter credential configured.",
                code="no_credential",
            )
        models = catalog.discover(capability)
        return jsonify(
            {
                "source": "live",
                "degraded": False,
                "models": [m.to_dict() for m in models],
            }
        )
    except PKCEConnectError as exc:
        # Outage / missing credential: verified seed, degraded, refreshable.
        return jsonify(
            {
                "source": "seed",
                "degraded": True,
                "message": str(exc),
                "models": [m.to_dict() for m in catalog.seed(capability)],
            }
        )


@orca_bp.route("/api/orcarouter/key", methods=["POST"])
def set_api_key():
    """API-key choice: the user pastes an existing ``sk-orca-...`` key.

    The key is stored in the project's own secret location (.env + env) and
    is never returned to the browser. Validity is left to the first real
    request, not to a paid validation call.
    """
    data = request.get_json(silent=True) or {}
    key = str(data.get("key") or "").strip()
    if not key:
        return jsonify({"error": "An OrcaRouter API key is required."}), 400

    adapter = ApiKeyAdapter(store=_store())
    try:
        adapter.set(key)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"status": _redacted_status()})


@orca_bp.route("/api/orcarouter/key", methods=["DELETE"])
def clear_api_key():
    """Remove the stored OrcaRouter credential."""
    _store().clear()
    return jsonify({"status": _redacted_status()})


@orca_bp.route("/api/orcarouter/connect/start", methods=["POST"])
def connect_start():
    """PKCE choice: begin an OAuth 2.0 + PKCE (S256) authorization.

    Returns the authorize URL (Flow B out-of-band: the browser opens the
    consent screen, the user copies the displayed code back). The verifier
    stays in this process; only the challenge and state ride the URL.
    """
    attempt = connect_manager.start()
    endpoints = OrcaEndpoints.from_env()
    from urllib.parse import urlencode

    params = {
        "callback_url": "oob",
        "code_challenge": attempt.challenge,
        "code_challenge_method": "S256",
        "state": attempt.state,
        "app_name": "MiroFish",
        "scope": "api",
    }
    authorize_url = endpoints.authorize_url + "?" + urlencode(params)
    return jsonify(
        {
            "attempt_id": attempt.attempt_id,
            "authorize_url": authorize_url,
        }
    )


@orca_bp.route("/api/orcarouter/connect/exchange", methods=["POST"])
def connect_exchange():
    """Exchange the user-supplied out-of-band code for a durable API key."""
    data = request.get_json(silent=True) or {}
    attempt_id = str(data.get("attempt_id") or "")
    code = str(data.get("code") or "").strip()
    if not attempt_id or not code:
        return jsonify(
            {"error": "Both the authorization link and code are required."}
        ), 400

    try:
        credential = connect_manager.exchange(attempt_id, code)
    except (PKCEConnectError, ScopeDowngradeError) as exc:
        return jsonify({"error": str(exc), "code": getattr(exc, "code", "pkce_error")}), 400

    store = _store()
    # Do not silently delete an old secret before a successful replacement;
    # save() overwrites atomically once the new key is confirmed.
    store.save(credential)
    return jsonify({"status": _redacted_status()})


@orca_bp.route("/api/orcarouter/connect/cancel", methods=["POST"])
def connect_cancel():
    """Explicit cancel of an in-flight PKCE authorization."""
    data = request.get_json(silent=True) or {}
    attempt_id = str(data.get("attempt_id") or "")
    if attempt_id:
        connect_manager.cancel(attempt_id)
    return jsonify({"ok": True})


@orca_bp.route("/api/orcarouter/model", methods=["POST"])
def set_model():
    """Persist the user's OrcaRouter model choice (revalidated on restore)."""
    data = request.get_json(silent=True) or {}
    model = str(data.get("model") or "").strip()
    if not model:
        return jsonify({"error": "A model id is required."}), 400
    _store().save_model(model)
    return jsonify({"model": model})


@orca_bp.route("/api/orcarouter/provider", methods=["POST"])
def set_provider():
    """Activate the OrcaRouter provider (or switch back to default).

    ``{ "provider": "orcarouter" | "default" }``. Switching to ``orcarouter``
    requires a stored OrcaRouter key; selecting it with none is rejected so
    the user is never routed into a dead provider.
    """
    data = request.get_json(silent=True) or {}
    provider = str(data.get("provider") or "").strip()
    if provider not in {"default", "orcarouter"}:
        return jsonify({"error": f"unsupported provider: {provider}"}), 400
    if provider == "orcarouter" and _credential() is None:
        return jsonify(
            {
                "error": "Select OrcaRouter requires a key first. Paste an "
                "sk-orca-... API key or connect with your OrcaRouter account."
            }
        ), 400
    _store().save_provider(provider)
    return jsonify({"provider": provider})


@orca_bp.route("/api/orcarouter/reauth", methods=["POST"])
def mark_reauth():
    """Terminal reauthentication marker for a revoked durable key.

    A 401 from the relay means the durable key was revoked: mark the exact
    account/credential generation as needing reauth and keep it unusable
    until a new login succeeds. No fake refresh is ever attempted.
    """
    credential = _credential()
    if credential is None:
        return jsonify({"needs_reauth": False}), 200
    return jsonify(classify_relay_401(credential))
