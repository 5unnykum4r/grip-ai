"""Hybrid search index: SQLite FTS5 (BM25) + vector cosine similarity.

The search index is a secondary index over grip's markdown-based memory.
Source files (MEMORY.md, HISTORY.md, knowledge.json) remain the source
of truth. If brain.db is deleted, it is rebuilt from those files.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from loguru import logger

_SCHEMA_VERSION = 1


@dataclass(slots=True)
class SearchResult:
    """A single search result from the index."""

    text: str
    source: str
    source_id: str
    score: float


class SearchIndex:
    """SQLite-backed hybrid search with FTS5 keyword and vector cosine scoring."""

    def __init__(self, db_path: Path, *, embedding_dimensions: int = 1536) -> None:
        self.db_path = db_path
        self._dims = embedding_dimensions
        self._conn: sqlite3.Connection | None = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        return self._conn

    def initialize(self) -> None:
        """Create tables and FTS5 virtual table if they don't exist."""
        conn = self._get_conn()
        conn.executescript(f"""
            CREATE TABLE IF NOT EXISTS entries (
                source_id TEXT PRIMARY KEY,
                source    TEXT NOT NULL,
                text      TEXT NOT NULL,
                embedding BLOB,
                indexed_at REAL NOT NULL DEFAULT (julianday('now'))
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
                text,
                content='entries',
                content_rowid='rowid',
                tokenize='porter unicode61'
            );

            CREATE TRIGGER IF NOT EXISTS entries_ai AFTER INSERT ON entries BEGIN
                INSERT INTO entries_fts(rowid, text) VALUES (new.rowid, new.text);
            END;

            CREATE TRIGGER IF NOT EXISTS entries_ad AFTER DELETE ON entries BEGIN
                INSERT INTO entries_fts(entries_fts, rowid, text) VALUES ('delete', old.rowid, old.text);
            END;

            CREATE TRIGGER IF NOT EXISTS entries_au AFTER UPDATE OF text ON entries BEGIN
                INSERT INTO entries_fts(entries_fts, rowid, text) VALUES ('delete', old.rowid, old.text);
                INSERT INTO entries_fts(rowid, text) VALUES (new.rowid, new.text);
            END;

            CREATE TABLE IF NOT EXISTS meta (
                key   TEXT PRIMARY KEY,
                value TEXT
            );

            INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', '{_SCHEMA_VERSION}');
        """)
        conn.commit()
        logger.debug("Search index initialized at {}", self.db_path)

    def index_text(
        self,
        text: str,
        *,
        source: str,
        source_id: str,
        embedding: np.ndarray | None = None,
    ) -> None:
        """Insert or update a text entry. Embedding stored as float32 BLOB."""
        conn = self._get_conn()
        blob = embedding.astype(np.float32).tobytes() if embedding is not None else None
        conn.execute(
            """
            INSERT INTO entries (source_id, source, text, embedding)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(source_id) DO UPDATE SET
                text = excluded.text,
                embedding = excluded.embedding,
                indexed_at = julianday('now')
            """,
            (source_id, source, text, blob),
        )
        conn.commit()

    def search_bm25(self, query: str, *, max_results: int = 20) -> list[SearchResult]:
        """Full-text search using FTS5 BM25 scoring."""
        if not query.strip():
            return []
        conn = self._get_conn()
        rows = conn.execute(
            """
            SELECT e.text, e.source, e.source_id, rank
            FROM entries_fts fts
            JOIN entries e ON e.rowid = fts.rowid
            WHERE entries_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, max_results),
        ).fetchall()
        return [SearchResult(text=r[0], source=r[1], source_id=r[2], score=-r[3]) for r in rows]

    def search_vector(
        self,
        query_embedding: np.ndarray,
        *,
        max_results: int = 20,
        min_similarity: float = 0.1,
    ) -> list[SearchResult]:
        """Cosine similarity search over stored embedding BLOBs."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT source_id, source, text, embedding FROM entries WHERE embedding IS NOT NULL"
        ).fetchall()

        if not rows:
            return []

        query_vec = query_embedding.astype(np.float32)
        query_norm = np.linalg.norm(query_vec)
        if query_norm == 0:
            return []
        query_vec = query_vec / query_norm

        scored: list[SearchResult] = []
        for source_id, source, text, blob in rows:
            stored_vec = np.frombuffer(blob, dtype=np.float32)
            norm = np.linalg.norm(stored_vec)
            if norm == 0:
                continue
            similarity = float(np.dot(query_vec, stored_vec / norm))
            if similarity >= min_similarity:
                scored.append(
                    SearchResult(text=text, source=source, source_id=source_id, score=similarity)
                )

        scored.sort(key=lambda r: r.score, reverse=True)
        return scored[:max_results]

    @staticmethod
    def rrf_merge(
        list_a: list[SearchResult],
        list_b: list[SearchResult],
        *,
        k: int = 60,
        weight_a: float = 1.0,
        weight_b: float = 1.0,
    ) -> list[SearchResult]:
        """Merge two ranked lists using Reciprocal Rank Fusion.

        RRF score = weight_a/(k+rank_a) + weight_b/(k+rank_b).
        Documents in only one list get their single-list score.
        """
        scores: dict[str, float] = {}
        best_result: dict[str, SearchResult] = {}

        for rank, result in enumerate(list_a, start=1):
            scores[result.source_id] = scores.get(result.source_id, 0) + weight_a / (k + rank)
            best_result[result.source_id] = result

        for rank, result in enumerate(list_b, start=1):
            scores[result.source_id] = scores.get(result.source_id, 0) + weight_b / (k + rank)
            if result.source_id not in best_result:
                best_result[result.source_id] = result

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [
            SearchResult(
                text=best_result[sid].text,
                source=best_result[sid].source,
                source_id=sid,
                score=rrf_score,
            )
            for sid, rrf_score in ranked
        ]

    def clear(self, *, source: str | None = None) -> int:
        """Delete entries, optionally filtered by source."""
        conn = self._get_conn()
        if source:
            cursor = conn.execute("DELETE FROM entries WHERE source = ?", (source,))
        else:
            cursor = conn.execute("DELETE FROM entries")
        conn.commit()
        return cursor.rowcount

    def count(self, *, source: str | None = None) -> int:
        """Return the number of indexed entries."""
        conn = self._get_conn()
        if source:
            row = conn.execute(
                "SELECT COUNT(*) FROM entries WHERE source = ?", (source,)
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) FROM entries").fetchone()
        return row[0] if row else 0

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
