"""Tests for connection pool lifecycle management."""

from __future__ import annotations

import pytest

from grip.pool import (
    get_http_pool,
    get_provider_pool,
    shutdown_pools,
)


class TestPoolLifecycle:
    def test_get_http_pool_returns_same_instance(self):
        pool1 = get_http_pool()
        pool2 = get_http_pool()
        assert pool1 is pool2

    def test_get_provider_pool_returns_same_instance(self):
        pool1 = get_provider_pool()
        pool2 = get_provider_pool()
        assert pool1 is pool2

    @pytest.mark.asyncio
    async def test_shutdown_pools_resets_globals(self):
        import grip.pool as pool_module

        get_http_pool()
        get_provider_pool()
        assert pool_module._global_http_pool is not None
        assert pool_module._global_provider_pool is not None

        await shutdown_pools()
        assert pool_module._global_http_pool is None
        assert pool_module._global_provider_pool is None
