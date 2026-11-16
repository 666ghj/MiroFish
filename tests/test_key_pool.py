"""
Unit tests for LLMKeyPool and RateLimit rotator.
"""

import time
import os
import sys
import pytest
from unittest.mock import MagicMock
from openai import RateLimitError

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'backend')))

from app.utils.key_pool import (
    LLMKeyPool,
    KeyEntry,
    parse_key_list,
    mask_key,
)


def test_mask_key():
    assert mask_key("sk-1234567890abcdef") == "sk-1...cdef"
    assert mask_key("short") == "***"
    assert mask_key("") == "***"


def test_parse_key_list():
    assert parse_key_list("k1, k2, k3") == ["k1", "k2", "k3"]
    assert parse_key_list("k1;k2;k3") == ["k1", "k2", "k3"]
    assert parse_key_list("k1\nk2\nk3") == ["k1", "k2", "k3"]
    assert parse_key_list('["k1", "k2"]') == ["k1", "k2"]
    assert parse_key_list(None) == []
    assert parse_key_list("") == []


def test_key_pool_round_robin():
    pool = LLMKeyPool(api_keys=["key1", "key2", "key3"], base_url="http://mock")
    assert pool.size == 3

    e1 = pool.get_next_entry()
    e2 = pool.get_next_entry()
    e3 = pool.get_next_entry()
    e4 = pool.get_next_entry()

    assert e1.key == "key1"
    assert e2.key == "key2"
    assert e3.key == "key3"
    assert e4.key == "key1"  # wrap around


def test_key_pool_cooldown_and_failover():
    pool = LLMKeyPool(api_keys=["key1", "key2"], base_url="http://mock", default_cooldown=10.0)

    # Key 1 hits rate limit
    pool.entries[0].mark_rate_limited(cooldown_seconds=10.0)
    assert not pool.entries[0].is_healthy()
    assert pool.entries[1].is_healthy()

    # Next entry should be key2
    entry = pool.get_next_entry()
    assert entry.key == "key2"

    # Next call should still skip key1 and return key2
    entry2 = pool.get_next_entry()
    assert entry2.key == "key2"


def test_execute_with_failover_success():
    pool = LLMKeyPool(api_keys=["k1", "k2"], base_url="http://mock")
    call_keys = []

    def fake_request(client, key):
        call_keys.append(key)
        return "success"

    result = pool.execute_with_failover(fake_request)
    assert result == "success"
    assert len(call_keys) == 1
    assert call_keys[0] == "k1"


def test_execute_with_failover_retry_on_429():
    pool = LLMKeyPool(api_keys=["k1", "k2"], base_url="http://mock", default_cooldown=5.0)
    call_keys = []

    def failing_first_request(client, key):
        call_keys.append(key)
        if key == "k1":
            # Simulate a 429 RateLimitError
            response_mock = MagicMock()
            response_mock.status_code = 429
            raise RateLimitError("Rate limit exceeded", response=response_mock, body=None)
        return f"success_from_{key}"

    result = pool.execute_with_failover(failing_first_request)
    assert result == "success_from_k2"
    assert call_keys == ["k1", "k2"]
    # k1 should now be in cooldown
    assert not pool.entries[0].is_healthy()
    assert pool.entries[1].is_healthy()
