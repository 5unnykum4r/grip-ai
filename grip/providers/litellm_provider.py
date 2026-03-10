"""LiteLLM-based provider adapter.

Wraps litellm.acompletion() to provide unified access to 100+ LLM
providers (OpenRouter, Anthropic, OpenAI, Gemini, Groq, etc.)
through a single interface.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, NoReturn

from loguru import logger

from grip.providers.types import (
    LLMMessage,
    LLMProvider,
    LLMResponse,
    StreamDelta,
    TokenUsage,
    ToolCall,
)


class LiteLLMProvider(LLMProvider):
    """Multi-provider LLM adapter backed by LiteLLM.

    LiteLLM handles the per-provider API translation, retry logic,
    and authentication under the hood.
    """

    _litellm_configured: bool = False

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
        """Prepare authentication for LiteLLM.

        Instead of writing API keys to os.environ (which exposes them to child
        processes and shell commands), we store the resolved env var name so
        the key can be passed directly via the api_key parameter at call time.
        Only falls back to env vars when LiteLLM strictly requires it for a
        specific provider.
        """
        self._litellm_env_var: str | None = None
        env_map = {
            "openrouter": "OPENROUTER_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "groq": "GROQ_API_KEY",
            "gemini": "GEMINI_API_KEY",
        }
        prefix_lower = self._model_prefix.lower().rstrip("/")
        self._litellm_env_var = env_map.get(prefix_lower)

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

        kwargs, resolved_model = self._build_kwargs(
            messages, model=model, tools=tools,
            temperature=temperature, max_tokens=max_tokens,
        )

        tool_count = len(tools) if tools else 0
        logger.info(
            "LiteLLM call: model={}, messages={}, tools={}",
            resolved_model,
            len(messages),
            tool_count,
        )

        try:
            response = await litellm.acompletion(**kwargs)
        except Exception as exc:
            self._raise_provider_error(exc, resolved_model)

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

    def _build_kwargs(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None,
        tools: list[dict[str, Any]] | None,
        temperature: float | None,
        max_tokens: int | None,
    ) -> tuple[dict[str, Any], str]:
        """Build the kwargs dict for litellm.acompletion and return (kwargs, resolved_model)."""
        import litellm

        if not LiteLLMProvider._litellm_configured:
            litellm.drop_params = True
            litellm.suppress_debug_info = True
            LiteLLMProvider._litellm_configured = True

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
            kwargs["tool_choice"] = "auto"
        if self._api_base:
            kwargs["api_base"] = self._api_base
        if self._api_key:
            kwargs["api_key"] = self._api_key
        if self._provider_name == "openrouter":
            kwargs["extra_headers"] = {
                "X-Title": "Grip AI",
                "HTTP-Referer": "https://github.com/5unnykum4r/grip-ai",
            }

        return kwargs, resolved_model

    def _raise_provider_error(self, exc: Exception, resolved_model: str) -> NoReturn:
        """Map provider exceptions to grip's error hierarchy. Always raises."""
        from grip.providers.exceptions import (
            AuthenticationError,
            ModelNotFoundError,
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
            raise ModelNotFoundError(
                f"[{self._provider_name}] Model '{resolved_model}' not found.",
                provider=self._provider_name,
                hint="Check available models on your provider's docs.",
            ) from exc

        raise ProviderError(
            f"[{self._provider_name}] {exc}",
            provider=self._provider_name,
        ) from exc

    async def chat_stream(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[StreamDelta]:
        """Stream incremental deltas from the LLM using litellm.acompletion(stream=True).

        Yields ``StreamDelta`` objects as tokens arrive. Tool calls are
        accumulated across chunks and emitted on the final delta (when
        ``finish_reason`` is set). Usage stats appear on the final chunk
        when supported by the provider.
        """
        import litellm

        kwargs, resolved_model = self._build_kwargs(
            messages, model=model, tools=tools,
            temperature=temperature, max_tokens=max_tokens,
        )
        kwargs["stream"] = True
        kwargs["stream_options"] = {"include_usage": True}

        tool_count = len(tools) if tools else 0
        logger.info(
            "LiteLLM stream call: model={}, messages={}, tools={}",
            resolved_model, len(messages), tool_count,
        )

        try:
            response = await litellm.acompletion(**kwargs)
        except Exception as exc:
            self._raise_provider_error(exc, resolved_model)

        # Accumulate tool_calls across chunks (they arrive in pieces)
        accumulated_tool_calls: dict[int, dict[str, Any]] = {}
        total_usage: TokenUsage | None = None

        async for chunk in response:
            choices = getattr(chunk, "choices", None)
            if not choices:
                # Final chunk may have usage but no choices
                usage_data = getattr(chunk, "usage", None)
                if usage_data:
                    total_usage = TokenUsage(
                        prompt_tokens=getattr(usage_data, "prompt_tokens", 0) or 0,
                        completion_tokens=getattr(usage_data, "completion_tokens", 0) or 0,
                    )
                continue

            choice = choices[0]
            delta = getattr(choice, "delta", None)
            if delta is None:
                continue

            content = getattr(delta, "content", None)

            # Tool calls arrive incrementally with index-based accumulation
            raw_tool_calls = getattr(delta, "tool_calls", None)
            if raw_tool_calls:
                for tc in raw_tool_calls:
                    idx = getattr(tc, "index", 0)
                    if idx not in accumulated_tool_calls:
                        accumulated_tool_calls[idx] = {
                            "id": "",
                            "name": "",
                            "arguments": "",
                        }
                    entry = accumulated_tool_calls[idx]
                    tc_id = getattr(tc, "id", None)
                    if tc_id:
                        entry["id"] = tc_id
                    fn = getattr(tc, "function", None)
                    if fn:
                        fn_name = getattr(fn, "name", None)
                        if fn_name:
                            entry["name"] = fn_name
                        fn_args = getattr(fn, "arguments", None)
                        if fn_args:
                            entry["arguments"] += fn_args

            # Usage from final chunk
            usage_data = getattr(chunk, "usage", None)
            if usage_data:
                total_usage = TokenUsage(
                    prompt_tokens=getattr(usage_data, "prompt_tokens", 0) or 0,
                    completion_tokens=getattr(usage_data, "completion_tokens", 0) or 0,
                )

            finish_reason = getattr(choice, "finish_reason", None)
            is_done = finish_reason is not None

            if content or is_done:
                completed_tools: list[ToolCall] = []
                if is_done and accumulated_tool_calls:
                    for tc_entry in accumulated_tool_calls.values():
                        args = self._safe_parse_json(tc_entry["arguments"])
                        completed_tools.append(
                            ToolCall(
                                id=tc_entry["id"],
                                function_name=tc_entry["name"],
                                arguments=args,
                            )
                        )

                yield StreamDelta(
                    content=content,
                    tool_calls=completed_tools if is_done else [],
                    usage=total_usage if is_done else None,
                    done=is_done,
                )

    @staticmethod
    def _safe_parse_json(text: str) -> dict[str, Any]:
        """Parse JSON from LLM output, using json-repair as a fallback."""
        if not text or not text.strip():
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            import json_repair

            parsed = json_repair.loads(text)
        return parsed if isinstance(parsed, dict) else {}
