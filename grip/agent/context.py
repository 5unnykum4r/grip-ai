"""Context builder: assembles the system prompt from workspace files.

Reads identity files (AGENT.md, IDENTITY.md, SOUL.md, USER.md, SHIELD.md),
appends a compact tool overview, skill listing, active todos, and metadata,
and returns a single system message ready for the LLM.

Full tool JSON schemas are sent via the API's ``tools`` parameter. The system
prompt includes a compact tools overview (name + category) so the LLM knows
which tools exist and is instructed to prefer them over writing manual code.
"""

from __future__ import annotations

import json
import platform
import re
from datetime import UTC, datetime

from loguru import logger

from grip import __version__
from grip.config.schema import ChannelsConfig
from grip.providers.types import LLMMessage
from grip.tools.base import ToolRegistry
from grip.workspace.manager import WorkspaceManager

# Patterns used by _detect_tone_hint() to classify the user's emotional state.
_ERROR_PATTERNS = re.compile(
    r"(traceback|error|exception|failed|crash|bug|broken|not working|won't work)",
    re.IGNORECASE,
)
_FRUSTRATION_PATTERNS = re.compile(
    r"(wtf|damn|hell|ugh|fuck|shit|crap|stupid|hate|awful|terrible|why won't)",
    re.IGNORECASE,
)
_BRAINSTORM_PATTERNS = re.compile(
    r"(idea|brainstorm|what if|how could|design|architect|plan|explore|suggest|creative)",
    re.IGNORECASE,
)


def _detect_tone_hint(user_message: str) -> str:
    """Return a short tone instruction based on the user's message content.

    Returns empty string when no special tone is warranted.
    """
    if not user_message:
        return ""

    is_caps = (
        sum(1 for c in user_message if c.isupper()) > len(user_message) * 0.6
        and len(user_message) > 10
    )
    frustrated = bool(_FRUSTRATION_PATTERNS.search(user_message)) or is_caps
    has_error = bool(_ERROR_PATTERNS.search(user_message))
    brainstorming = bool(_BRAINSTORM_PATTERNS.search(user_message))

    if frustrated and has_error:
        return (
            "## Tone Adaptation\n\n"
            "The user seems frustrated with an error. "
            "Be calm, precise, and surgical. Lead with the fix, not explanations. "
            "Show empathy briefly, then focus on solving the problem step by step."
        )
    if frustrated:
        return (
            "## Tone Adaptation\n\n"
            "The user seems stressed. Be patient and supportive. "
            "Break things into small, clear steps. Avoid jargon. "
            "Confirm understanding before proceeding."
        )
    if has_error:
        return (
            "## Tone Adaptation\n\n"
            "The user is dealing with an error. "
            "Be concise and action-oriented. Diagnose first, then provide a clear fix."
        )
    if brainstorming:
        return (
            "## Tone Adaptation\n\n"
            "The user is brainstorming. Be expansive and creative. "
            "Suggest multiple approaches, trade-offs, and alternatives. "
            "Encourage exploration."
        )
    return ""


