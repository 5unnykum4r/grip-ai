"""Direct OpenAI-compatible provider.

Calls any OpenAI-compatible /chat/completions endpoint using httpx.
Used for local models (Ollama, vLLM), custom deployments, or when
LiteLLM is not needed.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from loguru import logger

from grip.providers.exceptions import ProviderConnectionError, ProviderError, raise_for_status
from grip.providers.types import (
    LLMMessage,
    LLMProvider,
    LLMResponse,
    TokenUsage,
    ToolCall,
)

_DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)


class OpenAICompatProvider(LLMProvider):
    """Adapter for any endpoint that speaks the OpenAI chat completions protocol.

    Keeps a persistent httpx.AsyncClient with connection pooling for
    efficient repeated calls to the same host.
    """

    def __init__(
        self,
        provider_name: str,
        api_base: str,
        api_key: str,
        default_model: str,
    ) -> None:
        self._provider_name = provider_name
        self._api_base = api_base.rstrip("/")
        self._api_key = api_key
        self._default_model = default_model
        self._client: httpx.AsyncClient | None = None

    @property
    def name(self) -> str:
        return self._provider_name

    def supports_tools(self) -> bool:
        return True

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            headers: dict[str, str] = {"Content-Type": "application/json"}
            if self._api_key and self._api_key != "not-needed":
                headers["Authorization"] = f"Bearer {self._api_key}"

            self._client = httpx.AsyncClient(
                base_url=self._api_base,
                headers=headers,
                timeout=_DEFAULT_TIMEOUT,
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            )
        return self._client

    async def chat(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        client = await self._get_client()
        resolved_model = model or self._default_model

        payload: dict[str, Any] = {
            "model": resolved_model,
            "messages": [m.to_dict() for m in messages],
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools

        logger.debug(
            "OpenAI-compat call: base={}, model={}, messages={}, tools={}",
            self._api_base,
            resolved_model,
            len(messages),
            len(tools) if tools else 0,
        )

        # Try /chat/completions first, fall back to /v1/chat/completions
        for endpoint in ("/chat/completions", "/v1/chat/completions"):
            try:
                resp = await client.post(endpoint, json=payload)
            except httpx.ConnectError as exc:
                raise ProviderConnectionError(
                    f"[{self._provider_name}] Cannot connect to {self._api_base}",
                    provider=self._provider_name,
                    hint="Check that the API URL is correct and the service is running.",
                ) from exc
            except httpx.ReadTimeout as exc:
                raise ProviderError(
                    f"[{self._provider_name}] Request timed out waiting for a response.",
                    provider=self._provider_name,
                    hint="The model may be slow or overloaded. Try again or use a faster model.",
                ) from exc

            if resp.status_code == 404 and endpoint == "/chat/completions":
                continue

            if resp.status_code >= 400:
                body = resp.text[:300] if resp.text else ""
                raise_for_status(
                    resp.status_code,
                    self._provider_name,
                    self._api_base,
                    resolved_model,
                    raw_message=body,
                )

            return self._parse_response(resp.json())

        raise ProviderConnectionError(
            f"[{self._provider_name}] No valid chat completions endpoint found at {self._api_base}",
            provider=self._provider_name,
            hint="Verify the API base URL is correct.",
        )

    def _parse_response(self, data: dict[str, Any]) -> LLMResponse:
        choice = data["choices"][0]
        message = choice["message"]

        content = message.get("content")
        reasoning = message.get("reasoning_content")

        tool_calls: list[ToolCall] = []
        for tc in message.get("tool_calls") or []:
            fn = tc["function"]
            args = fn.get("arguments", "{}")
            if isinstance(args, str):
                args = self._safe_parse_json(args)
            tool_calls.append(ToolCall(id=tc["id"], function_name=fn["name"], arguments=args))

        usage_raw = data.get("usage", {})
        usage = TokenUsage(
            prompt_tokens=usage_raw.get("prompt_tokens", 0),
            completion_tokens=usage_raw.get("completion_tokens", 0),
        )

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            usage=usage,
            reasoning_content=reasoning,
            raw=data,
        )

    @staticmethod
    def _safe_parse_json(text: str) -> dict[str, Any]:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            import json_repair

            return json_repair.loads(text)

    async def close(self) -> None:
        """Close the underlying HTTP client. Call on shutdown."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
