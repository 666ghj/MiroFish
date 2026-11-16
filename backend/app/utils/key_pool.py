"""
LLM API Key Pool & Rate-Limit Rotator
Inspired by the LiteLLM Router architecture.
Provides thread-safe round-robin key distribution, cooldown periods for rate limits (HTTP 429),
and automatic failover retries across multiple healthy keys.
"""

import json
import logging
import os
import re
import threading
import time
from typing import List, Optional, Callable, Any, Dict
from openai import OpenAI, RateLimitError

logger = logging.getLogger(__name__)


def mask_key(key: str) -> str:
    """Safely mask an API key for logs (e.g. sk-1234...5678)."""
    if not key or len(key) <= 8:
        return "***"
    return f"{key[:4]}...{key[-4:]}"


def parse_key_list(raw_keys: Optional[str]) -> List[str]:
    """
    Parse a string of API keys into a list.
    Supports comma-separated, semicolon-separated, newline-separated, or JSON arrays.
    """
    if not raw_keys:
        return []
    raw = raw_keys.strip()
    if raw.startswith("[") and raw.endswith("]"):
        try:
            parsed = json.loads(raw)
            return [str(k).strip() for k in parsed if str(k).strip()]
        except Exception:
            pass
    # Split by comma, semicolon, newline, or carriage return
    keys = [k.strip() for k in re.split(r'[,;\n\r]+', raw) if k.strip()]
    return keys


class KeyEntry:
    """Represents a single API key with health status and cooldown tracking."""

    def __init__(self, key: str):
        self.key = key
        self.masked = mask_key(key)
        self.cooldown_until: float = 0.0
        self.failure_count: int = 0
        self.total_requests: int = 0

    def is_healthy(self, now: Optional[float] = None) -> bool:
        """Check if the key is not currently cooling down."""
        if now is None:
            now = time.time()
        return now >= self.cooldown_until

    def mark_rate_limited(self, cooldown_seconds: float = 60.0):
        """Put the key into cooldown after hitting a rate limit."""
        self.cooldown_until = time.time() + cooldown_seconds
        self.failure_count += 1
        logger.warning(
            f"API key {self.masked} hit rate limit (429/quota). "
            f"Cooling down for {cooldown_seconds}s (until {time.strftime('%H:%M:%S', time.localtime(self.cooldown_until))})."
        )

    def mark_success(self):
        """Record a successful request."""
        self.total_requests += 1
        self.failure_count = 0


class LLMKeyPool:
    """
    Thread-safe API Key Pool and Load Balancer.
    Rotates keys using round-robin and automatically evicts rate-limited keys
    to a temporary cooldown pool.
    """

    def __init__(
        self,
        api_keys: List[str],
        base_url: Optional[str] = None,
        default_cooldown: float = 60.0,
    ):
        clean_keys = [k.strip() for k in api_keys if k and k.strip()]
        if not clean_keys:
            raise ValueError("LLMKeyPool requires at least one valid API key")

        self.entries = [KeyEntry(k) for k in clean_keys]
        self.base_url = base_url
        self.default_cooldown = default_cooldown
        self._current_index = 0
        self._lock = threading.Lock()

        # Cache OpenAI client instances per key
        self._clients: Dict[str, OpenAI] = {
            k: OpenAI(api_key=k, base_url=base_url) for k in clean_keys
        }

        logger.info(
            f"Initialized LLMKeyPool with {len(self.entries)} key(s): "
            f"{[e.masked for e in self.entries]}"
        )

    @property
    def size(self) -> int:
        return len(self.entries)

    def get_client(self, key: str) -> OpenAI:
        """Get or create an OpenAI client for a specific key."""
        with self._lock:
            if key not in self._clients:
                self._clients[key] = OpenAI(api_key=key, base_url=self.base_url)
            return self._clients[key]

    def get_next_entry(self) -> KeyEntry:
        """
        Thread-safely select the next healthy key using round-robin.
        If all keys are currently cooling down, picks the key whose cooldown expires earliest.
        """
        now = time.time()
        num_keys = len(self.entries)

        with self._lock:
            # 1. Look for a healthy key in round-robin order
            for _ in range(num_keys):
                idx = self._current_index
                self._current_index = (self._current_index + 1) % num_keys
                entry = self.entries[idx]
                if entry.is_healthy(now):
                    return entry

            # 2. If all keys are in cooldown, pick the one expiring soonest
            earliest_entry = min(self.entries, key=lambda e: e.cooldown_until)
            wait_time = max(0.0, earliest_entry.cooldown_until - now)
            logger.warning(
                f"All {num_keys} API keys in pool are in cooldown. "
                f"Earliest key {earliest_entry.masked} will be available in {wait_time:.1f}s."
            )
            return earliest_entry

    def execute_with_failover(
        self,
        request_fn: Callable[[OpenAI, str], Any],
        max_attempts: Optional[int] = None,
    ) -> Any:
        """
        Execute an LLM request function with automatic key rotation and failover on rate limits.
        
        Args:
            request_fn: Function accepting (client: OpenAI, api_key: str) and returning the result.
            max_attempts: Maximum number of keys to attempt before raising the error.
                          Defaults to len(api_keys).
        """
        if max_attempts is None:
            max_attempts = len(self.entries)

        last_error = None

        for attempt in range(1, max_attempts + 1):
            entry = self.get_next_entry()
            client = self.get_client(entry.key)

            try:
                result = request_fn(client, entry.key)
                entry.mark_success()
                return result

            except Exception as e:
                last_error = e
                # Check for RateLimitError (HTTP 429) or quota exceeded
                is_rate_limit = (
                    isinstance(e, RateLimitError)
                    or getattr(e, "status_code", None) in {429, 402}
                    or "rate limit" in str(e).lower()
                    or "quota" in str(e).lower()
                )

                if is_rate_limit:
                    entry.mark_rate_limited(self.default_cooldown)
                    logger.warning(
                        f"Request attempt {attempt}/{max_attempts} failed with rate limit on {entry.masked}. "
                        "Failing over to next available key..."
                    )
                    if attempt < max_attempts:
                        continue

                # If it's not a rate limit error, or we reached max attempts, raise
                raise

        if last_error:
            raise last_error
        raise RuntimeError("No API keys available to fulfill request")


_global_pool_lock = threading.Lock()
_default_pool: Optional[LLMKeyPool] = None


def get_default_key_pool(base_url: Optional[str] = None) -> LLMKeyPool:
    """Retrieve or initialize the global default key pool from environment."""
    global _default_pool
    with _global_pool_lock:
        if _default_pool is None:
            raw = os.environ.get("LLM_API_KEYS") or os.environ.get("LLM_API_KEY") or ""
            keys = parse_key_list(raw)
            if not keys:
                raise ValueError("No LLM API keys configured. Set LLM_API_KEYS or LLM_API_KEY in .env")
            _default_pool = LLMKeyPool(
                api_keys=keys,
                base_url=base_url or os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1"),
            )
        return _default_pool


def reset_key_pools():
    """Reset key pools (useful for testing or config reload)."""
    global _default_pool
    with _global_pool_lock:
        _default_pool = None
