"""Base class for all chat channel integrations.

Each channel (Telegram, Discord, Slack, etc.) implements this interface.
Channels receive messages from their platform, wrap them as InboundMessage,
and push onto the MessageBus. They also subscribe to OutboundMessage for
delivering agent replies back to the platform.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from loguru import logger

from grip.bus.events import OutboundMessage
from grip.bus.queue import MessageBus
from grip.config.schema import ChannelEntry


class BaseChannel(ABC):
    """Abstract base for all chat channel implementations."""

    def __init__(self, config: ChannelEntry) -> None:
        self._config = config
        self._bus: MessageBus | None = None

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique channel identifier (e.g. 'telegram', 'discord', 'slack')."""

    @abstractmethod
    async def start(self, bus: MessageBus) -> None:
        """Connect to the platform and begin receiving messages.

        Implementations should store the bus reference and call
        bus.push_inbound() when messages arrive, and subscribe to
        outbound messages via bus.subscribe_outbound().
        """

    @abstractmethod
    async def stop(self) -> None:
        """Disconnect from the platform and clean up resources."""

    @abstractmethod
    async def send(self, chat_id: str, text: str, **kwargs) -> None:
        """Send a text message to a specific chat/channel on the platform."""

    async def send_file(self, chat_id: str, file_path: str, caption: str = "") -> None:
        """Send a file to a specific chat/channel on the platform.

        Subclasses should override this to send photos for image files
        and documents for everything else. The default implementation
        falls back to sending the caption as a text message.
        """
        fallback = caption or f"[File: {file_path}]"
        await self.send(chat_id, fallback)

    def is_allowed(self, user_id: str) -> bool:
        """Check if a user ID is in the allowlist. Empty list allows everyone."""
        if not self._config.allow_from:
            return True
        return user_id in self._config.allow_from

    async def _handle_outbound(self, message: OutboundMessage) -> None:
        """Default outbound handler that routes messages to this channel."""
        if message.channel != self.name:
            return
        try:
            if message.file_path:
                await self.send_file(message.chat_id, message.file_path, message.text)
            else:
                await self.send(message.chat_id, message.text)
        except Exception as exc:
            logger.error("Failed to send on {}: {}", self.name, exc)

    @staticmethod
    def split_message(text: str, max_length: int) -> list[str]:
        """Split text into chunks that fit within platform message limits.

        Splits on newline boundaries when possible, falls back to hard
        split at max_length if no newline found within range.
        """
        if len(text) <= max_length:
            return [text]

        chunks: list[str] = []
        remaining = text
        while remaining:
            if len(remaining) <= max_length:
                chunks.append(remaining)
                break

            split_at = remaining.rfind("\n", 0, max_length)
            if split_at == -1 or split_at < max_length // 2:
                split_at = max_length

            chunks.append(remaining[:split_at])
            remaining = remaining[split_at:].lstrip("\n")

        return chunks
