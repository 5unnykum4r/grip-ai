"""grip status — display system status overview."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from grip.config import load_config
from grip.providers.registry import ProviderRegistry
from grip.session import SessionManager
from grip.workspace import WorkspaceManager

console = Console()


def status_command() -> None:
    """Show system status: provider, workspace, sessions, channels, memory."""
    from grip.cli.app import state

    config = load_config(state.config_path)
    defaults = config.agents.defaults

    # Provider info
    model_str = defaults.model
    try:
        spec, bare_model = ProviderRegistry.resolve_model(model_str)
        provider_display = f"{spec.display_name} ({bare_model})"
    except ValueError:
        provider_display = model_str

    # Workspace info
    ws_path = defaults.workspace.expanduser().resolve()
    ws = WorkspaceManager(ws_path)
    ws_status = "Initialized" if ws.is_initialized else "Not initialized"

    # Session count
    sessions_dir = ws_path / "sessions"
    session_count = 0
    if sessions_dir.exists():
        session_mgr = SessionManager(sessions_dir)
        session_count = len(session_mgr.list_sessions())

    # Memory file sizes
    memory_path = ws_path / "memory" / "MEMORY.md"
    history_path = ws_path / "memory" / "HISTORY.md"
    memory_size = _file_size(memory_path)
    history_size = _file_size(history_path)

    # MCP server count
    mcp_count = len(config.tools.mcp_servers)

    # Build main status table
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Key", style="bold")
    table.add_column("Value")

    table.add_row("Provider", provider_display)
    table.add_row("Model", model_str)
    table.add_row("Max Tokens", str(defaults.max_tokens))
    table.add_row("Temperature", str(defaults.temperature))
    table.add_row("Tool Iterations", str(defaults.max_tool_iterations))
    table.add_row("Memory Window", str(defaults.memory_window))
    table.add_row("", "")
    table.add_row("Workspace", str(ws_path))
    table.add_row("Workspace Status", ws_status)
    table.add_row("Sessions", str(session_count))
    table.add_row("MEMORY.md", memory_size)
    table.add_row("HISTORY.md", history_size)
    table.add_row("", "")
    table.add_row("Sandbox Mode", "Enabled" if config.tools.restrict_to_workspace else "Disabled")
    table.add_row("Shell Timeout", f"{config.tools.shell_timeout}s")
    table.add_row("MCP Servers", str(mcp_count))

    # Channels status
    channels_info: list[str] = []
    for name in ("telegram", "discord", "slack"):
        ch = getattr(config.channels, name, None)
        if ch and ch.enabled:
            channels_info.append(f"{name} [green](enabled)[/green]")
        else:
            channels_info.append(f"{name} [dim](disabled)[/dim]")

    table.add_row("", "")
    table.add_row("Channels", ", ".join(channels_info))

    hb = config.heartbeat
    hb_display = f"Every {hb.interval_minutes}min" if hb.enabled else "Disabled"
    table.add_row("Heartbeat", hb_display)

    # Configured providers
    configured = []
    for pname, entry in config.providers.items():
        has_key = bool(entry.api_key)
        marker = "[green]key set[/green]" if has_key else "[dim]no key[/dim]"
        configured.append(f"{pname} ({marker})")
    if configured:
        table.add_row("", "")
        table.add_row("Providers", configured[0])
        for p in configured[1:]:
            table.add_row("", p)

    console.print(Panel(table, title="[bold cyan]grip Status[/bold cyan]", expand=False))


def _file_size(path: Path) -> str:
    if not path.exists():
        return "[dim]not created[/dim]"
    size = path.stat().st_size
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    else:
        return f"{size / (1024 * 1024):.1f} MB"
