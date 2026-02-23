"""Interactive MCP server management for the /mcp slash command.

Displays all MCP servers with their connection status and provides
actions: Connect, Reconnect, Login, Disable, Enable, Delete.
Uses InquirerPy for interactive selection within the terminal.
"""

from __future__ import annotations

import asyncio
from enum import StrEnum
from typing import TYPE_CHECKING

from InquirerPy import inquirer
from rich.console import Console
from rich.table import Table

from grip.config import save_config
from grip.config.schema import GripConfig, MCPServerConfig
from grip.security.token_store import TokenStore

if TYPE_CHECKING:
    from grip.tools.mcp import MCPManager

console = Console()


class ServerStatus(StrEnum):
    CONNECTED = "Connected"
    DISCONNECTED = "Disconnected"
    AUTH_REQUIRED = "Auth Required"
    DISABLED = "Disabled"


def determine_status(
    server_name: str,
    config: MCPServerConfig,
    mcp_manager: MCPManager | None,
) -> ServerStatus:
    """Determine the display status of an MCP server."""
    if not config.enabled:
        return ServerStatus.DISABLED

    if mcp_manager:
        conn = mcp_manager.get_connection(server_name)
        if conn and conn.is_connected:
            return ServerStatus.CONNECTED
        if conn and conn.error == "OAuth login required":
            return ServerStatus.AUTH_REQUIRED

    if config.oauth:
        store = TokenStore()
        if store.get(server_name) is None:
            return ServerStatus.AUTH_REQUIRED

    if config.url:
        from grip.tools.mcp_auth import MCPTokenStorage

        storage = MCPTokenStorage(server_name)
        has_token = storage.has_stored_token()
        if not has_token:
            return ServerStatus.AUTH_REQUIRED

    return ServerStatus.DISCONNECTED


def _status_display(status: ServerStatus) -> str:
    """Return a Rich-formatted status string."""
    match status:
        case ServerStatus.CONNECTED:
            return "[green]Connected[/green]"
        case ServerStatus.DISCONNECTED:
            return "[red]Disconnected[/red]"
        case ServerStatus.AUTH_REQUIRED:
            return "[yellow]Auth Required[/yellow]"
        case ServerStatus.DISABLED:
            return "[dim]Disabled[/dim]"


def actions_for_status(status: ServerStatus) -> list[str]:
    """Return available actions based on server status."""
    match status:
        case ServerStatus.CONNECTED:
            return ["Reconnect", "Disable"]
        case ServerStatus.DISCONNECTED:
            return ["Connect", "Login", "Delete"]
        case ServerStatus.AUTH_REQUIRED:
            return ["Login", "Delete"]
        case ServerStatus.DISABLED:
            return ["Enable", "Delete"]
    return []


async def interactive_mcp(
    config: GripConfig,
    mcp_manager: MCPManager | None = None,
    config_path=None,
) -> None:
    """Run the interactive /mcp command.

    Shows a table of servers, lets the user select one,
    then presents context-appropriate actions.
    """
    servers = config.tools.mcp_servers
    if not servers:
        console.print("[dim]No MCP servers configured.[/dim]")
        console.print("Use [cyan]grip mcp presets[/cyan] to add servers.")
        return

    table = Table(title="MCP Servers")
    table.add_column("Name", style="cyan")
    table.add_column("Type", style="magenta")
    table.add_column("Status")
    table.add_column("Transport", style="dim")

    server_statuses: dict[str, ServerStatus] = {}
    for name, srv in servers.items():
        status = determine_status(name, srv, mcp_manager)
        server_statuses[name] = status
        transport = srv.url if srv.url else f"{srv.command} {' '.join(srv.args)}"
        srv_type = srv.type or ("HTTP" if srv.url else "stdio")
        table.add_row(name, srv_type, _status_display(status), transport)

    console.print(table)
    console.print()

    choices = [{"name": name, "value": name} for name in servers]
    choices.append({"name": "Cancel", "value": "_cancel"})

    selected = await asyncio.to_thread(
        lambda: inquirer.select(
            message="Select a server:",
            choices=choices,
        ).execute()
    )

    if selected == "_cancel":
        return

    status = server_statuses[selected]
    srv_config = servers[selected]

    available_actions = actions_for_status(status)
    action_choices = [{"name": a, "value": a} for a in available_actions]
    action_choices.append({"name": "Cancel", "value": "_cancel"})

    action = await asyncio.to_thread(
        lambda: inquirer.select(
            message=f"Action for '{selected}':",
            choices=action_choices,
        ).execute()
    )

    if action == "_cancel":
        return

    await _execute_action(action, selected, srv_config, config, mcp_manager, config_path)


