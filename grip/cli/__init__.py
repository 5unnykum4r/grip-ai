"""grip CLI entry point.

The typer app is the `grip` command registered in pyproject.toml.
"""

from grip.cli.app import app

__all__ = ["app"]
