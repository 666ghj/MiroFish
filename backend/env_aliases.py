"""Clearer ``.env`` names for the four model endpoints, mapped onto the names the code has always read.

    TWITTER_LLM_*       the model the Twitter agents (and the end-of-run poll) use      was LLM_*
    REDDIT_LLM_*        the model the Reddit agents use                                 was LLM_BOOST_*
    TWITTER_RERANKER_*  the hosted embeddings behind the Twitter feed ranker            was LLM_EMBEDDING_*
    MAIN_LLM_*          the model that prepares a simulation and writes the report      was LLM_PREP_*

with ``API_KEY``, ``BASE_URL`` and ``MODEL_NAME`` (the reranker also takes ``TIMEOUT`` and ``BATCH``). A new name wins
when both are set; an ``.env`` that only has the old names keeps working unchanged. The code reads the old names, so
this runs once right after ``.env`` is loaded and copies each new name onto its old one.

No imports from the rest of the project: the backend and the run scripts both load it.
"""

import os
from typing import Dict, MutableMapping, Mapping

_FIELDS = ("API_KEY", "BASE_URL", "MODEL_NAME")

ALIASES: Dict[str, str] = {}
for _new, _old in (("TWITTER_LLM", "LLM"), ("REDDIT_LLM", "LLM_BOOST"), ("MAIN_LLM", "LLM_PREP")):
    for _field in _FIELDS:
        ALIASES[f"{_new}_{_field}"] = f"{_old}_{_field}"
for _field in _FIELDS + ("TIMEOUT", "BATCH"):
    ALIASES[f"TWITTER_RERANKER_{_field}"] = f"LLM_EMBEDDING_{_field}"


def with_aliases(environ: Mapping[str, str]) -> Dict[str, str]:
    """A copy of ``environ`` in which every set (non-blank) new name has been copied onto its old name."""
    resolved = dict(environ)
    for new, old in ALIASES.items():
        value = (resolved.get(new) or "").strip()
        if value:
            resolved[old] = value
    return resolved


def apply(environ: MutableMapping[str, str] = os.environ) -> None:
    """Do ``with_aliases`` in place (on the process environment by default)."""
    for key, value in with_aliases(environ).items():
        if environ.get(key) != value:
            environ[key] = value
