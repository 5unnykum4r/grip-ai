"""LiteLLM success callback that records per-call USD cost into a TokenTracker.

LiteLLM computes the dollar cost of each call from its own pricing tables and
exposes it as ``response_cost`` in the kwargs passed to success callbacks. The
engine's ``AgentRunResult`` only carries token counts, so cost has to be picked
up here, on LiteLLM's callback path, rather than in ``TrackedEngine.run()``.

This only fires for the LiteLLM engine path. The Claude Agent SDK path bypasses
LiteLLM entirely, so SDK runs are not cost-tracked here (a known limitation that
would require routing the SDK through a LiteLLM proxy to close).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from litellm.integrations.custom_logger import CustomLogger
from loguru import logger

if TYPE_CHECKING:
    from grip.security.token_tracker import TokenTracker


class CostTrackingLogger(CustomLogger):
    """Records ``response_cost`` from each successful LiteLLM call."""

    def __init__(self, tracker: TokenTracker) -> None:
        super().__init__()
        self._tracker = tracker

    @property
    def tracker(self) -> TokenTracker:
        return self._tracker

    def _record(self, kwargs: dict[str, Any]) -> None:
        cost = kwargs.get("response_cost")
        if cost is None:
            return
        try:
            self._tracker.record_cost(float(cost))
        except (TypeError, ValueError):
            logger.debug("Ignoring non-numeric response_cost: {!r}", cost)

    def log_success_event(self, kwargs, response_obj, start_time, end_time) -> None:  # noqa: ANN001
        self._record(kwargs)

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time) -> None:  # noqa: ANN001
        self._record(kwargs)


def register_cost_logger(tracker: TokenTracker) -> CostTrackingLogger:
    """Register a CostTrackingLogger on litellm.callbacks for the given tracker.

    Idempotent: if a CostTrackingLogger bound to this exact tracker is already
    registered, the existing instance is returned instead of adding a duplicate.
    """
    import litellm

    for cb in litellm.callbacks:
        if isinstance(cb, CostTrackingLogger) and cb.tracker is tracker:
            return cb

    cost_logger = CostTrackingLogger(tracker)
    litellm.callbacks.append(cost_logger)
    logger.debug("Registered LiteLLM cost-tracking callback.")
    return cost_logger
