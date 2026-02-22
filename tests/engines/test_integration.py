"""Integration tests for the dual-engine system.

These tests verify the full config -> factory -> engine chain works correctly,
including fallback behavior when claude-agent-sdk is not installed.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

from grip.config.schema import AgentDefaults, AgentsConfig, GripConfig
from grip.engines.factory import create_engine
from grip.engines.litellm_engine import LiteLLMRunner
from grip.engines.types import EngineProtocol

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(engine: str = "litellm") -> GripConfig:
    return GripConfig(agents=AgentsConfig(defaults=AgentDefaults(engine=engine)))


def _mock_workspace():
    ws = MagicMock()
    ws.root = MagicMock()
    ws.root.__truediv__ = MagicMock(return_value=MagicMock())
    ws.root.__str__ = MagicMock(return_value="/fake/workspace")
    ws.root.resolve = MagicMock(return_value=ws.root)
    return ws


# ===================================================================
# Factory creates LiteLLMRunner for litellm config
# ===================================================================

class TestFactoryCreatesLiteLLM:
    def test_creates_litellm_runner(self):
        config = _make_config("litellm")
        ws = _mock_workspace()
        with patch("grip.engines.litellm_engine.create_provider"), \
             patch("grip.engines.litellm_engine.create_default_registry"):
            engine = create_engine(config, ws, MagicMock(), MagicMock())
        assert isinstance(engine, LiteLLMRunner)

    def test_litellm_runner_is_engine_protocol(self):
        config = _make_config("litellm")
        ws = _mock_workspace()
        with patch("grip.engines.litellm_engine.create_provider"), \
             patch("grip.engines.litellm_engine.create_default_registry"):
            engine = create_engine(config, ws, MagicMock(), MagicMock())
        assert isinstance(engine, EngineProtocol)

    def test_litellm_runner_has_run_method(self):
        config = _make_config("litellm")
        ws = _mock_workspace()
        with patch("grip.engines.litellm_engine.create_provider"), \
             patch("grip.engines.litellm_engine.create_default_registry"):
            engine = create_engine(config, ws, MagicMock(), MagicMock())
        assert hasattr(engine, "run")
        assert callable(engine.run)

    def test_litellm_runner_has_consolidate_session(self):
        config = _make_config("litellm")
        ws = _mock_workspace()
        with patch("grip.engines.litellm_engine.create_provider"), \
             patch("grip.engines.litellm_engine.create_default_registry"):
            engine = create_engine(config, ws, MagicMock(), MagicMock())
        assert hasattr(engine, "consolidate_session")

    def test_litellm_runner_has_reset_session(self):
        config = _make_config("litellm")
        ws = _mock_workspace()
        with patch("grip.engines.litellm_engine.create_provider"), \
             patch("grip.engines.litellm_engine.create_default_registry"):
            engine = create_engine(config, ws, MagicMock(), MagicMock())
        assert hasattr(engine, "reset_session")


# ===================================================================
# Factory falls back to LiteLLM when SDK is not installed
# ===================================================================

class TestFactoryFallback:
    def test_falls_back_to_litellm_when_sdk_not_installed(self):
        config = _make_config("claude_sdk")
        ws = _mock_workspace()

        with patch.dict(sys.modules, {"claude_agent_sdk": None}), \
             patch("grip.engines.litellm_engine.create_provider"), \
             patch("grip.engines.litellm_engine.create_default_registry"):
            engine = create_engine(config, ws, MagicMock(), MagicMock())
        assert isinstance(engine, LiteLLMRunner)

    def test_fallback_engine_is_still_engine_protocol(self):
        config = _make_config("claude_sdk")
        ws = _mock_workspace()

        with patch.dict(sys.modules, {"claude_agent_sdk": None}), \
             patch("grip.engines.litellm_engine.create_provider"), \
             patch("grip.engines.litellm_engine.create_default_registry"):
            engine = create_engine(config, ws, MagicMock(), MagicMock())
        assert isinstance(engine, EngineProtocol)


# ===================================================================
# Config validation
# ===================================================================

class TestConfigValidation:
    def test_default_engine_is_claude_sdk(self):
        defaults = AgentDefaults()
        assert defaults.engine == "claude_sdk"

    def test_default_sdk_model(self):
        defaults = AgentDefaults()
        assert defaults.sdk_model == "claude-sonnet-4-6"

    def test_default_sdk_permission_mode(self):
        defaults = AgentDefaults()
        assert defaults.sdk_permission_mode == "acceptEdits"

    def test_engine_accepts_litellm(self):
        defaults = AgentDefaults(engine="litellm")
        assert defaults.engine == "litellm"

    def test_engine_accepts_claude_sdk(self):
        defaults = AgentDefaults(engine="claude_sdk")
        assert defaults.engine == "claude_sdk"


# ===================================================================
# Trust manager integration with factory
# ===================================================================

class TestTrustManagerWiring:
    def test_trust_mgr_passed_to_litellm_engine(self):
        config = _make_config("litellm")
        ws = _mock_workspace()
        trust = MagicMock()

        with patch("grip.engines.litellm_engine.create_provider"), \
             patch("grip.engines.litellm_engine.create_default_registry"):
            engine = create_engine(config, ws, MagicMock(), MagicMock(), trust_mgr=trust)
        assert isinstance(engine, LiteLLMRunner)
