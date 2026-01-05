"""
Shared OpenAI-compatible error classification for model rotation.

Goal: support gateway-style APIs (e.g. cliproxyapi) where each model can have
separate quotas. When a model is exhausted, we automatically try the next model
in the configured order.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple


def _safe_str(x: Any) -> str:
    try:
        return str(x)
    except Exception:
        return ""


def extract_error_info(err: BaseException) -> Dict[str, Any]:
    status_code = getattr(err, "status_code", None)
    if status_code is None:
        status_code = getattr(getattr(err, "response", None), "status_code", None)

    code = getattr(err, "code", None)
    if code is None:
        code = getattr(getattr(err, "error", None), "code", None)

    message = _safe_str(err)

    body = getattr(err, "body", None)
    if isinstance(body, dict):
        # OpenAI SDK often stores structured error here.
        code = code or body.get("error", {}).get("code") or body.get("code")
        msg2 = body.get("error", {}).get("message") or body.get("message")
        if msg2 and msg2 not in message:
            message = f"{message} | {msg2}"

    return {
        "type": err.__class__.__name__,
        "status_code": status_code,
        "code": code,
        "message": message,
    }


def should_rotate_model(err: BaseException) -> Tuple[bool, str]:
    """
    Returns (should_rotate, reason).
    """
    info = extract_error_info(err)
    status = info.get("status_code")
    code = (_safe_str(info.get("code")).lower() or "").strip()
    msg = (_safe_str(info.get("message")).lower() or "").strip()

    # Quota / balance exhaustion (most common in gateways).
    quota_hints = [
        "insufficient_quota",
        "quota",
        "billing",
        "balance",
        "credit",
        "exceeded",
        "payment required",
        "no remaining",
        "out of credits",
    ]

    # Model not available / not found.
    model_hints = [
        "model_not_found",
        "does not exist",
        "not found",
        "unknown model",
        "no such model",
    ]

    # Rotate on explicit codes first.
    if code in {"insufficient_quota", "model_not_found"}:
        return True, code

    # HTTP-based heuristics.
    if status in (402,):
        return True, "payment_required"
    if status in (429,):
        # Gateways commonly reuse 429 for quota depletion. We rotate to keep progress.
        return True, "rate_limit_or_quota"
    if status in (403,) and any(h in msg for h in quota_hints):
        return True, "forbidden_quota"
    if status in (404,) and ("model" in msg) and any(h in msg for h in model_hints):
        return True, "model_not_found"

    # Message-only fallbacks (no structured status).
    if any(h in msg for h in quota_hints):
        return True, "quota_hint"
    if ("model" in msg) and any(h in msg for h in model_hints):
        return True, "model_hint"

    return False, "non_rotatable"

