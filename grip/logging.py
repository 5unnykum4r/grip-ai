"""Logging configuration for grip using loguru.

Call `setup_logging()` once at startup. Provides:
- Console output with configurable verbosity
- Rotating file log at ~/.grip/logs/grip.log

Call `reconfigure_console_sink(interactive=True)` when entering an
interactive prompt_toolkit session so log messages from background
threads render above the prompt with proper formatting.
"""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

_console_sink_id: int | None = None
_console_level: str = "INFO"
_CONSOLE_FORMAT = "<level>{level:<8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - {message}"
_INTERACTIVE_FORMAT = "\n" + _CONSOLE_FORMAT


def setup_logging(
    verbose: bool = False,
    quiet: bool = False,
    log_dir: Path | None = None,
) -> None:
    """Configure loguru sinks for console and file output.

    Args:
        verbose: Show DEBUG-level messages on console.
        quiet: Suppress console output below WARNING.
        log_dir: Directory for log files. Defaults to ~/.grip/logs.
    """
    global _console_sink_id, _console_level
    logger.remove()

    if quiet:
        _console_level = "WARNING"
    elif verbose:
        _console_level = "DEBUG"
    else:
        _console_level = "INFO"

    _console_sink_id = logger.add(
        sys.stderr,
        level=_console_level,
        format=_CONSOLE_FORMAT,
        colorize=True,
    )

    log_path = log_dir or (Path.home() / ".grip" / "logs")
    log_path.mkdir(parents=True, exist_ok=True)

    logger.add(
        log_path / "grip.log",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {name}:{function}:{line} - {message}",
        rotation="10 MB",
        retention=5,
        encoding="utf-8",
        enqueue=True,
    )


def reconfigure_console_sink(*, interactive: bool = False) -> None:
    """Swap the loguru console sink between normal and interactive modes.

    In normal mode, loguru writes ANSI-colorized output to sys.stderr.

    In interactive mode (prompt_toolkit active), loguru writes to
    sys.stdout instead — which is the only stream that patch_stdout()
    intercepts and renders above the prompt. A leading newline is added
    for visual spacing. ANSI colors are preserved (ERROR=red,
    WARNING=yellow) via colorize=True.

    Args:
        interactive: True when a prompt_toolkit session is active and
            patch_stdout(raw=True) has replaced sys.stdout with a proxy.
    """
    global _console_sink_id
    if _console_sink_id is not None:
        logger.remove(_console_sink_id)
    if interactive:
        _console_sink_id = logger.add(
            sys.stdout,
            level=_console_level,
            format=_INTERACTIVE_FORMAT,
            colorize=True,
        )
    else:
        _console_sink_id = logger.add(
            sys.stderr,
            level=_console_level,
            format=_CONSOLE_FORMAT,
            colorize=True,
        )
