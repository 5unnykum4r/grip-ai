"""Tests for LiteLLMProvider.chat_stream() streaming support."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from grip.providers.litellm_provider import LiteLLMProvider
from grip.providers.types import LLMMessage


def _make_provider() -> LiteLLMProvider:
    return LiteLLMProvider(
        provider_name="test",
        model_prefix="test",
        api_key="fake-key",
        api_base="",
        default_model="test-model",
    )


def _chunk(
    content: str | None = None,
    finish_reason: str | None = None,
    tool_calls: list | None = None,
    usage: dict | None = None,
) -> SimpleNamespace:
    """Build a fake streaming chunk matching the litellm chunk format."""
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    chunk = SimpleNamespace(choices=[choice], usage=None)
    if usage:
        chunk.usage = SimpleNamespace(**usage)
    return chunk


async def _async_iter(items):
    """Turn a list into an async iterator."""
    for item in items:
        yield item


class TestChatStreamTextContent:
    @pytest.mark.asyncio
    async def test_streams_text_deltas(self):
        provider = _make_provider()
        chunks = [
            _chunk(content="Hello"),
            _chunk(content=" world"),
            _chunk(
                content="!",
                finish_reason="stop",
                usage={"prompt_tokens": 10, "completion_tokens": 3},
            ),
        ]

        with patch("litellm.acompletion", new_callable=AsyncMock, return_value=_async_iter(chunks)):
            messages = [LLMMessage(role="user", content="Hi")]
            deltas = []
            async for delta in provider.chat_stream(messages):
                deltas.append(delta)

        assert len(deltas) == 3
        assert deltas[0].content == "Hello"
        assert deltas[0].done is False
        assert deltas[1].content == " world"
        assert deltas[1].done is False
        assert deltas[2].content == "!"
        assert deltas[2].done is True
        assert deltas[2].usage is not None
        assert deltas[2].usage.prompt_tokens == 10
        assert deltas[2].usage.completion_tokens == 3

    @pytest.mark.asyncio
    async def test_skips_empty_content_chunks(self):
        provider = _make_provider()
        chunks = [
            _chunk(content=None),
            _chunk(content="data"),
            _chunk(finish_reason="stop"),
        ]

        with patch("litellm.acompletion", new_callable=AsyncMock, return_value=_async_iter(chunks)):
            messages = [LLMMessage(role="user", content="Hi")]
            deltas = []
            async for delta in provider.chat_stream(messages):
                deltas.append(delta)

        contents = [d.content for d in deltas if d.content]
        assert contents == ["data"]


class TestChatStreamToolCalls:
    @pytest.mark.asyncio
    async def test_accumulates_tool_calls_across_chunks(self):
        provider = _make_provider()

        tc_chunk1 = SimpleNamespace(
            index=0,
            id="call_123",
            function=SimpleNamespace(name="web_search", arguments='{"q":'),
        )
        tc_chunk2 = SimpleNamespace(
            index=0,
            id=None,
            function=SimpleNamespace(name=None, arguments=' "test"}'),
        )

        chunks = [
            _chunk(tool_calls=[tc_chunk1]),
            _chunk(tool_calls=[tc_chunk2]),
            _chunk(finish_reason="tool_calls", usage={"prompt_tokens": 5, "completion_tokens": 2}),
        ]

        with patch("litellm.acompletion", new_callable=AsyncMock, return_value=_async_iter(chunks)):
            messages = [LLMMessage(role="user", content="Search")]
            deltas = []
            async for delta in provider.chat_stream(messages):
                deltas.append(delta)

        done_deltas = [d for d in deltas if d.done]
        assert len(done_deltas) == 1
        assert len(done_deltas[0].tool_calls) == 1
        tc = done_deltas[0].tool_calls[0]
        assert tc.id == "call_123"
        assert tc.function_name == "web_search"
        assert tc.arguments == {"q": "test"}


class TestChatStreamUsage:
    @pytest.mark.asyncio
    async def test_usage_only_on_done_delta(self):
        provider = _make_provider()
        chunks = [
            _chunk(content="Hi"),
            _chunk(
                content="!",
                finish_reason="stop",
                usage={"prompt_tokens": 7, "completion_tokens": 2},
            ),
        ]

        with patch("litellm.acompletion", new_callable=AsyncMock, return_value=_async_iter(chunks)):
            messages = [LLMMessage(role="user", content="Hey")]
            deltas = []
            async for delta in provider.chat_stream(messages):
                deltas.append(delta)

        assert deltas[0].usage is None
        assert deltas[1].usage is not None
        assert deltas[1].usage.total_tokens == 9
