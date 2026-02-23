"""Tests for grip.tools.mcp — MCP connection and transport routing."""

from __future__ import annotations

import importlib.util
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from grip.config.schema import MCPServerConfig
from grip.tools.mcp import MCPConnection, MCPManager, MCPWrappedTool


class TestMCPConnectionTransportRouting:
    """MCPConnection should pick the right transport based on config.type."""

    def test_http_type_config(self):
        config = MCPServerConfig(url="https://mcp.supabase.com/mcp", type="http")
        conn = MCPConnection("supabase", config)
        assert conn._config.type == "http"
        assert conn._config.url == "https://mcp.supabase.com/mcp"

    def test_sse_type_config(self):
        config = MCPServerConfig(url="https://mcp.example.com/sse", type="sse")
        conn = MCPConnection("test", config)
        assert conn._config.type == "sse"

    def test_empty_type_defaults(self):
        config = MCPServerConfig(url="https://mcp.example.com")
        conn = MCPConnection("test", config)
        assert conn._config.type == ""

    def test_stdio_config(self):
        config = MCPServerConfig(command="npx", args=["-y", "test-mcp"])
        conn = MCPConnection("test", config)
        assert conn._config.command == "npx"
        assert conn._config.url == ""

    @pytest.mark.asyncio
    async def test_http_type_uses_streamable_transport(self):
        config = MCPServerConfig(url="https://mcp.supabase.com/mcp", type="http")
        conn = MCPConnection("supabase", config)

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.initialize = AsyncMock()
        mock_tools = MagicMock()
        mock_tools.tools = []
        mock_session.list_tools = AsyncMock(return_value=mock_tools)

        mock_streams = (MagicMock(), MagicMock(), MagicMock())
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_streams)

        with (
            patch(
                "mcp.client.streamable_http.streamablehttp_client",
                return_value=mock_ctx,
            ) as mock_streamable,
            patch("mcp.ClientSession", return_value=mock_session),
        ):
            await conn._connect_http()

        mock_streamable.assert_called_once_with(
            "https://mcp.supabase.com/mcp",
            headers=None,
            timeout=60.0,
            auth=ANY,
        )
        assert conn.is_connected is True

    @pytest.mark.asyncio
    async def test_sse_type_uses_sse_transport(self):
        config = MCPServerConfig(url="https://mcp.example.com/sse", type="sse")
        conn = MCPConnection("test_sse", config)

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.initialize = AsyncMock()
        mock_tools = MagicMock()
        mock_tools.tools = []
        mock_session.list_tools = AsyncMock(return_value=mock_tools)

        mock_streams = (MagicMock(), MagicMock())
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_streams)

        with (
            patch("mcp.client.sse.sse_client", return_value=mock_ctx) as mock_sse,
            patch("mcp.ClientSession", return_value=mock_session),
        ):
            await conn._connect_http()

        mock_sse.assert_called_once_with(
            "https://mcp.example.com/sse",
            headers=None,
            timeout=60.0,
            auth=ANY,
        )
        assert conn.is_connected is True

    @pytest.mark.asyncio
    async def test_empty_type_uses_sse_transport(self):
        config = MCPServerConfig(url="https://mcp.example.com")
        conn = MCPConnection("test_default", config)

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.initialize = AsyncMock()
        mock_tools = MagicMock()
        mock_tools.tools = []
        mock_session.list_tools = AsyncMock(return_value=mock_tools)

        mock_streams = (MagicMock(), MagicMock())
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_streams)

        with (
            patch("mcp.client.sse.sse_client", return_value=mock_ctx) as mock_sse,
            patch("mcp.ClientSession", return_value=mock_session),
        ):
            await conn._connect_http()

        mock_sse.assert_called_once()
        assert conn.is_connected is True

    @pytest.mark.asyncio
    async def test_http_type_passes_headers(self):
        config = MCPServerConfig(
            url="https://mcp.supabase.com/mcp",
            type="http",
            headers={"Authorization": "Bearer tok123"},
        )
        conn = MCPConnection("supabase_ci", config)

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.initialize = AsyncMock()
        mock_tools = MagicMock()
        mock_tools.tools = []
        mock_session.list_tools = AsyncMock(return_value=mock_tools)

        mock_streams = (MagicMock(), MagicMock(), MagicMock())
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_streams)

        with (
            patch(
                "mcp.client.streamable_http.streamablehttp_client",
                return_value=mock_ctx,
            ) as mock_streamable,
            patch("mcp.ClientSession", return_value=mock_session),
        ):
            await conn._connect_http()

        mock_streamable.assert_called_once_with(
            "https://mcp.supabase.com/mcp",
            headers={"Authorization": "Bearer tok123"},
            timeout=60.0,
            auth=ANY,
        )

    @pytest.mark.asyncio
    async def test_http_type_passes_custom_timeout(self):
        config = MCPServerConfig(
            url="https://mcp.supabase.com/mcp",
            type="http",
            timeout=120,
        )
        conn = MCPConnection("supabase_slow", config)

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.initialize = AsyncMock()
        mock_tools = MagicMock()
        mock_tools.tools = []
        mock_session.list_tools = AsyncMock(return_value=mock_tools)

        mock_streams = (MagicMock(), MagicMock(), MagicMock())
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_streams)

        with (
            patch(
                "mcp.client.streamable_http.streamablehttp_client",
                return_value=mock_ctx,
            ) as mock_streamable,
            patch("mcp.ClientSession", return_value=mock_session),
        ):
            await conn._connect_http()

        mock_streamable.assert_called_once_with(
            "https://mcp.supabase.com/mcp",
            headers=None,
            timeout=120.0,
            auth=ANY,
        )


