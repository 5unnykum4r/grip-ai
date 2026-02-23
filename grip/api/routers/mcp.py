"""MCP server management endpoints for the grip REST API.

GET  /api/v1/mcp/servers           - List all MCP servers with status
GET  /api/v1/mcp/{server}/status   - Get status of a single server
POST /api/v1/mcp/{server}/login    - Initiate OAuth flow (explicit or gateway-mediated MCP)
GET  /api/v1/mcp/callback          - OAuth redirect callback handler (both flow types)
POST /api/v1/mcp/{server}/enable   - Enable a server
POST /api/v1/mcp/{server}/disable  - Disable a server
"""

from __future__ import annotations

import base64
import hashlib
import html as html_mod
import secrets
import time
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from loguru import logger
from pydantic import BaseModel

from grip.api.auth import require_auth
from grip.api.dependencies import get_config
from grip.config import save_config
from grip.config.schema import GripConfig
from grip.security.token_store import StoredToken, TokenStore
from grip.tools.mcp_auth import MCPTokenStorage

router = APIRouter(prefix="/api/v1/mcp", tags=["mcp"])


def _has_any_token(server_name: str) -> bool:
    """Check if a server has a stored access token in either token store.

    A client registration alone (mcp_clients.json) does not count — it only
    means we registered with the OAuth server, not that we have an access token.
    """
    if TokenStore().get(server_name) is not None:
        return True
    storage = MCPTokenStorage(server_name)
    return storage.has_stored_token()


class MCPServerStatus(BaseModel):
    name: str
    type: str
    enabled: bool
    has_oauth: bool
    has_token: bool
    needs_login: bool
    transport: str


class OAuthLoginResponse(BaseModel):
    auth_url: str | None = None
    server_name: str
    status: str = "pending"
    tools_discovered: int = 0


class MCPServersListResponse(BaseModel):
    servers: list[MCPServerStatus]
    total: int


def _build_server_status(name: str, srv: Any) -> MCPServerStatus:
    """Build MCPServerStatus for a configured server."""
    transport = srv.url if srv.url else f"{srv.command} {' '.join(srv.args)}"
    srv_type = srv.type or ("http" if srv.url else "stdio")
    has_token = _has_any_token(name)
    has_oauth = srv.oauth is not None or bool(srv.url)

    return MCPServerStatus(
        name=name,
        type=srv_type,
        enabled=srv.enabled,
        has_oauth=has_oauth,
        has_token=has_token,
        needs_login=has_oauth and not has_token and srv.enabled,
        transport=transport,
    )


@router.get("/servers", response_model=MCPServersListResponse)
async def list_mcp_servers(
    request: Request,
    token: str = Depends(require_auth),  # noqa: B008
    config: GripConfig = Depends(get_config),  # noqa: B008
) -> MCPServersListResponse:
    """List all configured MCP servers with their status."""
    servers = [
        _build_server_status(name, srv)
        for name, srv in config.tools.mcp_servers.items()
    ]
    return MCPServersListResponse(servers=servers, total=len(servers))


@router.get("/{server}/status", response_model=MCPServerStatus)
async def get_server_status(
    server: str,
    request: Request,
    token: str = Depends(require_auth),  # noqa: B008
    config: GripConfig = Depends(get_config),  # noqa: B008
) -> MCPServerStatus:
    """Get the status of a single MCP server."""
    srv = config.tools.mcp_servers.get(server)
    if srv is None:
        raise HTTPException(status_code=404, detail=f"MCP server '{server}' not found")
    return _build_server_status(server, srv)


@router.post("/{server}/login", response_model=OAuthLoginResponse)
async def initiate_login(
    server: str,
    request: Request,
    token: str = Depends(require_auth),  # noqa: B008
    config: GripConfig = Depends(get_config),  # noqa: B008
) -> OAuthLoginResponse:
    """Start OAuth flow for a server.

    Two modes:
    - Servers with explicit OAuthConfig: returns auth_url for the client to
      open. The callback is handled by GET /api/v1/mcp/callback.
    - HTTP/SSE servers without OAuthConfig (e.g. Supabase): triggers the MCP
      library's browser-based OAuth flow (opens browser on the server machine).
    """
    srv = config.tools.mcp_servers.get(server)
    if srv is None:
        raise HTTPException(status_code=404, detail=f"MCP server '{server}' not found")

    if srv.oauth:
        return _initiate_explicit_oauth(server, srv, request, config)

    if srv.url:
        return await _initiate_mcp_gateway_oauth(server, srv, request, config)

    raise HTTPException(
        status_code=400,
        detail=f"Server '{server}' has no URL or OAuth configuration",
    )


