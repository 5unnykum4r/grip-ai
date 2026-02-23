"""SDK hooks for trust enforcement, security, and memory persistence.

These hooks integrate grip's security model with the Claude Agent SDK:
  - PreToolUse: blocks dangerous shell commands and enforces file access trust
  - PostToolUse: logs tool execution for observability
  - Stop: persists a conversation summary to history after each agent run

The shell deny patterns are imported from grip/tools/shell.py to stay in sync
with the LiteLLM engine's ShellTool.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from claude_agent_sdk import HookMatcher
from loguru import logger

from grip.tools.shell import _is_dangerous

if TYPE_CHECKING:
    from grip.memory import MemoryManager
    from grip.trust import TrustManager


def build_pre_tool_use_hook(
    workspace_root: Path,
    trust_mgr: TrustManager | None = None,
) -> list[HookMatcher]:
    """Return a PreToolUse HookMatcher list that enforces trust and blocks dangerous commands."""

    resolved_workspace = workspace_root.resolve()

    async def pre_tool_use(input_data, tool_use_id, context) -> dict[str, Any]:
        tool_name = input_data.get("tool_name", "")
        tool_input = input_data.get("tool_input", {})

        # Block dangerous shell commands using the same multi-layer checks as ShellTool
        if tool_name == "Bash":
            command = tool_input.get("command", "")
            danger = _is_dangerous(command)
            if danger:
                logger.warning(
                    "SDK hook blocked dangerous command: {} (reason: {})",
                    command[:100],
                    danger,
                )
                return {
                    "decision": "block",
                    "reason": danger,
                }

        # Enforce trust for file operations outside workspace
        if trust_mgr and tool_name in ("Read", "Write", "Edit"):
            file_path = tool_input.get("file_path", "")
            if file_path:
                resolved = Path(file_path).expanduser().resolve()
                if not trust_mgr.is_trusted(resolved.parent, resolved_workspace):
                    logger.warning(
                        "SDK hook blocked file access outside trusted dirs: {}",
                        resolved,
                    )
                    return {
                        "decision": "block",
                        "reason": (
                            f"Directory not trusted: {resolved.parent}. "
                            "Use /trust to allow access."
                        ),
                    }

        return {}

    return [HookMatcher(hooks=[pre_tool_use])]


def build_post_tool_use_hook() -> list[HookMatcher]:
    """Return a PostToolUse HookMatcher list that logs tool execution for observability."""

    async def post_tool_use(input_data, tool_use_id, context) -> dict[str, Any]:
        tool_name = input_data.get("tool_name", "")
        tool_response = input_data.get("tool_response", "")
        logger.debug(
            "SDK tool executed: {} -> {} chars output", tool_name, len(str(tool_response))
        )
        return {}

    return [HookMatcher(hooks=[post_tool_use])]


def build_stop_hook(memory_mgr: MemoryManager | None) -> list[HookMatcher]:
    """Return a Stop HookMatcher list that persists a conversation summary to history."""

    async def stop_hook(input_data, tool_use_id, context) -> dict[str, Any]:
        if memory_mgr:
            session_id = input_data.get("session_id", "")
            if session_id:
                memory_mgr.append_history(f"[Session ended] {session_id}")
                logger.debug("Stop hook: saved session end marker to history")
        return {}

    return [HookMatcher(hooks=[stop_hook])]
