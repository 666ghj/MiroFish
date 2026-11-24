"""
House style for generated GTM copy.

The site does not use em dashes. LLMs use them constantly, so every GTM generator
passes its parsed JSON through `strip_em_dashes` before the data is stored or shown.
"""

import re
from typing import Any

_SPACED_EM_DASH = re.compile(r'\s*—\s*')


def _fix_text(text: str) -> str:
    # "a — b" reads naturally as "a, b"; a bare em dash between words becomes a hyphen.
    text = re.sub(r'(\S)\s+—\s+(\S)', r'\1, \2', text)
    return _SPACED_EM_DASH.sub('-', text)


def strip_em_dashes(value: Any) -> Any:
    """Return a copy of `value` (str, list, dict, or scalar) with em dashes removed."""
    if isinstance(value, str):
        return _fix_text(value) if '—' in value else value
    if isinstance(value, list):
        return [strip_em_dashes(v) for v in value]
    if isinstance(value, dict):
        return {k: strip_em_dashes(v) for k, v in value.items()}
    return value
