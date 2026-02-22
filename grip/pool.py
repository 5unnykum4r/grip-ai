"""Connection pool utilities for HTTP clients and LLM providers.

Provides reusable connection pools to avoid creating new connections
for each request, improving performance.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from loguru import logger


class _PooledSession:
    """Internal session class for connection pool context manager."""

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> httpx.AsyncClient:
        self._client = await self._pool.get_client()
        return self._client

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass


class ConnectionPool:
    """Async HTTP connection pool with limits."""

    def __init__(
        self,
        max_connections: int = 10,
        max_keepalive: int = 20,
        timeout: float = 30.0,
    ) -> None:
        self._max_connections = max_connections
        self._max_keepalive = max_keepalive
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()

    async def get_client(self) -> httpx.AsyncClient:
        """Get or create the pooled HTTP client."""
        if self._client is None:
            async with self._lock:
                if self._client is None:
                    limits = httpx.Limits(
                        max_connections=self._max_connections,
                        max_keepalive_connections=self._max_keepalive,
                    )
                    self._client = httpx.AsyncClient(
                        limits=limits,
                        timeout=httpx.Timeout(self._timeout),
                    )
                    logger.debug(
                        "Created HTTP connection pool (max_connections={}, max_keepalive={})",
                        self._max_connections,
                        self._max_keepalive,
                    )
        return self._client

    async def close(self) -> None:
        """Close the connection pool."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            logger.debug("Closed HTTP connection pool")

    def session(self) -> Any:
        """Context manager for a pooled HTTP session."""
        return _PooledSession(self)


class ProviderPool:
    """Connection pool for LLM providers."""

    def __init__(self) -> None:
        self._providers: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    async def register(self, name: str, provider: Any) -> None:
        """Register a provider."""
        async with self._lock:
            self._providers[name] = provider
            logger.debug("Registered LLM provider: {}", name)

    async def get(self, name: str) -> Any | None:
        """Get a provider by name."""
        return self._providers.get(name)

    async def close_all(self) -> None:
        """Close all provider connections."""
        for name, provider in self._providers.items():
            if hasattr(provider, "close"):
                try:
                    await provider.close()
                except Exception as e:
                    logger.warning("Failed to close provider {}: {}", name, e)
        self._providers.clear()
        logger.debug("Closed all LLM provider connections")


_global_http_pool: ConnectionPool | None = None
_global_provider_pool: ProviderPool | None = None


def get_http_pool(
    max_connections: int = 10,
    max_keepalive: int = 20,
    timeout: float = 30.0,
) -> ConnectionPool:
    """Get the global HTTP connection pool."""
    global _global_http_pool
    if _global_http_pool is None:
        _global_http_pool = ConnectionPool(
            max_connections=max_connections,
            max_keepalive=max_keepalive,
            timeout=timeout,
        )
    return _global_http_pool


def get_provider_pool() -> ProviderPool:
    """Get the global provider pool."""
    global _global_provider_pool
    if _global_provider_pool is None:
        _global_provider_pool = ProviderPool()
    return _global_provider_pool
