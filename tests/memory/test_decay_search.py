"""Tests for decay-weighted relevance, category search, and memory stats."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from grip.memory.manager import MemoryManager


@pytest.fixture
def memory_mgr(tmp_path: Path) -> MemoryManager:
    ws = tmp_path / "workspace"
    (ws / "memory").mkdir(parents=True)
    return MemoryManager(ws)


class TestDecayWeightedSearch:
    def test_recent_entries_score_higher(self, memory_mgr: MemoryManager):
        """Recent entries should rank higher than old entries for the same query."""
        now = datetime.now(UTC)
        old_time = (now - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        recent_time = (now - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")

        memory_mgr._history_path.write_text(
            f"[{old_time} UTC] discussion about python programming language features\n"
            f"[{recent_time} UTC] discussion about python programming language features\n",
            encoding="utf-8",
        )

        results = memory_mgr.search_history("python programming language features")
        assert len(results) == 2
        assert recent_time in results[0]

    def test_decay_rate_zero_equals_original(self, memory_mgr: MemoryManager):
        """With decay_rate=0, all entries should be treated equally."""
        now = datetime.now(UTC)
        old_time = (now - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        recent_time = (now - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")

        memory_mgr._history_path.write_text(
            f"[{old_time} UTC] unique alpha beta gamma delta\n"
            f"[{recent_time} UTC] unique alpha beta gamma delta\n",
            encoding="utf-8",
        )

        results = memory_mgr.search_history("alpha beta gamma delta", decay_rate=0)
        assert len(results) == 2


class TestCategorySearch:
    def test_category_filter_returns_only_matching(self, memory_mgr: MemoryManager):
        memory_mgr.write_memory(
            "- [preference] User likes dark mode\n"
            "- [project] Working on grip-ai\n"
            "- [preference] User prefers Python\n"
        )
        results = memory_mgr.search_memory("user", category="preference")
        assert all("[preference]" in r for r in results)
        assert not any("[project]" in r for r in results)

    def test_no_category_returns_all(self, memory_mgr: MemoryManager):
        memory_mgr.write_memory(
            "- [preference] User likes dark mode\n- [project] Working on grip-ai\n"
        )
        results = memory_mgr.search_memory("user")
        assert len(results) >= 1


class TestMemoryStats:
    def test_stats_returns_correct_counts(self, memory_mgr: MemoryManager):
        memory_mgr.write_memory(
            "- [preference] Dark mode\n- [preference] Python\n- [project] grip-ai\n"
        )
        stats = memory_mgr.get_memory_stats()
        assert stats["total_entries"] == 3
        assert stats["categories"]["preference"] == 2
        assert stats["categories"]["project"] == 1
        assert stats["memory_size_bytes"] > 0

    def test_stats_empty_memory(self, memory_mgr: MemoryManager):
        stats = memory_mgr.get_memory_stats()
        assert stats["total_entries"] == 0
        assert stats["categories"] == {}


class TestMemoryCompaction:
    def test_near_duplicates_removed(self, memory_mgr: MemoryManager):
        memory_mgr.write_memory(
            "- [pref] User prefers dark mode for editing code\n"
            "- [pref] User prefers dark mode for editing code always\n"
            "- [project] Working on grip-ai platform\n"
        )
        removed = memory_mgr.compact_memory(similarity_threshold=0.7)
        assert removed >= 1
        remaining = memory_mgr.read_memory()
        assert "grip-ai" in remaining

    def test_unique_entries_preserved(self, memory_mgr: MemoryManager):
        memory_mgr.write_memory(
            "- [pref] User likes Python\n"
            "- [project] Building a web app\n"
            "- [fact] Earth orbits the Sun\n"
        )
        removed = memory_mgr.compact_memory()
        assert removed == 0

    def test_configurable_threshold(self, memory_mgr: MemoryManager):
        memory_mgr.write_memory("- Alpha beta gamma delta epsilon\n- Alpha beta gamma delta zeta\n")
        removed_strict = memory_mgr.compact_memory(similarity_threshold=0.95)
        assert removed_strict == 0

        memory_mgr.write_memory("- Alpha beta gamma delta epsilon\n- Alpha beta gamma delta zeta\n")
        removed_loose = memory_mgr.compact_memory(similarity_threshold=0.5)
        assert removed_loose >= 1

    def test_empty_memory_returns_zero(self, memory_mgr: MemoryManager):
        assert memory_mgr.compact_memory() == 0

    def test_single_entry_returns_zero(self, memory_mgr: MemoryManager):
        memory_mgr.write_memory("- Single entry\n")
        assert memory_mgr.compact_memory() == 0

    def test_optimized_matches_brute_force(self, memory_mgr: MemoryManager):
        """Inverted-index optimized compact_memory produces identical results to brute-force."""
        from grip.memory.manager import _tokenize

        entries = [
            "- [pref] User prefers dark mode for editing code",
            "- [pref] User prefers dark mode for editing code always",
            "- [project] Working on grip-ai platform",
            "- [fact] Python is a great programming language",
            "- [fact] Python is a wonderful programming language for data",
            "- [pref] Favorite color is blue",
            "- [project] Building REST API with FastAPI",
            "- [project] Building REST API with FastAPI framework",
            "- [fact] The earth revolves around the sun",
            "- [pref] Prefers vim keybindings in editor",
        ]
        threshold = 0.7

        # Brute-force reference
        token_sets = [set(_tokenize(e)) for e in entries]
        keep_bf = [True] * len(entries)
        for i in range(len(entries)):
            if not keep_bf[i]:
                continue
            for j in range(i + 1, len(entries)):
                if not keep_bf[j] or not token_sets[i] or not token_sets[j]:
                    continue
                inter = len(token_sets[i] & token_sets[j])
                union = len(token_sets[i] | token_sets[j])
                if union > 0 and inter / union >= threshold:
                    keep_bf[j] = False
        expected = [e for e, k in zip(entries, keep_bf, strict=True) if k]

        # Optimized path
        memory_mgr.write_memory("\n".join(entries) + "\n")
        memory_mgr.compact_memory(similarity_threshold=threshold)
        actual_lines = [
            line.strip()
            for line in memory_mgr.read_memory().splitlines()
            if line.strip()
        ]

        assert actual_lines == expected

    def test_compact_memory_scales(self, memory_mgr: MemoryManager):
        """2000 entries should compact in under 5 seconds."""
        import time

        entries = [f"- [entry] item number {i} with extra words alpha beta" for i in range(2000)]
        # Add 200 near-duplicates (every 10th entry gets a variant)
        for i in range(0, 2000, 10):
            entries.append(f"- [entry] item number {i} with extra words alpha beta gamma")

        memory_mgr.write_memory("\n".join(entries) + "\n")
        start = time.monotonic()
        removed = memory_mgr.compact_memory(similarity_threshold=0.7)
        elapsed = time.monotonic() - start

        assert elapsed < 5.0, f"compact_memory took {elapsed:.2f}s on 2200 entries"
        assert removed > 0
