"""Shared types and abstract protocol for the dual-engine system.

Every engine (SDKRunner, LiteLLMRunner) implements ``EngineProtocol`` and
returns ``AgentRunResult`` objects so callers never depend on a specific backend.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field


@dataclass(slots=True)
class ToolCallDetail:
    """Metadata captured for a single tool invocation during an agent run."""

    name: str
    success: bool
    duration_ms: float
    output_preview: str = ""


@dataclass(slots=True)
class AgentRunResult:
    """Unified result object returned by every engine after an agent run.

    Only ``response`` is required. Token counts, iteration counts, and tool-call
    metadata default to zero / empty so callers can rely on safe defaults.
    """

    response: str
    iterations: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    tool_calls_made: list[str] = field(default_factory=list)
    tool_details: list[ToolCallDetail] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        """Sum of prompt and completion tokens for convenience."""
        return self.prompt_tokens + self.completion_tokens


@dataclass(slots=True)
class StreamEvent:
    """A single event yielded by ``EngineProtocol.run_stream()``.

    Event types:
      - ``"token"``: incremental text chunk (``text`` field)
      - ``"tool_start"``: a tool execution is beginning (``tool_name`` field)
      - ``"tool_end"``: a tool execution finished (``tool_name`` field)
      - ``"done"``: stream complete (usage and tool_calls_made fields)
      - ``"error"``: an error occurred (``text`` field contains detail)
    """

    type: str
    text: str = ""
    tool_name: str = ""
    iterations: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    tool_calls_made: list[str] = field(default_factory=list)


class EngineProtocol(ABC):
    """Abstract base class that both engine implementations must satisfy.

    Callers (CLI, gateway, REST API, cron) depend only on this protocol, so
    swapping or falling back between engines requires no caller-side changes.
    """

    @abstractmethod
    async def run(
        self,
        user_message: str,
        *,
        session_key: str = "cli:default",
        model: str | None = None,
    ) -> AgentRunResult:
        """Send a user message through the engine and return the result."""

    async def run_stream(
        self,
        user_message: str,
        *,
        session_key: str = "cli:default",
        model: str | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Stream incremental events during agent execution.

        Default implementation falls back to ``run()`` and yields the full
        response as a single token event followed by a done event.
        Engines override this for true token-by-token streaming.
        """
        result = await self.run(user_message, session_key=session_key, model=model)
        yield StreamEvent(type="token", text=result.response)
        yield StreamEvent(
            type="done",
            iterations=result.iterations,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            tool_calls_made=result.tool_calls_made,
        )

    @abstractmethod
    async def consolidate_session(self, session_key: str) -> None:
        """Summarise and compact the conversation history for a session."""

    @abstractmethod
    async def reset_session(self, session_key: str) -> None:
        """Clear all conversation history for a session."""
