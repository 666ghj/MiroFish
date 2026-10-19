"""
OpenAI Chat Completions compatibility helpers.

This module keeps existing behavior for legacy models/providers while
gracefully adapting request parameters for GPT-5 family models.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def is_gpt5_family(model: Optional[str]) -> bool:
    """Return True when model belongs to GPT-5 family aliases/snapshots."""
    if not model:
        return False
    return model.strip().lower().startswith("gpt-5")


def _extract_retry_delay(error: Exception) -> Optional[float]:
    """Extract retry delay in seconds from rate limit errors if available."""
    err_str = str(error)
    # Check for Gemini message format: "retry in 21.913422298s"
    m = re.search(r"retry in (\d+(?:\.\d+)?)s", err_str, re.IGNORECASE)
    if m:
        return float(m.group(1))
    # Check for Gemini details: 'retryDelay': '21s'
    m = re.search(r"['\"]retryDelay['\"]\s*:\s*['\"]?(\d+(?:\.\d+)?)s?['\"]?", err_str, re.IGNORECASE)
    if m:
        return float(m.group(1))
    # Check for response headers: retry-after
    response = getattr(error, "response", None)
    if response is not None and hasattr(response, "headers"):
        retry_after = response.headers.get("retry-after")
        if retry_after:
            try:
                return float(retry_after)
            except (ValueError, TypeError):
                pass
    return None


def _is_rate_limit_error(error: Exception) -> bool:
    """Check if an error is an HTTP 429 rate limit or quota exhaustion."""
    status_code = getattr(error, "status_code", None)
    if status_code == 429:
        return True

    err_str = str(error)
    if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "rate limit" in err_str.lower():
        return True
    return False


_CLIENT_CACHE: Dict[str, Any] = {}


def _get_or_create_client(api_key: str, base_url: str) -> Any:
    """Cache and reuse OpenAI client instances for each provider."""
    from openai import OpenAI
    cache_key = f"{api_key}::{base_url}"
    if cache_key not in _CLIENT_CACHE:
        _CLIENT_CACHE[cache_key] = OpenAI(api_key=api_key, base_url=base_url)
    return _CLIENT_CACHE[cache_key]


def get_fallback_candidates() -> List[Dict[str, str]]:
    """
    Get the configured 4-model fallback chain:
    1. Google Gemini Model 1 (e.g. gemini-3.5-flash-lite)
    2. Google Gemini Model 2 (e.g. gemini-3.8-flash)
    3. OpenRouter Model 1 (e.g. google/gemini-2.5-flash)
    4. OpenRouter Model 2 (e.g. openai/gpt-4o-mini)
    """
    try:
        from ..config import Config
    except Exception:
        return []

    candidates = []

    # 1. Google Gemini Models (2 models)
    gemini_key = getattr(Config, "GEMINI_API_KEY", None) or getattr(Config, "LLM_API_KEY", None)
    gemini_url = getattr(Config, "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
    gemini_m1 = getattr(Config, "GEMINI_MODEL_1", "gemini-3.5-flash-lite")
    gemini_m2 = getattr(Config, "GEMINI_MODEL_2", "gemini-3.8-flash")

    if gemini_key:
        candidates.append({
            "name": f"Google Gemini ({gemini_m1})",
            "provider": "google",
            "model": gemini_m1,
            "base_url": gemini_url,
            "api_key": gemini_key,
        })
        candidates.append({
            "name": f"Google Gemini ({gemini_m2})",
            "provider": "google",
            "model": gemini_m2,
            "base_url": gemini_url,
            "api_key": gemini_key,
        })

    # 2. OpenRouter Models (2 models)
    openrouter_key = getattr(Config, "OPENROUTER_API_KEY", None)
    openrouter_url = getattr(Config, "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    openrouter_m1 = getattr(Config, "OPENROUTER_MODEL_1", "google/gemini-2.5-flash")
    openrouter_m2 = getattr(Config, "OPENROUTER_MODEL_2", "openai/gpt-4o-mini")

    if openrouter_key:
        candidates.append({
            "name": f"OpenRouter ({openrouter_m1})",
            "provider": "openrouter",
            "model": openrouter_m1,
            "base_url": openrouter_url,
            "api_key": openrouter_key,
        })
        candidates.append({
            "name": f"OpenRouter ({openrouter_m2})",
            "provider": "openrouter",
            "model": openrouter_m2,
            "base_url": openrouter_url,
            "api_key": openrouter_key,
        })

    return candidates


def create_chat_completion(
    client: Any,
    *,
    model: str,
    messages: List[Dict[str, Any]],
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    response_format: Optional[Dict[str, Any]] = None,
    max_retries: int = 5,
    enable_fallback: bool = True,
) -> Any:
    """
    Create a chat completion with model-specific request parameters,
    automatic retry for short-term rate limits, and an automated 4-model
    fallback chain (2x Google Gemini, 2x OpenRouter).
    """
    kwargs: Dict[str, Any] = {
        "model": model,
        "messages": messages,
    }

    if response_format is not None:
        kwargs["response_format"] = response_format

    gpt5_family = is_gpt5_family(model)

    if temperature is not None and not gpt5_family:
        kwargs["temperature"] = temperature

    if max_tokens is not None:
        if gpt5_family:
            kwargs["max_completion_tokens"] = max_tokens
        else:
            kwargs["max_tokens"] = max_tokens

    primary_error: Optional[Exception] = None

    for attempt in range(max_retries + 1):
        try:
            return client.chat.completions.create(**kwargs)
        except Exception as error:
            primary_error = error
            if attempt < max_retries and _is_rate_limit_error(error):
                retry_delay = _extract_retry_delay(error)
                # If retry delay is within a reasonable short-term range (<= 30s), wait and retry
                if retry_delay is None or retry_delay <= 30:
                    wait_seconds = (retry_delay + 2.0) if retry_delay is not None else min(30.0, 5.0 * (attempt + 1))
                    logger.warning(
                        f"Rate limit hit (429/RPM). Waiting {wait_seconds:.1f}s before retrying "
                        f"(attempt {attempt + 1}/{max_retries})..."
                    )
                    time.sleep(wait_seconds)
                    continue

            # Exhausted short retries or daily quota / fatal error, break to fallback
            break

    if not enable_fallback:
        raise primary_error

    # Fallback Chain Execution
    candidates = get_fallback_candidates()
    current_base_url = str(getattr(client, "base_url", "")).rstrip('/')

    for candidate in candidates:
        cand_model = candidate["model"]
        cand_base_url = candidate["base_url"].rstrip('/')

        # Skip candidate if it matches the exact failed client and model
        if cand_model == model and (not current_base_url or current_base_url == cand_base_url):
            continue

        logger.warning(
            f"[LLM Fallback] Primary model '{model}' failed ({primary_error}). "
            f"Switching to fallback candidate: {candidate['name']}..."
        )

        try:
            cand_client = _get_or_create_client(candidate["api_key"], candidate["base_url"])

            cand_kwargs: Dict[str, Any] = {
                "model": cand_model,
                "messages": messages,
            }
            if response_format is not None:
                cand_kwargs["response_format"] = response_format

            cand_gpt5 = is_gpt5_family(cand_model)
            if temperature is not None and not cand_gpt5:
                cand_kwargs["temperature"] = temperature

            # Ensure max_tokens is specified to prevent OpenRouter 402 credit-cap errors
            cand_max = max_tokens or 4096
            if cand_gpt5:
                cand_kwargs["max_completion_tokens"] = cand_max
            else:
                cand_kwargs["max_tokens"] = cand_max

            for cand_attempt in range(2):
                try:
                    resp = cand_client.chat.completions.create(**cand_kwargs)
                    logger.info(
                        f"[LLM Fallback] SUCCESS: Received response from fallback candidate '{candidate['name']}'!"
                    )
                    return resp
                except Exception as cand_err:
                    if cand_attempt < 1 and _is_rate_limit_error(cand_err):
                        c_delay = _extract_retry_delay(cand_err)
                        if c_delay is not None and c_delay <= 25:
                            time.sleep(c_delay + 1.0)
                            continue
                    raise
        except Exception as cand_err:
            logger.warning(
                f"[LLM Fallback] Candidate '{candidate['name']}' failed ({cand_err}). "
                f"Proceeding to next fallback..."
            )
            continue

    # If all fallback candidates also failed, raise the original error
    raise primary_error


def extract_chat_completion_text(response: Any) -> str:
    """Extract plain text from chat completion response across SDK content shapes."""
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""

    message = getattr(choices[0], "message", None)
    if message is None:
        return ""

    content = getattr(message, "content", "")

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        chunks: List[str] = []
        for item in content:
            if isinstance(item, dict):
                text_obj = item.get("text")
                if isinstance(text_obj, dict):
                    text_obj = text_obj.get("value")
                if isinstance(text_obj, str):
                    chunks.append(text_obj)
                elif isinstance(item.get("content"), str):
                    chunks.append(item["content"])
                continue

            text_obj = getattr(item, "text", None)
            if isinstance(text_obj, dict):
                text_obj = text_obj.get("value")
            if isinstance(text_obj, str):
                chunks.append(text_obj)
                continue

            content_obj = getattr(item, "content", None)
            if isinstance(content_obj, str):
                chunks.append(content_obj)

        return "".join(chunks).strip()

    return str(content or "")
