"""Session management endpoints for the grip REST API.

GET  /api/v1/sessions         — list all session keys
GET  /api/v1/sessions/{key}   — session detail (message count, timestamps)
DELETE /api/v1/sessions/{key} — delete a session
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Request, status

from grip.api.auth import require_auth
from grip.api.dependencies import check_rate_limit, check_token_rate_limit, get_session_mgr
from grip.session.manager import SessionManager

router = APIRouter(prefix="/api/v1", tags=["sessions"])


@router.get(
    "/sessions",
    dependencies=[Depends(check_rate_limit)],
)
async def list_sessions(
    request: Request,
    token: str = Depends(require_auth),
    session_mgr: SessionManager = Depends(get_session_mgr),  # noqa: B008
) -> dict:
    """List all session keys with metadata."""
    check_token_rate_limit(request, token)

    keys = session_mgr.list_sessions()
    return {"sessions": keys, "count": len(keys)}


@router.get(
    "/sessions/{key:path}",
    dependencies=[Depends(check_rate_limit)],
)
async def get_session(
    key: str,
    request: Request,
    token: str = Depends(require_auth),
    session_mgr: SessionManager = Depends(get_session_mgr),  # noqa: B008
) -> dict:
    """Get detail for a single session."""
    check_token_rate_limit(request, token)

    session = session_mgr.get(key)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )

    return {
        "key": session.key,
        "message_count": session.message_count,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "age_seconds": round(time.time() - session.created_at, 1),
    }


@router.delete(
    "/sessions/{key:path}",
    dependencies=[Depends(check_rate_limit)],
)
async def delete_session(
    key: str,
    request: Request,
    token: str = Depends(require_auth),
    session_mgr: SessionManager = Depends(get_session_mgr),  # noqa: B008
) -> dict:
    """Delete a session by key."""
    check_token_rate_limit(request, token)

    deleted = session_mgr.delete(key)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )
    return {"deleted": True, "key": key}
