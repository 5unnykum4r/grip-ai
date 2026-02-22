"""Security middleware stack for the grip REST API.

Applied outermost-first during app setup:
  1. RequestSizeLimitMiddleware — rejects oversized bodies before parsing
  2. AuditLogMiddleware — logs every request with method/path/status/duration/IP
  3. SecurityHeadersMiddleware — adds defensive HTTP headers
"""

from __future__ import annotations

import time

from fastapi import Request, Response
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests with Content-Length exceeding the configured limit.

    Checks the Content-Length header before the body is read. Requests
    without Content-Length are allowed through (streaming/chunked), but
    will be bounded by uvicorn's own limits.
    """

    def __init__(self, app, max_bytes: int = 1_048_576) -> None:
        super().__init__(app)
        self._max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self._max_bytes:
            return JSONResponse(
                status_code=413,
                content={
                    "detail": f"Request body too large (max {self._max_bytes} bytes)",
                },
            )
        return await call_next(request)


class AuditLogMiddleware(BaseHTTPMiddleware):
    """Log every API request with method, path, status code, duration, and client IP."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        start = time.monotonic()
        client_ip = _get_client_ip(request)

        request_id = request.headers.get("x-request-id")
        if not request_id:
            import uuid

            request_id = uuid.uuid4().hex[:12]

        request.state.request_id = request_id

        response = await call_next(request)

        duration_ms = (time.monotonic() - start) * 1000
        logger.info(
            "API {} {} {} {:.0f}ms ip={} request_id={}",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            client_ip,
            request_id,
        )
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add defensive HTTP headers to every response.

    - X-Content-Type-Options: nosniff — prevent MIME type sniffing
    - X-Frame-Options: DENY — prevent clickjacking
    - Content-Security-Policy: default-src 'none' — block all resource loading
    - Cache-Control: no-store — prevent caching of API responses
    - X-Request-ID — echoed or generated for request tracing
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'none'"
        response.headers["Cache-Control"] = "no-store"

        request_id = getattr(request.state, "request_id", None)
        if request_id:
            response.headers["X-Request-ID"] = request_id

        return response


def _get_client_ip(request: Request) -> str:
    """Extract client IP, checking X-Forwarded-For for reverse proxy setups."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
