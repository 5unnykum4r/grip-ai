"""MCP (Model Context Protocol) client integration.

Connects to MCP servers defined in config.tools.mcp_servers, discovers
their tools, and wraps them as grip Tool instances for the ToolRegistry.

Supports two transports:
  - stdio: spawn a subprocess (command + args)
  - HTTP/SSE: connect to a URL endpoint

Falls back gracefully if the mcp package is not installed.
"""

from __future__ import annotations

import contextlib
import json
from typing import Any

from loguru import logger

from grip.config.schema import MCPServerConfig
from grip.tools.base import Tool, ToolContext, ToolRegistry


class MCPWrappedTool(Tool):
    """A grip Tool that delegates execution to an MCP server tool.

    Category defaults to 'mcp' but can be overridden per-server.
    """

    def __init__(
        self,
        tool_name: str,
        tool_description: str,
        tool_schema: dict[str, Any],
        server_name: str,
        call_fn: Any,
    ) -> None:
        self._name = f"mcp_{server_name}_{tool_name}"
        self._raw_name = tool_name
        self._description = tool_description
        self._parameters = tool_schema
        self._server_name = server_name
        self._call_fn = call_fn

    @property
    def category(self) -> str:
        return "mcp"

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"[MCP:{self._server_name}] {self._description}"

    @property
    def parameters(self) -> dict[str, Any]:
        return self._parameters

    async def execute(self, params: dict[str, Any], ctx: ToolContext) -> str:
        try:
            result = await self._call_fn(self._raw_name, params)
            if isinstance(result, str):
                return result
            return json.dumps(result, indent=2, default=str)
        except Exception as exc:
            return f"Error calling MCP tool '{self._raw_name}' on '{self._server_name}': {exc}"


class MCPConnection:
    """Manages a single MCP server connection (stdio or HTTP)."""

    def __init__(self, server_name: str, config: MCPServerConfig) -> None:
        self.server_name = server_name
        self._config = config
        self._session = None
        self._read_stream = None
        self._write_stream = None
        self._process = None
        self._tools: list[MCPWrappedTool] = []

    @property
    def tools(self) -> list[MCPWrappedTool]:
        return list(self._tools)

    async def connect(self) -> list[MCPWrappedTool]:
        """Connect to the MCP server and discover available tools."""
        import importlib.util

        if importlib.util.find_spec("mcp") is None:
            logger.warning("MCP package not installed. Install with: pip install mcp>=1.0")
            return []

        if self._config.url:
            return await self._connect_http()
        elif self._config.command:
            return await self._connect_stdio()
        else:
            logger.error("MCP server '{}' has no command or url configured", self.server_name)
            return []

    async def _connect_stdio(self) -> list[MCPWrappedTool]:
        """Connect via stdio transport (spawn subprocess)."""
        try:
            from mcp import ClientSession
            from mcp.client.stdio import StdioServerParameters, stdio_client

            params = StdioServerParameters(
                command=self._config.command,
                args=self._config.args,
                env=self._config.env if self._config.env else None,
            )

            self._read_stream, self._write_stream = await stdio_client(params).__aenter__()
            self._session = ClientSession(self._read_stream, self._write_stream)
            await self._session.__aenter__()
            await self._session.initialize()

            tools_response = await self._session.list_tools()
            return self._wrap_tools(tools_response.tools)

        except Exception as exc:
            logger.error("Failed to connect stdio MCP '{}': {}", self.server_name, exc)
            return []

    async def _connect_http(self) -> list[MCPWrappedTool]:
        """Connect via HTTP/SSE transport."""
        try:
            from mcp import ClientSession
            from mcp.client.sse import sse_client

            headers = self._config.headers if self._config.headers else None
            self._read_stream, self._write_stream = await sse_client(
                self._config.url,
                headers=headers,
            ).__aenter__()
            self._session = ClientSession(self._read_stream, self._write_stream)
            await self._session.__aenter__()
            await self._session.initialize()

            tools_response = await self._session.list_tools()
            return self._wrap_tools(tools_response.tools)

        except Exception as exc:
            logger.error("Failed to connect HTTP MCP '{}': {}", self.server_name, exc)
            return []

    def _wrap_tools(self, mcp_tools) -> list[MCPWrappedTool]:
        """Convert MCP tool definitions into grip Tool wrappers."""
        self._tools = []
        for tool in mcp_tools:
            schema = (
                tool.inputSchema
                if hasattr(tool, "inputSchema")
                else {"type": "object", "properties": {}}
            )
            wrapped = MCPWrappedTool(
                tool_name=tool.name,
                tool_description=getattr(tool, "description", tool.name),
                tool_schema=schema,
                server_name=self.server_name,
                call_fn=self._call_tool,
            )
            self._tools.append(wrapped)
            logger.debug("Discovered MCP tool: {}.{}", self.server_name, tool.name)

        logger.info("MCP '{}': {} tools discovered", self.server_name, len(self._tools))
        return self._tools

    async def _call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Execute a tool call on the connected MCP server."""
        if not self._session:
            raise RuntimeError(f"MCP session '{self.server_name}' not connected")
        result = await self._session.call_tool(tool_name, arguments)
        # MCP returns content blocks; extract text
        texts = []
        for block in result.content:
            if hasattr(block, "text"):
                texts.append(block.text)
        return "\n".join(texts) if texts else str(result.content)

    async def disconnect(self) -> None:
        """Close the MCP session and underlying transport."""
        if self._session:
            with contextlib.suppress(Exception):
                await self._session.__aexit__(None, None, None)
        logger.debug("MCP '{}' disconnected", self.server_name)


class MCPManager:
    """Manages all MCP server connections and their lifecycle."""

    def __init__(self) -> None:
        self._connections: dict[str, MCPConnection] = {}

    async def connect_all(
        self,
        mcp_servers: dict[str, MCPServerConfig],
        registry: ToolRegistry,
    ) -> int:
        """Connect to all configured MCP servers and register their tools.

        Returns the total number of MCP tools registered.
        """
        total_tools = 0

        for server_name, server_config in mcp_servers.items():
            conn = MCPConnection(server_name, server_config)
            tools = await conn.connect()
            self._connections[server_name] = conn

            for tool in tools:
                registry.register(tool)
                total_tools += 1

        if total_tools:
            logger.info(
                "MCP: {} tools registered from {} servers", total_tools, len(self._connections)
            )
        return total_tools

    async def disconnect_all(self) -> None:
        """Disconnect from all MCP servers."""
        for conn in self._connections.values():
            await conn.disconnect()
        self._connections.clear()

    @property
    def server_count(self) -> int:
        return len(self._connections)

    def get_connection(self, server_name: str) -> MCPConnection | None:
        return self._connections.get(server_name)
