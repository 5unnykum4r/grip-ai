"""SDKRunner — EngineProtocol implementation using claude_agent_sdk.query().

This is the PRIMARY engine for Claude models. It delegates all tool execution,
agentic looping, and context management to the Claude Agent SDK. Grip handles:
  - System prompt assembly (identity files, memory, skills)
  - Custom tools (send_message, send_file, remember, recall)
  - MCP server config translation from grip format to SDK format
  - History persistence via MemoryManager
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from loguru import logger

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    query,
    tool,
)

from grip.engines.sdk_hooks import (
    build_post_tool_use_hook,
    build_pre_tool_use_hook,
    build_stop_hook,
)
from grip.engines.types import AgentRunResult, EngineProtocol
from grip.skills.loader import SkillsLoader

if TYPE_CHECKING:
    from grip.config.schema import GripConfig
    from grip.memory import MemoryManager
    from grip.session import SessionManager
    from grip.trust import TrustManager
    from grip.workspace import WorkspaceManager


class SDKRunner(EngineProtocol):
    """EngineProtocol implementation that uses claude_agent_sdk.query() for agentic runs.

    Unlike LiteLLMRunner (which wraps the internal AgentLoop), SDKRunner delegates
    the full agent loop to the Claude Agent SDK. Grip only provides the system
    prompt, custom tools, and MCP server configuration.
    """

    def __init__(
        self,
        config: GripConfig,
        workspace: WorkspaceManager,
        session_mgr: SessionManager,
        memory_mgr: MemoryManager,
        trust_mgr: TrustManager | None = None,
    ) -> None:
        self._config = config
        self._workspace = workspace
        self._session_mgr = session_mgr
        self._memory_mgr = memory_mgr
        self._trust_mgr = trust_mgr

        # Resolve ANTHROPIC_API_KEY: config providers take priority, then env var
        api_key = ""
        anthropic_provider = config.providers.get("anthropic")
        if anthropic_provider:
            api_key = anthropic_provider.api_key
        if not api_key:
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if api_key:
            os.environ["ANTHROPIC_API_KEY"] = api_key

        defaults = config.agents.defaults
        self._model: str = defaults.sdk_model
        self._permission_mode: str = defaults.sdk_permission_mode
        self._cwd: str = str(workspace.root)
        self._mcp_servers = config.tools.mcp_servers
        self._clients: dict[str, Any] = {}
        self._send_callback: Callable | None = None
        self._send_file_callback: Callable | None = None

    # -- Callback wiring (called by gateway to route messages to channels) --

    def set_send_callback(self, callback: Callable) -> None:
        """Register the callback for send_message tool invocations."""
        self._send_callback = callback

    def set_send_file_callback(self, callback: Callable) -> None:
        """Register the callback for send_file tool invocations."""
        self._send_file_callback = callback

    # -- MCP config translation --

    def _build_mcp_config(self) -> list[dict[str, Any]]:
        """Convert grip MCPServerConfig entries to SDK-compatible dicts.

        URL-based servers produce: {"name": ..., "url": ..., "headers": ...}
        Stdio-based servers produce: {"name": ..., "command": ..., "args": ..., "env": ...}
        """
        result: list[dict[str, Any]] = []
        for name, srv in self._mcp_servers.items():
            if srv.url:
                result.append({
                    "name": name,
                    "url": srv.url,
                    "headers": dict(srv.headers),
                })
            elif srv.command:
                result.append({
                    "name": name,
                    "command": srv.command,
                    "args": list(srv.args),
                    "env": dict(srv.env),
                })
        return result

    # -- System prompt assembly --

    def _build_system_prompt(self, user_message: str, session_key: str) -> str:
        """Assemble the system prompt from identity files, memory, skills, and metadata.

        Parts are joined with markdown horizontal rules for clear separation.
        Missing identity files are silently skipped.
        """
        parts: list[str] = []

        # Load identity files (AGENT.md, IDENTITY.md, SOUL.md, USER.md)
        identity_files = self._workspace.read_identity_files()
        for filename, content in identity_files.items():
            parts.append(f"## {filename}\n\n{content}")

        # Search long-term memory for relevant facts
        memory_results = self._memory_mgr.search_memory(user_message, max_results=5)
        if memory_results:
            memory_text = "\n".join(f"- {fact}" for fact in memory_results)
            parts.append(f"## Relevant Memory\n\n{memory_text}")

        # Search conversation history for relevant past interactions
        history_results = self._memory_mgr.search_history(user_message, max_results=5)
        if history_results:
            history_text = "\n".join(f"- {entry}" for entry in history_results)
            parts.append(f"## Relevant History\n\n{history_text}")

        # Load available skills and list their names + descriptions
        try:
            loader = SkillsLoader(self._workspace.root)
            skills = loader.scan()
            if skills:
                skill_lines = [f"- **{s.name}**: {s.description}" for s in skills]
                parts.append(f"## Available Skills\n\n" + "\n".join(skill_lines))
        except Exception as exc:
            logger.debug("Failed to load skills for system prompt: {}", exc)

        # Runtime metadata
        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        metadata = (
            f"## Runtime Metadata\n\n"
            f"- **Date/Time**: {now}\n"
            f"- **Session**: {session_key}\n"
            f"- **Workspace**: {self._cwd}"
        )
        parts.append(metadata)

        return "\n\n---\n\n".join(parts)

    # -- Custom tool definitions --

    def _build_custom_tools(self) -> list:
        """Build the list of custom tool functions for the SDK agent.

        Returns decorated callables that the SDK will expose as tools:
          - send_message: Route a text message through the gateway callback
          - send_file: Route a file through the gateway callback
          - remember: Store a fact in long-term memory
          - recall: Search long-term memory for matching facts
          - stock_quote: (optional) Fetch stock price if yfinance is installed
        """
        tools: list = []

        # Capture references for closures
        send_cb = self._send_callback
        send_file_cb = self._send_file_callback
        memory_mgr = self._memory_mgr

        # -- Keep references to self for dynamic callback lookup --
        runner = self

        @tool
        def send_message(text: str, session_key: str) -> str:
            """Send a text message to the user via the configured channel."""
            cb = runner._send_callback
            if cb is None:
                return "Send callback not configured; message not delivered."
            return cb(text, session_key)

        @tool
        def send_file(file_path: str, caption: str, session_key: str) -> str:
            """Send a file to the user via the configured channel."""
            cb = runner._send_file_callback
            if cb is None:
                return "Send file callback not configured; file not delivered."
            return cb(file_path, caption, session_key)

        @tool
        def remember(fact: str, category: str) -> str:
            """Store a fact in long-term memory for future recall."""
            entry = f"- [{category}] {fact}"
            memory_mgr.append_to_memory(entry)
            return f"Stored fact under category '{category}'."

        @tool
        def recall(query_text: str) -> str:
            """Search long-term memory for facts matching the query."""
            results = memory_mgr.search_memory(query_text, max_results=10)
            if not results:
                return "No matching facts found in memory."
            return "\n".join(results)

        tools.extend([send_message, send_file, remember, recall])

        # Optional stock_quote tool (only if yfinance is available)
        try:
            import yfinance  # noqa: F401

            @tool
            def stock_quote(symbol: str) -> str:
                """Fetch the current stock price for a given ticker symbol."""
                import yfinance as yf

                ticker = yf.Ticker(symbol)
                info = ticker.info
                price = info.get("currentPrice") or info.get("regularMarketPrice", "N/A")
                name = info.get("shortName", symbol)
                return f"{name} ({symbol}): ${price}"

            tools.append(stock_quote)
        except ImportError:
            pass

        return tools

    # -- EngineProtocol implementation --

    async def run(
        self,
        user_message: str,
        *,
        session_key: str = "cli:default",
        model: str | None = None,
    ) -> AgentRunResult:
        """Send a user message through the Claude Agent SDK and return the result.

        Streams messages from claude_agent_sdk.query(), collecting assistant text
        and tool call names. Persists the exchange to history via MemoryManager.
        """
        system_prompt = self._build_system_prompt(user_message, session_key)
        custom_tools = self._build_custom_tools()
        mcp_config = self._build_mcp_config()

        effective_model = model or self._model

        pre_hook = build_pre_tool_use_hook(
            Path(self._cwd), self._trust_mgr
        )
        post_hook = build_post_tool_use_hook()
        stop_hook = build_stop_hook(self._memory_mgr)

        options = ClaudeAgentOptions(
            model=effective_model,
            system_prompt=system_prompt,
            tools=custom_tools,
            mcp_servers=mcp_config,
            permission_mode=self._permission_mode,
            cwd=self._cwd,
            hooks={
                "pre_tool_use": pre_hook,
                "post_tool_use": post_hook,
                "stop": stop_hook,
            },
        )

        response_parts: list[str] = []
        tool_calls_made: list[str] = []

        async for message in query(prompt=user_message, options=options):
            if isinstance(message, AssistantMessage):
                for block in getattr(message, "content", []):
                    if hasattr(block, "text"):
                        response_parts.append(block.text)
                    if hasattr(block, "name"):
                        tool_calls_made.append(block.name)
            elif isinstance(message, ResultMessage):
                for block in getattr(message, "content", []):
                    if hasattr(block, "text"):
                        response_parts.append(block.text)

        response_text = "\n".join(response_parts) if response_parts else ""

        # Persist user message and agent response to conversation history
        self._memory_mgr.append_history(f"User ({session_key}): {user_message[:200]}")
        self._memory_mgr.append_history(f"Agent ({session_key}): {response_text[:200]}")

        return AgentRunResult(
            response=response_text,
            tool_calls_made=tool_calls_made,
        )

    async def consolidate_session(self, session_key: str) -> None:
        """No-op for SDK engine: the SDK manages its own context window internally.

        Logged for observability so operators can see when consolidation was requested.
        """
        logger.info("consolidate_session called for '{}' (SDK handles context internally)", session_key)

    async def reset_session(self, session_key: str) -> None:
        """Clear all state for a session: remove SDK client and delete persisted session."""
        self._clients.pop(session_key, None)
        self._session_mgr.delete(session_key)
        logger.info("Reset session '{}'", session_key)
