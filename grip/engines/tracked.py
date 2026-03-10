"""TrackedEngine — decorator that adds token usage tracking to any EngineProtocol."""

from __future__ import annotations

from collections.abc import AsyncIterator

from grip.engines.types import AgentRunResult, EngineProtocol, StreamEvent
from grip.security.token_tracker import TokenTracker


class TrackedEngine(EngineProtocol):
    """Wraps any EngineProtocol to add daily token tracking and limits.

    Calls check_limit() before delegating to the inner engine's run(),
    and records token usage after a successful run. If the daily limit
    is exceeded, TokenLimitError propagates to the caller.
    """

    def __init__(self, inner: EngineProtocol, tracker: TokenTracker) -> None:
        self._inner = inner
        self._tracker = tracker

    @property
    def tracker(self) -> TokenTracker:
        """Expose the tracker for status queries."""
        return self._tracker

    async def run(
        self,
        user_message: str,
        *,
        session_key: str = "cli:default",
        model: str | None = None,
    ) -> AgentRunResult:
        self._tracker.check_limit()
        result = await self._inner.run(user_message, session_key=session_key, model=model)
        self._tracker.record(result.prompt_tokens, result.completion_tokens)
        return result

    async def run_stream(
        self,
        user_message: str,
        *,
        session_key: str = "cli:default",
        model: str | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Check token limit, forward the stream, record usage from the done event."""
        self._tracker.check_limit()
        async for event in self._inner.run_stream(
            user_message, session_key=session_key, model=model
        ):
            if event.type == "done":
                self._tracker.record(event.prompt_tokens, event.completion_tokens)
            yield event

    async def consolidate_session(self, session_key: str) -> None:
        await self._inner.consolidate_session(session_key)

    async def reset_session(self, session_key: str) -> None:
        await self._inner.reset_session(session_key)
