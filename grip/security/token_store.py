"""Secure OAuth token storage for MCP servers.

Tokens are stored in ~/.grip/tokens.json, separate from config.json to
prevent accidental leakage in config dumps or log output. File permissions
are set to 0o600 (owner read/write only) on creation.

Uses atomic writes (temp file + rename) following the same pattern as
grip.config.loader.save_config().
"""

from __future__ import annotations

import contextlib
import json
import os
import time
from pathlib import Path

from loguru import logger
from pydantic import BaseModel, Field


class StoredToken(BaseModel):
    """Persisted OAuth token data for a single MCP server."""

    access_token: str = ""
    refresh_token: str = ""
    expires_at: float = 0.0
    token_type: str = "Bearer"
    scopes: list[str] = Field(default_factory=list)

    @property
    def is_expired(self) -> bool:
        """Check if the access token has expired (with 30-second buffer)."""
        if self.expires_at <= 0:
            return False
        return time.time() >= (self.expires_at - 30)


class TokenStore:
    """File-backed OAuth token store.

    Reads and writes ~/.grip/tokens.json with atomic writes
    and restrictive file permissions (0o600).
    """

    def __init__(self, tokens_path: Path | None = None) -> None:
        self._path = tokens_path or Path("~/.grip/tokens.json").expanduser()

    def get(self, server_name: str) -> StoredToken | None:
        """Retrieve stored token for a server, or None if not found."""
        all_tokens = self._read_all()
        raw = all_tokens.get(server_name)
        if raw is None:
            return None
        return StoredToken(**raw)

    def save(self, server_name: str, token: StoredToken) -> None:
        """Save or update the token for a server."""
        all_tokens = self._read_all()
        all_tokens[server_name] = token.model_dump(mode="json")
        self._write_all(all_tokens)
        logger.debug("Saved OAuth token for MCP server '{}'", server_name)

    def delete(self, server_name: str) -> bool:
        """Remove the token for a server. Returns True if it existed."""
        all_tokens = self._read_all()
        if server_name not in all_tokens:
            return False
        del all_tokens[server_name]
        self._write_all(all_tokens)
        logger.debug("Deleted OAuth token for MCP server '{}'", server_name)
        return True

    def list_servers(self) -> list[str]:
        """Return names of all servers that have stored tokens."""
        return list(self._read_all().keys())

    def _read_all(self) -> dict[str, dict]:
        """Read the entire token store from disk."""
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read token store {}: {}", self._path, exc)
            return {}

    def _write_all(self, data: dict[str, dict]) -> None:
        """Atomically write the token store with restrictive permissions."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        with contextlib.suppress(OSError):
            os.chmod(tmp_path, 0o600)
        tmp_path.rename(self._path)
