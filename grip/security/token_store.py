"""Secure OAuth token storage for MCP servers with automatic refresh.

Tokens are stored in ~/.grip/tokens.json, separate from config.json to
prevent accidental leakage in config dumps or log output. File permissions
are set to 0o600 (owner read/write only) on creation.

Uses atomic writes (temp file + rename) following the same pattern as
grip.config.loader.save_config().

Auto-refresh: get_valid() checks expiration and transparently refreshes
using the stored refresh_token before returning, so callers always get
a usable access_token without manual intervention.
"""

from __future__ import annotations

import asyncio
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

    @property
    def expires_in_seconds(self) -> float:
        """Seconds until expiration. Negative means already expired."""
        if self.expires_at <= 0:
            return float("inf")
        return self.expires_at - time.time()

    @property
    def needs_proactive_refresh(self) -> bool:
        """True if token expires within 5 minutes (proactive refresh window)."""
        if self.expires_at <= 0:
            return False
        return self.expires_in_seconds < 300


class TokenStore:
    """File-backed OAuth token store with automatic refresh support.

    Reads and writes ~/.grip/tokens.json with atomic writes
    and restrictive file permissions (0o600).
    """

    def __init__(self, tokens_path: Path | None = None) -> None:
        self._path = tokens_path or Path("~/.grip/tokens.json").expanduser()
        self._refresh_locks: dict[str, asyncio.Lock] = {}

    def get(self, server_name: str) -> StoredToken | None:
        """Retrieve stored token for a server, or None if not found."""
        all_tokens = self._read_all()
        raw = all_tokens.get(server_name)
        if raw is None:
            return None
        return StoredToken(**raw)

    async def get_valid(
        self,
        server_name: str,
        oauth_config: object | None = None,
    ) -> StoredToken | None:
        """Retrieve a valid (non-expired) token, auto-refreshing if needed.

        If the token is expired or about to expire and a refresh_token
        is available, this transparently performs the refresh, persists
        the new token, and returns it. Callers always receive a usable
        token or None.

        Args:
            server_name: MCP server name.
            oauth_config: OAuthConfig instance needed for refresh endpoint.
                          If None and token needs refresh, returns the
                          expired token as-is (caller must handle).
        """
        token = self.get(server_name)
        if token is None:
            return None

        if not token.needs_proactive_refresh:
            return token

        if not token.refresh_token:
            logger.warning(
                "Token for '{}' expires in {:.0f}s but has no refresh_token",
                server_name,
                token.expires_in_seconds,
            )
            return token

        if oauth_config is None:
            return token

        lock = self._refresh_locks.setdefault(server_name, asyncio.Lock())
        async with lock:
            fresh = self.get(server_name)
            if fresh and not fresh.needs_proactive_refresh:
                return fresh

            try:
                from grip.security.oauth import OAuthFlow

                flow = OAuthFlow(oauth_config, server_name)  # type: ignore[arg-type]
                new_token = await flow.refresh(token.refresh_token)
                self.save(server_name, new_token)
                logger.info(
                    "Auto-refreshed token for '{}' (valid for {:.0f}s)",
                    server_name,
                    new_token.expires_in_seconds,
                )
                return new_token
            except Exception as exc:
                logger.error("Auto-refresh failed for '{}': {}", server_name, exc)
                return token

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

    def list_expiring_soon(self, within_seconds: float = 300) -> list[tuple[str, StoredToken]]:
        """Return servers whose tokens expire within the given window."""
        results = []
        for name in self.list_servers():
            token = self.get(name)
            if token and 0 < token.expires_in_seconds < within_seconds:
                results.append((name, token))
        return results

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
