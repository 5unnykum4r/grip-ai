"""Importing grip must silence LiteLLM's noisy import-time warnings."""

from __future__ import annotations

import logging


def test_litellm_logger_silenced_on_grip_import():
    import grip  # noqa: F401

    # The bedrock/sagemaker pre-load warnings are emitted by the "LiteLLM"
    # logger at WARNING level; grip raises its threshold to ERROR on import.
    assert logging.getLogger("LiteLLM").level >= logging.ERROR