class TestMCPConnectionStatus:
    def test_initial_state(self):
        config = MCPServerConfig(url="https://mcp.supabase.com/mcp", type="http")
        conn = MCPConnection("supabase", config)
        assert conn.is_connected is False
        assert conn.error == ""
        assert conn.tools == []

    @pytest.mark.asyncio
    async def test_no_mcp_package_returns_empty(self):
        config = MCPServerConfig(url="https://mcp.supabase.com/mcp", type="http")
        conn = MCPConnection("supabase", config)

        with patch.object(importlib.util, "find_spec", return_value=None):
            result = await conn.connect()

        assert result == []
        assert conn.is_connected is False

    @pytest.mark.asyncio
    async def test_connection_error_sets_error_state(self):
        config = MCPServerConfig(url="https://mcp.supabase.com/mcp", type="http")
        conn = MCPConnection("supabase", config)

        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(side_effect=ConnectionError("refused"))

        with patch(
            "mcp.client.streamable_http.streamablehttp_client",
            return_value=mock_ctx,
        ):
            result = await conn._connect_http()

        assert result == []
        assert conn.is_connected is False
        assert "refused" in conn.error


class TestMCPManagerDisabledServers:
    @pytest.mark.asyncio
    async def test_skips_disabled_supabase(self):
        config = MCPServerConfig(
            url="https://mcp.supabase.com/mcp",
            type="http",
            enabled=False,
        )
        registry = MagicMock()
        mgr = MCPManager()
        total = await mgr.connect_all({"supabase": config}, registry)
        assert total == 0
        assert mgr.get_connection("supabase") is None


