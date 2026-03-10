"""Tests for provider-level streaming types."""

from __future__ import annotations

from grip.providers.types import StreamDelta, TokenUsage, ToolCall


class TestStreamDelta:
    def test_defaults(self):
        d = StreamDelta()
        assert d.content is None
        assert d.tool_calls == []
        assert d.usage is None
        assert d.done is False

    def test_with_content(self):
        d = StreamDelta(content="hello", done=True)
        assert d.content == "hello"
        assert d.done is True

    def test_with_tool_calls(self):
        tc = ToolCall(id="tc_1", function_name="web_search", arguments={"q": "test"})
        d = StreamDelta(tool_calls=[tc], done=True)
        assert len(d.tool_calls) == 1
        assert d.tool_calls[0].function_name == "web_search"

    def test_with_usage(self):
        usage = TokenUsage(prompt_tokens=10, completion_tokens=5)
        d = StreamDelta(usage=usage, done=True)
        assert d.usage is not None
        assert d.usage.total_tokens == 15

    def test_mutable_list_defaults_are_independent(self):
        a = StreamDelta()
        b = StreamDelta()
        a.tool_calls.append(ToolCall(id="x", function_name="y", arguments={}))
        assert b.tool_calls == []
