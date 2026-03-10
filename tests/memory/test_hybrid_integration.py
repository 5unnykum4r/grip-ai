"""Tests for MemoryManager integration with HybridSearch."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from grip.memory.manager import MemoryManager


@pytest.fixture
def memory_mgr(tmp_path: Path) -> MemoryManager:
    ws = tmp_path / "workspace"
    (ws / "memory").mkdir(parents=True)
    return MemoryManager(ws)


class TestHybridIntegration:
    @pytest.mark.asyncio
    async def test_attach_hybrid_enables_search(self, memory_mgr: MemoryManager, tmp_path: Path):
        from grip.memory.hybrid_search import HybridSearch
        from grip.memory.search_index import SearchResult

        hybrid = HybridSearch(
            workspace_path=tmp_path / "workspace",
            embedding_dimensions=8,
        )
        memory_mgr.attach_hybrid_search(hybrid)

        fake_results = [SearchResult(text="found it", source="history", source_id="h1", score=0.5)]
        with patch.object(hybrid, "search", new_callable=AsyncMock, return_value=fake_results):
            results = await memory_mgr.search_history_hybrid("test query", max_results=5)
        assert len(results) == 1
        assert results[0] == "found it"

    def test_search_history_still_works_without_hybrid(self, memory_mgr: MemoryManager):
        memory_mgr._history_path.write_text(
            "[2026-01-01 00:00:00 UTC] python async programming guide\n",
            encoding="utf-8",
        )
        results = memory_mgr.search_history("python async")
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_fallback_to_tfidf_without_hybrid(self, memory_mgr: MemoryManager):
        memory_mgr._history_path.write_text(
            "[2026-01-01 00:00:00 UTC] python async programming guide\n",
            encoding="utf-8",
        )
        results = await memory_mgr.search_history_hybrid("python async")
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_append_history_async_indexes_to_hybrid(
        self, memory_mgr: MemoryManager, tmp_path: Path
    ):
        from grip.memory.hybrid_search import HybridSearch

        hybrid = HybridSearch(
            workspace_path=tmp_path / "workspace",
            embedding_dimensions=8,
        )
        memory_mgr.attach_hybrid_search(hybrid)

        with patch.object(hybrid, "index", new_callable=AsyncMock) as mock_index:
            await memory_mgr.append_history_async("new conversation about python")
            mock_index.assert_called_once()
