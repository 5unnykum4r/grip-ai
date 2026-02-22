"""grip serve — standalone REST API server without channels/cron/heartbeat.

Good for API-only deployments where you only need the HTTP interface
and don't want to run Telegram/Discord/Slack channels or the cron scheduler.

Start: grip serve
       grip serve --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import typer
from rich.console import Console

console = Console()


def serve_command(
    host: str = typer.Option(None, "--host", "-H", help="Bind address (overrides config)."),  # noqa: B008
    port: int = typer.Option(None, "--port", "-p", help="Bind port (overrides config)."),  # noqa: B008
) -> None:
    """Start the grip REST API server (standalone, no channels)."""
    from grip.api import is_available

    if not is_available():
        console.print(
            "[red]API dependencies not installed.[/red]\n"
            "Install with: [bold]pip install grip[api][/bold]  or  [bold]uv pip install grip[api][/bold]"
        )
        raise typer.Exit(1)

    from grip.cli.app import state
    from grip.config import load_config

    config = load_config(state.config_path)

    bind_host = host or config.gateway.host
    bind_port = port or config.gateway.port

    console.print(f"[bold cyan]grip API server[/bold cyan] starting on {bind_host}:{bind_port}")

    import uvicorn

    from grip.api.app import create_api_app

    app = create_api_app(config, state.config_path)
    uvicorn.run(
        app,
        host=bind_host,
        port=bind_port,
        log_level="warning",
        access_log=False,
    )
