"""Async message bus connecting chat channels to the agent loop.

The bus decouples message producers (channels) from consumers (gateway).
Channels push InboundMessage onto the inbound queue. The gateway pops
from the queue, runs the agent, and publishes OutboundMessage to all
subscribed outbound listeners (channels that need to send the reply).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable, Coroutine
from typing import Any

from loguru import logger

from grip.bus.events import InboundMessage, OutboundMessage

OutboundListener = Callable[[OutboundMessage], Coroutine[Any, Any, None]]


class MessageBus:
    """Async message bus with an inbound queue and outbound pub/sub."""

    def __init__(self, max_queue_size: int = 256) -> None:
        self._inbound: asyncio.Queue[InboundMessage] = asyncio.Queue(maxsize=max_queue_size)
        self._outbound_listeners: list[OutboundListener] = []

    async def push_inbound(self, message: InboundMessage) -> None:
        """Called by channels to submit an incoming user message."""
        await self._inbound.put(message)
        logger.debug(
            "Inbound queued: channel={} chat_id={} len={}",
            message.channel,
            message.chat_id,
            len(message.text),
        )

    async def pop_inbound(self) -> InboundMessage:
        """Called by the gateway consumer to get the next message to process."""
        return await self._inbound.get()

    def subscribe_outbound(self, listener: OutboundListener) -> None:
        """Register a listener that receives all outbound messages."""
        self._outbound_listeners.append(listener)
        logger.debug("Outbound listener registered (total: {})", len(self._outbound_listeners))

    def unsubscribe_outbound(self, listener: OutboundListener) -> None:
        """Remove a previously registered outbound listener."""
        with contextlib.suppress(ValueError):
            self._outbound_listeners.remove(listener)

    async def publish_outbound(self, message: OutboundMessage) -> None:
        """Broadcast an outbound message to all subscribed listeners."""
        logger.debug(
            "Publishing outbound: channel={} chat_id={} len={}",
            message.channel,
            message.chat_id,
            len(message.text),
        )
        results = await asyncio.gather(
            *(listener(message) for listener in self._outbound_listeners),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, Exception):
                logger.error("Outbound listener error: {}", result)

    @property
    def inbound_pending(self) -> int:
        return self._inbound.qsize()

    @property
    def outbound_listener_count(self) -> int:
        return len(self._outbound_listeners)
