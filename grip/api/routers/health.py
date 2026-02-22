"""Health check endpoints.

GET /health — unauthenticated, for load balancer probes
GET /api/v1/health — authenticated, returns version + uptime
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request

from grip.api.auth import require_auth
from grip.api.dependencies import check_rate_limit

public_router = APIRouter(tags=["health"])
authed_router = APIRouter(prefix="/api/v1", tags=["health"])


@public_router.get("/health")
async def health_probe() -> dict:
    """Unauthenticated health check for load balancers and uptime monitors."""
    return {"status": "ok"}


@authed_router.get(
    "/health",
    dependencies=[Depends(check_rate_limit), Depends(require_auth)],
)
async def health_detail(request: Request) -> dict:
    """Authenticated health check with version and uptime."""
    start_time: float = request.app.state.start_time
    uptime_seconds = time.time() - start_time
    return {
        "status": "ok",
        "version": "0.1.1",
        "uptime_seconds": round(uptime_seconds, 1),
    }
