"""Heartbeat service: periodic autonomous agent wake-up.

Reads HEARTBEAT.md from the workspace at a configurable interval and
sends its contents to the agent loop as a user message. This allows
the agent to perform periodic self-directed tasks like checking
system health, summarizing recent activity, or running maintenance.

If HEARTBEAT.md is missing or empty, the heartbeat is silently skipped.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from loguru import logger

from grip.config.schema import HeartbeatConfig

SESSION_KEY = "heartbeat:periodic"


class HeartbeatService:
    """Periodically reads HEARTBEAT.md and feeds it to the agent loop."""

    def __init__(
        self,
        workspace_root: Path,
        agent_loop: Any,
        config: HeartbeatConfig,
    ) -> None:
        self._workspace_root = workspace_root
        self._heartbeat_file = workspace_root / "HEARTBEAT.md"
        self._agent_loop = agent_loop
        self._config = config
        self._running = False

    async def start(self) -> None:
        """Start the heartbeat loop. Runs until cancelled."""
        if not self._config.enabled:
            logger.debug("Heartbeat service disabled")
            return

        self._running = True
        interval = self._config.interval_minutes * 60
        logger.info("Heartbeat service started (interval: {}min)", self._config.interval_minutes)

        while self._running:
            await asyncio.sleep(interval)
            await self._beat()

    async def stop(self) -> None:
        """Signal the heartbeat to stop."""
        self._running = False
        logger.debug("Heartbeat service stopped")

    async def _beat(self) -> None:
        """Read HEARTBEAT.md and send to agent if it has content."""
        if not self._heartbeat_file.exists():
            logger.debug("No HEARTBEAT.md found, skipping")
            return

        content = self._heartbeat_file.read_text(encoding="utf-8").strip()
        if not content:
            logger.debug("HEARTBEAT.md is empty, skipping")
            return

        logger.info("Heartbeat triggered ({} chars)", len(content))
        try:
            result = await self._agent_loop.run(content, session_key=SESSION_KEY)
            logger.info(
                "Heartbeat completed: {} iterations, {} tokens",
                result.iterations,
                result.total_usage.total_tokens,
            )
        except Exception as exc:
            logger.error("Heartbeat agent run failed: {}", exc)
