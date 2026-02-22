"""Discord channel integration using discord.py (async native).

Requires: pip install grip[channels-discord]
Config: config.channels.discord.enabled = true, .token = "BOT_TOKEN"
Optional: config.channels.discord.allow_from = ["user_id_1", "user_id_2"]
"""

from __future__ import annotations

import asyncio
import contextlib

from loguru import logger

from grip.bus.events import InboundMessage
from grip.bus.queue import MessageBus
from grip.channels.base import BaseChannel
from grip.config.schema import ChannelEntry

DISCORD_MAX_MESSAGE_LENGTH = 2000


class DiscordChannel(BaseChannel):
    """Discord bot channel via discord.py library."""

    def __init__(self, config: ChannelEntry) -> None:
        super().__init__(config)
        self._client = None
        self._ready_event = asyncio.Event()
        self._task: asyncio.Task | None = None

    @property
    def name(self) -> str:
        return "discord"

    async def start(self, bus: MessageBus) -> None:
        try:
            import discord
        except ImportError as exc:
            raise RuntimeError(
                "discord.py is required for Discord channel. "
                "Install with: uv pip install grip[channels-discord]"
            ) from exc

        self._bus = bus
        bus.subscribe_outbound(self._handle_outbound)

        token = self._config.token
        if not token:
            raise ValueError("Discord bot token is required (config.channels.discord.token)")

        intents = discord.Intents.default()
        intents.message_content = True
        self._client = discord.Client(intents=intents)
        channel_ref = self

        @self._client.event
        async def on_ready():
            logger.info("Discord bot connected as {}", self._client.user)
            self._ready_event.set()

        @self._client.event
        async def on_message(message: discord.Message):
            if message.author == self._client.user:
                return
            if message.author.bot:
                return

            user_id = str(message.author.id)
            if not channel_ref.is_allowed(user_id):
                logger.warning("Discord: blocked message from non-allowed user {}", user_id)
                return

            msg = InboundMessage(
                channel="discord",
                chat_id=str(message.channel.id),
                user_id=user_id,
                text=message.content,
                metadata={
                    "message_id": str(message.id),
                    "guild_id": str(message.guild.id) if message.guild else "",
                },
            )
            await bus.push_inbound(msg)

        self._task = asyncio.create_task(
            self._client.start(token), name="discord-bot"
        )
        await self._ready_event.wait()
        logger.info("Discord channel started")

    async def stop(self) -> None:
        if self._client:
            await self._client.close()
        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        logger.info("Discord channel stopped")

    async def send(self, chat_id: str, text: str, **kwargs) -> None:
        if not self._client:
            logger.error("Discord: cannot send, client not initialized")
            return

        channel = self._client.get_channel(int(chat_id))
        if not channel:
            try:
                channel = await self._client.fetch_channel(int(chat_id))
            except Exception as exc:
                logger.error("Discord: channel {} not found: {}", chat_id, exc)
                return

        chunks = self.split_message(text, DISCORD_MAX_MESSAGE_LENGTH)
        for chunk in chunks:
            await channel.send(chunk)
