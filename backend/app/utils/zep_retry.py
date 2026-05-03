import time
import functools
from typing import Callable, Any, TypeVar, cast

from zep_cloud.core.api_error import ApiError
from zep_cloud import InternalServerError

from .logger import get_logger
from .locale import t

logger = get_logger('mirofish.zep_retry')

T = TypeVar('T', bound=Callable[..., Any])


class ZepQuotaExceededError(Exception):
    """Raised when Zep Account is over the episode usage limit (403 Quota limit)."""
    pass


def with_zep_retry(
    max_retries: int = 3,
    initial_delay: float = 2.0,
    operation_name: str = "Zep API Call"
) -> Callable[[T], T]:
    """
    Decorator to wrap Zep API calls with retry logic.
    - Handles 429 Rate Limit by respecting 'Retry-After' headers.
    - Handles 403 Quota Limit by failing fast with a clear exception.
    - Retries other transient errors (ConnectionError, TimeoutError, etc) with exponential backoff.
    """
    def decorator(func: T) -> T:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception = None
            delay = initial_delay

            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except ApiError as e:
                    # 403 Forbidden: Account is over the episode usage limit
                    if e.status_code == 403 and hasattr(e, 'body') and 'forbidden: Account is over the episode usage limit' in str(e.body):
                        logger.error(f"{operation_name} Failed: Zep Free Plan quota exceeded (403).")
                        error_msg = t("api.zepQuotaExceeded")
                        if not error_msg or error_msg == "api.zepQuotaExceeded":
                            error_msg = "Zep Free Plan Quota Exceeded: Your account has reached the maximum allowed episode usage. Please upgrade your Zep plan or clear old data."
                        raise ZepQuotaExceededError(error_msg) from e
                        
                    # 429 Rate limit
                    if e.status_code == 429:
                        retry_after = 60  # Default fallback
                        if hasattr(e, 'headers') and e.headers:
                            retry_after = int(e.headers.get('retry-after', retry_after))
                        elif hasattr(e, 'body') and 'retry-after' in str(e.body):
                            retry_after = 60
                            
                        logger.warning(
                            f"Zep rate limit hit on {operation_name}, waiting {retry_after}s before retry (attempt {attempt + 1}/{max_retries})"
                        )
                        if attempt < max_retries - 1:
                            time.sleep(retry_after + 1)
                            continue
                        else:
                            logger.error(f"{operation_name} rate limited after {max_retries} attempts")
                            raise
                    
                    # Other ApiErrors should not be retried unless we want to, but normally we fail fast
                    raise
                except (ConnectionError, TimeoutError, OSError, InternalServerError) as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        logger.warning(
                            f"{operation_name} attempt {attempt + 1} failed: {str(e)[:100]}, retrying in {delay:.1f}s..."
                        )
                        time.sleep(delay)
                        delay *= 2
                    else:
                        logger.error(f"{operation_name} failed after {max_retries} attempts: {str(e)}")

            if last_exception:
                raise last_exception
        return cast(T, wrapper)
    return decorator
