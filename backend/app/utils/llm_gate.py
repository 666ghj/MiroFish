from __future__ import annotations

from contextlib import contextmanager
from threading import BoundedSemaphore

from ..config import Config


_MAIN_LLM_GATE = BoundedSemaphore(max(1, Config.LLM_MAX_CONCURRENCY))


@contextmanager
def main_llm_slot():
    """Limit concurrent calls to the local main LLM endpoint."""
    _MAIN_LLM_GATE.acquire()
    try:
        yield
    finally:
        _MAIN_LLM_GATE.release()
