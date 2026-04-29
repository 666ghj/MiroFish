"""Typed exceptions raised by memory backend implementations.

Concrete backends translate provider-specific errors into these so that
callers can handle them uniformly without depending on Zep / Graphiti /
Neo4j exception types.
"""

from __future__ import annotations


class MemoryBackendError(Exception):
    """Base class for all memory backend errors."""


class MemoryBackendNotConfigured(MemoryBackendError):
    """Required configuration (API key, Neo4j URL, etc.) is missing."""


class MemoryBackendUnavailable(MemoryBackendError):
    """The backend is reachable but failed to serve the request."""


class MemoryBackendRateLimited(MemoryBackendUnavailable):
    """The backend rejected the call due to rate limiting."""


class MemoryBackendQuotaExceeded(MemoryBackendUnavailable):
    """The backend rejected the call because account quota is exhausted."""
