"""Event hooks system: pre/post callbacks for tool execution and LLM calls.

Hooks allow users to customize agent behavior at key execution points.
Hook functions are async callables registered by event name. Pre-hooks
can modify the data flowing through; post-hooks observe only.

Supported events:
  - pre_tool_execute(tool_name, params, ctx) -> modified params or None
  - post_tool_execute(tool_name, params, ctx, result) -> None
  - pre_llm_call(messages, model, tools) -> modified messages or None
  - post_llm_call(messages, model, response) -> None
  - message_received(inbound_message) -> modified message or None
  - message_sent(outbound_message) -> None

Hook modules are Python files in ~/.grip/hooks/ that export async
functions matching the event names above.
"""

from __future__ import annotations

import contextlib
import importlib.util
from collections import defaultdict
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

from loguru import logger

HookFn = Callable[..., Coroutine[Any, Any, Any]]


class HooksManager:
    """Registry and dispatcher for event hooks."""

    __slots__ = ("_hooks",)

    def __init__(self) -> None:
        self._hooks: dict[str, list[HookFn]] = defaultdict(list)

    def register(self, event: str, hook: HookFn) -> None:
        """Register a hook function for an event."""
        self._hooks[event].append(hook)
        logger.debug("Hook registered: {} (total: {})", event, len(self._hooks[event]))

    def unregister(self, event: str, hook: HookFn) -> None:
        """Remove a specific hook function from an event."""
        with contextlib.suppress(ValueError):
            self._hooks[event].remove(hook)

    def clear(self, event: str | None = None) -> None:
        """Clear hooks for a specific event, or all hooks if event is None."""
        if event:
            self._hooks[event].clear()
        else:
            self._hooks.clear()

    async def trigger(self, event: str, *args, **kwargs) -> Any:
        """Fire all hooks for an event in registration order.

        For pre-hooks (events starting with 'pre_'), if any hook returns
        a non-None value, that value replaces the first argument for
        subsequent hooks and is returned. This allows pre-hooks to
        modify data flowing through the pipeline.

        For post-hooks, return values are ignored.
        """
        hooks = self._hooks.get(event, [])
        if not hooks:
            return None

        is_pre_hook = event.startswith("pre_")
        modified_value = None

        for hook in hooks:
            try:
                result = await hook(*args, **kwargs)
                if is_pre_hook and result is not None:
                    modified_value = result
                    # Replace the first positional arg for the next hook
                    if args:
                        args = (result, *args[1:])
            except Exception as exc:
                logger.error("Hook '{}' failed: {}", event, exc)

        return modified_value

    def has_hooks(self, event: str) -> bool:
        return bool(self._hooks.get(event))

    @property
    def registered_events(self) -> list[str]:
        return [event for event, hooks in self._hooks.items() if hooks]

    def load_from_directory(self, hooks_dir: Path) -> int:
        """Load hook modules from a directory. Each .py file can export
        async functions named after hook events.

        Returns the number of hooks loaded.
        """
        if not hooks_dir.exists():
            return 0

        count = 0
        for py_file in sorted(hooks_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            loaded = self._load_module(py_file)
            count += loaded

        if count:
            logger.info("Loaded {} hooks from {}", count, hooks_dir)
        return count

    def _load_module(self, path: Path) -> int:
        """Import a Python module and register any hook functions it exports.

        Only loads files owned by the current user with no group/other write
        permissions to reduce the risk of loading tampered hook files.
        """
        known_events = {
            "pre_tool_execute",
            "post_tool_execute",
            "pre_llm_call",
            "post_llm_call",
            "message_received",
            "message_sent",
        }

        try:
            import os
            import stat

            st = path.stat()
            # Reject hooks not owned by the current user
            if st.st_uid != os.getuid():
                logger.warning(
                    "Skipping hook {} — not owned by current user (uid {})",
                    path, os.getuid(),
                )
                return 0
            # Reject hooks writable by group or others
            if st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
                logger.warning(
                    "Skipping hook {} — writable by group/others (mode {:o})",
                    path, st.st_mode,
                )
                return 0

            spec = importlib.util.spec_from_file_location(f"grip_hook_{path.stem}", path)
            if not spec or not spec.loader:
                return 0

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            count = 0
            for event_name in known_events:
                fn = getattr(module, event_name, None)
                if fn and callable(fn):
                    self.register(event_name, fn)
                    count += 1
                    logger.debug("Loaded hook: {}:{}", path.name, event_name)

            return count

        except Exception as exc:
            logger.error("Failed to load hook module {}: {}", path, exc)
            return 0