class TestMCPManagerReconnectServer:
    """MCPManager.reconnect_server() disconnects old, connects new, registers tools."""

    @pytest.mark.asyncio
    async def test_reconnect_registers_tools_in_registry(self):
        from grip.tools.base import ToolRegistry

        config = MCPServerConfig(url="https://mcp.supabase.com/mcp", type="http")
        registry = ToolRegistry()
        mgr = MCPManager()
        mgr._registry = registry

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.initialize = AsyncMock()
        mock_tool = MagicMock()
        mock_tool.name = "list_tables"
        mock_tool.description = "List tables"
        mock_tool.inputSchema = {"type": "object", "properties": {}}
        mock_tools = MagicMock()
        mock_tools.tools = [mock_tool]
        mock_session.list_tools = AsyncMock(return_value=mock_tools)

        mock_streams = (MagicMock(), MagicMock(), MagicMock())
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_streams)

        with (
            patch(
                "mcp.client.streamable_http.streamablehttp_client",
                return_value=mock_ctx,
            ),
            patch("mcp.ClientSession", return_value=mock_session),
        ):
            tools = await mgr.reconnect_server("supabase", config)

        assert len(tools) == 1
        assert tools[0].name == "mcp_supabase_list_tables"
        assert registry.get("mcp_supabase_list_tables") is not None
        conn = mgr.get_connection("supabase")
        assert conn is not None
        assert conn.is_connected is True

    @pytest.mark.asyncio
    async def test_reconnect_disconnects_old_connection(self):
        from grip.tools.base import ToolRegistry

        config = MCPServerConfig(url="https://mcp.supabase.com/mcp", type="http")
        registry = ToolRegistry()
        mgr = MCPManager()
        mgr._registry = registry

        old_conn = MagicMock()
        old_conn.disconnect = AsyncMock()
        old_tool = MagicMock()
        old_tool.name = "mcp_supabase_old_tool"
        old_conn.tools = [old_tool]
        mgr._connections["supabase"] = old_conn
        registry.register(MagicMock(name="mcp_supabase_old_tool"))

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.initialize = AsyncMock()
        mock_tools = MagicMock()
        mock_tools.tools = []
        mock_session.list_tools = AsyncMock(return_value=mock_tools)

        mock_streams = (MagicMock(), MagicMock(), MagicMock())
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_streams)

        with (
            patch(
                "mcp.client.streamable_http.streamablehttp_client",
                return_value=mock_ctx,
            ),
            patch("mcp.ClientSession", return_value=mock_session),
        ):
            await mgr.reconnect_server("supabase", config)

        old_conn.disconnect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reconnect_without_registry_returns_empty(self):
        config = MCPServerConfig(url="https://mcp.supabase.com/mcp", type="http")
        mgr = MCPManager()
        tools = await mgr.reconnect_server("supabase", config)
        assert tools == []

    @pytest.mark.asyncio
    async def test_registry_stores_mcp_manager(self):
        from grip.tools.base import ToolRegistry

        registry = ToolRegistry()
        assert registry.mcp_manager is None

        mgr = MCPManager()
        registry.mcp_manager = mgr
        assert registry.mcp_manager is mgr


class TestSupabasePreset:
    def test_preset_exists(self):
        from grip.cli.mcp_cmd import MCP_PRESETS

        assert "supabase" in MCP_PRESETS

    def test_preset_config(self):
        from grip.cli.mcp_cmd import MCP_PRESETS

        preset = MCP_PRESETS["supabase"]
        assert preset["url"] == "https://mcp.supabase.com/mcp"
        assert preset["type"] == "http"

    def test_preset_creates_valid_mcp_server_config(self):
        from grip.cli.mcp_cmd import MCP_PRESETS

        config = MCPServerConfig(**MCP_PRESETS["supabase"])
        assert config.url == "https://mcp.supabase.com/mcp"
        assert config.type == "http"
        assert config.enabled is True
        assert config.timeout == 60


