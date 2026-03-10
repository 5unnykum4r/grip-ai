"""Core LLM types shared across all providers.

These dataclasses define the internal message format that grip uses.
Providers translate between this format and their native wire format.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A single tool invocation requested by the LLM."""

    id: str
    function_name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Token consumption for a single LLM call."""

    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(slots=True)
class LLMMessage:
    """A single message in the conversation history.

    Supports all OpenAI-style roles: system, user, assistant, tool.
    """

    role: str
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the OpenAI chat completions message format."""
        msg: dict[str, Any] = {"role": self.role}

        if self.content is not None:
            msg["content"] = self.content

        if self.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function_name,
                        "arguments": (
                            tc.arguments
                            if isinstance(tc.arguments, str)
                            else json.dumps(tc.arguments)
                        ),
                    },
                }
                for tc in self.tool_calls
            ]

        if self.tool_call_id is not None:
            msg["tool_call_id"] = self.tool_call_id

        if self.name is not None:
            msg["name"] = self.name

        return msg


@dataclass(slots=True)
class LLMResponse:
    """Parsed response from an LLM provider."""

    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: TokenUsage = field(default_factory=TokenUsage)
    reasoning_content: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StreamDelta:
    """A single incremental chunk from a streaming LLM response.

    Provider ``chat_stream()`` implementations yield these as tokens arrive.
    Fields are populated incrementally — only ``content`` or ``tool_calls``
    will be set on any given delta, and ``usage`` / ``done`` only appear on
    the final chunk.
    """

    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: TokenUsage | None = None
    done: bool = False


class LLMProvider(ABC):
    """Abstract base class for LLM provider adapters.

    Each provider translates between grip's LLMMessage/LLMResponse
    and the provider's native API format.
    """

    @abstractmethod
    async def chat(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Send a chat completion request and return the parsed response."""
        ...

    async def chat_stream(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[StreamDelta]:
        """Stream incremental deltas from the LLM.

        Default implementation falls back to ``chat()`` and yields the full
        response as a single delta. Providers override this for true streaming.
        """
        response = await self.chat(
            messages,
            model=model,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        yield StreamDelta(
            content=response.content,
            tool_calls=response.tool_calls,
            usage=response.usage,
            done=True,
        )

    @abstractmethod
    def supports_tools(self) -> bool:
        """Whether this provider supports function/tool calling."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable provider name."""
        ...
