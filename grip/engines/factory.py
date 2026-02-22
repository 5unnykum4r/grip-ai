"""Engine factory — single entry point for constructing the active engine.

Reads ``config.agents.defaults.engine`` and returns the appropriate
``EngineProtocol`` implementation:

* ``"claude_sdk"`` — tries to import ``SDKRunner`` from
  ``grip.engines.sdk_engine``.  If the ``claude_agent_sdk`` package is
  missing, logs a warning and falls back to ``LiteLLMRunner``.
* ``"litellm"`` — directly returns a ``LiteLLMRunner`` wrapping the
  existing ``AgentLoop`` stack.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from grip.config.schema import GripConfig
    from grip.memory import MemoryManager
    from grip.session import SessionManager
    from grip.trust import TrustManager
    from grip.workspace import WorkspaceManager

from grip.engines.types import EngineProtocol

logger = logging.getLogger(__name__)


def _import_sdk_runner():
    """Import and return the SDKRunner class.

    Separated into its own function so tests can patch it to simulate
    an ImportError without touching ``sys.modules``.
    """
    from grip.engines.sdk_engine import SDKRunner  # type: ignore[import-not-found]

    return SDKRunner


def _build_litellm_runner(
    config: GripConfig,
    workspace: WorkspaceManager,
    session_mgr: SessionManager,
    memory_mgr: MemoryManager,
    trust_mgr: TrustManager | None,
) -> EngineProtocol:
    """Construct and return a LiteLLMRunner instance."""
    from grip.engines.litellm_engine import LiteLLMRunner

    return LiteLLMRunner(
        config=config,
        workspace=workspace,
        session_mgr=session_mgr,
        memory_mgr=memory_mgr,
        trust_mgr=trust_mgr,
    )


def create_engine(
    config: GripConfig,
    workspace: WorkspaceManager,
    session_mgr: SessionManager,
    memory_mgr: MemoryManager,
    *,
    trust_mgr: TrustManager | None = None,
) -> EngineProtocol:
    """Create and return the engine specified by the user's configuration.

    Parameters
    ----------
    config:
        Root grip configuration (engine choice read from
        ``config.agents.defaults.engine``).
    workspace:
        Manages the on-disk workspace directory tree.
    session_mgr:
        Handles conversation session persistence.
    memory_mgr:
        Handles long-term memory reads and writes.
    trust_mgr:
        Optional directory trust manager for sandboxed file access.

    Returns
    -------
    EngineProtocol
        Either an ``SDKRunner`` (when engine is ``"claude_sdk"`` and the SDK
        package is installed) or a ``LiteLLMRunner`` (explicit choice or
        automatic fallback).
    """
    engine_choice = config.agents.defaults.engine

    if engine_choice == "claude_sdk":
        try:
            sdk_runner_cls = _import_sdk_runner()
            logger.info("Using Claude Agent SDK engine (SDKRunner).")
            return sdk_runner_cls(
                config=config,
                workspace=workspace,
                session_mgr=session_mgr,
                memory_mgr=memory_mgr,
                trust_mgr=trust_mgr,
            )
        except ImportError:
            logger.warning(
                "claude_agent_sdk is not installed; falling back to LiteLLM engine. "
                "Install it with: pip install claude-agent-sdk"
            )
            return _build_litellm_runner(
                config, workspace, session_mgr, memory_mgr, trust_mgr
            )

    # engine_choice == "litellm" (the regex pattern on the field guarantees
    # only "claude_sdk" or "litellm" reach this point)
    logger.info("Using LiteLLM engine (LiteLLMRunner).")
    return _build_litellm_runner(config, workspace, session_mgr, memory_mgr, trust_mgr)
