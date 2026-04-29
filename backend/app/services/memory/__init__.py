"""Memory backend abstraction for MiroFish.

This package decouples MiroFish from any specific graph-memory provider.
Consumers depend only on the abstract :class:`MemoryBackend` and the
DTOs defined in :mod:`app.services.memory.base`. The concrete backend
is selected at runtime via the ``MEMORY_BACKEND`` environment variable
(default: ``zep``).

Available backends:

* ``zep``       — Zep Cloud (managed, paid above free tier).
* ``graphiti``  — Self-hosted Graphiti + Neo4j (free, unlimited).

Switching backend is a config change; no application code needs to be
modified. Adding a new backend means dropping a new module that
implements :class:`MemoryBackend` and registering it in
:mod:`app.services.memory.factory`.
"""

from .base import (
    Edge,
    EpisodeRef,
    EpisodeInput,
    EpisodeType,
    MemoryBackend,
    Node,
    OntologySpec,
    SearchResult,
)
from .exceptions import (
    MemoryBackendError,
    MemoryBackendNotConfigured,
    MemoryBackendQuotaExceeded,
    MemoryBackendRateLimited,
    MemoryBackendUnavailable,
)
from .factory import build_memory_backend, get_memory_backend, reset_memory_backend

__all__ = [
    # DTOs
    "Edge",
    "EpisodeInput",
    "EpisodeRef",
    "EpisodeType",
    "Node",
    "OntologySpec",
    "SearchResult",
    # Abstract base
    "MemoryBackend",
    # Factory
    "build_memory_backend",
    "get_memory_backend",
    "reset_memory_backend",
    # Exceptions
    "MemoryBackendError",
    "MemoryBackendNotConfigured",
    "MemoryBackendQuotaExceeded",
    "MemoryBackendRateLimited",
    "MemoryBackendUnavailable",
]
