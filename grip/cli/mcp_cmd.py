"""grip mcp — manage MCP server configurations.

Subcommands:
  grip mcp add      Add an MCP server configuration
  grip mcp remove   Remove an MCP server configuration
  grip mcp list     List configured MCP servers
  grip mcp presets  Add popular MCP server presets (todoist, excalidraw, firecrawl, etc.)
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from grip.config import GripConfig, load_config, save_config

console = Console()
mcp_app = typer.Typer(no_args_is_help=True)

MCP_PRESETS: dict[str, dict] = {
    "todoist": {
        "command": "npx",
        "args": ["-y", "mcp-remote", "https://ai.todoist.net/mcp"],
    },
    "excalidraw": {
        "url": "https://mcp.excalidraw.com",
    },
    "firecrawl": {
        "command": "npx",
        "args": ["-y", "firecrawl-mcp"],
    },
    "bluesky": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-bluesky"],
    },
    "filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/"],
    },
    "git": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-git"],
    },
    "memory": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-memory"],
    },
    "postgres": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-postgres"],
    },
    "sqlite": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-sqlite"],
    },
    "fetch": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-fetch"],
    },
    "puppeteer": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-puppeteer"],
    },
    "stack": {
        "command": "npx",
        "args": ["-y", "mcp-remote", "mcp.stackoverflow.com"],
    },
    "tomba": {
        "command": "npx",
        "args": ["-y", "tomba-mcp-server"],
    },
}


@mcp_app.command(name="add")
def mcp_add(
    name: str = typer.Argument(..., help="Name for the MCP server (e.g., todoist, excalidraw)"),
    url: str | None = typer.Option(None, "--url", help="HTTP/SSE URL for the MCP server"),
    command: str | None = typer.Option(
        None, "--command", help="Command to run (e.g., npx, node, python)"
    ),
    args: str | None = typer.Option(
        None, "--args", help="Comma-separated arguments (e.g., -y,mcp-server)"
    ),
    header: list[str] | None = typer.Option(  # noqa: B008
        None, "--header", help="HTTP headers (e.g., Authorization:Bearer token)"
    ),
) -> None:
    """Add an MCP server configuration."""
    from grip.cli.app import state

    config = load_config(state.config_path)
    data = config.model_dump(mode="json")

    tools_config = data.setdefault("tools", {})
    mcp_servers = tools_config.setdefault("mcp_servers", {})

    if name in mcp_servers:
        console.print(f"[yellow]Warning: Overwriting existing MCP server '{name}'[/yellow]")

    server_config: dict = {}

    if url:
        server_config["url"] = url
    elif command:
        server_config["command"] = command
        if args:
            server_config["args"] = args.split(",")
    else:
        console.print("[red]Error: Must provide either --url or --command[/red]")
        raise typer.Exit(1)

    if header:
        headers = {}
        for h in header:
            if ":" in h:
                key, value = h.split(":", 1)
                headers[key.strip()] = value.strip()
        if headers:
            server_config["headers"] = headers

    mcp_servers[name] = server_config

    try:
        updated_config = GripConfig(**data)
    except Exception as exc:
        console.print(f"[red]Validation error: {exc}[/red]")
        raise typer.Exit(1) from exc

    save_config(updated_config, state.config_path)
    console.print(f"[green]Added MCP server '{name}'[/green]")
    _print_server_config(name, server_config)


@mcp_app.command(name="remove")
def mcp_remove(
    name: str = typer.Argument(..., help="Name of the MCP server to remove"),
) -> None:
    """Remove an MCP server configuration."""
    from grip.cli.app import state

    config = load_config(state.config_path)
    data = config.model_dump(mode="json")

    tools_config = data.get("tools", {})
    mcp_servers = tools_config.get("mcp_servers", {})

    if name not in mcp_servers:
        console.print(f"[red]Error: MCP server '{name}' not found[/red]")
        raise typer.Exit(1)

    del mcp_servers[name]

    try:
        updated_config = GripConfig(**data)
    except Exception as exc:
        console.print(f"[red]Validation error: {exc}[/red]")
        raise typer.Exit(1) from exc

    save_config(updated_config, state.config_path)
    console.print(f"[green]Removed MCP server '{name}'[/green]")


@mcp_app.command(name="list")
def mcp_list() -> None:
    """List all configured MCP servers."""
    from grip.cli.app import state

    config = load_config(state.config_path)
    mcp_servers = config.tools.mcp_servers

    if not mcp_servers:
        console.print("[yellow]No MCP servers configured[/yellow]")
        console.print("Use [cyan]grip mcp presets[/cyan] to add popular servers")
        return

    table = Table(title="Configured MCP Servers")
    table.add_column("Name", style="cyan")
    table.add_column("Type", style="magenta")
    table.add_column("Config", style="green")

    for name, srv in mcp_servers.items():
        if srv.url:
            config_str = srv.url
            srv_type = "HTTP"
        else:
            parts = [srv.command] + (srv.args or [])
            config_str = " ".join(parts)
            srv_type = "stdio"

        table.add_row(name, srv_type, config_str)

    console.print(table)


@mcp_app.command(name="presets")
def mcp_presets(
    servers: list[str] = typer.Argument(  # noqa: B008
        None,
        help="Server names to add (omit to see available presets)",
    ),
    all: bool = typer.Option(False, "--all", help="Add all available presets"),  # noqa: B008, A002
) -> None:
    """Add popular MCP server presets."""
    from grip.cli.app import state

    if not servers and not all:
        console.print("[bold]Available MCP Server Presets:[/bold]\n")
        table = Table()
        table.add_column("Name", style="cyan")
        table.add_column("Command/URL", style="green")

        for name, config in MCP_PRESETS.items():
            if "url" in config:
                detail = config["url"]
            else:
                detail = f"{config['command']} {' '.join(config.get('args', []))}"
            table.add_row(name, detail)

        console.print(table)
        console.print("\n[dim]Run: grip mcp presets <name> [<name>...][/dim]")
        console.print("[dim]Or:  grip mcp presets --all[/dim]")
        return

    servers_to_add = list(MCP_PRESETS.keys()) if all else servers

    config = load_config(state.config_path)
    data = config.model_dump(mode="json")

    tools_config = data.setdefault("tools", {})
    mcp_servers = tools_config.setdefault("mcp_servers", {})

    added: list[str] = []
    skipped: list[str] = []

    for name in servers_to_add:
        if name not in MCP_PRESETS:
            console.print(f"[yellow]Skipping unknown preset: {name}[/yellow]")
            skipped.append(name)
            continue

        mcp_servers[name] = MCP_PRESETS[name]
        added.append(name)

    if not added:
        console.print("[red]No servers added[/red]")
        raise typer.Exit(1)

    try:
        updated_config = GripConfig(**data)
    except Exception as exc:
        console.print(f"[red]Validation error: {exc}[/red]")
        raise typer.Exit(1) from exc

    save_config(updated_config, state.config_path)

    console.print(f"[green]Added {len(added)} MCP server(s): {', '.join(added)}[/green]")
    if skipped:
        console.print(f"[yellow]Skipped: {', '.join(skipped)}[/yellow]")


def _print_server_config(name: str, config: dict) -> None:
    """Print the server configuration in a nice format."""
    if "url" in config:
        console.print(f"  [dim]URL:[/dim] {config['url']}")
    if "command" in config:
        console.print(f"  [dim]Command:[/dim] {config['command']}")
    if "args" in config:
        console.print(f"  [dim]Args:[/dim] {' '.join(config['args'])}")
    if "env" in config:
        console.print(f"  [dim]Env:[/dim] {list(config['env'].keys())}")
    if "headers" in config:
        console.print(f"  [dim]Headers:[/dim] {list(config['headers'].keys())}")
