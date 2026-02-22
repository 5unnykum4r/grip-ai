"""Tests for the memory system."""

from __future__ import annotations

from pathlib import Path

import pytest

from grip.memory.manager import MemoryManager


@pytest.fixture
def memory_mgr(tmp_path: Path) -> MemoryManager:
    return MemoryManager(tmp_path)


def test_read_memory_empty(memory_mgr: MemoryManager):
    assert memory_mgr.read_memory() == ""


def test_write_and_read_memory(memory_mgr: MemoryManager):
    memory_mgr.write_memory("fact 1\nfact 2")
    content = memory_mgr.read_memory()
    assert "fact 1" in content
    assert "fact 2" in content


def test_append_to_memory(memory_mgr: MemoryManager):
    memory_mgr.write_memory("existing")
    memory_mgr.append_to_memory("new fact")
    content = memory_mgr.read_memory()
    assert "existing" in content
    assert "new fact" in content


def test_read_history_empty(memory_mgr: MemoryManager):
    assert memory_mgr.read_history() == ""


def test_append_history(memory_mgr: MemoryManager):
    memory_mgr.append_history("user asked about Python")
    memory_mgr.append_history("user asked about Rust")
    content = memory_mgr.read_history()
    assert "Python" in content
    assert "Rust" in content


def test_search_history(memory_mgr: MemoryManager):
    memory_mgr.append_history("discussed Python packaging")
    memory_mgr.append_history("talked about Go modules")
    memory_mgr.append_history("Python async patterns")

    results = memory_mgr.search_history("python")
    assert len(results) == 2


def test_search_history_case_insensitive(memory_mgr: MemoryManager):
    memory_mgr.append_history("IMPORTANT: Deploy to AWS")
    results = memory_mgr.search_history("deploy")
    assert len(results) == 1


def test_needs_consolidation(memory_mgr: MemoryManager):
    assert memory_mgr.needs_consolidation(10, 50) is False
    assert memory_mgr.needs_consolidation(101, 50) is True