_OAUTH_STATE_TTL = 600  # 10 minutes
_OAUTH_STATE_MAX = 100


def _prune_oauth_pending(pending: dict[str, dict]) -> None:
    """Remove expired entries and cap the dict at _OAUTH_STATE_MAX."""
    now = time.time()
    expired = [k for k, v in pending.items() if now - v.get("created_at", 0) > _OAUTH_STATE_TTL]
    for k in expired:
        del pending[k]
    while len(pending) > _OAUTH_STATE_MAX:
        oldest_key = min(pending, key=lambda k: pending[k].get("created_at", 0))
        del pending[oldest_key]


def _initiate_explicit_oauth(
    server: str,
    srv: Any,
    request: Request,
    config: GripConfig,
) -> OAuthLoginResponse:
    """Build an auth URL for servers with explicit OAuthConfig."""
    from urllib.parse import urlencode

    state_token = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")

    if not hasattr(request.app.state, "oauth_pending"):
        request.app.state.oauth_pending = {}
    _prune_oauth_pending(request.app.state.oauth_pending)

    gateway_host = config.gateway.host
    gateway_port = config.gateway.port
    redirect_uri = f"http://{gateway_host}:{gateway_port}/api/v1/mcp/callback"

    request.app.state.oauth_pending[state_token] = {
        "flow_type": "explicit",
        "server_name": server,
        "code_verifier": code_verifier,
        "redirect_uri": redirect_uri,
        "token_url": srv.oauth.token_url,
        "client_id": srv.oauth.client_id,
        "created_at": time.time(),
    }

    params: dict[str, str] = {
        "client_id": srv.oauth.client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": state_token,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    if srv.oauth.scopes:
        params["scope"] = " ".join(srv.oauth.scopes)

    auth_url = f"{srv.oauth.auth_url}?{urlencode(params)}"
    return OAuthLoginResponse(auth_url=auth_url, server_name=server, status="pending")


async def _initiate_mcp_gateway_oauth(
    server: str, srv: Any, request: Request, config: GripConfig,
) -> OAuthLoginResponse:
    """Perform MCP OAuth discovery on the gateway and return an auth_url.

    Instead of opening a browser on the server machine, the gateway discovers
    the OAuth endpoints and registers a client, then returns an auth_url for
    the API client to open in the user's browser.
    """
    from urllib.parse import urlencode

    from grip.tools.mcp_auth import discover_mcp_oauth_metadata

    gateway_host = config.gateway.host
    gateway_port = config.gateway.port
    redirect_uri = f"http://{gateway_host}:{gateway_port}/api/v1/mcp/callback"

    logger.info("Starting gateway-mediated MCP OAuth for '{}'", server)
    oauth_metadata, client_info = await discover_mcp_oauth_metadata(
        server, srv.url, redirect_uri
    )

    code_verifier = secrets.token_urlsafe(64)
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    state_token = secrets.token_urlsafe(32)

    if not hasattr(request.app.state, "oauth_pending"):
        request.app.state.oauth_pending = {}
    _prune_oauth_pending(request.app.state.oauth_pending)

    request.app.state.oauth_pending[state_token] = {
        "flow_type": "mcp",
        "server_name": server,
        "code_verifier": code_verifier,
        "redirect_uri": redirect_uri,
        "token_url": str(oauth_metadata.token_endpoint),
        "client_id": client_info.client_id,
        "client_secret": getattr(client_info, "client_secret", None),
        "created_at": time.time(),
    }

    params: dict[str, str] = {
        "client_id": client_info.client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": state_token,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    if oauth_metadata.scopes_supported:
        params["scope"] = " ".join(oauth_metadata.scopes_supported)

    auth_url = f"{oauth_metadata.authorization_endpoint}?{urlencode(params)}"
    return OAuthLoginResponse(auth_url=auth_url, server_name=server, status="pending")


@router.get("/callback", response_class=HTMLResponse)
async def oauth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> HTMLResponse:
    """Handle the OAuth provider's redirect with the authorization code.

    This endpoint is public (no Bearer auth required) because the OAuth
    provider redirects the user's browser here.
    Handles both explicit OAuthConfig flows and gateway-mediated MCP OAuth flows.
    """
    if error:
        safe_error = html_mod.escape(error)
        error_html = (
            "<html><body><h1>Login Failed</h1>"
            f"<p>Error: {safe_error}</p></body></html>"
        )
        return HTMLResponse(content=error_html, status_code=400)

    if not state or not code:
        return HTMLResponse(
            content="<html><body><h1>Bad Request</h1><p>Missing code or state.</p></body></html>",
            status_code=400,
        )

    pending: dict[str, Any] = getattr(request.app.state, "oauth_pending", {})
    flow_data = pending.pop(state, None)
    if flow_data is None:
        return HTMLResponse(
            content="<html><body><h1>Invalid State</h1><p>Session expired or invalid.</p></body></html>",
            status_code=400,
        )

    if time.time() - flow_data["created_at"] > 300:
        return HTMLResponse(
            content="<html><body><h1>Expired</h1><p>Login session expired.</p></body></html>",
            status_code=400,
        )

    flow_type = flow_data.get("flow_type", "explicit")

    try:
        token_data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": flow_data["redirect_uri"],
            "client_id": flow_data["client_id"],
            "code_verifier": flow_data["code_verifier"],
        }
        if flow_type == "mcp" and flow_data.get("client_secret"):
            token_data["client_secret"] = flow_data["client_secret"]

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(flow_data["token_url"], data=token_data)

        if response.status_code not in (200, 201):
            logger.error("OAuth token exchange failed: {} {}", response.status_code, response.text[:200])
            return HTMLResponse(
                content="<html><body><h1>Login Failed</h1><p>Token exchange failed.</p></body></html>",
                status_code=500,
            )

        data = response.json()
        server_name = flow_data["server_name"]

        if flow_type == "mcp":
            from mcp.shared.auth import OAuthToken

            oauth_token = OAuthToken(
                access_token=data.get("access_token", ""),
                token_type=data.get("token_type", "Bearer"),
                expires_in=data.get("expires_in"),
                refresh_token=data.get("refresh_token"),
                scope=data.get("scope"),
            )
            mcp_storage = MCPTokenStorage(server_name)
            await mcp_storage.set_tokens(oauth_token)
            logger.info("MCP OAuth login successful for '{}'", server_name)
        else:
            expires_in = data.get("expires_in", 0)
            stored = StoredToken(
                access_token=data.get("access_token", ""),
                refresh_token=data.get("refresh_token", ""),
                expires_at=time.time() + expires_in if expires_in else 0.0,
                token_type=data.get("token_type", "Bearer"),
                scopes=data.get("scope", "").split() if data.get("scope") else [],
            )
            store = TokenStore()
            store.save(server_name, stored)
            logger.info("OAuth login successful for MCP server '{}'", server_name)

        html = (
            "<!DOCTYPE html><html><head><title>Login Successful</title></head>"
            "<body style='font-family:system-ui,sans-serif;display:flex;justify-content:center;"
            "align-items:center;height:100vh;margin:0;background:#f8f9fa;'>"
            "<div style='text-align:center;padding:2rem;background:white;border-radius:12px;"
            "box-shadow:0 2px 8px rgba(0,0,0,0.1);'>"
            "<h1 style='color:#22c55e;'>Login Successful!</h1>"
            "<p style='color:#64748b;'>You can close this tab and return to grip.</p>"
            "</div></body></html>"
        )
        return HTMLResponse(content=html, status_code=200)

    except Exception as exc:
        logger.error("OAuth callback error: {}", exc)
        return HTMLResponse(
            content="<html><body><h1>Error</h1><p>An unexpected error occurred.</p></body></html>",
            status_code=500,
        )


@router.post("/{server}/enable")
async def enable_server(
    server: str,
    request: Request,
    token: str = Depends(require_auth),  # noqa: B008
    config: GripConfig = Depends(get_config),  # noqa: B008
) -> dict:
    """Enable a disabled MCP server."""
    return _toggle_server(server, config, enabled=True)


@router.post("/{server}/disable")
async def disable_server(
    server: str,
    request: Request,
    token: str = Depends(require_auth),  # noqa: B008
    config: GripConfig = Depends(get_config),  # noqa: B008
) -> dict:
    """Disable an MCP server without deleting it."""
    return _toggle_server(server, config, enabled=False)


def _toggle_server(server: str, config: GripConfig, *, enabled: bool) -> dict:
    """Toggle the enabled state of a server and persist to config."""
    if server not in config.tools.mcp_servers:
        raise HTTPException(status_code=404, detail=f"MCP server '{server}' not found")

    data = config.model_dump(mode="json")
    data["tools"]["mcp_servers"][server]["enabled"] = enabled
    updated = GripConfig(**data)
    save_config(updated)

    state_str = "enabled" if enabled else "disabled"
    return {"server": server, "status": state_str}
