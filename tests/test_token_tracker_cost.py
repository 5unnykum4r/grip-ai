"""Tests for TokenTracker USD cost accumulation (Fix #4)."""

from __future__ import annotations

from grip.security.token_tracker import TokenTracker


def test_record_cost_accumulates(tmp_path):
    tracker = TokenTracker(tmp_path / "state")
    tracker.record_cost(0.0012)
    tracker.record_cost(0.0008)
    assert tracker.total_cost_today == 0.002


def test_summary_includes_cost(tmp_path):
    tracker = TokenTracker(tmp_path / "state")
    tracker.record_cost(0.5)
    summary = tracker.summary()
    assert summary["cost_usd"] == 0.5


def test_cost_persists_across_instances(tmp_path):
    state = tmp_path / "state"
    tracker = TokenTracker(state)
    tracker.record_cost(0.25)

    reopened = TokenTracker(state)
    assert reopened.total_cost_today == 0.25


def test_cost_independent_of_token_record(tmp_path):
    tracker = TokenTracker(tmp_path / "state")
    tracker.record(prompt_tokens=100, completion_tokens=50)
    tracker.record_cost(0.01)
    # Token recording must not reset or affect cost, and vice versa.
    assert tracker.total_today == 150
    assert tracker.total_cost_today == 0.01
