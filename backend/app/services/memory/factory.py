"""Memory backend factory and process-level singleton.

Selection happens via the ``MEMORY_BACKEND`` environment variable.
The default is ``zep`` so existing deployments continue to work
unchanged after this refactor lands. Switching to a self-hosted
Graphiti is a pure configuration change.
"""

from __future__ import annotations

import os
import threading
from typing import Optional

from .base import MemoryBackend
from .exceptions import MemoryBackendNotConfigured

_BACKEND_ENV = "MEMORY_BACKEND"
_DEFAULT_BACKEND = "zep"

_lock = threading.Lock()
_singleton: Optional[MemoryBackend] = None


def _import_zep_backend() -> type[MemoryBackend]:
    from .zep_cloud_backend import ZepCloudBackend

    return ZepCloudBackend


def _import_graphiti_backend() -> type[MemoryBackend]:
    from .graphiti_backend import GraphitiBackend

    return GraphitiBackend


_REGISTRY: dict[str, callable] = {
    "zep": _import_zep_backend,
    "zep_cloud": _import_zep_backend,
    "graphiti": _import_graphiti_backend,
}


def build_memory_backend(name: Optional[str] = None) -> MemoryBackend:
    """Construct a fresh :class:`MemoryBackend` instance.

    Tests and one-off scripts use this to get an isolated backend.
    Long-running services should prefer :func:`get_memory_backend`,
    which returns a process-level singleton.
    """
    backend_name = (name or os.environ.get(_BACKEND_ENV) or _DEFAULT_BACKEND).lower()

    loader = _REGISTRY.get(backend_name)
    if loader is None:
        raise MemoryBackendNotConfigured(
            f"Unknown MEMORY_BACKEND={backend_name!r}; "
            f"valid options: {', '.join(sorted(set(_REGISTRY)))}"
        )
    cls = loader()
    return cls()


def get_memory_backend() -> MemoryBackend:
    """Return the process-level memory backend singleton.

    First call constructs the backend, subsequent calls reuse it.
    Thread-safe.
    """
    global _singleton
    if _singleton is None:
        with _lock:
            if _singleton is None:
                _singleton = build_memory_backend()
    return _singleton


def reset_memory_backend() -> None:
    """Drop the singleton so the next call rebuilds.

    Useful in tests and when env vars change at runtime.
    """
    global _singleton
    with _lock:
        _singleton = None
