"""Tests for the API rate limiter."""

from __future__ import annotations

from grip.api.rate_limit import SlidingWindowRateLimiter


def test_allows_under_limit():
    limiter = SlidingWindowRateLimiter(max_requests=5, window_seconds=60)
    for _ in range(5):
        allowed, remaining, retry_after = limiter.is_allowed("client1")
        assert allowed is True
        assert retry_after == 0.0


def test_blocks_over_limit():
    limiter = SlidingWindowRateLimiter(max_requests=3, window_seconds=60)
    for _ in range(3):
        limiter.is_allowed("client1")

    allowed, remaining, retry_after = limiter.is_allowed("client1")
    assert allowed is False
    assert remaining == 0
    assert retry_after > 0


def test_independent_keys():
    limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=60)
    limiter.is_allowed("client_a")
    limiter.is_allowed("client_a")

    allowed, _, _ = limiter.is_allowed("client_b")
    assert allowed is True


def test_remaining_decreases():
    limiter = SlidingWindowRateLimiter(max_requests=5, window_seconds=60)

    _, remaining1, _ = limiter.is_allowed("x")
    _, remaining2, _ = limiter.is_allowed("x")

    assert remaining1 == 4
    assert remaining2 == 3


def test_cleanup_removes_stale():
    limiter = SlidingWindowRateLimiter(max_requests=10, window_seconds=0)
    limiter.is_allowed("stale_client")
    removed = limiter.cleanup()
    assert removed >= 1
