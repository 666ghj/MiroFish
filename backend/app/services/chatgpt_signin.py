"""Local Sign in with ChatGPT OAuth session for an open-source installation."""

from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
import secrets
import tempfile
import threading
import time
import uuid
from ctypes import wintypes
from pathlib import Path
from urllib.parse import urlencode

import jwt
from jwt import PyJWKClient
import httpx

from ..config import Config
from . import local_codex_provider


ISSUER = "https://auth.openai.com"
AUTHORIZE_URL = f"{ISSUER}/api/accounts/authorize"
TOKEN_URL = f"{ISSUER}/api/accounts/oauth/token"
JWKS_URL = f"{ISSUER}/.well-known/jwks.json"
RESOURCE = "https://api.openai.com/v1"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
_lock = threading.RLock()
_pending: dict[str, object] | None = None
_active = False
_secret = secrets.token_urlsafe(32)
_jwk_client = PyJWKClient(JWKS_URL)


def _store_path() -> Path:
    home = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".config")
    return Path(home) / "MiroFish" / "chatgpt-session.dat"


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _dpapi(data: bytes, *, protect: bool) -> bytes:
    if os.name != "nt":
        raise RuntimeError("El almacenamiento protegido de ChatGPT requiere Windows")
    source = ctypes.create_string_buffer(data)
    input_blob = _DataBlob(len(data), ctypes.cast(source, ctypes.POINTER(ctypes.c_byte)))
    output_blob = _DataBlob()
    operation = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    if not operation(ctypes.byref(input_blob), None, None, None, None, 0, ctypes.byref(output_blob)):
        raise RuntimeError("No se pudo proteger la sesión de ChatGPT")
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output_blob.pbData)


def _load() -> dict:
    path = _store_path()
    if not path.exists():
        return {"host_id": f"urn:uuid:{uuid.uuid4()}", "accounts": [], "selected": None}
    return json.loads(_dpapi(path.read_bytes(), protect=False).decode("utf-8"))


def _save(state: dict) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _dpapi(json.dumps(state).encode("utf-8"), protect=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".session-", delete=False) as temp:
        temp.write(data)
        temporary_path = Path(temp.name)
    temporary_path.replace(path)


def _selected(state: dict) -> dict | None:
    return next((item for item in state["accounts"] if item["key"] == state.get("selected")), None)


def status() -> dict:
    with _lock:
        state = _load()
        account = _selected(state)
        return {
            "connected": bool(_active and account and "chatgpt.tokens.use.direct" in account.get("scopes", [])),
            "saved_account": bool(account and account.get("refresh_token")),
            "account_key": account.get("key") if account else None,
            "authorized_at": account.get("authorized_at") if account else None,
            "email": account.get("email") if account else None,
            "model": account.get("model") if account else None,
            "active_provider": "chatgpt" if _active else local_codex_provider.status()["active_provider"],
            "configured_provider": local_codex_provider.status()["configured_provider"],
        }


def start(*, account_key: str | None = None) -> str:
    global _pending
    with _lock:
        state = _load()
        if not _store_path().exists():
            _save(state)
        account = next((a for a in state["accounts"] if a["key"] == account_key), None) if account_key else None
        if account_key and account is None:
            raise ValueError("Cuenta de ChatGPT desconocida")
        verifier = secrets.token_urlsafe(64)
        nonce = secrets.token_urlsafe(32)
        oauth_state = secrets.token_urlsafe(32)
        port = int(os.environ.get("FLASK_PORT", "5001"))
        redirect_uri = f"http://127.0.0.1:{port}/api/provider/auth/callback"
        _pending = {
            "state": oauth_state, "nonce": nonce, "verifier": verifier,
            "redirect_uri": redirect_uri, "account_key": account_key,
            "client_id": account["client_id"] if account else "dynamic_agent_client",
            "expires_at": time.time() + 600,
        }
        params = {
            "client_id": _pending["client_id"], "response_type": "code",
            "redirect_uri": redirect_uri, "scope": SCOPES, "resource": RESOURCE,
            "state": oauth_state, "nonce": nonce,
            "code_challenge_method": "S256",
            "code_challenge": base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode(),
            "ext_agent_host_id": state["host_id"],
        }
        if account:
            if account.get("email"):
                params["login_hint"] = account["email"]
        else:
            params["agent_name_hint"] = "MiroFish"
        return f"{AUTHORIZE_URL}?{urlencode(params)}"


def _validate_id_token(token: str, *, client_id: str, nonce: str) -> dict:
    key = _jwk_client.get_signing_key_from_jwt(token)
    claims = jwt.decode(token, key.key, algorithms=["RS256"], audience=client_id, issuer=ISSUER)
    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise ValueError("El inicio de sesión no coincide con la solicitud")
    if not claims.get("sub"):
        raise ValueError("La cuenta de ChatGPT no tiene identidad verificable")
    return claims


def _token_request(fields: dict) -> dict:
    try:
        with httpx.Client(timeout=20, follow_redirects=False) as client:
            response = client.post(TOKEN_URL, data=fields, headers={"Accept": "application/json"})
    except httpx.HTTPError as error:
        raise RuntimeError("No se pudo contactar el servicio de autorización de ChatGPT") from error
    if response.status_code != 200:
        raise RuntimeError(f"ChatGPT rechazó la autorización (HTTP {response.status_code})")
    return response.json()


