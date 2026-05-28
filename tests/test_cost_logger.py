"""Tests for the LiteLLM cost-tracking callback (Fix #4)."""

from __future__ import annotations

import pytest

from grip.observe.cost_logger import CostTrackingLogger, register_cost_logger
from grip.security.token_tracker import TokenTracker


@pytest.mark.asyncio
async def test_logger_records_response_cost(tmp_path):
    tracker = TokenTracker(tmp_path / "state")
    logger = CostTrackingLogger(tracker)

    await logger.async_log_success_event(
        kwargs={"response_cost": 0.0042, "model": "gpt-4o"},
        response_obj=None,
        start_time=None,
        end_time=None,
    )

    assert tracker.total_cost_today == 0.0042


@pytest.mark.asyncio
async def test_logger_ignores_missing_cost(tmp_path):
    tracker = TokenTracker(tmp_path / "state")
    logger = CostTrackingLogger(tracker)

    await logger.async_log_success_event(
        kwargs={"model": "gpt-4o"},  # no response_cost key
        response_obj=None,
        start_time=None,
        end_time=None,
    )

    assert tracker.total_cost_today == 0.0


def test_register_cost_logger_appends_to_litellm_callbacks(tmp_path):
    import litellm

    original = list(litellm.callbacks)
    try:
        tracker = TokenTracker(tmp_path / "state")
        logger = register_cost_logger(tracker)
        assert logger in litellm.callbacks
        # Idempotent: registering the same tracker twice does not duplicate.
        register_cost_logger(tracker)
        assert sum(isinstance(c, CostTrackingLogger) for c in litellm.callbacks) == 1
    finally:
        litellm.callbacks = original
