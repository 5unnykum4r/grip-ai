"""Hybrid search orchestrator: coordinates FTS5 + vector search.

Owns a SearchIndex (SQLite) and an EmbeddingService (litellm). Provides
a unified async search API that runs BM25 and vector search, then merges
via Reciprocal Rank Fusion.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from loguru import logger

from grip.memory.embeddings import EmbeddingService
from grip.memory.search_index import SearchIndex, SearchResult


class HybridSearch:
    """Async hybrid search combining FTS5 keyword and vector cosine results."""

    def __init__(
        self,
        *,
        workspace_path: Path,
        embedding_model: str = "text-embedding-3-small",
        embedding_dimensions: int = 1536,
        vector_weight: float = 0.6,
        bm25_weight: float = 0.4,
        rrf_k: int = 60,
        api_key: str = "",
        api_base: str = "",
    ) -> None:
        db_path = workspace_path / "memory" / "brain.db"
        self._index = SearchIndex(db_path, embedding_dimensions=embedding_dimensions)
        self._embedder = EmbeddingService(
            model=embedding_model,
            dimensions=embedding_dimensions,
            api_key=api_key,
            api_base=api_base,
        )
        self._vector_weight = vector_weight
        self._bm25_weight = bm25_weight
        self._rrf_k = rrf_k
        self._initialized = False

    def initialize(self) -> None:
        """Create the SQLite schema. Safe to call multiple times."""
        self._index.initialize()
        self._initialized = True

    def _ensure_init(self) -> None:
        if not self._initialized:
            self.initialize()

    async def index(self, text: str, *, source: str, source_id: str) -> None:
        """Index a single text entry with optional embedding."""
        self._ensure_init()
        embedding = await self._embedder.embed(text)
        await asyncio.to_thread(
            self._index.index_text,
            text,
            source=source,
            source_id=source_id,
            embedding=embedding,
        )

    async def reindex_bulk(
        self,
        entries: list[tuple[str, str]],
        *,
        source: str,
        batch_size: int = 50,
    ) -> int:
        """Clear a source and reindex from (text, source_id) tuples."""
        self._ensure_init()
        await asyncio.to_thread(self._index.clear, source=source)

        count = 0
        for i in range(0, len(entries), batch_size):
            batch = entries[i : i + batch_size]
            texts = [t for t, _ in batch]
            embeddings = await self._embedder.embed_batch(texts)

            for (text, source_id), emb in zip(batch, embeddings, strict=True):
                await asyncio.to_thread(
                    self._index.index_text,
                    text,
                    source=source,
                    source_id=source_id,
                    embedding=emb,
                )
                count += 1

        logger.info("Reindexed {} entries for source '{}'", count, source)
        return count

    async def search(self, query: str, *, max_results: int = 10) -> list[SearchResult]:
        """Run hybrid search: BM25 + vector, merged via RRF.

        If embedding generation fails, falls back to BM25-only.
        """
        self._ensure_init()

        bm25_results = await asyncio.to_thread(
            self._index.search_bm25, query, max_results=max_results * 2
        )

        query_embedding = await self._embedder.embed(query)

        if query_embedding is not None:
            vector_results = await asyncio.to_thread(
                self._index.search_vector, query_embedding, max_results=max_results * 2
            )
            merged = SearchIndex.rrf_merge(
                bm25_results,
                vector_results,
                k=self._rrf_k,
                weight_a=self._bm25_weight,
                weight_b=self._vector_weight,
            )
            return merged[:max_results]

        return bm25_results[:max_results]

    async def reindex_from_workspace(self, workspace_path: Path) -> int:
        """Rebuild the search index from MEMORY.md, HISTORY.md, and knowledge.json."""
        self._ensure_init()
        memory_dir = workspace_path / "memory"
        entries: list[tuple[str, str]] = []

        memory_path = memory_dir / "MEMORY.md"
        if memory_path.exists():
            for i, line in enumerate(memory_path.read_text(encoding="utf-8").splitlines()):
                stripped = line.strip()
                if stripped:
                    entries.append((stripped, f"m_{i}"))

        history_path = memory_dir / "HISTORY.md"
        if history_path.exists():
            for i, line in enumerate(history_path.read_text(encoding="utf-8").splitlines()):
                stripped = line.strip()
                if stripped:
                    entries.append((stripped, f"h_{i}"))

        kb_path = memory_dir / "knowledge.json"
        if kb_path.exists():
            try:
                data = json.loads(kb_path.read_text(encoding="utf-8"))
                for entry_data in data.get("entries", []):
                    content = entry_data.get("content", "").strip()
                    entry_id = entry_data.get("id", "")
                    if content:
                        entries.append((content, f"kb_{entry_id}"))
            except (json.JSONDecodeError, KeyError):
                pass

        if not entries:
            return 0

        memory_entries = [(t, sid) for t, sid in entries if sid.startswith("m_")]
        history_entries = [(t, sid) for t, sid in entries if sid.startswith("h_")]
        kb_entries = [(t, sid) for t, sid in entries if sid.startswith("kb_")]

        total = 0
        if memory_entries:
            total += await self.reindex_bulk(memory_entries, source="memory")
        if history_entries:
            total += await self.reindex_bulk(history_entries, source="history")
        if kb_entries:
            total += await self.reindex_bulk(kb_entries, source="knowledge")

        logger.info("Reindexed {} total entries from workspace", total)
        return total

    def close(self) -> None:
        """Close the underlying database."""
        self._index.close()
