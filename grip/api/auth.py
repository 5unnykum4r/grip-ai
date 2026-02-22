"""Bearer token authentication for the grip REST API.

Auto-generates a grip_ prefixed token on first startup if none is configured.
All token comparisons use secrets.compare_digest to prevent timing attacks.
"""

from __future__ import annotations

import json
import secrets
import sys
from pathlib import Path

from fastapi import HTTPException, Request, status
from loguru import logger

from grip.config.schema import GripConfig

_GENERATED_TOKEN: str | None = None


def ensure_auth_token(config: GripConfig, config_path: Path | None) -> str:
    """Return the configured auth token, generating one if empty.

    When a token is auto-generated it is persisted to config.json so it
    survives restarts, and printed once to stderr so the operator can
    copy it.
    """
    global _GENERATED_TOKEN  # noqa: PLW0603

    token = config.gateway.api.auth_token
    if token:
        return token

    if _GENERATED_TOKEN:
        return _GENERATED_TOKEN

    token = f"grip_{secrets.token_urlsafe(32)}"
    _GENERATED_TOKEN = token

    _persist_token(config, config_path, token)

    print(
        f"\n  AUTH TOKEN (save this — shown only once):\n  {token}\n",
        file=sys.stderr,
        flush=True,
    )
    logger.info("Auto-generated API auth token (persisted to config.json)")
    return token


def _persist_token(config: GripConfig, config_path: Path | None, token: str) -> None:
    """Write the generated token back to the config JSON file."""
    resolved = config_path or Path("~/.grip/config.json").expanduser()
    if not resolved.exists():
        return

    try:
        data = json.loads(resolved.read_text(encoding="utf-8"))
        data.setdefault("gateway", {}).setdefault("api", {})["auth_token"] = token
        tmp = resolved.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.rename(resolved)
    except Exception as exc:
        logger.warning("Could not persist auto-generated token: {}", exc)


def require_auth(request: Request) -> str:
    """FastAPI dependency that validates the Bearer token.

    Extracts the token from the Authorization header, compares it
    against the configured token using timing-safe comparison, and
    returns the token on success. Raises 401 on any failure with a
    generic message to avoid leaking auth details.
    """
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    provided_token = auth_header[7:]
    expected_token: str = request.app.state.auth_token

    if not expected_token or not secrets.compare_digest(provided_token, expected_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return provided_token
