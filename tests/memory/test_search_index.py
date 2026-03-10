"""Tests for the hybrid search index."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from grip.memory.search_index import SearchIndex, SearchResult


@pytest.fixture
def search_index(tmp_path: Path) -> SearchIndex:
    db_path = tmp_path / "brain.db"
    return SearchIndex(db_path, embedding_dimensions=8)


class TestSearchIndexSchema:
    def test_creates_database_file(self, search_index: SearchIndex):
        search_index.initialize()
        assert search_index.db_path.exists()

    def test_initialize_is_idempotent(self, search_index: SearchIndex):
        search_index.initialize()
        search_index.initialize()
        assert search_index.db_path.exists()


class TestFTS5Insert:
    def test_index_and_search_by_keyword(self, search_index: SearchIndex):
        search_index.initialize()
        search_index.index_text(
            "python async programming patterns", source="memory", source_id="m1"
        )
        search_index.index_text(
            "javascript callback hell solutions", source="memory", source_id="m2"
        )
        results = search_index.search_bm25("python async", max_results=5)
        assert len(results) >= 1
        assert results[0].source_id == "m1"

    def test_bm25_returns_empty_for_no_match(self, search_index: SearchIndex):
        search_index.initialize()
        search_index.index_text("hello world", source="memory", source_id="m1")
        results = search_index.search_bm25("quantum physics", max_results=5)
        assert results == []

    def test_duplicate_source_id_updates(self, search_index: SearchIndex):
        search_index.initialize()
        search_index.index_text("old content", source="memory", source_id="m1")
        search_index.index_text("new content replaced", source="memory", source_id="m1")
        results = search_index.search_bm25("new content replaced", max_results=5)
        assert len(results) == 1
        assert "new content" in results[0].text


class TestVectorInsert:
    def test_index_with_embedding_and_search(self, search_index: SearchIndex):
        search_index.initialize()
        vec_a = np.random.default_rng(42).random(8).astype(np.float32)
        vec_a /= np.linalg.norm(vec_a)
        search_index.index_text(
            "machine learning basics", source="memory", source_id="v1", embedding=vec_a
        )

        results = search_index.search_vector(vec_a, max_results=5)
        assert len(results) == 1
        assert results[0].source_id == "v1"
        assert results[0].score > 0.99


class TestRRFMerge:
    def test_rrf_merge_combines_results(self):
        list_a = [
            SearchResult(text="alpha", source="m", source_id="1", score=10.0),
            SearchResult(text="beta", source="m", source_id="2", score=5.0),
        ]
        list_b = [
            SearchResult(text="beta", source="m", source_id="2", score=0.9),
            SearchResult(text="gamma", source="m", source_id="3", score=0.8),
        ]
        merged = SearchIndex.rrf_merge(list_a, list_b, k=60, weight_a=1.0, weight_b=1.0)
        ids = [r.source_id for r in merged]
        assert "2" in ids

    def test_rrf_merge_respects_weights(self):
        list_a = [SearchResult(text="only_bm25", source="m", source_id="1", score=10.0)]
        list_b = [SearchResult(text="only_vec", source="m", source_id="2", score=0.9)]
        merged = SearchIndex.rrf_merge(list_a, list_b, k=60, weight_a=0.0, weight_b=1.0)
        assert merged[0].source_id == "2"


class TestClearAndCount:
    def test_clear_by_source(self, search_index: SearchIndex):
        search_index.initialize()
        search_index.index_text("entry one", source="memory", source_id="m1")
        search_index.index_text("entry two", source="history", source_id="h1")
        search_index.clear(source="memory")
        assert search_index.count(source="memory") == 0
        assert search_index.count(source="history") == 1

    def test_entry_count(self, search_index: SearchIndex):
        search_index.initialize()
        search_index.index_text("a", source="memory", source_id="1")
        search_index.index_text("b", source="history", source_id="2")
        assert search_index.count() == 2
        assert search_index.count(source="memory") == 1
