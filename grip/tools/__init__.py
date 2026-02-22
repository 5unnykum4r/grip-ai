from grip.tools.base import Tool, ToolContext, ToolRegistry
from grip.tools.filesystem import create_filesystem_tools
from grip.tools.finance import create_finance_tools
from grip.tools.mcp import MCPManager
from grip.tools.message import create_message_tools
from grip.tools.shell import create_shell_tools
from grip.tools.spawn import SubagentManager, create_spawn_tools
from grip.tools.web import create_web_tools

__all__ = [
    "Tool",
    "ToolContext",
    "ToolRegistry",
    "SubagentManager",
    "create_filesystem_tools",
    "create_finance_tools",
    "create_message_tools",
    "create_shell_tools",
    "create_spawn_tools",
    "create_web_tools",
]


def create_default_registry(
    *,
    workspace_path: str | None = None,
    subagent_manager: SubagentManager | None = None,
    message_callback: object | None = None,
    mcp_servers: dict | None = None,
) -> ToolRegistry:
    """Build a ToolRegistry pre-loaded with all built-in tools."""
    import asyncio

    registry = ToolRegistry()
    registry.register_many(create_filesystem_tools())
    registry.register_many(create_shell_tools())
    registry.register_many(create_web_tools())
    registry.register_many(create_message_tools(message_callback))
    registry.register_many(create_spawn_tools(subagent_manager))
    registry.register_many(create_finance_tools())

    if mcp_servers:
        mcp_manager = MCPManager()
        try:
            import asyncio
            import threading

            def _load_mcp():
                try:
                    new_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(new_loop)
                    new_loop.run_until_complete(mcp_manager.connect_all(mcp_servers, registry))
                except Exception:
                    pass  # Silently ignore MCP failures

            thread = threading.Thread(target=_load_mcp, daemon=True)
            thread.start()
        except Exception:
            pass  # Silently ignore MCP failures - don't break the agent

    return registry