def finish(query: dict) -> dict:
    global _pending, _active
    with _lock:
        pending = _pending
        _pending = None
        if not pending or time.time() >= pending["expires_at"]:
            raise ValueError("El inicio de sesión venció; inténtalo de nuevo")
        if not secrets.compare_digest(str(query.get("state", "")), str(pending["state"])):
            raise ValueError("El inicio de sesión no coincide con la solicitud")
        if query.get("error"):
            raise ValueError("No se autorizó el uso de ChatGPT")
        code = query.get("code")
        if not code:
            raise ValueError("ChatGPT no devolvió un código de autorización")
        registered = pending["account_key"] is None
        issued_id = query.get("client_id") if registered else pending["client_id"]
        if not issued_id or issued_id == "dynamic_agent_client":
            raise ValueError("ChatGPT no devolvió el ID del cliente registrado")
        if not registered and query.get("client_id") not in (None, issued_id):
            raise ValueError("El cliente registrado no coincide")
        tokens = _token_request({
            "grant_type": "authorization_code", "client_id": issued_id,
            "code": code, "code_verifier": pending["verifier"],
            "redirect_uri": pending["redirect_uri"], "resource": RESOURCE,
        })
        claims = _validate_id_token(tokens["id_token"], client_id=issued_id, nonce=pending["nonce"])
        scopes = tokens.get("scope", "").split()
        if "chatgpt.tokens.use.direct" not in scopes or not tokens.get("refresh_token"):
            raise ValueError("La cuenta no autorizó el uso del plan de ChatGPT")
        state = _load()
        prior = next((a for a in state["accounts"] if a["key"] == pending["account_key"]), None)
        if prior and (prior["subject"] != claims["sub"] or prior["client_id"] != issued_id):
            raise ValueError("La cuenta seleccionada no coincide con la cuenta autorizada")
        account = prior or {"key": uuid.uuid4().hex}
        account.update({
            "client_id": issued_id, "subject": claims["sub"],
            "email": claims.get("email"), "id_token": tokens["id_token"],
            "access_token": tokens["access_token"], "refresh_token": tokens["refresh_token"],
            "scopes": scopes, "expires_at": time.time() + int(tokens.get("expires_in", 3600)),
            "authorized_at": time.time(),
        })
        if not prior:
            state["accounts"].append(account)
        state["selected"] = account["key"]
        _save(state)
        _active = False
        return status()


def access_token() -> str:
    with _lock:
        state = _load()
        account = _selected(state)
        if not account or not account.get("refresh_token"):
            raise RuntimeError("Inicia sesión con ChatGPT")
        if time.time() + 120 >= account.get("expires_at", 0):
            tokens = _token_request({
                "grant_type": "refresh_token", "client_id": account["client_id"],
                "refresh_token": account["refresh_token"], "resource": RESOURCE,
            })
            if not tokens.get("refresh_token"):
                raise RuntimeError("ChatGPT no renovó la sesión")
            account.update({
                "access_token": tokens["access_token"], "refresh_token": tokens["refresh_token"],
                "scopes": tokens.get("scope", "").split(),
                "expires_at": time.time() + int(tokens.get("expires_in", 3600)),
            })
            _save(state)
        return account["access_token"]


def list_models() -> list[dict]:
    token = access_token()
    try:
        with httpx.Client(timeout=20, follow_redirects=False) as client:
            response = client.get(f"{RESOURCE}/models", headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError as error:
        raise RuntimeError("No se pudo consultar el catálogo de ChatGPT") from error
    if response.status_code != 200:
        raise RuntimeError(f"No se pudieron consultar los modelos de ChatGPT (HTTP {response.status_code})")
    return [{"slug": m["slug"], "display_name": m.get("display_name", m["slug"])}
            for m in response.json().get("models", []) if m.get("visibility") == "list" and m.get("slug")]


def activate(model: str | None = None) -> dict:
    global _active
    with _lock:
        models = list_models()
        if not models:
            raise RuntimeError("La cuenta no tiene modelos disponibles para esta integración")
        available = {item["slug"] for item in models}
        state = _load()
        account = _selected(state)
        selected_model = model or account.get("model") or ("gpt-6-luna" if "gpt-6-luna" in available else models[0]["slug"])
        if selected_model not in available:
            raise ValueError("El modelo elegido no está disponible para esta cuenta")
        # Confirm an actual completed inference before showing Connected.
        from . import chatgpt_compat
        chatgpt_compat.complete({
            "model": selected_model,
            "messages": [{"role": "user", "content": "Responde exactamente: conexión lista"}],
        })
        local_codex_provider.deactivate()
        account["model"] = selected_model
        _save(state)
        port = int(os.environ.get("FLASK_PORT", "5001"))
        local_codex_provider._set_llm(_secret, f"http://127.0.0.1:{port}/api/provider/compat/v1", selected_model)
        _active = True
        return status()


def deactivate() -> dict:
    global _active
    with _lock:
        _active = False
        local_codex_provider.deactivate()
        return status()


def check_bridge_token(value: str | None) -> bool:
    return bool(_active and value and secrets.compare_digest(value, f"Bearer {_secret}"))
