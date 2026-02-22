"""Shared test fixtures for grip test suite."""

from __future__ import annotations

from pathlib import Path

import pytest

from grip.config.schema import GripConfig


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """Create a temporary workspace directory with standard structure."""
    ws = tmp_path / "workspace"
    for dirname in ("sessions", "memory", "skills", "cron", "hooks", "workflows"):
        (ws / dirname).mkdir(parents=True)

    (ws / "AGENT.md").write_text("# Test Agent\nYou are a test agent.")
    (ws / "memory" / "MEMORY.md").write_text("")
    (ws / "memory" / "HISTORY.md").write_text("")
    return ws


@pytest.fixture
def config(tmp_workspace: Path) -> GripConfig:
    """Create a test config pointing at the temporary workspace."""
    return GripConfig(
        agents={"defaults": {"workspace": str(tmp_workspace)}},
        tools={"restrict_to_workspace": True},
    )


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    """Create a temporary config file path."""
    path = tmp_path / "config.json"
    path.write_text("{}", encoding="utf-8")
    return path
