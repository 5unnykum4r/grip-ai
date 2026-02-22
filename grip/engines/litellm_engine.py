"""LiteLLMRunner — wraps the existing AgentLoop behind EngineProtocol.

This is the FALLBACK engine used for non-Claude models. It creates the full
AgentLoop stack internally (provider, tool registry, optional semantic cache)
and translates between the old AgentRunResult format (with ``total_usage``)
and the new flat ``AgentRunResult`` used by the dual-engine protocol.
"""

from __future__ import annotations

from grip.agent.loop import AgentLoop
from grip.agent.loop import AgentRunResult as OldAgentRunResult
from grip.agent.loop import ToolCallDetail as OldToolCallDetail
from grip.config.schema import GripConfig
from grip.engines.types import AgentRunResult, EngineProtocol, ToolCallDetail
from grip.memory import MemoryManager
from grip.memory.semantic_cache import SemanticCache
from grip.providers.registry import create_provider
from grip.session import SessionManager
from grip.tools import create_default_registry
from grip.trust import TrustManager
from grip.workspace import WorkspaceManager


class LiteLLMRunner(EngineProtocol):
    """EngineProtocol implementation that delegates to the existing AgentLoop.

    The constructor assembles the full AgentLoop dependency graph:
      1. ``create_provider(config)`` -> LLM provider
      2. ``create_default_registry(...)`` -> tool registry
      3. Optionally ``SemanticCache(...)`` if enabled in config
      4. ``AgentLoop(...)`` with all of the above wired together

    Callers interact only via the three EngineProtocol methods (``run``,
    ``consolidate_session``, ``reset_session``). Legacy code that still
    needs the raw loop or registry can access them through the ``loop`` and
    ``registry`` properties.
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

        # Build the LLM provider from the user's config
        provider = create_provider(config)

        # Build the tool registry with any configured MCP servers
        self._registry = create_default_registry(mcp_servers=config.tools.mcp_servers)

        # Optionally create a semantic cache for duplicate-query savings
        cache: SemanticCache | None = None
        defaults = config.agents.defaults
        if defaults.semantic_cache_enabled:
            state_dir = defaults.workspace.expanduser().resolve() / "state"
            cache = SemanticCache(
                state_dir,
                ttl_seconds=defaults.semantic_cache_ttl,
                enabled=True,
            )

        # Wire everything into the AgentLoop
        self._loop = AgentLoop(
            config,
            provider,
            workspace,
            tool_registry=self._registry,
            session_manager=session_mgr,
            memory_manager=memory_mgr,
            semantic_cache=cache,
            trust_manager=trust_mgr,
        )

    # -- Properties for legacy callers --

    @property
    def loop(self) -> AgentLoop:
        """Return the underlying AgentLoop for callers that need direct access."""
        return self._loop

    @property
    def registry(self):
        """Return the tool registry for gateway MessageTool wire-up."""
        return self._registry

    # -- EngineProtocol implementation --

    async def run(
        self,
        user_message: str,
        *,
        session_key: str = "cli:default",
        model: str | None = None,
    ) -> AgentRunResult:
        """Run the agent loop and translate the old result into the new format.

        The old ``AgentRunResult`` (from ``grip.agent.loop``) stores token
        counts inside a nested ``total_usage: TokenUsage`` object. The new
        ``AgentRunResult`` (from ``grip.engines.types``) uses flat
        ``prompt_tokens`` / ``completion_tokens`` fields.
        """
        old_result: OldAgentRunResult = await self._loop.run(
            user_message, session_key=session_key, model=model
        )

        # Translate old ToolCallDetail list to new ToolCallDetail list
        new_details = [
            ToolCallDetail(
                name=d.name,
                success=d.success,
                duration_ms=d.duration_ms,
                output_preview=d.output_preview,
            )
            for d in old_result.tool_details
        ]

        return AgentRunResult(
            response=old_result.response,
            iterations=old_result.iterations,
            prompt_tokens=old_result.total_usage.prompt_tokens,
            completion_tokens=old_result.total_usage.completion_tokens,
            tool_calls_made=old_result.tool_calls_made,
            tool_details=new_details,
        )

    async def consolidate_session(self, session_key: str) -> None:
        """Summarise and compact conversation history for the given session.

        Looks up (or creates) the Session object via the session manager,
        then delegates to the AgentLoop's on-demand consolidation method.
        """
        session = self._session_mgr.get_or_create(session_key)
        await self._loop.consolidate_session(session)

    async def reset_session(self, session_key: str) -> None:
        """Clear all conversation history for a session by deleting it."""
        self._session_mgr.delete(session_key)
