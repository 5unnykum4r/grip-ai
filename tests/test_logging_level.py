"""Tests for runtime console log-level control (slim interactive output)."""

from __future__ import annotations

import io
import sys

from loguru import logger

import grip.logging as logging_mod
from grip.logging import set_console_level, setup_logging


def test_set_console_level_updates_level():
    setup_logging()
    assert logging_mod._console_level == "INFO"
    try:
        set_console_level("WARNING")
        assert logging_mod._console_level == "WARNING"
    finally:
        setup_logging()


def test_warning_level_hides_info_shows_warning():
    setup_logging()
    real_stderr = sys.stderr
    buf = io.StringIO()
    try:
        sys.stderr = buf
        set_console_level("WARNING")
        logger.info("HIDE_THIS_INFO_LINE")
        logger.warning("SHOW_THIS_WARNING")
        out = buf.getvalue()
        assert "HIDE_THIS_INFO_LINE" not in out
        assert "SHOW_THIS_WARNING" in out
    finally:
        sys.stderr = real_stderr
        setup_logging()


def test_info_visible_at_info_level():
    setup_logging()
    real_stderr = sys.stderr
    buf = io.StringIO()
    try:
        sys.stderr = buf
        set_console_level("INFO")
        logger.info("VISIBLE_INFO_LINE")
        assert "VISIBLE_INFO_LINE" in buf.getvalue()
    finally:
        sys.stderr = real_stderr
        setup_logging()
