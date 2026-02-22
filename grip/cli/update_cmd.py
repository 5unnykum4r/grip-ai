"""grip update — pull the latest source and re-sync dependencies."""

from __future__ import annotations

import subprocess
from pathlib import Path

import typer
from rich.console import Console

console = Console()

# Root of the grip installation (two levels up from this file: grip/cli/ -> grip/ -> project root)
_INSTALL_DIR = Path(__file__).resolve().parent.parent.parent


def update_command(
    skip_deps: bool = typer.Option(  # noqa: B008
        False, "--skip-deps", help="Pull source only, skip dependency sync."
    ),
) -> None:
    """Pull the latest grip source and re-sync dependencies."""
    git_dir = _INSTALL_DIR / ".git"
    if not git_dir.is_dir():
        console.print(
            "[red]Error: grip was not installed via git. "
            "Cannot auto-update.[/red]\n"
            f"Expected git repo at: {_INSTALL_DIR}"
        )
        raise typer.Exit(1)

    console.print(f"[dim]Updating grip from {_INSTALL_DIR}[/dim]")

    # Step 1: git pull --ff-only (safe: refuses if local diverges)
    console.print("[cyan]Pulling latest changes...[/cyan]")
    result = subprocess.run(
        ["git", "-C", str(_INSTALL_DIR), "pull", "--ff-only"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        console.print(f"[red]git pull failed:[/red]\n{result.stderr.strip()}")
        console.print(
            "[yellow]Hint: You may have local changes. "
            "Commit or stash them first, then retry.[/yellow]"
        )
        raise typer.Exit(1)

    console.print(result.stdout.strip())

    # Step 2: re-sync dependencies
    if skip_deps:
        console.print("[dim]Skipping dependency sync (--skip-deps)[/dim]")
    else:
        console.print("[cyan]Syncing dependencies...[/cyan]")
        sync_result = subprocess.run(
            ["uv", "sync"],
            cwd=str(_INSTALL_DIR),
            capture_output=True,
            text=True,
        )
        if sync_result.returncode != 0:
            # Fall back to pip if uv is not installed
            console.print("[dim]uv not available, trying pip...[/dim]")
            sync_result = subprocess.run(
                ["pip", "install", "-e", "."],
                cwd=str(_INSTALL_DIR),
                capture_output=True,
                text=True,
            )
            if sync_result.returncode != 0:
                console.print(f"[red]Dependency sync failed:[/red]\n{sync_result.stderr.strip()}")
                raise typer.Exit(1)

        console.print("[dim]Dependencies synced.[/dim]")

    console.print("[bold green]grip updated successfully.[/bold green]")
