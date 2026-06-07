"""
CJK Leak Sanitization Utility
==============================

Even with proper ``get_language_instruction()`` injected into LLM system prompts,
the model can still leak Chinese characters mid-sentence when generating persona
quotes (BI economists, ministry officials, Reddit commenters, etc.). The LLM
sometimes reaches back to its Chinese training data for fluent-sounding speech,
producing output like::

    "BI economist said: Purbaya过于倾向财政扩张..."

This module provides :func:`sanitize_cjk_in_text` which:

1. Detects runs of CJK Unified Ideographs (U+4E00..U+9FFF) and CJK Symbols
   & Punctuation (U+3000..U+303F) ≥ 2 characters in length
2. Batch-translates them via the configured LLM endpoint (reusing the same
   ``LLM_BASE_URL`` / ``LLM_API_KEY`` as the rest of MiroFish)
3. Replaces each run in-place, injecting spaces at ASCII boundaries so the
   result reads naturally in the surrounding language
4. Iterates up to 3 passes so any fragments the LLM leaves in its first
   response are caught in subsequent passes

The function is a no-op when the input is short of CJK characters, when the
target locale is Chinese (``locale == 'zh'``), or when no LLM API key is
configured. It is safe to call from any code path — failures are logged and
the original text is returned unchanged.

Configuration (env vars, all optional):
    CJK_SANITIZE_ENABLED   — ``"1"`` / ``"true"`` to force-enable; ``"0"`` to force-disable.
                             Default: auto-enable for non-zh locales.
    CJK_SANITIZE_LANGS     — comma-separated locales where sanitization runs.
                             Default: ``"en,es,fr,pt,ru,de,id"`` (any non-zh locale).
    CJK_SANITIZE_MAX_PASSES — maximum retry passes (default ``3``).
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

# Match runs of ≥2 CJK ideographs or CJK punctuation/symbols.
# Single-character matches (e.g. lone "（" or "】") are usually false positives
# in mixed-language text; the 2-char floor filters most of those out.
_CJK_PATTERN = re.compile(r"[\u4e00-\u9fff\u3000-\u303f]{2,}")

# Default locales where sanitization is helpful. Chinese is intentionally
# excluded — Chinese reports can and should contain CJK characters.
_DEFAULT_TARGET_LOCALES = frozenset({"en", "es", "fr", "pt", "ru", "de", "id"})


def _extract_cjk_runs(text: str) -> list[str]:
    """Return unique CJK runs in order of first appearance."""
    seen: set[str] = set()
    out: list[str] = []
    for m in _CJK_PATTERN.finditer(text):
        s = m.group(0)
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _smart_replace(text: str, cjk_run: str, translation: str) -> str:
    """Replace a CJK run with its English translation, adding spaces at ASCII
    boundaries so the result reads naturally in surrounding English/Latin text.

    The LLM only sees the CJK snippet (not its surrounding context), so it can't
    preserve the original spacing. We compensate with boundary lookbehind/ahead.
    """
    out = text
    # ASCII on both sides → " trans "
    pat = re.compile(r"(?<=[A-Za-z0-9])" + re.escape(cjk_run) + r"(?=[A-Za-z0-9])")
    out = pat.sub(" " + translation + " ", out)
    # ASCII on left only (e.g. "Purbaya过于扩张,") → " trans"
    pre = re.compile(r"(?<=[A-Za-z0-9])" + re.escape(cjk_run))
    out = pre.sub(" " + translation, out)
    # ASCII on right only (e.g. "（中央银行）officials") → "trans "
    post = re.compile(re.escape(cjk_run) + r"(?=[A-Za-z0-9])")
    out = post.sub(translation + " ", out)
    # Surrounded by non-ASCII (e.g. fullwidth parens) → bare translation
    out = out.replace(cjk_run, translation)
    return out


def _batch_translate(
    snippets: list[str],
    api_key: str,
    base_url: str,
    model: str,
    timeout: int = 60,
    max_retries: int = 2,
) -> dict[str, str]:
    """Translate a list of CJK snippets to English via the configured LLM."""
    if not snippets:
        return {}

    numbered = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(snippets))
    prompt = (
        "You are a translator. The following are short Chinese fragments that "
        "leaked into an otherwise English report. Translate each to natural "
        "English. Output a JSON array of strings, one per input, in the same "
        "order. Do not add commentary, numbering, or markdown fences — output "
        f"only the JSON array.\n\n{numbered}"
    )
    body = json.dumps(
        {
            "model": model,
            "max_tokens": 4096,
            "temperature": 0.1,
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode()

    url = base_url.rstrip("/") + "/chat/completions"
    last_err: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(
                url,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read())
            content = payload["choices"][0]["message"]["content"].strip()
            # Strip markdown fences if the model added them despite instructions
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)
            arr = json.loads(content)
            if not isinstance(arr, list) or len(arr) != len(snippets):
                raise ValueError(
                    f"Got {len(arr) if isinstance(arr, list) else 'non-list'} "
                    f"translations for {len(snippets)} snippets"
                )
            return {orig: trans for orig, trans in zip(snippets, arr)}
        except Exception as e:  # any failure (network, JSON, schema) → retry
            last_err = e
            logger.warning(
                "cjk_sanitize translation attempt %d/%d failed: %s",
                attempt + 1,
                max_retries,
                e,
            )
    raise RuntimeError(f"Translation failed after {max_retries} attempts: {last_err}")


def is_enabled(locale: Optional[str] = None) -> bool:
    """Return True if sanitization should run for the given locale.

    Honors the ``CJK_SANITIZE_ENABLED`` env var (force on/off). When unset,
    enables for any locale in ``CJK_SANITIZE_LANGS`` (default: non-Chinese
    supported locales).
    """
    override = os.environ.get("CJK_SANITIZE_ENABLED", "").strip().lower()
    if override in ("1", "true", "yes", "on"):
        return True
    if override in ("0", "false", "no", "off"):
        return False
    if not locale:
        return False
    target_langs_env = os.environ.get("CJK_SANITIZE_LANGS", "").strip()
    if target_langs_env:
        target = {x.strip().lower() for x in target_langs_env.split(",") if x.strip()}
    else:
        target = _DEFAULT_TARGET_LOCALES
    return locale.lower() in target


def sanitize_cjk_in_text(
    text: str,
    locale: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
) -> str:
    """Return ``text`` with CJK runs replaced by English translations.

    No-op if:
        - ``text`` is empty or contains no CJK runs
        - ``locale`` is Chinese (``zh`` / ``zh-CN`` / ``zh-TW``)
        - no LLM ``api_key`` is configured
        - the LLM call fails (logs warning, returns original text)

    Args:
        text: The text to sanitize (typically a generated report or section).
        locale: Target report locale (e.g. ``"en"``). Chinese is skipped.
        api_key: LLM API key. Defaults to ``LLM_API_KEY`` env var.
        base_url: LLM endpoint base URL. Defaults to ``LLM_BASE_URL`` env var.
        model: LLM model name. Defaults to ``LLM_MODEL_NAME`` env var.

    Returns:
        Sanitized text. If sanitization is skipped or fails, returns the
        original ``text`` unchanged.
    """
    if not text:
        return text

    if locale and locale.lower().split("-")[0] == "zh":
        return text  # Chinese reports legitimately contain CJK

    runs = _extract_cjk_runs(text)
    if not runs:
        return text

    api_key = api_key or os.environ.get("LLM_API_KEY")
    base_url = base_url or os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
    model = model or os.environ.get("LLM_MODEL_NAME", "gpt-4o-mini")

    if not api_key:
        logger.warning(
            "cjk_sanitize: %d CJK runs detected but no LLM_API_KEY; skipping",
            len(runs),
        )
        return text

    max_passes = int(os.environ.get("CJK_SANITIZE_MAX_PASSES", "3"))
    out = text
    n_total = 0
    pass_n = 0
    for pass_n in range(1, max_passes + 1):
        runs = _extract_cjk_runs(out)
        if not runs:
            break
        try:
            translations = _batch_translate(runs, api_key, base_url, model)
        except RuntimeError as e:
            logger.warning("cjk_sanitize: %s — returning original text", e)
            return text
        n_replaced = 0
        for orig, trans in translations.items():
            if not trans or not trans.strip() or trans == orig:
                continue
            before = out.count(orig)
            out = _smart_replace(out, orig, trans)
            n_replaced += before
        n_total += n_replaced
        if n_replaced == 0:
            break  # LLM didn't translate anything new — stop iterating

    leftover = _extract_cjk_runs(out)
    if leftover:
        logger.warning(
            "cjk_sanitize: %d CJK runs still present after %d passes: %s",
            len(leftover),
            pass_n or 1,
            leftover,
        )

    logger.info("cjk_sanitize: replaced %d CJK runs across %d passes", n_total, pass_n or 1)
    return out
