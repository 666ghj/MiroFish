"""
Shared helpers for LLM rate-limit handling.
"""

import random
import re
import time
from typing import Any, Callable, Optional

from openai import RateLimitError

from ..config import Config
from ..utils.logger import get_logger

logger = get_logger('mirofish.llm_rate_limit')


def is_rate_limit_error(error: Exception) -> bool:
    """Return True when an exception represents an LLM 429/rate-limit response."""
    if isinstance(error, RateLimitError):
        return True
    message = str(error).lower()
    return "429" in message or "rate_limit" in message or "速率限制" in message


def retry_after_seconds(error: Exception) -> Optional[float]:
    """Extract retry-after seconds from OpenAI-compatible errors when available."""
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    if headers:
        retry_after = headers.get("retry-after") or headers.get("Retry-After")
        if retry_after:
            try:
                return max(1.0, float(retry_after))
            except ValueError:
                pass

    message = str(error)
    match = re.search(r"retry[- ]after[:= ]+([0-9]+(?:\.[0-9]+)?)", message, re.IGNORECASE)
    if match:
        return max(1.0, float(match.group(1)))
    return None


def call_llm_with_rate_limit_retry(
    call: Callable[[], Any],
    operation_name: str,
    max_attempts: Optional[int] = None,
    initial_delay: Optional[float] = None,
    max_delay: Optional[float] = None,
) -> Any:
    """
    Run an LLM call. On HTTP 429, sleep and retry instead of dropping the task.
    """
    attempts = max_attempts or Config.LLM_RATE_LIMIT_MAX_ATTEMPTS
    delay = initial_delay or Config.LLM_RATE_LIMIT_INITIAL_DELAY
    max_sleep = max_delay or Config.LLM_RATE_LIMIT_MAX_DELAY
    last_error: Optional[Exception] = None

    for attempt in range(1, attempts + 1):
        try:
            return call()
        except Exception as error:
            last_error = error
            if not is_rate_limit_error(error):
                raise
            if attempt >= attempts:
                logger.error(
                    f"{operation_name} 遇到 429 限流，已等待重试 {attempts} 次仍失败: {error}"
                )
                raise

            retry_after = retry_after_seconds(error)
            sleep_seconds = retry_after if retry_after is not None else min(delay, max_sleep)
            sleep_seconds = sleep_seconds * (0.9 + random.random() * 0.2)
            logger.warning(
                f"{operation_name} 遇到 429 限流，暂停 {sleep_seconds:.1f} 秒后继续 "
                f"({attempt}/{attempts})"
            )
            time.sleep(sleep_seconds)
            delay = min(delay * Config.LLM_RATE_LIMIT_BACKOFF_FACTOR, max_sleep)

    raise last_error or RuntimeError(f"{operation_name} 调用失败")