class ContextBuilder:
    """Builds a system prompt from workspace files and runtime metadata.

    The system prompt follows this structure:
      1. Agent identity (AGENT.md + IDENTITY.md + SOUL.md + USER.md)
      2. Shield policy (SHIELD.md — runtime threat feed evaluation rules)
      3. Compact tools overview (category + tool names so the LLM knows what's available)
      4. Compact skill listing (name + one-line description only)
      5. Active task list (from workspace/tasks.json, pending/in_progress only)
      6. Tone adaptation (based on user message sentiment)
      7. Runtime metadata (datetime, platform, version)

    Full tool JSON schemas travel via the API's ``tools`` parameter. The
    system prompt carries only a compact overview so the LLM prefers
    registered tools over writing manual code.
    """

    def __init__(
        self,
        workspace: WorkspaceManager,
        channels: ChannelsConfig | None = None,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        self._workspace = workspace
        self._channels = channels
        self._registry = tool_registry
        self._cached_identity: str | None = None

    def invalidate_cache(self) -> None:
        """Force re-read of identity files on next build."""
        self._cached_identity = None

    def build_system_message(
        self,
        *,
        user_message: str = "",
        session_key: str = "",
    ) -> LLMMessage:
        """Assemble the full system prompt and return it as an LLMMessage."""
        parts: list[str] = []

        identity = self._build_identity_section()
        if identity:
            parts.append(identity)

        tools_overview = self._build_tools_overview()
        if tools_overview:
            parts.append(tools_overview)

        skills_listing = self._build_skills_listing()
        if skills_listing:
            parts.append(skills_listing)

        todos_section = self._build_todos_section()
        if todos_section:
            parts.append(todos_section)

        tone_hint = _detect_tone_hint(user_message)
        if tone_hint:
            parts.append(tone_hint)

        parts.append(self._build_metadata_section(session_key=session_key, channels=self._channels))

        system_prompt = "\n\n---\n\n".join(parts)
        logger.debug("System prompt built: {} chars", len(system_prompt))
        return LLMMessage(role="system", content=system_prompt)

    def _build_identity_section(self) -> str:
        """Concatenate identity + shield files into a single block.

        Includes AGENT.md, IDENTITY.md, SOUL.md, USER.md, and SHIELD.md.
        Caches the result since these files rarely change mid-session.
        """
        if self._cached_identity is not None:
            return self._cached_identity

        identity_files = self._workspace.read_identity_files()
        sections: list[str] = []

        for filename in ("AGENT.md", "IDENTITY.md", "SOUL.md", "USER.md", "SHIELD.md"):
            content = identity_files.get(filename)
            if content and content.strip():
                sections.append(content.strip())

        self._cached_identity = "\n\n".join(sections)
        return self._cached_identity

    def _build_tools_overview(self) -> str:
        """Build a compact category-grouped listing of registered tools.

        Gives the LLM awareness of available tools so it prefers calling them
        over writing scripts or shell commands for the same task. Full JSON
        schemas are still sent via the API's ``tools`` parameter.
        """
        if not self._registry:
            return ""

        by_category = self._registry.get_tools_by_category()
        if not by_category:
            return ""

        lines = [
            "## Available Tools\n",
            "You have specialized tools registered below. ALWAYS call the "
            "appropriate tool instead of writing code or shell commands to "
            "accomplish the same task.\n",
        ]

        for category in sorted(by_category):
            tools = by_category[category]
            entries = ", ".join(f"**{t.name}**" for t in tools)
            lines.append(f"- {category}: {entries}")

        lines.append(
            "\nWhen a user's request matches a tool's purpose, call it directly. "
            "For example, use **stock_quote** for stock prices, **web_search** "
            "for web queries, **web_fetch** to read a URL — never write a script "
            "or install a package for something a tool already handles."
        )

        return "\n".join(lines)

    def _build_skills_listing(self) -> str:
        """Build a compact name+description listing of available skills.

        Full skill content is NOT injected — the LLM can load a skill's
        instructions on demand via the read_file tool when needed.
        """
        from grip.skills.loader import SkillsLoader

        try:
            loader = SkillsLoader(self._workspace.root)
            skills = loader.scan()
        except Exception as exc:
            logger.debug("Failed to scan skills for system prompt: {}", exc)
            return ""

        if not skills:
            return ""

        lines = ["## Available Skills\n"]
        for s in skills:
            desc = f": {s.description}" if s.description else ""
            lines.append(f"- **{s.name}**{desc}")
        lines.append("\nUse the read_file tool to load a skill's full instructions when needed.")
        return "\n".join(lines)

    def _build_todos_section(self) -> str:
        """Read workspace/tasks.json and inject active (pending/in_progress) todos.

        Returns empty string when no tasks file exists or all tasks are done.
        This is NOT cached — tasks change during a run and must be fresh each call.
        """
        tasks_path = self._workspace.root / "tasks.json"
        if not tasks_path.exists():
            return ""

        try:
            todos = json.loads(tasks_path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            logger.debug("Failed to read tasks.json for system prompt: {}", exc)
            return ""

        active = [t for t in todos if t.get("status") in ("pending", "in_progress")]
        if not active:
            return ""

        status_icons = {"pending": "○", "in_progress": "◑"}
        lines = [f"## Active Tasks ({len(active)} remaining)\n"]
        for t in active:
            icon = status_icons.get(t.get("status", "pending"), "○")
            priority = t.get("priority", "")
            priority_label = f" [{priority}]" if priority else ""
            lines.append(
                f"{icon} [{t['id']}]{priority_label} {t['content']} — {t.get('status')}"
            )
        lines.append("\nUpdate tasks via todo_write as you progress through them.")
        return "\n".join(lines)

    @staticmethod
    def _build_metadata_section(
        session_key: str = "", channels: ChannelsConfig | None = None
    ) -> str:
        now = datetime.now(UTC)
        lines = [
            "## Runtime Info\n",
            f"- Current UTC time: {now.strftime('%Y-%m-%d %H:%M:%S')}",
            f"- Platform: {platform.system()} {platform.release()}",
            f"- Python: {platform.python_version()}",
            f"- grip version: {__version__}",
        ]
        if session_key:
            lines.append(f"- Session key: {session_key}")

        if channels:
            connected: list[str] = []
            for ch_name in ChannelsConfig.CHANNEL_NAMES:
                ch = getattr(channels, ch_name, None)
                if ch and ch.is_active():
                    ids = ", ".join(ch.allow_from) if ch.allow_from else "unknown"
                    connected.append(f"{ch_name} (chat_id: {ids})")
            if connected:
                lines.append(
                    "- Connected channels: "
                    + "; ".join(connected)
                    + ". Use send_message with the listed chat_id to reach the user."
                )
            else:
                lines.append("- Connected channels: none")

        return "\n".join(lines)
