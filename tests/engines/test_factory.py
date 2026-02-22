"""Tests for engine config fields and the create_engine() factory."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from grip.config.schema import AgentDefaults, GripConfig

# ---------------------------------------------------------------------------
# Part A: AgentDefaults engine config fields
# ---------------------------------------------------------------------------


class TestEngineConfigField:
    """The ``engine`` field on AgentDefaults controls which backend is used."""

    def test_default_is_claude_sdk(self):
        defaults = AgentDefaults()
        assert defaults.engine == "claude_sdk"

    def test_accepts_litellm(self):
        defaults = AgentDefaults(engine="litellm")
        assert defaults.engine == "litellm"

    def test_accepts_claude_sdk_explicitly(self):
        defaults = AgentDefaults(engine="claude_sdk")
        assert defaults.engine == "claude_sdk"

    def test_rejects_invalid_value(self):
        with pytest.raises(ValidationError):
            AgentDefaults(engine="openai")

    def test_rejects_empty_string(self):
        with pytest.raises(ValidationError):
            AgentDefaults(engine="")

    def test_rejects_partial_match(self):
        with pytest.raises(ValidationError):
            AgentDefaults(engine="claude_sdk_extra")


class TestSdkModelField:
    """The ``sdk_model`` field selects the Claude model for SDK mode."""

    def test_default_is_claude_sonnet(self):
        defaults = AgentDefaults()
        assert defaults.sdk_model == "claude-sonnet-4-6"

    def test_accepts_custom_value(self):
        defaults = AgentDefaults(sdk_model="claude-opus-4-6")
        assert defaults.sdk_model == "claude-opus-4-6"


class TestSdkPermissionModeField:
    """The ``sdk_permission_mode`` field controls SDK permission behavior."""

    def test_default_is_accept_edits(self):
        defaults = AgentDefaults()
        assert defaults.sdk_permission_mode == "acceptEdits"

    def test_accepts_custom_value(self):
        defaults = AgentDefaults(sdk_permission_mode="bypassPermissions")
        assert defaults.sdk_permission_mode == "bypassPermissions"


# ---------------------------------------------------------------------------
# Fixtures for factory tests
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """Create a minimal workspace with standard subdirectories."""
    ws = tmp_path / "workspace"
    for dirname in ("sessions", "memory", "skills", "cron", "hooks", "workflows", "state"):
        (ws / dirname).mkdir(parents=True)
    (ws / "AGENT.md").write_text("# Test Agent\nYou are a test agent.")
    (ws / "memory" / "MEMORY.md").write_text("")
    (ws / "memory" / "HISTORY.md").write_text("")
    return ws


@pytest.fixture
def litellm_config(tmp_workspace: Path) -> GripConfig:
    """Config with engine='litellm' and semantic_cache disabled."""
    return GripConfig(
        agents={
            "defaults": {
                "workspace": str(tmp_workspace),
                "semantic_cache_enabled": False,
                "engine": "litellm",
            }
        },
        tools={"restrict_to_workspace": True},
    )


@pytest.fixture
def sdk_config(tmp_workspace: Path) -> GripConfig:
    """Config with engine='claude_sdk' and semantic_cache disabled."""
    return GripConfig(
        agents={
            "defaults": {
                "workspace": str(tmp_workspace),
                "semantic_cache_enabled": False,
                "engine": "claude_sdk",
            }
        },
        tools={"restrict_to_workspace": True},
    )


@pytest.fixture
def mock_workspace(tmp_workspace: Path) -> MagicMock:
    ws = MagicMock()
    ws.root = tmp_workspace
    return ws


@pytest.fixture
def mock_session_mgr() -> MagicMock:
    mgr = MagicMock()
    mgr.get_or_create = MagicMock()
    mgr.delete = MagicMock(return_value=True)
    mgr.save = MagicMock()
    return mgr


@pytest.fixture
def mock_memory_mgr() -> MagicMock:
    return MagicMock()


# Patch targets for LiteLLMRunner constructor dependencies
_PATCH_CREATE_PROVIDER = "grip.engines.litellm_engine.create_provider"
_PATCH_CREATE_REGISTRY = "grip.engines.litellm_engine.create_default_registry"
_PATCH_AGENT_LOOP = "grip.engines.litellm_engine.AgentLoop"


# ---------------------------------------------------------------------------
# Part B: create_engine() factory
# ---------------------------------------------------------------------------


class TestCreateEngineWithLiteLLM:
    """create_engine() with engine='litellm' returns a LiteLLMRunner."""

    def test_returns_litellm_runner(
        self, litellm_config, mock_workspace, mock_session_mgr, mock_memory_mgr
    ):
        from grip.engines.factory import create_engine
        from grip.engines.litellm_engine import LiteLLMRunner

        with (
            patch(_PATCH_CREATE_PROVIDER, return_value=MagicMock()),
            patch(_PATCH_CREATE_REGISTRY, return_value=MagicMock()),
            patch(_PATCH_AGENT_LOOP, return_value=MagicMock()),
        ):
            engine = create_engine(
                litellm_config, mock_workspace, mock_session_mgr, mock_memory_mgr
            )

        assert isinstance(engine, LiteLLMRunner)


class TestCreateEngineSdkFallback:
    """create_engine() with engine='claude_sdk' falls back to LiteLLMRunner
    when the claude_agent_sdk package is not installed."""

    def test_falls_back_to_litellm_on_import_error(
        self, sdk_config, mock_workspace, mock_session_mgr, mock_memory_mgr
    ):
        from grip.engines.factory import create_engine
        from grip.engines.litellm_engine import LiteLLMRunner

        # Simulate SDKRunner import failure by making the import raise ImportError
        with (
            patch(
                "grip.engines.factory._import_sdk_runner",
                side_effect=ImportError("no module named claude_agent_sdk"),
            ),
            patch(_PATCH_CREATE_PROVIDER, return_value=MagicMock()),
            patch(_PATCH_CREATE_REGISTRY, return_value=MagicMock()),
            patch(_PATCH_AGENT_LOOP, return_value=MagicMock()),
        ):
            engine = create_engine(
                sdk_config, mock_workspace, mock_session_mgr, mock_memory_mgr
            )

        assert isinstance(engine, LiteLLMRunner)
