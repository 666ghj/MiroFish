from __future__ import annotations

import threading
from typing import Any


class CircuitOpenError(RuntimeError):
    pass


class ProviderRouter:
    def __init__(self, direct: Any, fallback: Any | None = None) -> None:
        self.direct = direct
        self.fallback = fallback
        self._protocol_failures = 0
        self._circuit_reason = None
        self._lock = threading.Lock()

    def complete(self, request: dict):
        with self._lock:
            if self._circuit_reason:
                raise CircuitOpenError(self._circuit_reason)
        try:
            result = self.direct.complete(request)
            with self._lock:
                self._protocol_failures = 0
            return result
        except Exception as error:
            status = getattr(error, "status_code", None)
            with self._lock:
                if status in {401, 403}:
                    self._circuit_reason = "authentication_unavailable"
                elif status == 429:
                    self._circuit_reason = "rate_limited"
                elif isinstance(error, (RuntimeError, ValueError)):
                    self._protocol_failures += 1
                    if self._protocol_failures >= 3:
                        self._circuit_reason = "protocol_incompatible"
            if self.fallback is None:
                raise
            return self.fallback.complete(request)
