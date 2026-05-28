"""Tests for LiteLLMProvider retries + Router-based cross-provider fallback (Fix #1)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from grip.providers.litellm_provider import LiteLLMProvider
from grip.providers.types import LLMMessage


def _response(content: str = "ok") -> SimpleNamespace:
    """Minimal object shaped like a litellm ModelResponse for _parse_response."""
    message = SimpleNamespace(content=content, reasoning_content=None, tool_calls=None)
    choice = SimpleNamespace(message=message)
    usage = SimpleNamespace(prompt_tokens=3, completion_tokens=4)
    return SimpleNamespace(choices=[choice], usage=usage)


def _make_provider(**kwargs) -> LiteLLMProvider:
    base = dict(
        provider_name="test",
        model_prefix="test",
        api_key="fake-key",
        api_base="",
        default_model="test-model",
    )
    base.update(kwargs)
    return LiteLLMProvider(**base)


class TestNumRetries:
    @pytest.mark.asyncio
    async def test_default_num_retries_is_2(self):
        provider = _make_provider()
        with patch(
            "litellm.acompletion", new_callable=AsyncMock, return_value=_response()
        ) as mock_call:
            await provider.chat([LLMMessage(role="user", content="hi")])
        assert mock_call.call_args.kwargs["num_retries"] == 2

    @pytest.mark.asyncio
    async def test_custom_num_retries_forwarded(self):
        provider = _make_provider(num_retries=5)
        with patch(
            "litellm.acompletion", new_callable=AsyncMock, return_value=_response()
        ) as mock_call:
            await provider.chat([LLMMessage(role="user", content="hi")])
        assert mock_call.call_args.kwargs["num_retries"] == 5


class TestRouterFallback:
    def _deployments(self) -> list[dict]:
        return [
            {
                "model": "anthropic/claude-haiku-4-5",
                "api_key": "k2",
                "api_base": "https://api.anthropic.com/v1",
            }
        ]

    def test_no_router_built_without_fallbacks(self):
        provider = _make_provider()
        assert provider.router is None

    def test_router_built_with_fallbacks(self):
        with patch("litellm.Router") as mock_router_cls:
            _make_provider(fallback_deployments=self._deployments())
        assert mock_router_cls.called
        kwargs = mock_router_cls.call_args.kwargs
        # model_list contains the primary plus each fallback deployment.
        assert len(kwargs["model_list"]) == 2
        # An ordered fallback mapping points the primary alias at the fallback alias.
        assert kwargs["fallbacks"]

    @pytest.mark.asyncio
    async def test_chat_uses_router_when_present(self):
        mock_router = MagicMock()
        mock_router.acompletion = AsyncMock(return_value=_response("from-router"))
        with patch("litellm.Router", return_value=mock_router):
            provider = _make_provider(fallback_deployments=self._deployments())
            with patch("litellm.acompletion", new_callable=AsyncMock) as direct_call:
                result = await provider.chat([LLMMessage(role="user", content="hi")])

        assert result.content == "from-router"
        assert mock_router.acompletion.called
        direct_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_stream_uses_router_when_present(self):
        async def _aiter(items):
            for item in items:
                yield item

        stop_delta = SimpleNamespace(content="hi", tool_calls=None)
        stop_choice = SimpleNamespace(delta=stop_delta, finish_reason="stop")
        chunk = SimpleNamespace(
            choices=[stop_choice], usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1)
        )

        mock_router = MagicMock()
        mock_router.acompletion = AsyncMock(return_value=_aiter([chunk]))
        with patch("litellm.Router", return_value=mock_router):
            provider = _make_provider(fallback_deployments=self._deployments())
            deltas = [d async for d in provider.chat_stream([LLMMessage(role="user", content="hi")])]

        assert mock_router.acompletion.called
        # Router call uses the primary alias, not the raw model string.
        assert mock_router.acompletion.call_args.kwargs["model"] == "grip-primary"
        assert deltas[-1].done is True
