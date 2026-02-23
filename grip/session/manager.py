"""Session persistence: stores conversation history per channel+user.

Each session is a JSON file containing the message history, an optional
summary of older messages, and timestamps. Writes use temp-file-then-rename
for crash safety (atomic writes).
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

from grip.providers.types import LLMMessage, ToolCall


@dataclass(slots=True)
class Session:
    """A single conversation session with its message history."""

    key: str
    messages: list[LLMMessage] = field(default_factory=list)
    summary: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def add_message(self, msg: LLMMessage) -> None:
        self.messages.append(msg)
        self.updated_at = time.time()

    def get_recent(self, window: int) -> list[LLMMessage]:
        """Return the last `window` messages for LLM context."""
        if len(self.messages) <= window:
            return list(self.messages)
        return self.messages[-window:]

    def get_old_messages(self, window: int) -> list[LLMMessage]:
        """Return messages older than the recent `window` (candidates for consolidation)."""
        if len(self.messages) <= window:
            return []
        return self.messages[:-window]

    def prune_to_window(self, window: int) -> int:
        """Remove messages older than the recent `window`. Returns count of pruned messages."""
        if len(self.messages) <= window:
            return 0
        pruned_count = len(self.messages) - window
        self.messages = self.messages[-window:]
        self.updated_at = time.time()
        return pruned_count

    @property
    def message_count(self) -> int:
        return len(self.messages)


def _sanitize_key(key: str) -> str:
    """Convert a session key to a safe filename."""
    return re.sub(r"[^\w\-.]", "_", key)


def _message_to_dict(msg: LLMMessage) -> dict[str, Any]:
    """Serialize an LLMMessage to a JSON-safe dict."""
    d: dict[str, Any] = {"role": msg.role}
    if msg.content is not None:
        d["content"] = msg.content
    if msg.tool_calls:
        d["tool_calls"] = [
            {
                "id": tc.id,
                "function_name": tc.function_name,
                "arguments": tc.arguments,
            }
            for tc in msg.tool_calls
        ]
    if msg.tool_call_id is not None:
        d["tool_call_id"] = msg.tool_call_id
    if msg.name is not None:
        d["name"] = msg.name
    return d


def _dict_to_message(d: dict[str, Any]) -> LLMMessage:
    """Deserialize a dict back into an LLMMessage."""
    tool_calls = [
        ToolCall(
            id=tc["id"],
            function_name=tc["function_name"],
            arguments=tc["arguments"],
        )
        for tc in d.get("tool_calls", [])
    ]
    return LLMMessage(
        role=d["role"],
        content=d.get("content"),
        tool_calls=tool_calls,
        tool_call_id=d.get("tool_call_id"),
        name=d.get("name"),
    )


def _session_to_dict(session: Session) -> dict[str, Any]:
    return {
        "key": session.key,
        "messages": [_message_to_dict(m) for m in session.messages],
        "summary": session.summary,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
    }


def _dict_to_session(d: dict[str, Any]) -> Session:
    return Session(
        key=d["key"],
        messages=[_dict_to_message(m) for m in d.get("messages", [])],
        summary=d.get("summary"),
        created_at=d.get("created_at", time.time()),
        updated_at=d.get("updated_at", time.time()),
    )


class SessionManager:
    """Manages conversation session files on disk.

    Sessions are stored as individual JSON files in the sessions/ directory
    within the workspace. All writes are atomic (temp file + rename).
    """

    _DEFAULT_MAX_CACHE = 200

    def __init__(self, sessions_dir: Path, max_cache_size: int = _DEFAULT_MAX_CACHE) -> None:
        self._dir = sessions_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, Session] = {}
        self._max_cache_size = max_cache_size

    def _path_for(self, key: str) -> Path:
        return self._dir / f"{_sanitize_key(key)}.json"

    def get(self, key: str) -> Session | None:
        """Load an existing session, or return None if it doesn't exist."""
        if key in self._cache:
            return self._cache[key]

        path = self._path_for(key)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            session = _dict_to_session(data)
            self._cache[key] = session
            self._evict_if_needed()
            return session
        except (json.JSONDecodeError, KeyError) as exc:
            logger.warning("Corrupt session file {}: {}", path, exc)
            return None

    def get_or_create(self, key: str) -> Session:
        """Load an existing session from disk, or create a new empty one."""
        if key in self._cache:
            return self._cache[key]

        path = self._path_for(key)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                session = _dict_to_session(data)
                self._cache[key] = session
                logger.debug("Loaded session '{}' ({} messages)", key, session.message_count)
                return session
            except (json.JSONDecodeError, KeyError) as exc:
                logger.warning("Corrupt session file {}, creating new: {}", path, exc)

        session = Session(key=key)
        self._cache[key] = session
        self._evict_if_needed()
        logger.debug("Created new session: {}", key)
        return session

    def save(self, session: Session) -> None:
        """Persist a session to disk atomically."""
        session.updated_at = time.time()
        path = self._path_for(session.key)
        tmp_path = path.with_suffix(".tmp")

        data = _session_to_dict(session)
        tmp_path.write_text(
            json.dumps(data, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        tmp_path.rename(path)

        self._cache[session.key] = session
        self._evict_if_needed()
        logger.debug("Saved session '{}' ({} messages)", session.key, session.message_count)

    def delete(self, key: str) -> bool:
        """Remove a session from disk and cache."""
        self._cache.pop(key, None)
        path = self._path_for(key)
        if path.exists():
            path.unlink()
            logger.debug("Deleted session: {}", key)
            return True
        return False

    def list_sessions(self) -> list[str]:
        """Return all session keys found on disk.

        Uses the in-memory cache for sessions already loaded (avoids
        re-reading their JSON files). Only reads JSON for sessions
        not yet in cache.
        """
        keys: set[str] = set(self._cache.keys())
        cached_stems = {_sanitize_key(k) for k in keys}
        for path in self._dir.glob("*.json"):
            if path.stem in cached_stems:
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                keys.add(data["key"])
            except (json.JSONDecodeError, KeyError):
                keys.add(path.stem)
        return sorted(keys)

    def _evict_if_needed(self) -> None:
        """Evict least-recently-updated sessions when cache exceeds max size."""
        if len(self._cache) <= self._max_cache_size:
            return
        sorted_keys = sorted(self._cache, key=lambda k: self._cache[k].updated_at)
        excess = len(self._cache) - self._max_cache_size
        for key in sorted_keys[:excess]:
            del self._cache[key]

    def clear_cache(self) -> None:
        """Drop all in-memory cached sessions."""
        self._cache.clear()
