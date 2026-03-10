"""Tests for the hybrid search orchestrator."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from grip.memory.hybrid_search import HybridSearch


@pytest.fixture
def hybrid(tmp_path: Path) -> HybridSearch:
    return HybridSearch(
        workspace_path=tmp_path / "workspace",
        embedding_model="text-embedding-3-small",
        embedding_dimensions=8,
        vector_weight=0.6,
        bm25_weight=0.4,
        rrf_k=60,
    )


def _fake_embed(dims: int = 8) -> np.ndarray:
    vec = np.random.default_rng(42).random(dims).astype(np.float32)
    return vec / np.linalg.norm(vec)


class TestHybridSearch:
    @pytest.mark.asyncio
    async def test_index_and_search_keyword_only(self, hybrid: HybridSearch):
        hybrid.initialize()
        await hybrid.index("python async programming guide", source="memory", source_id="m1")
        await hybrid.index("javascript callback patterns", source="memory", source_id="m2")

        with patch.object(hybrid._embedder, "embed", return_value=None):
            results = await hybrid.search("python async", max_results=5)
        assert len(results) >= 1
        assert results[0].source_id == "m1"

    @pytest.mark.asyncio
    async def test_index_and_search_with_vectors(self, hybrid: HybridSearch):
        hybrid.initialize()

        fake_vec = _fake_embed(8)
        with patch.object(hybrid._embedder, "embed", return_value=fake_vec):
            await hybrid.index("python async programming guide", source="memory", source_id="m1")

        with patch.object(hybrid._embedder, "embed", return_value=fake_vec):
            results = await hybrid.search("python async", max_results=5)
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_search_empty_index_returns_empty(self, hybrid: HybridSearch):
        hybrid.initialize()
        with patch.object(hybrid._embedder, "embed", return_value=None):
            results = await hybrid.search("anything", max_results=5)
        assert results == []


class TestReindexBulk:
    @pytest.mark.asyncio
    async def test_reindex_from_texts(self, hybrid: HybridSearch):
        hybrid.initialize()
        await hybrid.index("old stuff", source="memory", source_id="old1")

        with patch.object(hybrid._embedder, "embed_batch", return_value=[None, None]):
            await hybrid.reindex_bulk(
                [("new entry one", "m1"), ("new entry two", "m2")],
                source="memory",
            )
        assert hybrid._index.count(source="memory") == 2


class TestAutoReindex:
    @pytest.mark.asyncio
    async def test_reindex_from_memory_files(self, tmp_path: Path):
        ws = tmp_path / "workspace"
        (ws / "memory").mkdir(parents=True)
        (ws / "memory" / "MEMORY.md").write_text(
            "- [preference] User likes Python\n- [project] Building grip-ai\n"
        )
        (ws / "memory" / "HISTORY.md").write_text(
            "[2026-01-01 00:00:00 UTC] Discussed async patterns\n"
        )

        hybrid = HybridSearch(workspace_path=ws, embedding_dimensions=8)
        hybrid.initialize()

        with patch.object(
            hybrid._embedder, "embed_batch", side_effect=lambda texts: [None] * len(texts)
        ):
            count = await hybrid.reindex_from_workspace(ws)
        assert count >= 3
