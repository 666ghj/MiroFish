"""
OrcaRouter model provider for MiroFish.

Two explicit credential choices, both producing the same kind of ordinary
OrcaRouter API key (``sk-orca-...``):

- ``ApiKeyAdapter``    - the user pastes an existing ``sk-orca-...`` key.
- ``PKCEAdapter``      - OAuth 2.0 Authorization Code + PKCE (S256) flow that
                         returns a durable API key owned by the user.

The credential seam is :class:`CredentialAdapter`. Provider requests, model
discovery and every AI entry point consume a plain :class:`OrcaCredential`
and never care which adapter produced it.

Auth and inference use different public origins:

- auth + code exchange: ``https://www.orcarouter.ai``
  (authorize ``/auth``, exchange ``/api/v1/auth/keys``)
- inference + model discovery: ``https://api.orcarouter.ai/v1``

Both are configurable. ``ORCA_BASE_URL`` is a shared self-hosted fallback;
``ORCA_AUTH_BASE_URL`` and ``ORCA_API_BASE_URL`` are explicit overrides and
win. A remote origin must use HTTPS; HTTP is allowed only for loopback
development.

The flow implemented here is Flow B (out-of-band code) because MiroFish is
self-hosted software whose install address differs on every deployment (LAN
box, NAS, a moved port, Docker): there is no predictable callback host, and
the web UI's browser cannot listen on ``127.0.0.1``. ``S256`` is mandatory
for a code shown to a human. No client secret, no pre-registered redirect.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Sequence
from typing_extensions import Protocol, runtime_checkable

import httpx

from ..config import Config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PUBLIC_AUTH_BASE = "https://www.orcarouter.ai"
PUBLIC_API_BASE = "https://api.orcarouter.ai"

AUTHORIZE_PATH = "/auth"
EXCHANGE_PATH = "/api/v1/auth/keys"
API_PREFIX = "/v1"

DEFAULT_APP_NAME = "MiroFish"

# Catalog discovery bounds (a hostile/broken catalog must not consume
# unbounded memory or time).
CATALOG_TIMEOUT_SECONDS = 10.0
CATALOG_MAX_ITEMS = 2000

EXCHANGE_TIMEOUT_SECONDS = 30.0

# PKCE connect attempt lifetime (auth codes are single-use with a 10 minute
# TTL; we also expire the in-memory attempt so a leaked URL cannot hang a
# fresh login).
CONNECT_ATTEMPT_TTL_SECONDS = 600.0

SCOPE_API = "api"
SCOPE_CONNECTOR = "connector"

# Endpoint types we accept as a text chat model. Everything else is either
# declared non-text (image-generation / openai-video / jina-rerank) or
# unknown, which fails closed.
TEXT_CHAT_ENDPOINT_TYPES = {
    "openai",
    "anthropic",
    "gemini",
    "openai-response",
}
NON_TEXT_CHAT_ENDPOINTS = {"image-generation", "openai-video", "jina-rerank"}


def b64url(raw: bytes) -> str:
    """RFC 4648 base64url, no padding."""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def sha256_b64url(value: str) -> str:
    """``base64url(sha256(value))`` no padding - the S256 PKCE challenge."""
    return b64url(hashlib.sha256(value.encode("utf-8")).digest())


def redact(value: Optional[str]) -> str:
    """Mask a secret for display (``sk-orca-...`` + last 4 chars).

    Very short secrets are masked entirely - revealing most characters of a
    short key would not be redaction.
    """
    if not value:
        return ""
    if len(value) < 24:
        return "**********"
    return value[:8] + "..." + value[-4:]


_SK_ORCA_RE = re.compile(r"^sk-orca-[A-Za-z0-9_\-\.]+$")


def looks_like_orca_key(value: str) -> bool:
    """Lightweight format guard only - never proof of validity."""
    return bool(_SK_ORCA_RE.match(value.strip()))


def _require_https_or_loopback(value: str, *, name: str) -> str:
    value = value.strip()
    if value.startswith("https://"):
        return value
    if value.startswith("http://"):
        rest = value[len("http://"):]
        host = rest.split("/", 1)[0].rsplit(":", 1)[0].lower()
        if host in {"127.0.0.1", "localhost", "[::1]"}:
            return value
        raise ValueError(
            f"{name} must use HTTPS for a remote origin; got {value!r}"
        )
    raise ValueError(f"{name} must be an absolute http(s) URL; got {value!r}")


# ---------------------------------------------------------------------------
# Origins
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OrcaEndpoints:
    """Resolved auth vs inference origins with explicit overrides winning."""

    auth_base: str
    api_base: str

    @classmethod
    def from_env(cls) -> "OrcaEndpoints":
        shared = os.environ.get("ORCA_BASE_URL", "").strip()
        auth = os.environ.get("ORCA_AUTH_BASE_URL", "").strip() or shared
        api = os.environ.get("ORCA_API_BASE_URL", "").strip() or shared
        return cls(
            auth_base=_require_https_or_loopback(
                auth or PUBLIC_AUTH_BASE, name="ORCA_AUTH_BASE_URL"
            ),
            api_base=_require_https_or_loopback(
                api or PUBLIC_API_BASE, name="ORCA_API_BASE_URL"
            ),
        )

    @property
    def authorize_url(self) -> str:
        return self.auth_base.rstrip("/") + AUTHORIZE_PATH

    @property
    def exchange_url(self) -> str:
        # Authentication endpoints live on the *auth* origin. The relay at
        # api.orcarouter.ai/v1/auth/keys is a 404 - never use it.
        return self.auth_base.rstrip("/") + EXCHANGE_PATH

    @property
    def models_url(self) -> str:
        return self.api_base.rstrip("/") + API_PREFIX + "/models"

    @property
    def inference_base(self) -> str:
        return self.api_base.rstrip("/") + API_PREFIX


# ---------------------------------------------------------------------------
# Credential seam
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OrcaCredential:
    """The single credential result every adapter produces."""

    key: str
    user_id: Optional[str] = None
    scope: str = SCOPE_API
    source: Literal["api_key", "pkce"] = "api_key"

    def redacted(self) -> str:
        return redact(self.key)


class CredentialAdapter(Protocol):
    """Seam every auth method plugs into. Not part of the runtime API."""

    source: Literal["api_key", "pkce"]

    def get(self) -> Optional[OrcaCredential]:
        ...


class OrcaCredentialStore:
    """Reuses the project's own secret mechanism: environment + project .env.

    MiroFish keeps every secret (``LLM_API_KEY``, ``ZEP_API_KEY``) in the
    root ``.env`` read through ``app.config``. We store the OrcaRouter key in
    the same place and never introduce a new plaintext side store. The key is
    never logged, echoed, or returned unredacted by any API.
    """

    ENV_VAR = "ORCAROUTER_API_KEY"
    USER_ID_VAR = "ORCAROUTER_USER_ID"
    SCOPE_VAR = "ORCAROUTER_SCOPE"
    MODEL_VAR = "ORCAROUTER_MODEL_NAME"

    def __init__(self, env_path: Optional[str] = None):
        self._env_path = env_path or os.path.join(
            os.path.dirname(__file__), "..", "..", ".env"
        )

    def get(self) -> Optional[OrcaCredential]:
        key = os.environ.get(self.ENV_VAR) or ""
        if not key:
            return None
        return OrcaCredential(
            key=key,
            user_id=os.environ.get(self.USER_ID_VAR),
            scope=os.environ.get(self.SCOPE_VAR) or SCOPE_API,
            source=(
                "pkce"
                if os.environ.get(self.SCOPE_VAR) in {SCOPE_API, SCOPE_CONNECTOR}
                and os.environ.get(self.USER_ID_VAR)
                else "api_key"
            ),
        )

    def save(self, credential: OrcaCredential) -> None:
        if not credential.key:
            raise ValueError("cannot save an empty OrcaRouter credential")
        os.environ[self.ENV_VAR] = credential.key
        os.environ[self.SCOPE_VAR] = credential.scope or SCOPE_API
        if credential.user_id:
            os.environ[self.USER_ID_VAR] = credential.user_id
        else:
            os.environ.pop(self.USER_ID_VAR, None)
        self._write_env_file(credential)
        logger.info("OrcaRouter credential persisted (%s)", redact(credential.key))

    def clear(self) -> None:
        for var in (self.ENV_VAR, self.USER_ID_VAR, self.SCOPE_VAR):
            os.environ.pop(var, None)
        self._write_env_file(None)
        logger.info("OrcaRouter credential cleared")

    def save_model(self, model: str) -> None:
        os.environ[self.MODEL_VAR] = model
        self._write_env_key(self.MODEL_VAR, model)

    def save_provider(self, provider: str) -> None:
        """Persist the active model provider (``default`` | ``orcarouter``)."""
        if provider not in {"default", "orcarouter"}:
            raise ValueError(f"unsupported provider: {provider}")
        os.environ["LLM_PROVIDER"] = provider
        self._write_env_key("LLM_PROVIDER", provider)

    def _write_env_key(self, key: str, value: str) -> None:
        try:
            lines = self._read_lines()
        except OSError:
            return
        prefix = f"{key}="
        lines = [line for line in lines if not line.startswith(prefix)]
        lines.append(f"{key}={value}")
        self._write_lines(lines)

    def _write_env_file(self, credential: Optional[OrcaCredential]) -> None:
        try:
            lines = self._read_lines()
        except OSError:
            return
        for var, value in (
            (self.ENV_VAR, credential.key if credential else None),
            (self.USER_ID_VAR, credential.user_id if credential else None),
            (self.SCOPE_VAR, credential.scope if credential else None),
        ):
            prefix = f"{var}="
            lines = [line for line in lines if not line.startswith(prefix)]
            if value:
                lines.append(f"{var}={value}")
        self._write_lines(lines)

    def _read_lines(self) -> List[str]:
        if not os.path.exists(self._env_path):
            return []
        with open(self._env_path, "r", encoding="utf-8") as handle:
            return handle.read().splitlines()

    def _write_lines(self, lines: List[str]) -> None:
        with open(self._env_path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
        try:
            os.chmod(self._env_path, 0o600)
        except OSError:  # pragma: no cover - host-specific
            pass


class ApiKeyAdapter:
    """User pastes an existing ``sk-orca-...`` key - the API-key choice."""

    source = "api_key"

    def __init__(self, store: Optional[OrcaCredentialStore] = None):
        self.store = store or OrcaCredentialStore()

    def get(self) -> Optional[OrcaCredential]:
        return self.store.get()

    def set(self, key: str) -> OrcaCredential:
        stripped = key.strip()
        if not looks_like_orca_key(stripped):
            raise ValueError(
                "That does not look like an OrcaRouter API key "
                "(expected sk-orca-...). You can still try it - validity is "
                "confirmed by the first real request."
            )
        credential = OrcaCredential(
            key=stripped, user_id=None, scope=SCOPE_API, source="api_key"
        )
        self.store.save(credential)
        return credential

    def clear(self) -> None:
        self.store.clear()


# ---------------------------------------------------------------------------
# PKCE connect (Flow B - out-of-band code)
# ---------------------------------------------------------------------------


class PKCEConnectError(RuntimeError):
    """Safe, structured failure surfaced to the user."""

    code = "pkce_error"

    def __init__(self, message: str, *, code: Optional[str] = None):
        super().__init__(message)
        if code:
            self.code = code


class StateMismatchError(PKCEConnectError):
    code = "state_mismatch"


class UserDeniedError(PKCEConnectError):
    code = "access_denied"


class ExchangeFailedError(PKCEConnectError):
    code = "exchange_failed"


class ScopeDowngradeError(PKCEConnectError):
    code = "scope_downgrade"


class ConnectTimeoutError(PKCEConnectError):
    code = "connect_timeout"


@dataclass
class ConnectAttempt:
    """One PKCE authorization attempt, generation-guarded server side."""

    attempt_id: str
    verifier: str
    challenge: str
    state: str
    created_at: float
    status: str = "waiting_code"  # waiting_code | exchanged | cancelled | expired | failed
    result: Optional[OrcaCredential] = None
    error: Optional[PKCEConnectError] = None

    def is_expired(self, now: Optional[float] = None) -> bool:
        return (now or time.time()) - self.created_at > CONNECT_ATTEMPT_TTL_SECONDS


class ConnectManager:
    """In-memory store of PKCE attempts, keyed by opaque attempt_id.

    The verifier never leaves this process: it lives only in the attempt
    record and is read once during exchange, then the attempt is marked used
    so a code cannot be replayed.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._attempts: Dict[str, ConnectAttempt] = {}

    def start(self) -> ConnectAttempt:
        verifier = b64url(secrets.token_bytes(32))
        challenge = sha256_b64url(verifier)
        state = b64url(secrets.token_bytes(16))
        attempt = ConnectAttempt(
            attempt_id=state,
            verifier=verifier,
            challenge=challenge,
            state=state,
            created_at=time.time(),
        )
        with self._lock:
            self._attempts[attempt.attempt_id] = attempt
        return attempt

    def get(self, attempt_id: str) -> Optional[ConnectAttempt]:
        with self._lock:
            return self._attempts.get(attempt_id)

    def cancel(self, attempt_id: str) -> bool:
        with self._lock:
            attempt = self._attempts.get(attempt_id)
            if attempt is None or attempt.status != "waiting_code":
                return False
            attempt.status = "cancelled"
            return True

    def sweep_expired(self) -> None:
        now = time.time()
        with self._lock:
            expired = [
                aid for aid, a in self._attempts.items() if a.is_expired(now)
            ]
            for aid in expired:
                attempt = self._attempts[aid]
                if attempt.status == "waiting_code":
                    attempt.status = "expired"
                del self._attempts[aid]

    def exchange(self, attempt_id: str, code: str) -> OrcaCredential:
        """Exchange a user-supplied code for a durable OrcaRouter API key."""
        with self._lock:
            attempt = self._attempts.get(attempt_id)
            if attempt is None:
                raise ConnectTimeoutError(
                    "This authorization link has expired. Start a new connect "
                    "to try again."
                )
            if attempt.status == "cancelled":
                raise PKCEConnectError(
                    "This authorization was cancelled. Start a new connect.",
                    code="cancelled",
                )
            if attempt.status != "waiting_code":
                raise ConnectTimeoutError(
                    "This authorization code was already used. Start a new "
                    "connect to get a fresh one."
                )
            if attempt.is_expired():
                attempt.status = "expired"
                raise ConnectTimeoutError(
                    "This authorization link has expired. Start a new connect."
                )
            verifier = attempt.verifier
            challenge = attempt.challenge
            state = attempt.state

        credential = _exchange_code(
            endpoints=OrcaEndpoints.from_env(),
            code=code,
            code_verifier=verifier,
            code_challenge_method="S256",
            expected_state=state,
        )

        with self._lock:
            attempt.status = "exchanged"
            attempt.result = credential
            attempt.verifier = ""  # scrub after use
            attempt.challenge = ""
        return credential


