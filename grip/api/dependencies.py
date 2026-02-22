"""Shared FastAPI dependencies injected into route handlers.

All dependencies pull from app.state which is populated during the
lifespan startup in app.py. Rate limiting checks both per-IP and
per-token limits before the request reaches the handler.
"""

from __future__ import annotations

import math

from fastapi import HTTPException, Request, status

from grip.api.rate_limit import SlidingWindowRateLimiter
from grip.config.schema import GripConfig
from grip.engines.types import EngineProtocol
from grip.memory.manager import MemoryManager
from grip.session.manager import SessionManager


def get_engine(request: Request) -> EngineProtocol:
    """Retrieve the Engine from app.state."""
    return request.app.state.engine


def get_session_mgr(request: Request) -> SessionManager:
    """Retrieve the SessionManager from app.state."""
    return request.app.state.session_mgr


def get_memory_mgr(request: Request) -> MemoryManager:
    """Retrieve the MemoryManager from app.state."""
    return request.app.state.memory_mgr


def get_config(request: Request) -> GripConfig:
    """Retrieve the GripConfig from app.state."""
    return request.app.state.config


def check_rate_limit(request: Request) -> None:
    """Enforce per-IP rate limiting. Raises 429 if exceeded.

    Uses the per-IP limiter stored on app.state. The client IP is
    extracted from X-Forwarded-For (for reverse proxy) or the
    direct connection address.
    """
    limiter: SlidingWindowRateLimiter = request.app.state.ip_rate_limiter
    client_ip = _get_client_ip(request)

    allowed, remaining, retry_after = limiter.is_allowed(client_ip)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
            headers={
                "Retry-After": str(math.ceil(retry_after)),
                "X-RateLimit-Remaining": "0",
            },
        )

    request.state.rate_limit_remaining = remaining


def check_token_rate_limit(request: Request, token: str) -> None:
    """Enforce per-token rate limiting after authentication.

    Called explicitly in authenticated routes alongside require_auth.
    Uses the per-token limiter stored on app.state.
    """
    limiter: SlidingWindowRateLimiter = request.app.state.token_rate_limiter

    allowed, remaining, retry_after = limiter.is_allowed(token)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
            headers={
                "Retry-After": str(math.ceil(retry_after)),
                "X-RateLimit-Remaining": "0",
            },
        )

    request.state.rate_limit_remaining = remaining


def _get_client_ip(request: Request) -> str:
    """Extract client IP from X-Forwarded-For or direct connection."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
