"""Shared test fixtures for grip test suite.

The _isolate_grip_config fixture (autouse) prevents GripConfig from reading
the user's real ~/.grip/config.json during tests.  Without this, MCP presets
or other settings added by the user would leak into test configs.

The _isolate_mcp_tokens fixture (autouse) prevents MCPTokenStorage from
reading the user's real ~/.grip/mcp_tokens.json and ~/.grip/mcp_clients.json
during tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from grip.config.schema import GripConfig


@pytest.fixture(autouse=True)
def _isolate_grip_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point GripConfig's json_file at an empty temp file for every test.

    This prevents the real ~/.grip/config.json from leaking values (like MCP
    presets the user has installed) into test-constructed GripConfig instances.
    """
    empty_config = tmp_path / "grip_test_config.json"
    empty_config.write_text("{}", encoding="utf-8")
    monkeypatch.setitem(GripConfig.model_config, "json_file", empty_config)


@pytest.fixture(autouse=True)
def _isolate_mcp_tokens(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect MCPTokenStorage to a temp directory for every test.

    Prevents the real ~/.grip/mcp_tokens.json and ~/.grip/mcp_clients.json
    from leaking stored OAuth tokens into tests.
    """
    mcp_token_dir = tmp_path / "mcp_tokens"
    mcp_token_dir.mkdir()
    from grip.tools.mcp_auth import MCPTokenStorage

    _orig_init = MCPTokenStorage.__init__

    def _patched_init(self, server_name, base_dir=None):
        _orig_init(self, server_name, base_dir=base_dir or mcp_token_dir)

    monkeypatch.setattr(MCPTokenStorage, "__init__", _patched_init)


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