class TestMCPConnectionOAuthAuth:
    """MCPConnection._build_oauth_auth() creates OAuthClientProvider."""

    def test_build_oauth_auth_returns_none_without_stored_tokens(self):
        config = MCPServerConfig(url="https://mcp.supabase.com/mcp", type="http")
        conn = MCPConnection("supabase", config)
        auth = conn._build_oauth_auth()
        assert auth is None

    def test_build_oauth_auth_returns_none_with_force_oauth_but_no_token(self):
        """force_oauth alone should not create a provider — only stored tokens do."""
        config = MCPServerConfig(url="https://mcp.supabase.com/mcp", type="http")
        conn = MCPConnection("supabase", config, force_oauth=True)
        auth = conn._build_oauth_auth()
        assert auth is None

    @pytest.mark.asyncio
    async def test_build_oauth_auth_returns_provider_with_stored_token(self):
        from mcp.client.auth import OAuthClientProvider
        from mcp.shared.auth import OAuthToken

        from grip.tools.mcp_auth import MCPTokenStorage

        storage = MCPTokenStorage("test_oauth_srv")
        await storage.set_tokens(OAuthToken(access_token="tok123"))

        config = MCPServerConfig(url="https://mcp.example.com/mcp", type="http")
        conn = MCPConnection("test_oauth_srv", config)
        auth = conn._build_oauth_auth()
        assert isinstance(auth, OAuthClientProvider)

    @pytest.mark.asyncio
    async def test_build_oauth_auth_uses_custom_redirect_port(self):
        from mcp.shared.auth import OAuthToken

        from grip.config.schema import OAuthConfig
        from grip.tools.mcp_auth import MCPTokenStorage

        storage = MCPTokenStorage("test_port_srv")
        await storage.set_tokens(OAuthToken(access_token="tok456"))

        config = MCPServerConfig(
            url="https://mcp.example.com/mcp",
            type="http",
            oauth=OAuthConfig(redirect_port=19999),
        )
        conn = MCPConnection("test_port_srv", config)
        auth = conn._build_oauth_auth()
        assert auth is not None

    @pytest.mark.asyncio
    async def test_http_connect_passes_oauth_auth_when_token_stored(self):
        from mcp.shared.auth import OAuthToken

        from grip.tools.mcp_auth import MCPTokenStorage

        storage = MCPTokenStorage("supabase_connect_test")
        await storage.set_tokens(OAuthToken(access_token="stored_tok"))

        config = MCPServerConfig(url="https://mcp.supabase.com/mcp", type="http")
        conn = MCPConnection("supabase_connect_test", config)

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.initialize = AsyncMock()
        mock_tools = MagicMock()
        mock_tools.tools = []
        mock_session.list_tools = AsyncMock(return_value=mock_tools)

        mock_streams = (MagicMock(), MagicMock(), MagicMock())
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_streams)

        with (
            patch(
                "mcp.client.streamable_http.streamablehttp_client",
                return_value=mock_ctx,
            ) as mock_streamable,
            patch("mcp.ClientSession", return_value=mock_session),
        ):
            await conn._connect_http()

        call_kwargs = mock_streamable.call_args.kwargs
        assert "auth" in call_kwargs
        assert call_kwargs["auth"] is not None

    @pytest.mark.asyncio
    async def test_http_connect_passes_none_auth_without_tokens(self):
        config = MCPServerConfig(url="https://mcp.supabase.com/mcp", type="http")
        conn = MCPConnection("supabase", config)

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.initialize = AsyncMock()
        mock_tools = MagicMock()
        mock_tools.tools = []
        mock_session.list_tools = AsyncMock(return_value=mock_tools)

        mock_streams = (MagicMock(), MagicMock(), MagicMock())
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_streams)

        with (
            patch(
                "mcp.client.streamable_http.streamablehttp_client",
                return_value=mock_ctx,
            ) as mock_streamable,
            patch("mcp.ClientSession", return_value=mock_session),
        ):
            await conn._connect_http()

        call_kwargs = mock_streamable.call_args.kwargs
        assert call_kwargs["auth"] is None


class TestMCPWrappedToolBasics:
    def test_tool_naming(self):
        tool = MCPWrappedTool(
            tool_name="execute_sql",
            tool_description="Execute SQL against Supabase",
            tool_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            server_name="supabase",
            call_fn=AsyncMock(),
        )
        assert tool.name == "mcp_supabase_execute_sql"
        assert tool.category == "mcp"
        assert "MCP:supabase" in tool.description

    def test_tool_parameters(self):
        schema = {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "SQL query to execute"},
            },
            "required": ["query"],
        }
        tool = MCPWrappedTool(
            tool_name="execute_sql",
            tool_description="Execute SQL",
            tool_schema=schema,
            server_name="supabase",
            call_fn=AsyncMock(),
        )
        assert tool.parameters == schema
        assert tool.parameters["properties"]["query"]["type"] == "string"
