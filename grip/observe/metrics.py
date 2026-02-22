"""In-memory metrics collection for grip.

Thread-safe counters and gauges for tracking agent activity. No external
dependencies — works in CLI mode with in-memory storage and can be
exposed via the /api/v1/metrics endpoint.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class MetricsSnapshot:
    """Point-in-time snapshot of all collected metrics."""

    total_agent_runs: int = 0
    total_tool_calls: int = 0
    total_llm_calls: int = 0
    total_errors: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_workflow_runs: int = 0
    active_sessions: int = 0
    uptime_seconds: float = 0.0

    def to_dict(self) -> dict:
        return {
            "total_agent_runs": self.total_agent_runs,
            "total_tool_calls": self.total_tool_calls,
            "total_llm_calls": self.total_llm_calls,
            "total_errors": self.total_errors,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_workflow_runs": self.total_workflow_runs,
            "active_sessions": self.active_sessions,
            "uptime_seconds": round(self.uptime_seconds, 1),
        }


class MetricsCollector:
    """Thread-safe in-memory metrics collector.

    All counter methods are safe to call from any thread or asyncio task.
    Use snapshot() to get a frozen copy of current values.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._start_time = time.monotonic()
        self._agent_runs = 0
        self._tool_calls = 0
        self._llm_calls = 0
        self._errors = 0
        self._prompt_tokens = 0
        self._completion_tokens = 0
        self._workflow_runs = 0
        self._active_sessions = 0

    def record_agent_run(self) -> None:
        with self._lock:
            self._agent_runs += 1

    def record_tool_call(self, count: int = 1) -> None:
        with self._lock:
            self._tool_calls += count

    def record_llm_call(self) -> None:
        with self._lock:
            self._llm_calls += 1

    def record_error(self) -> None:
        with self._lock:
            self._errors += 1

    def record_tokens(self, prompt: int, completion: int) -> None:
        with self._lock:
            self._prompt_tokens += prompt
            self._completion_tokens += completion

    def record_workflow_run(self) -> None:
        with self._lock:
            self._workflow_runs += 1

    def set_active_sessions(self, count: int) -> None:
        with self._lock:
            self._active_sessions = count

    def snapshot(self) -> MetricsSnapshot:
        """Return a frozen copy of current metrics."""
        with self._lock:
            return MetricsSnapshot(
                total_agent_runs=self._agent_runs,
                total_tool_calls=self._tool_calls,
                total_llm_calls=self._llm_calls,
                total_errors=self._errors,
                total_prompt_tokens=self._prompt_tokens,
                total_completion_tokens=self._completion_tokens,
                total_workflow_runs=self._workflow_runs,
                active_sessions=self._active_sessions,
                uptime_seconds=time.monotonic() - self._start_time,
            )

    def reset(self) -> None:
        """Reset all counters (for testing)."""
        with self._lock:
            self._agent_runs = 0
            self._tool_calls = 0
            self._llm_calls = 0
            self._errors = 0
            self._prompt_tokens = 0
            self._completion_tokens = 0
            self._workflow_runs = 0
            self._active_sessions = 0
            self._start_time = time.monotonic()


# Global singleton — importable from anywhere
_global_metrics: MetricsCollector | None = None


def get_metrics() -> MetricsCollector:
    """Get or create the global metrics collector."""
    global _global_metrics  # noqa: PLW0603
    if _global_metrics is None:
        _global_metrics = MetricsCollector()
    return _global_metrics
