"""grip skills — manage agent skills.

Subcommands:
  grip skills list       Show all available skills
  grip skills install    Install a skill from a .md file
  grip skills remove     Remove a workspace skill by name
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from grip.config import load_config
from grip.skills.loader import SkillsLoader

console = Console()
skills_app = typer.Typer(no_args_is_help=True)


def _get_loader() -> SkillsLoader:
    from grip.cli.app import state

    config = load_config(state.config_path)
    ws_path = config.agents.defaults.workspace.expanduser().resolve()
    loader = SkillsLoader(ws_path)
    loader.scan()
    return loader


@skills_app.command(name="list")
def skills_list() -> None:
    """List all available skills (built-in and workspace)."""
    loader = _get_loader()
    skills = loader.list_skills()

    if not skills:
        console.print("[dim]No skills found.[/dim]")
        return

    table = Table(title="Skills")
    table.add_column("Name", style="cyan")
    table.add_column("Description")
    table.add_column("Source", style="dim")
    table.add_column("Always Loaded")

    for skill in skills:
        source = "built-in" if "builtin" in str(skill.source_path) else "workspace"
        always = "[green]Yes[/green]" if skill.always_loaded else "[dim]No[/dim]"
        table.add_row(skill.name, skill.description[:60], source, always)

    console.print(table)


@skills_app.command(name="install")
def skills_install(
    file_path: Path = typer.Argument(help="Path to a SKILL.md file to install."),  # noqa: B008
) -> None:
    """Install a skill from a markdown file into the workspace."""
    if not file_path.exists():
        console.print(f"[red]File not found:[/red] {file_path}")
        raise typer.Exit(1)

    content = file_path.read_text(encoding="utf-8")
    loader = _get_loader()
    installed_path = loader.install_skill(content, file_path.name)
    console.print(f"[green]Skill installed:[/green] {installed_path}")

    # Re-scan to verify
    loader.scan()
    skill = loader.get_skill(file_path.stem)
    if skill:
        console.print(f"  Name: {skill.name}")
        console.print(f"  Description: {skill.description}")


@skills_app.command(name="remove")
def skills_remove(
    name: str = typer.Argument(help="Name of the skill to remove."),  # noqa: B008
) -> None:
    """Remove a workspace skill by name (cannot remove built-in skills)."""
    loader = _get_loader()
    if loader.remove_skill(name):
        console.print(f"[green]Removed:[/green] {name}")
    else:
        console.print(f"[red]Cannot remove:[/red] {name} (not found or built-in)")
        raise typer.Exit(1)
