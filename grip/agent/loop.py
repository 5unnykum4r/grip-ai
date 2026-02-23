"""Core agent execution loop.

The AgentLoop is the beating heart of grip. It orchestrates the
iterative cycle of:

  1. Send conversation + tool definitions to the LLM
  2. If LLM returns tool_calls -> execute each tool -> append results -> goto 1
  3. If LLM returns plain text -> return it as the final answer
  4. Safety: stop after max_tool_iterations (0 = unlimited) to prevent infinite loops

Mid-run compaction: when the in-flight message list exceeds 50 non-system
messages, older messages are summarized and replaced with a compact block,
preventing context overflow on long multi-step tasks.

The loop is fully async and designed to be called from the CLI,
REST API, or gateway message bus. It integrates with ToolRegistry
for tool execution, SessionManager for history, and MemoryManager
for long-term fact storage.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from grip.agent.context import ContextBuilder
from grip.agent.router import ModelTiers, classify_complexity, select_model
from grip.config.schema import GripConfig
from grip.memory.manager import MemoryManager
from grip.memory.semantic_cache import SemanticCache
from grip.providers.types import LLMMessage, LLMProvider, LLMResponse, TokenUsage, ToolCall
from grip.session.manager import Session, SessionManager
from grip.tools.base import ToolContext, ToolRegistry
from grip.workspace.manager import WorkspaceManager


@dataclass(slots=True)
class ToolExecutionResult:
    """Result from executing a single tool call."""

    tool_call_id: str
    tool_name: str
    output: str
    success: bool = True
    duration_ms: float = 0.0


@dataclass(slots=True)
class ToolCallDetail:
    """Per-tool-call detail for the run result."""

    name: str
    success: bool
    duration_ms: float
    output_preview: str = ""


@dataclass(slots=True)
class AgentRunResult:
    """Complete result of an agent run including the final response and metrics."""

    response: str
    iterations: int
    total_usage: TokenUsage = field(default_factory=TokenUsage)
    tool_calls_made: list[str] = field(default_factory=list)
    tool_details: list[ToolCallDetail] = field(default_factory=list)


# Kept for backward compatibility with Phase 2 API
ToolExecutor = Callable[[str, dict[str, Any]], Awaitable[str]]

# Mid-run compaction thresholds
_COMPACT_THRESHOLD = 50  # compact when non-system messages exceed this
_COMPACT_KEEP_RECENT = 20  # keep this many recent messages after compaction

# Credential scrubbing: redact common secret patterns from tool outputs
_SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(sk-[A-Za-z0-9]{20,})", re.IGNORECASE), "[REDACTED_API_KEY]"),
    (re.compile(r"(ghp_[A-Za-z0-9]{36,})", re.IGNORECASE), "[REDACTED_GH_TOKEN]"),
    (re.compile(r"(xox[baprs]-[0-9A-Za-z\-]{10,})", re.IGNORECASE), "[REDACTED_SLACK_TOKEN]"),
    (re.compile(r"(Bearer\s+)[A-Za-z0-9\-_.~+/]{20,}=*", re.IGNORECASE), r"\1[REDACTED_TOKEN]"),
    (re.compile(r"(password[\"'\s:=]+)[^\s,}\"'\n]{6,}", re.IGNORECASE), r"\1[REDACTED]"),
]


def _scrub_secrets(text: str) -> str:
    """Redact high-confidence secret patterns before storing in message history."""
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class AgentLoop:
    """Orchestrates the LLM <-> tool execution cycle.

    Full integration usage (Phase 3+4):
        registry = create_default_registry()
        session_mgr = SessionManager(workspace / "sessions")
        memory_mgr = MemoryManager(workspace)

        loop = AgentLoop(config, provider, workspace_mgr,
                         tool_registry=registry,
                         session_manager=session_mgr,
                         memory_manager=memory_mgr)
        result = await loop.run("Hello", session_key="cli:user")

    Minimal usage (Phase 2 API still works):
        loop = AgentLoop(config, provider, workspace_mgr)
        loop.set_tool_executor(my_executor)
        result = await loop.run("Hello")
    """

    def __init__(
        self,
        config: GripConfig,
        provider: LLMProvider,
        workspace: WorkspaceManager,
        *,
        tool_registry: ToolRegistry | None = None,
        session_manager: SessionManager | None = None,
        memory_manager: MemoryManager | None = None,
        semantic_cache: SemanticCache | None = None,
        trust_manager: Any | None = None,
        knowledge_base: Any | None = None,
    ) -> None:
        self._config = config
        self._provider = provider
        self._workspace = workspace
        self._context_builder = ContextBuilder(workspace, channels=config.channels)
        self._registry = tool_registry
        self._session_mgr = session_manager
        self._memory_mgr = memory_manager
        self._semantic_cache = semantic_cache
        self._trust_manager = trust_manager
        self._kb = knowledge_base

        # Phase 2 compat: manual tool definitions + executor
        self._tool_definitions: list[dict[str, Any]] = []
        self._tool_executor: ToolExecutor | None = None

    # ── Phase 2 backward-compatible setters ──

    def set_tool_definitions(self, definitions: list[dict[str, Any]]) -> None:
        """Register tool JSON schemas that will be sent to the LLM."""
        self._tool_definitions = definitions
        self._context_builder.invalidate_cache()

    def set_tool_executor(self, executor: ToolExecutor) -> None:
        """Register a callback that executes tool calls (Phase 2 API)."""
        self._tool_executor = executor

    # ── Derived properties ──

    def _get_tool_definitions(self) -> list[dict[str, Any]]:
        """Return tool definitions from registry (preferred) or manual list."""
        if self._registry:
            return self._registry.get_definitions()
        return self._tool_definitions

    def _build_tool_context(self, session_key: str) -> ToolContext:
        defaults = self._config.agents.defaults
        tools_cfg = self._config.tools
        workspace_path = defaults.workspace.expanduser().resolve()

        extra: dict[str, Any] = {}
        if tools_cfg.web.brave.enabled and tools_cfg.web.brave.api_key.get_secret_value():
            extra["brave_api_key"] = tools_cfg.web.brave.api_key.get_secret_value()
        if defaults.dry_run:
            extra["dry_run"] = True
        if self._trust_manager is not None and tools_cfg.trust_mode != "trust_all":
            extra["trust_manager"] = self._trust_manager

        return ToolContext(
            workspace_path=workspace_path,
            restrict_to_workspace=tools_cfg.restrict_to_workspace,
            shell_timeout=tools_cfg.shell_timeout,
            session_key=session_key,
            extra=extra,
        )

    # ── Main entry point ──

    async def run(
        self,
        user_message: str,
        *,
        session_key: str = "cli:default",
        session_messages: list[LLMMessage] | None = None,
        model: str | None = None,
    ) -> AgentRunResult:
        """Execute a full agent run for a single user message.

        When session_manager is available, automatically loads/saves session
        history and triggers memory consolidation when needed.
        """
        defaults = self._config.agents.defaults

        # Cost-aware model routing: classify complexity and select model tier
        if model:
            effective_model = model
        elif self._config.agents.model_tiers.enabled:
            tiers_cfg = self._config.agents.model_tiers
            session_tool_count = sum(len(m.tool_calls) for m in (session_messages or []) if m.tool_calls)
            complexity = classify_complexity(
                user_message,
                tool_calls_in_session=session_tool_count,
            )
            effective_model = select_model(
                defaults.model,
                ModelTiers(low=tiers_cfg.low, medium=tiers_cfg.medium, high=tiers_cfg.high),
                complexity,
            )
        else:
            effective_model = defaults.model

        # Check semantic cache for an identical recent query
        if self._semantic_cache:
            cached = self._semantic_cache.get(user_message, effective_model)
            if cached is not None:
                logger.info("Semantic cache hit — returning cached response")
                self._persist_session(
                    self._session_mgr.get_or_create(session_key) if self._session_mgr else None,
                    user_message,
                    cached,
                )
                return AgentRunResult(
                    response=cached,
                    iterations=0,
                    total_usage=TokenUsage(),
                    tool_calls_made=[],
                )

        # Limit massive token injection by capping immediate message history.
        # Ensure we always keep an even number so User/Assistant pairs stay balanced
        immediate_window = min(defaults.memory_window, 10)

        session: Session | None = None
        session_summary: str | None = None

        if self._session_mgr:
            session = self._session_mgr.get_or_create(session_key)
            history = session.get_recent(immediate_window)
            session_summary = session.summary
        elif session_messages:
            history = session_messages[-immediate_window:]
        else:
            history = []

        tool_defs = self._get_tool_definitions()

        system_msg = self._context_builder.build_system_message(
            user_message=user_message,
            session_key=session_key,
        )

        messages: list[LLMMessage] = [system_msg]

        # Inject consolidated summary from previous conversations
        if session_summary:
            messages.append(
                LLMMessage(
                    role="system",
                    content=session_summary,
                )
            )

        # Infinite context: retrieve relevant facts from long-term memory
        # based on the current query. Injects targeted historical knowledge
        # without loading the entire memory into context.
        if self._memory_mgr:
            relevant_context = self._retrieve_relevant_context(user_message)
            if relevant_context:
                messages.append(
                    LLMMessage(
                        role="system",
                        content=relevant_context,
                    )
                )

        messages.extend(history)
        messages.append(LLMMessage(role="user", content=user_message))

        tools = tool_defs if tool_defs else None
        tool_ctx = self._build_tool_context(session_key)
        total_prompt_tokens = 0
        total_completion_tokens = 0
        all_tool_calls: list[str] = []
        all_tool_details: list[ToolCallDetail] = []

        max_iter = defaults.max_tool_iterations  # 0 = unlimited
        iteration = 0
        while True:
            iteration += 1
            if max_iter > 0 and iteration > max_iter:
                break
            limit_label = str(max_iter) if max_iter > 0 else "∞"
            logger.info("Agent loop iteration {}/{}", iteration, limit_label)

            # Mid-run compaction: prevent context overflow on long tasks
            if iteration > 1:
                messages = await self._maybe_compact_mid_run(messages, effective_model)

            response = await self._call_llm(
                messages,
                tools=tools,
                model=effective_model,
                temperature=defaults.temperature,
                max_tokens=defaults.max_tokens,
            )

            total_prompt_tokens += response.usage.prompt_tokens
            total_completion_tokens += response.usage.completion_tokens

            if not response.tool_calls:
                final_text = response.content or ""
                logger.info(
                    "Agent finished after {} iterations ({} tool calls)",
                    iteration,
                    len(all_tool_calls),
                )
                result = AgentRunResult(
                    response=final_text,
                    iterations=iteration,
                    total_usage=TokenUsage(
                        prompt_tokens=total_prompt_tokens,
                        completion_tokens=total_completion_tokens,
                    ),
                    tool_calls_made=all_tool_calls,
                    tool_details=all_tool_details,
                )
                self._persist_session(session, user_message, final_text)
                if session:
                    await self._maybe_consolidate(session)

                # Cache pure Q&A responses (no tool calls = deterministic answer)
                if self._semantic_cache and not all_tool_calls:
                    self._semantic_cache.put(user_message, effective_model, final_text)

                return result

            messages.append(
                LLMMessage(
                    role="assistant",
                    content=response.content,
                    tool_calls=response.tool_calls,
                )
            )

            # Execute all tool calls in parallel via asyncio.gather.
            # Results are collected in the same order as the original tool_calls
            # list so tool_call_id alignment is preserved for the LLM.
            exec_results = await asyncio.gather(
                *(self._execute_tool(tc, tool_ctx) for tc in response.tool_calls)
            )

            failed_tools: list[str] = []
            for exec_result in exec_results:
                all_tool_calls.append(exec_result.tool_name)
                all_tool_details.append(
                    ToolCallDetail(
                        name=exec_result.tool_name,
                        success=exec_result.success,
                        duration_ms=exec_result.duration_ms,
                        output_preview=exec_result.output[:120],
                    )
                )
                # Scrub secrets before storing tool output in message history
                scrubbed_output = _scrub_secrets(exec_result.output)
                messages.append(
                    LLMMessage(
                        role="tool",
                        content=scrubbed_output,
                        tool_call_id=exec_result.tool_call_id,
                        name=exec_result.tool_name,
                    )
                )
                if not exec_result.success:
                    failed_tools.append(f"{exec_result.tool_name}: {exec_result.output[:200]}")

            # Self-correction: if tools failed, inject a reflection nudge
            if failed_tools and defaults.enable_self_correction:
                failure_summary = "; ".join(failed_tools)
                messages.append(
                    LLMMessage(
                        role="system",
                        content=(
                            f"[Self-correction] The following tool calls failed: {failure_summary}. "
                            "Before proceeding, analyze what went wrong and adjust your approach. "
                            "Consider: wrong arguments, missing prerequisites, or alternative tools."
                        ),
                    )
                )

        # Exhausted max iterations — force a final text response
        logger.warning(
            "Agent hit max iterations ({}), generating forced response",
            max_iter,
        )
        exhaust_msg = (
            "I've reached my maximum number of tool iterations for this request. "
            "Here's what I've done so far based on the tool results above."
        )
        messages.append(LLMMessage(role="user", content=exhaust_msg))

        response = await self._call_llm(
            messages,
            tools=None,
            model=effective_model,
            temperature=defaults.temperature,
            max_tokens=defaults.max_tokens,
        )
        total_prompt_tokens += response.usage.prompt_tokens
        total_completion_tokens += response.usage.completion_tokens

        final_text = (
            response.content or "I was unable to complete the request within the iteration limit."
        )
        result = AgentRunResult(
            response=final_text,
            iterations=iteration - 1,
            total_usage=TokenUsage(
                prompt_tokens=total_prompt_tokens,
                completion_tokens=total_completion_tokens,
            ),
            tool_calls_made=all_tool_calls,
            tool_details=all_tool_details,
        )
        self._persist_session(session, user_message, final_text)
        if session:
            await self._maybe_consolidate(session)
        return result

    # ── Session persistence ──

    def _persist_session(
        self, session: Session | None, user_message: str, assistant_response: str
    ) -> None:
        """Save user message + assistant response to session, trigger consolidation check."""
        if session is None or self._session_mgr is None:
            return

        session.add_message(LLMMessage(role="user", content=user_message))
        session.add_message(LLMMessage(role="assistant", content=assistant_response))
        self._session_mgr.save(session)

        if self._memory_mgr:
            self._memory_mgr.append_history(f"User: {user_message[:200]}")
            self._memory_mgr.append_history(f"Assistant: {assistant_response[:200]}")

        logger.debug(
            "Session '{}' saved ({} messages)",
            session.key,
            session.message_count,
        )

    async def _maybe_consolidate(self, session: Session) -> None:
        """Check if session needs consolidation and run it if so.

        Triggered when message count exceeds 2x memory_window. Extracts key
        facts from old messages using the LLM (routed to consolidation_model
        if configured), saves them to MEMORY.md, prunes old messages, and
        stores a summary on the session for future context injection.
        """
        if not self._memory_mgr:
            return
        defaults = self._config.agents.defaults
        if not defaults.auto_consolidate:
            return
        if not self._memory_mgr.needs_consolidation(session.message_count, defaults.memory_window):
            return

        old_messages = session.get_old_messages(defaults.memory_window)
        if not old_messages:
            return

        consolidation_model = defaults.consolidation_model or defaults.model
        logger.info(
            "Consolidating session '{}': {} old messages using model '{}'",
            session.key,
            len(old_messages),
            consolidation_model,
        )

        try:
            facts = await self._memory_mgr.consolidate(
                old_messages, self._provider, consolidation_model
            )
            if facts and "no new facts" not in facts.lower():
                session.summary = f"[Previous conversation context]\n{facts}"
            pruned = session.prune_to_window(defaults.memory_window)
            if self._session_mgr:
                self._session_mgr.save(session)
            logger.info(
                "Consolidation complete: pruned {} messages, summary saved",
                pruned,
            )
        except Exception as exc:
            logger.error("Memory consolidation failed (non-fatal): {}", exc)

    async def consolidate_session(self, session: Session) -> None:
        """On-demand session consolidation triggered by the /compact command.

        Unlike _maybe_consolidate, this skips the auto_consolidate and
        threshold checks — it always runs consolidation on whatever old
        messages exist outside the memory window.
        """
        if not self._memory_mgr:
            return
        defaults = self._config.agents.defaults
        old_messages = session.get_old_messages(defaults.memory_window)
        if not old_messages:
            return

        consolidation_model = defaults.consolidation_model or defaults.model
        logger.info(
            "Manual consolidation for '{}': {} old messages",
            session.key,
            len(old_messages),
        )

        try:
            facts = await self._memory_mgr.consolidate(
                old_messages, self._provider, consolidation_model
            )
            if facts and "no new facts" not in facts.lower():
                session.summary = f"[Previous conversation context]\n{facts}"
            pruned = session.prune_to_window(defaults.memory_window)
            if self._session_mgr:
                self._session_mgr.save(session)
            logger.info("Manual consolidation complete: pruned {} messages", pruned)
        except Exception as exc:
            logger.error("Manual consolidation failed: {}", exc)

    # ── Mid-run compaction ──

    async def _maybe_compact_mid_run(
        self, messages: list[LLMMessage], model: str
    ) -> list[LLMMessage]:
        """Compact in-flight messages when non-system messages exceed the threshold.

        Splits messages into leading system messages (always kept) and
        conversation messages. When conversation messages exceed
        _COMPACT_THRESHOLD, older ones are summarized via LLM and replaced
        with a single compact summary block, keeping _COMPACT_KEEP_RECENT
        recent messages intact.
        """
        system_msgs = [m for m in messages if m.role == "system"]
        conv_msgs = [m for m in messages if m.role != "system"]

        if len(conv_msgs) <= _COMPACT_THRESHOLD:
            return messages

        to_summarize = conv_msgs[:-_COMPACT_KEEP_RECENT]
        to_keep = conv_msgs[-_COMPACT_KEEP_RECENT:]

        logger.info(
            "Mid-run compaction triggered: {} conv messages → summarizing {}, keeping {}",
            len(conv_msgs),
            len(to_summarize),
            len(to_keep),
        )

        history_text = "\n".join(
            f"[{m.role}]: {(m.content or '')[:500]}" for m in to_summarize
        )

        consolidation_model = self._config.agents.defaults.consolidation_model or model
        summary_prompt = [
            LLMMessage(
                role="system",
                content=(
                    "You are a summarizer for an AI agent's in-progress task history. "
                    "Summarize the following conversation and tool execution history concisely. "
                    "Focus on: completed sub-tasks, key findings, important decisions, "
                    "current state, and any errors encountered. Be specific but brief."
                ),
            ),
            LLMMessage(
                role="user",
                content=f"Conversation to summarize:\n\n{history_text}",
            ),
        ]

        try:
            response = await self._call_llm(
                summary_prompt,
                tools=None,
                model=consolidation_model,
                temperature=0.3,
                max_tokens=1024,
            )
            summary = response.content or "Previous task history (compacted)."
            logger.info("Mid-run compaction complete, summary: {} chars", len(summary))
        except Exception as exc:
            logger.warning("Mid-run compaction LLM call failed (using truncation): {}", exc)
            summary = f"[Compacted {len(to_summarize)} earlier messages due to context length]"

        summary_msg = LLMMessage(
            role="system",
            content=f"[Mid-run context compaction — earlier history summary]\n{summary}",
        )
        return system_msgs + [summary_msg] + to_keep

    # ── Infinite context: relevance-scored retrieval ──

    def _retrieve_relevant_context(self, query: str) -> str:
        """Retrieve relevant facts from long-term memory for the current query.

        Searches both MEMORY.md (structured facts) and HISTORY.md (conversation
        log) using keyword-weighted TF-IDF scoring. Returns a compact context
        block with the most relevant hits, or empty string if nothing matches.
        """
        if not self._memory_mgr:
            return ""

        parts: list[str] = []

        # Search structured facts in MEMORY.md
        memory_hits = self._memory_mgr.search_memory(query, max_results=5)
        if memory_hits:
            facts_block = "\n".join(f"- {hit}" for hit in memory_hits)
            parts.append(f"[Relevant facts from long-term memory]\n{facts_block}")

        # Search conversation history in HISTORY.md
        history_hits = self._memory_mgr.search_history(query, max_results=5)
        if history_hits:
            history_block = "\n".join(f"- {hit}" for hit in history_hits)
            parts.append(f"[Relevant past conversations]\n{history_block}")

        # Search learned patterns from KnowledgeBase (max 3 entries)
        if self._kb:
            try:
                kb_hits = self._kb.search(query, max_results=3)
                if kb_hits:
                    kb_block = "\n".join(f"- [{e.category}] {e.content}" for e in kb_hits)
                    parts.append(f"[Learned patterns]\n{kb_block}")
            except Exception:
                pass

        if not parts:
            return ""

        return "\n\n".join(parts)

    # ── LLM call with retry ──

    async def _call_llm(
        self,
        messages: list[LLMMessage],
        *,
        tools: list[dict[str, Any]] | None,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse:
        """Call the LLM provider with retry logic for transient failures."""
        import anyio

        max_retries = 3
        base_delay = 1.0

        for attempt in range(max_retries):
            try:
                return await self._provider.chat(
                    messages,
                    model=model,
                    tools=tools,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except Exception as exc:
                is_retryable = _is_retryable_error(exc)
                if not is_retryable or attempt == max_retries - 1:
                    logger.error(
                        "LLM call failed (attempt {}/{}): {}", attempt + 1, max_retries, exc
                    )
                    raise

                delay = base_delay * (2**attempt)
                logger.warning(
                    "LLM call failed (attempt {}/{}), retrying in {:.1f}s: {}",
                    attempt + 1,
                    max_retries,
                    delay,
                    exc,
                )
                await anyio.sleep(delay)

        raise RuntimeError("Unreachable: all LLM retries exhausted")

    # ── Tool execution ──

    async def _execute_tool(self, tool_call: ToolCall, ctx: ToolContext) -> ToolExecutionResult:
        """Execute a single tool call through the registry or legacy executor."""
        import time

        args = tool_call.arguments if isinstance(tool_call.arguments, dict) else {}
        logger.info(
            "Executing tool: {}({})",
            tool_call.function_name,
            ", ".join(f"{k}={v!r}" for k, v in list(args.items())[:3]),
        )

        start = time.perf_counter()

        # Prefer ToolRegistry (Phase 3+)
        if self._registry:
            output = await self._registry.execute(tool_call.function_name, args, ctx)
            elapsed = (time.perf_counter() - start) * 1000
            success = not output.startswith("Error:")
            return ToolExecutionResult(
                tool_call_id=tool_call.id,
                tool_name=tool_call.function_name,
                output=output,
                success=success,
                duration_ms=elapsed,
            )

        # Fallback to Phase 2 executor callback
        if self._tool_executor is not None:
            try:
                output = await self._tool_executor(tool_call.function_name, tool_call.arguments)
                elapsed = (time.perf_counter() - start) * 1000
                return ToolExecutionResult(
                    tool_call_id=tool_call.id,
                    tool_name=tool_call.function_name,
                    output=output,
                    success=True,
                    duration_ms=elapsed,
                )
            except Exception as exc:
                elapsed = (time.perf_counter() - start) * 1000
                logger.error("Tool execution failed: {} - {}", tool_call.function_name, exc)
                return ToolExecutionResult(
                    tool_call_id=tool_call.id,
                    tool_name=tool_call.function_name,
                    output=f"Error executing {tool_call.function_name}: {exc}",
                    success=False,
                    duration_ms=elapsed,
                )

        return ToolExecutionResult(
            tool_call_id=tool_call.id,
            tool_name=tool_call.function_name,
            output=f"Error: No tool executor available. Cannot run '{tool_call.function_name}'.",
            success=False,
        )


def _is_retryable_error(exc: Exception) -> bool:
    """Determine if an LLM API error is transient and worth retrying."""
    from grip.providers.exceptions import (
        AuthenticationError,
        InsufficientQuotaError,
        ModelNotFoundError,
        RateLimitError,
        ServerError,
    )

    if isinstance(exc, (AuthenticationError, InsufficientQuotaError, ModelNotFoundError)):
        return False

    if isinstance(exc, (RateLimitError, ServerError)):
        return True

    import httpx

    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)

    if isinstance(exc, (httpx.ConnectError, httpx.ReadTimeout, httpx.PoolTimeout)):
        return True

    exc_str = str(exc).lower()
    return any(keyword in exc_str for keyword in ("rate limit", "timeout", "overloaded", "503"))
