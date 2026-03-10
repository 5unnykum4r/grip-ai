"""LearningEngine — post-run behavioral pattern extraction wrapper.

Wraps any EngineProtocol to extract behavioral patterns after each
interaction using rule-based heuristics (zero LLM calls). Extracted
patterns are stored in the KnowledgeBase for injection into future
system prompts.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from loguru import logger

from grip.engines.types import AgentRunResult, EngineProtocol, StreamEvent
from grip.memory.knowledge_base import KnowledgeBase
from grip.memory.pattern_extractor import PatternExtractor


class LearningEngine(EngineProtocol):
    """Transparent wrapper that adds behavioral learning to any engine.

    After each ``run()``, the extractor scans the user message, agent
    response, and tool calls for patterns (preferences, decisions, errors,
    tool frequency) and stores them in the KnowledgeBase. The result is
    returned unchanged.
    """

    def __init__(
        self,
        inner: EngineProtocol,
        knowledge_base: KnowledgeBase,
        extractor: PatternExtractor,
    ) -> None:
        self._inner = inner
        self._kb = knowledge_base
        self._extractor = extractor

    @property
    def knowledge_base(self) -> KnowledgeBase:
        """Expose KB for status queries."""
        return self._kb

    async def run(
        self,
        user_message: str,
        *,
        session_key: str = "cli:default",
        model: str | None = None,
    ) -> AgentRunResult:
        result = await self._inner.run(user_message, session_key=session_key, model=model)

        try:
            patterns = self._extractor.extract(
                user_message, result.response, result.tool_calls_made
            )
            for p in patterns:
                self._kb.add(p.category, p.content, source=p.source, tags=p.tags)
            self._kb.flush()
            if patterns:
                logger.debug(
                    "Extracted {} behavioral pattern(s) from interaction",
                    len(patterns),
                )
        except Exception as exc:
            logger.debug("Behavioral extraction failed (non-fatal): {}", exc)

        return result

    async def run_stream(
        self,
        user_message: str,
        *,
        session_key: str = "cli:default",
        model: str | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Forward the inner stream, then extract behavioral patterns from the result."""
        response_parts: list[str] = []
        tool_calls: list[str] = []

        async for event in self._inner.run_stream(
            user_message, session_key=session_key, model=model
        ):
            if event.type == "token":
                response_parts.append(event.text)
            elif event.type == "done":
                tool_calls = list(event.tool_calls_made)
            yield event

        try:
            full_response = "".join(response_parts)
            patterns = self._extractor.extract(user_message, full_response, tool_calls)
            for p in patterns:
                self._kb.add(p.category, p.content, source=p.source, tags=p.tags)
            self._kb.flush()
            if patterns:
                logger.debug(
                    "Extracted {} behavioral pattern(s) from streamed interaction",
                    len(patterns),
                )
        except Exception as exc:
            logger.debug("Behavioral extraction failed (non-fatal): {}", exc)

    async def consolidate_session(self, session_key: str) -> None:
        await self._inner.consolidate_session(session_key)

    async def reset_session(self, session_key: str) -> None:
        await self._inner.reset_session(session_key)
