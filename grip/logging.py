"""Logging configuration for grip using loguru.

Call `setup_logging()` once at startup. Provides:
- Console output with configurable verbosity
- Rotating file log at ~/.grip/logs/grip.log
"""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger


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
    logger.remove()

    if quiet:
        console_level = "WARNING"
    elif verbose:
        console_level = "DEBUG"
    else:
        console_level = "INFO"

    logger.add(
        sys.stderr,
        level=console_level,
        format="<level>{level:<8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - {message}",
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
