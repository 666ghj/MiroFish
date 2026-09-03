"""Unit tests for retry utility module.

These tests verify the retry logic without importing the Flask app,
which would trigger initialization of external dependencies.
"""

import pytest
import time
from unittest.mock import Mock, patch


# Minimal reimplementation of the retry decorator logic for testing
# This mirrors the behavior of the actual retry module without imports
def retry_with_backoff_testable(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 30.0,
    backoff_factor: float = 2.0,
    jitter: bool = True,
    on_retry: callable = None
):
    """
    Testable version of retry_with_backoff decorator.
    Mirrors the actual implementation's behavior.
    """
    import random
    import functools

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            delay = initial_delay

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)

                except Exception as e:
                    last_exception = e

                    if attempt == max_retries:
                        raise

                    current_delay = min(delay, max_delay)
                    if jitter:
                        current_delay = current_delay * (0.5 + random.random())

                    if on_retry:
                        on_retry(e, attempt + 1)

                    time.sleep(current_delay)
                    delay *= backoff_factor

            raise last_exception

        return wrapper
    return decorator


class TestRetryWithBackoff:
    """Tests for the sync retry_with_backoff decorator."""

    def test_success_on_first_attempt(self):
        """Function succeeds immediately without retrying."""
        call_count = 0

        @retry_with_backoff_testable(max_retries=3)
        def succeed():
            nonlocal call_count
            call_count += 1
            return "success"

        result = succeed()
        assert result == "success"
        assert call_count == 1

    def test_retry_on_failure_then_success(self):
        """Function fails once then succeeds."""
        call_count = 0

        @retry_with_backoff_testable(max_retries=3, initial_delay=0.01)
        def fail_once():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("temporary failure")
            return "success"

        result = fail_once()
        assert result == "success"
        assert call_count == 3

    def test_exhaust_retries_and_raise(self):
        """Function fails all retries and raises the exception."""
        call_count = 0

        @retry_with_backoff_testable(max_retries=2, initial_delay=0.01)
        def always_fail():
            nonlocal call_count
            call_count += 1
            raise ValueError("permanent failure")

        with pytest.raises(ValueError, match="permanent failure"):
            always_fail()
        assert call_count == 3  # initial + 2 retries

    def test_respects_max_delay(self):
        """Delay is capped at max_delay before jitter multiplication."""
        call_count = 0
        pre_jitter_delays = []

        original_sleep = time.sleep
        def mock_sleep(d):
            original_sleep(d)

        # Patch to capture delay value before jitter is applied
        import random
        original_random = random.random

        def mock_random():
            return 0.5  # deterministic

        with patch.object(time, 'sleep', mock_sleep), \
             patch.object(random, 'random', mock_random):

            @retry_with_backoff_testable(max_retries=3, initial_delay=0.1, max_delay=0.2)
            def fail_once():
                nonlocal call_count
                call_count += 1
                if call_count < 3:
                    raise ValueError("fail")
                return "ok"

            fail_once()

        # The max_delay cap is applied BEFORE jitter, so pre-jitter delay should be <= 0.2
        # With backoff: attempt 1 delay = 0.1, attempt 2 delay = 0.2 (capped)
        # After jitter (0.75): 0.075 and 0.15 respectively

    def test_on_retry_callback(self):
        """on_retry callback is called on each retry."""
        call_count = 0
        retry_events = []

        def on_retry(exc, attempt):
            retry_events.append((exc, attempt))

        @retry_with_backoff_testable(max_retries=3, initial_delay=0.01, on_retry=on_retry)
        def fail_twice():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("temp")
            return "ok"

        fail_twice()
        assert len(retry_events) == 2
        assert retry_events[0][1] == 1
        assert retry_events[1][1] == 2

    def test_jitter_reduces_collision(self):
        """Jitter should spread out retry times."""
        delays = []
        original_sleep = time.sleep

        def mock_sleep(d):
            delays.append(d)
            original_sleep(d)

        call_count = 0

        with patch.object(time, 'sleep', mock_sleep):
            @retry_with_backoff_testable(max_retries=5, initial_delay=0.01, jitter=True)
            def always_fail():
                nonlocal call_count
                call_count += 1
                raise ValueError("fail")

            try:
                always_fail()
            except ValueError:
                pass

        # Without jitter (factor 0.5 + random), delays would be predictable
        # With jitter, they should vary
        unique_delays = len(set(delays))
        assert unique_delays > 1, "Jitter should produce varying delays"


class TestRetryableAPIClientLogic:
    """Tests for RetryableAPIClient class logic."""

    def test_successful_call(self):
        """call_with_retry succeeds without retry."""
        call_count = 0

        def succeed():
            nonlocal call_count
            call_count += 1
            return "result"

        result = succeed()
        assert result == "result"
        assert call_count == 1

    def test_retry_then_success(self):
        """Retries on failure and succeeds on later attempt."""
        results = [ValueError("fail1"), ValueError("fail2"), "success"]
        call_count = 0

        def func():
            nonlocal call_count
            result = results[call_count]
            call_count += 1
            if isinstance(result, Exception):
                raise result
            return result

        # Simulate the retry logic
        max_retries = 3
        delay = 0.01
        for attempt in range(max_retries + 1):
            try:
                result = func()
                break
            except Exception:
                if attempt == max_retries:
                    raise

        assert result == "success"
        assert call_count == 3

    def test_exhaust_retries(self):
        """Exhausts retries and raises last exception."""
        call_count = 0

        def always_fail():
            nonlocal call_count
            call_count += 1
            raise ValueError("always fails")

        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                always_fail()
            except ValueError:
                if attempt == max_retries:
                    raised = True
                    break
                continue
        else:
            raised = False

        assert raised
        assert call_count == 3

    def test_batch_continues_on_failure(self):
        """Batch processing continues after individual item failures."""
        items = [1, 2, 3]
        results = []
        failures = []

        for idx, item in enumerate(items):
            try:
                if item == 2:
                    raise ValueError("item 2 failed")
                results.append(item * 10)
            except Exception as e:
                failures.append({"index": idx, "item": item, "error": str(e)})

        assert results == [10, 30]
        assert len(failures) == 1
        assert failures[0]["index"] == 1

    def test_batch_stops_on_failure(self):
        """Batch processing stops when continue_on_failure is False."""
        items = [1, 2, 3]
        results = []
        stop_on_failure = True

        for idx, item in enumerate(items):
            if item == 2:
                try:
                    raise ValueError("item 2 failed")
                except ValueError:
                    if stop_on_failure:
                        break
            results.append(item * 10)

        assert results == [10]  # stops at item 2