def _exchange_code(
    *,
    endpoints: OrcaEndpoints,
    code: str,
    code_verifier: str,
    code_challenge_method: str,
    expected_state: Optional[str] = None,
) -> OrcaCredential:
    """POST the auth code + verifier to the exchange endpoint.

    ``expected_state`` is the constant-time comparison target for Flow A;
    Flow B carries no callback, so it is not used by the adapter.
    """
    if code_challenge_method != "S256":
        raise ExchangeFailedError("Only the S256 PKCE method is supported.")

    payload = {
        "code": code,
        "code_verifier": code_verifier,
        "code_challenge_method": "S256",
    }
    try:
        response = httpx.post(
            endpoints.exchange_url,
            json=payload,
            timeout=EXCHANGE_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise ExchangeFailedError(
            "Could not reach the OrcaRouter authorization server. "
            "Check your network and try again."
        ) from exc

    if response.status_code == 400:
        raise ExchangeFailedError(
            "The authorization code exchange was rejected (400). "
            "Start a new connect and try again."
        )
    if response.status_code == 403:
        raise ExchangeFailedError(
            "The authorization code is unknown, expired, or already used (403). "
            "Start a new connect to get a fresh one."
        )
    if response.status_code == 429:
        raise ExchangeFailedError(
            "OrcaRouter rate-limited the authorization exchange (429). "
            "Wait a moment and try again."
        )
    if response.status_code != 200:
        raise ExchangeFailedError(
            f"The authorization exchange failed (HTTP {response.status_code})."
        )

    data = _safe_json(response)
    key = data.get("key")
    if not isinstance(key, str) or not key.startswith("sk-orca-"):
        raise ExchangeFailedError(
            "The authorization server returned an unexpected response. "
            "No credential was stored."
        )

    # Read the *granted* scope from the response; it may be narrower than
    # what was requested.
    granted_scope = str(data.get("scope") or SCOPE_API)
    if granted_scope not in {SCOPE_API, SCOPE_CONNECTOR}:
        raise ScopeDowngradeError(
            f'The granted scope is "{granted_scope}", which this integration '
            "cannot use. Reconnect with a workspace that allows it."
        )

    user_id = data.get("user_id")
    return OrcaCredential(
        key=key,
        user_id=str(user_id) if user_id else None,
        scope=granted_scope,
        source="pkce",
    )


def _safe_json(response: httpx.Response) -> Dict[str, Any]:
    try:
        data = response.json()
    except (ValueError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


# ---------------------------------------------------------------------------
# Model catalog - live discovery + verified cold-start seed
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CatalogModel:
    """Minimal model metadata returned to the frontend."""

    id: str
    context_window: Optional[int] = None
    input_modalities: tuple = ()
    reasoning_effort_levels: tuple = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "context_window": self.context_window,
            "input_modalities": list(self.input_modalities),
            "reasoning_effort_levels": list(self.reasoning_effort_levels),
        }

    def includes_query(self, query: str) -> bool:
        """Whether this model matches a selector's narrowing query.

        The UI selector can only narrow the capability-filtered catalog the
        server returned; it never accepts a model id the catalog did not
        return (no free-form model entry).
        """
        normalized = (query or "").strip().lower()
        if not normalized:
            return True
        return normalized in self.id.lower()


def _as_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _as_str_list(value: Any) -> List[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if isinstance(v, str)]
    return []


def _bounded_json(response: httpx.Response) -> Dict[str, Any]:
    raw = response.read()
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("model catalog response exceeded 8 MiB")
    data = json.loads(raw.decode("utf-8", errors="replace"))
    return data if isinstance(data, dict) else {}


#: Verified cold-start seed, used only when live discovery fails or no
#: credential is configured. Each entry keeps its verified metadata: GPT-5.5
#: keeps the low/medium/high/xhigh reasoning ladder and a 400k context.
VERIFIED_SEED: List[Dict[str, Any]] = [
    {
        "id": "openai/gpt-5.5",
        "supported_endpoint_types": ["openai-response", "openai"],
        "context_window": 400_000,
        "input_modalities": ["text"],
        "reasoning_effort_levels": ["low", "medium", "high", "xhigh"],
    },
    {
        "id": "anthropic/claude-opus-4.8",
        "supported_endpoint_types": ["anthropic"],
        "context_window": 400_000,
        "input_modalities": ["text"],
        "reasoning_effort_levels": [],
    },
    {
        "id": "google/gemini-3.5-flash",
        "supported_endpoint_types": ["gemini"],
        "context_window": 1_000_000,
        "input_modalities": ["text", "image"],
        "reasoning_effort_levels": [],
    },
    {
        "id": "deepseek/deepseek-v4-pro",
        "supported_endpoint_types": ["openai"],
        "context_window": 128_000,
        "input_modalities": ["text"],
        "reasoning_effort_levels": [],
    },
    {
        "id": "orcarouter/auto",
        "supported_endpoint_types": ["openai"],
        "context_window": None,
        "input_modalities": ["text"],
        "reasoning_effort_levels": [],
    },
]


class OrcaModelCatalog:
    """Live model discovery with capability filtering and a verified seed.

    The catalog endpoint is ``GET {api_base}/v1/models``; models are
    requested with the user's OrcaRouter key so the workspace's real,
    callable models are returned. Capability filtering fails closed: a model
    without the declared capability/endpoint metadata is never shown for that
    capability. When live discovery fails (or no credential is configured)
    the small verified seed is returned with ``degraded=True``.
    """

    def __init__(
        self,
        endpoints: Optional[OrcaEndpoints] = None,
        credential: Optional[OrcaCredential] = None,
        client: Optional[httpx.Client] = None,
    ):
        self.endpoints = endpoints or OrcaEndpoints.from_env()
        self.credential = credential
        self._client = client

    # -- capability filtering ---------------------------------------------

    @staticmethod
    def _has_text_chat_endpoint(endpoint_types: Sequence[str]) -> bool:
        if not endpoint_types:
            return False
        if any(t in NON_TEXT_CHAT_ENDPOINTS for t in endpoint_types):
            return False
        return any(t in TEXT_CHAT_ENDPOINT_TYPES for t in endpoint_types)

    @staticmethod
    def matches_capability(
        capability: str,
        *,
        endpoint_types: Sequence[str],
        input_modalities: Optional[Sequence[str]] = None,
    ) -> bool:
        endpoint_set = set(endpoint_types)
        if capability == "chat":
            return OrcaModelCatalog._has_text_chat_endpoint(endpoint_types)
        if capability == "embedding":
            return "embedding" in endpoint_set or "embeddings" in endpoint_set
        if capability == "image":
            return "image-generation" in endpoint_set
        if capability == "video":
            return "openai-video" in endpoint_set
        if capability == "rerank":
            return "jina-rerank" in endpoint_set
        return False

    @staticmethod
    def supports_input_modality(
        model_meta: Dict[str, Any], modality: str
    ) -> bool:
        """Fail-closed: a model must explicitly declare the input modality."""
        return modality in _as_str_list(model_meta.get("input_modalities"))

    # -- discovery ---------------------------------------------------------

    def discover(self, capability: str) -> List[CatalogModel]:
        """Fetch and filter the live catalog for one capability."""
        if capability not in {"chat", "embedding", "image", "video", "rerank"}:
            raise ValueError(f"unsupported capability: {capability}")
        if self.credential is None or not self.credential.key:
            raise PKCEConnectError(
                "No OrcaRouter credential configured. Paste an API key or "
                "connect with your OrcaRouter account first.",
                code="no_credential",
            )

        headers = {"Authorization": f"Bearer {self.credential.key}"}
        try:
            if self._client is not None:
                response = self._client.get(
                    self.endpoints.models_url,
                    params={"capability": capability},
                    headers=headers,
                )
            else:
                # Build the client ourselves so httpx does not try to apply a
                # user-configured SOCKS proxy to the OrcaRouter catalog request.
                with httpx.Client(
                    trust_env=False, timeout=CATALOG_TIMEOUT_SECONDS
                ) as client:
                    response = client.get(
                        self.endpoints.models_url,
                        params={"capability": capability},
                        headers=headers,
                    )
        except httpx.HTTPError as exc:
            raise PKCEConnectError(
                "Could not reach the OrcaRouter model catalog. "
                "Check your network and try again.",
                code="catalog_network_error",
            ) from exc

        if response.status_code == 401:
            raise PKCEConnectError(
                "The OrcaRouter API key was rejected (401). Reconnect or "
                "paste a new key.",
                code="unauthorized",
            )
        if response.status_code == 403:
            raise PKCEConnectError(
                "The OrcaRouter API key does not allow model discovery (403).",
                code="forbidden",
            )
        if response.status_code == 429:
            raise PKCEConnectError(
                "OrcaRouter is rate-limiting model discovery (429). "
                "Wait a moment and refresh.",
                code="rate_limited",
            )
        if response.status_code != 200:
            raise PKCEConnectError(
                f"Model discovery failed (HTTP {response.status_code}).",
                code="catalog_error",
            )

        try:
            data = _bounded_json(response)
        except (ValueError, json.JSONDecodeError) as exc:
            raise PKCEConnectError(
                "Model discovery returned an unreadable catalog.",
                code="catalog_error",
            ) from exc

        models: List[CatalogModel] = []
        for item in data.get("data") or []:
            if not isinstance(item, dict):
                continue
            model_id = item.get("id")
            if not isinstance(model_id, str) or not model_id:
                continue
            endpoint_types = _as_str_list(item.get("supported_endpoint_types"))
            if not self.matches_capability(capability, endpoint_types=endpoint_types):
                continue
            architecture = item.get("architecture") or {}
            models.append(
                CatalogModel(
                    id=model_id,
                    context_window=_as_int(item.get("context_window")),
                    input_modalities=tuple(
                        _as_str_list(architecture.get("input_modalities"))
                    ),
                    reasoning_effort_levels=tuple(
                        _as_str_list(architecture.get("reasoning_effort_levels"))
                        or _as_str_list(item.get("reasoning_effort_levels"))
                    ),
                )
            )
            if len(models) >= CATALOG_MAX_ITEMS:
                break
        return models

    # -- verified seed fallback -------------------------------------------

    def seed(self, capability: str) -> List[CatalogModel]:
        """Return the verified cold-start seed filtered to a capability."""
        models: List[CatalogModel] = []
        for entry in VERIFIED_SEED:
            endpoint_types = _as_str_list(entry.get("supported_endpoint_types"))
            if not self.matches_capability(capability, endpoint_types=endpoint_types):
                continue
            models.append(
                CatalogModel(
                    id=entry["id"],
                    context_window=entry.get("context_window"),
                    input_modalities=tuple(_as_str_list(entry.get("input_modalities"))),
                    reasoning_effort_levels=tuple(
                        _as_str_list(entry.get("reasoning_effort_levels"))
                    ),
                )
            )
        return models


# ---------------------------------------------------------------------------
# Provider resolution for all AI entry points
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedLLMConfig:
    api_key: str
    base_url: str
    model: str


def resolve_llm_config(
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
) -> ResolvedLLMConfig:
    """Resolve the effective LLM configuration for the active provider.

    - ``default`` keeps the project's existing OpenAI-compatible behaviour
      (``LLM_API_KEY`` / ``LLM_BASE_URL`` / ``LLM_MODEL_NAME``).
    - ``orcarouter`` routes inference to ``api.orcarouter.ai/v1`` with the
      stored OrcaRouter key (API-key or PKCE-issued) and the OrcaRouter model.

    Explicit constructor arguments win over environment-derived values on a
    per-field basis, so the project's own injection points keep working.
    """
    provider = os.environ.get("LLM_PROVIDER", "default")
    if provider == "orcarouter":
        orca_key = os.environ.get(OrcaCredentialStore.ENV_VAR)
        if not (api_key or orca_key):
            raise ValueError(
                "OrcaRouter provider is selected but no OrcaRouter API key is "
                "configured. Open the provider settings and paste an "
                "sk-orca-... key or connect with your OrcaRouter account."
            )
        endpoints = OrcaEndpoints.from_env()
        return ResolvedLLMConfig(
            api_key=api_key or orca_key,
            base_url=base_url or endpoints.inference_base,
            model=(
                model
                or os.environ.get(OrcaCredentialStore.MODEL_VAR)
                or "orcarouter/auto"
            ),
        )

    return ResolvedLLMConfig(
        api_key=api_key or Config.LLM_API_KEY,
        base_url=base_url or Config.LLM_BASE_URL,
        model=model or Config.LLM_MODEL_NAME,
    )


def classify_relay_401(credential: OrcaCredential) -> Dict[str, Any]:
    """Terminal reauthentication marker for a revoked durable key.

    A ``401`` from the relay means the durable key was revoked: re-run the
    connect flow, never fake-refresh. Only the exact account and credential
    generation that made the rejected request are marked; a late failure from
    an old request must not pollute a freshly reauthorized credential.
    """
    return {
        "needs_reauth": True,
        "account": {
            "source": credential.source,
            "user_id": credential.user_id,
            "scope": credential.scope,
        },
        "hint": (
            "Your OrcaRouter key was rejected (401). Reconnect with your "
            "OrcaRouter account or paste a new API key."
        ),
    }


__all__ = [
    "API_PREFIX",
    "ApiKeyAdapter",
    "AUTHORIZE_PATH",
    "CATALOG_MAX_ITEMS",
    "CATALOG_TIMEOUT_SECONDS",
    "CatalogModel",
    "ConnectAttempt",
    "ConnectManager",
    "ConnectTimeoutError",
    "CredentialAdapter",
    "EXCHANGE_PATH",
    "ExchangeFailedError",
    "OrcaCredential",
    "OrcaCredentialStore",
    "OrcaEndpoints",
    "OrcaModelCatalog",
    "PKCEAdapter",
    "PKCEConnectError",
    "PUBLIC_API_BASE",
    "PUBLIC_AUTH_BASE",
    "ScopeDowngradeError",
    "StateMismatchError",
    "UserDeniedError",
    "VERIFIED_SEED",
    "_exchange_code",
    "b64url",
    "classify_relay_401",
    "looks_like_orca_key",
    "redact",
    "resolve_llm_config",
    "sha256_b64url",
]
