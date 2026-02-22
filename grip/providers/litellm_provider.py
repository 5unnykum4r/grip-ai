"""LiteLLM-based provider adapter.

Wraps litellm.acompletion() to provide unified access to 100+ LLM
providers (OpenRouter, Anthropic, OpenAI, Gemini, Groq, etc.)
through a single interface.
"""

from __future__ import annotations

import json
import os
from typing import Any

from loguru import logger

from grip.providers.types import (
    LLMMessage,
    LLMProvider,
    LLMResponse,
    TokenUsage,
    ToolCall,
)


class LiteLLMProvider(LLMProvider):
    """Multi-provider LLM adapter backed by LiteLLM.

    LiteLLM handles the per-provider API translation, retry logic,
    and authentication under the hood.
    """

    def __init__(
        self,
        provider_name: str,
        model_prefix: str,
        api_key: str,
        api_base: str,
        default_model: str,
    ) -> None:
        self._provider_name = provider_name
        self._model_prefix = model_prefix
        self._api_key = api_key
        self._api_base = api_base
        self._default_model = default_model
        self._setup_env()

    def _setup_env(self) -> None:
        """Set environment variables that LiteLLM expects for authentication."""
        env_map = {
            "openrouter": "OPENROUTER_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "groq": "GROQ_API_KEY",
            "gemini": "GEMINI_API_KEY",
        }
        prefix_lower = self._model_prefix.lower().rstrip("/")
        env_var = env_map.get(prefix_lower)
        if env_var and self._api_key:
            os.environ[env_var] = self._api_key

    @property
    def name(self) -> str:
        return self._provider_name

    def supports_tools(self) -> bool:
        return True

    async def chat(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        import litellm

        litellm.drop_params = True

        resolved_model = model or self._default_model
        if self._model_prefix and not resolved_model.startswith(self._model_prefix):
            resolved_model = f"{self._model_prefix}/{resolved_model}"

        kwargs: dict[str, Any] = {
            "model": resolved_model,
            "messages": [m.to_dict() for m in messages],
        }

        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if tools:
            kwargs["tools"] = tools

        if self._api_base:
            kwargs["api_base"] = self._api_base
        if self._api_key:
            kwargs["api_key"] = self._api_key

        logger.debug(
            "LiteLLM call: model={}, messages={}, tools={}",
            resolved_model,
            len(messages),
            len(tools) if tools else 0,
        )

        try:
            response = await litellm.acompletion(**kwargs)
        except Exception as exc:
            from grip.providers.exceptions import (
                AuthenticationError,
                ProviderError,
                RateLimitError,
                ServerError,
            )

            exc_str = str(exc).lower()
            status = getattr(exc, "status_code", None)

            if status == 401 or "authenticationerror" in type(exc).__name__.lower():
                raise AuthenticationError(
                    f"[{self._provider_name}] Authentication failed — your API key is invalid or missing.",
                    provider=self._provider_name,
                    hint="Run 'grip setup' to reconfigure your API key.",
                ) from exc
            if status == 429 or "ratelimit" in exc_str:
                raise RateLimitError(
                    f"[{self._provider_name}] Rate limit exceeded.",
                    provider=self._provider_name,
                    hint="Wait a moment and try again.",
                ) from exc
            if status and status >= 500:
                raise ServerError(
                    f"[{self._provider_name}] Provider server error (HTTP {status}).",
                    provider=self._provider_name,
                    hint="Try again in a moment.",
                ) from exc
            if "notfounderror" in type(exc).__name__.lower() or status == 404:
                from grip.providers.exceptions import ModelNotFoundError

                raise ModelNotFoundError(
                    f"[{self._provider_name}] Model '{resolved_model}' not found.",
                    provider=self._provider_name,
                    hint="Check available models on your provider's docs.",
                ) from exc

            raise ProviderError(
                f"[{self._provider_name}] {exc}",
                provider=self._provider_name,
            ) from exc

        return self._parse_response(response)

    def _parse_response(self, response: Any) -> LLMResponse:
        """Convert a LiteLLM ModelResponse into our LLMResponse."""
        choice = response.choices[0]
        message = choice.message

        content = getattr(message, "content", None)
        reasoning = getattr(message, "reasoning_content", None)

        tool_calls: list[ToolCall] = []
        raw_tool_calls = getattr(message, "tool_calls", None)
        if raw_tool_calls:
            for tc in raw_tool_calls:
                fn = tc.function
                args = fn.arguments
                if isinstance(args, str):
                    args = self._safe_parse_json(args)
                tool_calls.append(
                    ToolCall(
                        id=tc.id,
                        function_name=fn.name,
                        arguments=args,
                    )
                )

        usage_data = getattr(response, "usage", None)
        usage = TokenUsage(
            prompt_tokens=getattr(usage_data, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage_data, "completion_tokens", 0) or 0,
        )

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            usage=usage,
            reasoning_content=reasoning,
            raw=response.model_dump() if hasattr(response, "model_dump") else {},
        )

    @staticmethod
    def _safe_parse_json(text: str) -> dict[str, Any]:
        """Parse JSON from LLM output, using json-repair as a fallback."""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            import json_repair

            return json_repair.loads(text)
