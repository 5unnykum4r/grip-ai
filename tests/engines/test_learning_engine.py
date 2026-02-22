"""Tests for LearningEngine behavioral extraction wrapper."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from grip.engines.learning import LearningEngine
from grip.engines.types import AgentRunResult, EngineProtocol
from grip.memory.knowledge_base import KnowledgeBase
from grip.memory.pattern_extractor import PatternExtractor


@pytest.fixture
def mock_inner() -> MagicMock:
    inner = MagicMock(spec=EngineProtocol)
    inner.run = AsyncMock(
        return_value=AgentRunResult(
            response="Done!",
            iterations=1,
            prompt_tokens=100,
            completion_tokens=50,
            tool_calls_made=["read_file"],
        )
    )
    inner.consolidate_session = AsyncMock()
    inner.reset_session = AsyncMock()
    return inner


@pytest.fixture
def kb(tmp_path: Path) -> KnowledgeBase:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    return KnowledgeBase(memory_dir)


@pytest.fixture
def extractor() -> PatternExtractor:
    return PatternExtractor()


class TestLearningEngine:
    @pytest.mark.asyncio
    async def test_delegates_run_to_inner(self, mock_inner, kb, extractor):
        engine = LearningEngine(mock_inner, kb, extractor)
        result = await engine.run("hello")
        assert result.response == "Done!"
        mock_inner.run.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_result_passes_through_unchanged(self, mock_inner, kb, extractor):
        engine = LearningEngine(mock_inner, kb, extractor)
        result = await engine.run("test")
        assert result.prompt_tokens == 100
        assert result.completion_tokens == 50
        assert result.tool_calls_made == ["read_file"]

    @pytest.mark.asyncio
    async def test_extracts_and_stores_patterns(self, mock_inner, kb, extractor):
        mock_inner.run.return_value = AgentRunResult(response="OK", tool_calls_made=[])
        engine = LearningEngine(mock_inner, kb, extractor)
        await engine.run("I prefer dark mode for all editors")
        assert kb.count >= 1
        entries = kb.by_category("user_preference")
        assert len(entries) >= 1
        assert any("dark mode" in e.content for e in entries)

    @pytest.mark.asyncio
    async def test_extraction_failure_does_not_break_run(self, mock_inner, kb):
        broken_extractor = MagicMock()
        broken_extractor.extract.side_effect = RuntimeError("extractor broke")
        engine = LearningEngine(mock_inner, kb, broken_extractor)
        result = await engine.run("hello")
        assert result.response == "Done!"

    @pytest.mark.asyncio
    async def test_delegates_consolidate_session(self, mock_inner, kb, extractor):
        engine = LearningEngine(mock_inner, kb, extractor)
        await engine.consolidate_session("test:session")
        mock_inner.consolidate_session.assert_awaited_once_with("test:session")

    @pytest.mark.asyncio
    async def test_delegates_reset_session(self, mock_inner, kb, extractor):
        engine = LearningEngine(mock_inner, kb, extractor)
        await engine.reset_session("test:session")
        mock_inner.reset_session.assert_awaited_once_with("test:session")

    def test_is_engine_protocol(self, mock_inner, kb, extractor):
        engine = LearningEngine(mock_inner, kb, extractor)
        assert isinstance(engine, EngineProtocol)

    def test_knowledge_base_property(self, mock_inner, kb, extractor):
        engine = LearningEngine(mock_inner, kb, extractor)
        assert engine.knowledge_base is kb

    @pytest.mark.asyncio
    async def test_no_patterns_still_returns_result(self, mock_inner, kb, extractor):
        engine = LearningEngine(mock_inner, kb, extractor)
        result = await engine.run("hello world")
        assert result.response == "Done!"
        assert kb.count == 0