async def _execute_action(
    action: str,
    server_name: str,
    srv_config: MCPServerConfig,
    config: GripConfig,
    mcp_manager: MCPManager | None,
    config_path=None,
) -> None:
    """Execute the selected action on the MCP server."""
    match action:
        case "Login":
            await _handle_login(server_name, srv_config, mcp_manager)
        case "Connect":
            await _handle_connect(server_name, srv_config, mcp_manager)
        case "Reconnect":
            await _handle_reconnect(server_name, srv_config, mcp_manager)
        case "Disable":
            _handle_toggle(server_name, config, enabled=False, config_path=config_path)
        case "Enable":
            _handle_toggle(server_name, config, enabled=True, config_path=config_path)
        case "Delete":
            _handle_delete(server_name, config, config_path=config_path)


async def _handle_login(
    server_name: str,
    srv_config: MCPServerConfig,
    mcp_manager: MCPManager | None = None,
) -> None:
    """Execute the OAuth flow for the selected server.

    For servers with explicit OAuthConfig: uses grip's OAuthFlow.
    For HTTP/SSE servers without OAuthConfig (e.g. Supabase): performs
    MCP OAuth discovery, opens the browser for the user to authorize,
    waits for the callback, and exchanges the code for tokens (including
    client_secret which providers like Supabase require).

    After a successful login, automatically reconnects the server so
    its tools become available in the current session.
    """
    login_ok = False

    if srv_config.oauth:
        from grip.security.oauth import OAuthFlow, OAuthFlowError

        flow = OAuthFlow(srv_config.oauth, server_name)
        console.print(f"[dim]Opening browser for {server_name} login...[/dim]")
        try:
            token = await flow.execute()
            store = TokenStore()
            store.save(server_name, token)
            console.print(f"[green]Login successful for '{server_name}'![/green]")
            login_ok = True
        except OAuthFlowError as exc:
            console.print(f"[red]Login failed: {exc}[/red]")

    elif srv_config.url:
        login_ok = await _handle_mcp_oauth_login(server_name, srv_config.url)

    else:
        console.print("[red]No OAuth configuration for this server.[/red]")

    if login_ok:
        await _auto_reconnect(server_name, srv_config, mcp_manager)


async def _handle_mcp_oauth_login(server_name: str, server_url: str) -> bool:
    """Perform MCP OAuth discovery, browser login, and token exchange.

    Returns True on success, False on failure.

    1. Discover OAuth endpoints and register a dynamic client
    2. Build an authorization URL with PKCE
    3. Open the browser and wait for the callback on localhost
    4. Exchange the authorization code for tokens (with client_secret)
    5. Store tokens in MCPTokenStorage for automatic use on reconnect
    """
    import base64
    import hashlib
    import secrets
    from urllib.parse import urlencode

    import httpx
    from mcp.shared.auth import OAuthToken

    from grip.tools.mcp_auth import (
        _DEFAULT_CALLBACK_PORT,
        MCPTokenStorage,
        _open_browser,
        _wait_for_oauth_callback,
        discover_mcp_oauth_metadata,
    )

    redirect_uri = f"http://localhost:{_DEFAULT_CALLBACK_PORT}/callback"

    console.print(f"[dim]Discovering OAuth endpoints for {server_name}...[/dim]")
    try:
        oauth_metadata, client_info = await discover_mcp_oauth_metadata(
            server_name, server_url, redirect_uri
        )
    except RuntimeError as exc:
        console.print(f"[red]OAuth discovery failed: {exc}[/red]")
        return False

    code_verifier = secrets.token_urlsafe(64)
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")

    params: dict[str, str] = {
        "client_id": client_info.client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    if oauth_metadata.scopes_supported:
        params["scope"] = " ".join(oauth_metadata.scopes_supported)

    auth_url = f"{oauth_metadata.authorization_endpoint}?{urlencode(params)}"

    await _open_browser(auth_url)

    console.print("[dim]Waiting for OAuth callback...[/dim]")
    try:
        code, _state = await _wait_for_oauth_callback(port=_DEFAULT_CALLBACK_PORT)
    except (RuntimeError, TimeoutError) as exc:
        console.print(f"[red]OAuth callback failed: {exc}[/red]")
        return False

    token_data: dict[str, str] = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_info.client_id,
        "code_verifier": code_verifier,
    }
    client_secret = getattr(client_info, "client_secret", None)
    if client_secret:
        token_data["client_secret"] = client_secret

    try:
        async with httpx.AsyncClient(timeout=30) as http_client:
            response = await http_client.post(
                str(oauth_metadata.token_endpoint), data=token_data
            )

        if response.status_code not in (200, 201):
            console.print(
                f"[red]Token exchange failed ({response.status_code}): "
                f"{response.text[:200]}[/red]"
            )
            return False

        data = response.json()
        oauth_token = OAuthToken(
            access_token=data.get("access_token", ""),
            token_type=data.get("token_type", "Bearer"),
            expires_in=data.get("expires_in"),
            refresh_token=data.get("refresh_token"),
            scope=data.get("scope"),
        )

        storage = MCPTokenStorage(server_name)
        await storage.set_tokens(oauth_token)
        console.print(f"[green]Login successful for '{server_name}'![/green]")
        return True

    except Exception as exc:
        console.print(f"[red]Token exchange error: {exc}[/red]")
        return False


async def _auto_reconnect(
    server_name: str,
    srv_config: MCPServerConfig,
    mcp_manager: MCPManager | None,
) -> None:
    """Automatically reconnect to a server after successful login.

    Uses MCPManager.reconnect_server() to disconnect the old (failed)
    connection, establish a new one with the freshly stored token, and
    register the discovered tools in the ToolRegistry.
    """
    if mcp_manager is None:
        console.print("[dim]Server will connect automatically on next agent run.[/dim]")
        return

    console.print(f"[dim]Connecting to {server_name}...[/dim]")
    tools = await mcp_manager.reconnect_server(server_name, srv_config)
    conn = mcp_manager.get_connection(server_name)
    if conn and conn.is_connected:
        console.print(f"[green]Connected to '{server_name}' ({len(tools)} tools available)[/green]")
    else:
        error = conn.error if conn else "unknown"
        console.print(f"[yellow]Login succeeded but connection failed: {error}[/yellow]")
        console.print("[dim]Tools will be available after restarting the session.[/dim]")


async def _handle_connect(
    server_name: str,
    srv_config: MCPServerConfig,
    mcp_manager: MCPManager | None,
) -> None:
    """Attempt to connect to the MCP server."""
    if mcp_manager is None:
        console.print("[dim]Direct connection not available in SDK engine mode.[/dim]")
        console.print("[dim]The server will connect automatically on next agent run.[/dim]")
        return

    from grip.tools.mcp import MCPConnection

    console.print(f"[dim]Connecting to {server_name}...[/dim]")
    conn = MCPConnection(server_name, srv_config)
    tools = await conn.connect()
    if conn.is_connected:
        console.print(f"[green]Connected to '{server_name}' ({len(tools)} tools)[/green]")
    else:
        console.print(f"[red]Failed to connect: {conn.error}[/red]")


async def _handle_reconnect(
    server_name: str,
    srv_config: MCPServerConfig,
    mcp_manager: MCPManager | None,
) -> None:
    """Disconnect and reconnect to the MCP server."""
    if mcp_manager is None:
        console.print("[dim]Reconnection not available in SDK engine mode.[/dim]")
        return

    existing = mcp_manager.get_connection(server_name)
    if existing:
        await existing.disconnect()
        console.print(f"[dim]Disconnected from {server_name}[/dim]")

    await _handle_connect(server_name, srv_config, mcp_manager)


def _handle_toggle(
    server_name: str,
    config: GripConfig,
    *,
    enabled: bool,
    config_path=None,
) -> None:
    """Toggle the enabled state of a server and persist to config."""
    data = config.model_dump(mode="json")
    tools_section = data.get("tools", {})
    mcp_servers = tools_section.get("mcp_servers", {})

    if server_name in mcp_servers:
        mcp_servers[server_name]["enabled"] = enabled

    updated = GripConfig(**data)
    save_config(updated, config_path)

    state_str = "enabled" if enabled else "disabled"
    console.print(f"[green]Server '{server_name}' {state_str}[/green]")


def _handle_delete(server_name: str, config: GripConfig, config_path=None) -> None:
    """Remove the server from config and persist."""
    data = config.model_dump(mode="json")
    tools_section = data.get("tools", {})
    mcp_servers = tools_section.get("mcp_servers", {})

    if server_name in mcp_servers:
        del mcp_servers[server_name]

    updated = GripConfig(**data)
    save_config(updated, config_path)

    store = TokenStore()
    store.delete(server_name)

    console.print(f"[green]Deleted server '{server_name}'[/green]")
