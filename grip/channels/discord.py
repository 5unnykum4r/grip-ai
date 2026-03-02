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

_DISCORD_COMMANDS = {
    "help": "List available commands",
    "new": "Start a fresh conversation",
    "status": "Show session info",
    "model": "Show or switch AI model",
    "clear": "Clear conversation history",
    "compact": "Summarize and compress history",
    "version": "Show grip version",
}


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

        token = self._config.token.get_secret_value()
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

            text = message.content.strip()
            if text.startswith(("!", "/")):
                parts = text[1:].split(maxsplit=1)
                command = parts[0].lower()
                arg = parts[1] if len(parts) > 1 else ""
                if command in _DISCORD_COMMANDS:
                    cmd_msg = InboundMessage(
                        channel="discord",
                        chat_id=str(message.channel.id),
                        user_id=user_id,
                        text=f"/{command} {arg}".strip(),
                        metadata={
                            "message_id": str(message.id),
                            "guild_id": str(message.guild.id) if message.guild else "",
                            "command": command,
                            "arg": arg,
                        },
                    )
                    await bus.push_inbound(cmd_msg)
                    return

            content = message.content

            # Auto-convert file attachments to markdown
            if message.attachments:
                import tempfile
                from pathlib import Path

                for attachment in message.attachments:
                    ext = Path(attachment.filename).suffix.lower()
                    tmp_path = None
                    try:
                        from grip.tools.markitdown import (
                            SUPPORTED_EXTENSIONS,
                            convert_file_to_markdown,
                        )

                        if ext in SUPPORTED_EXTENSIONS:
                            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                                tmp_path = Path(tmp.name)
                            file_bytes = await attachment.read()
                            tmp_path.write_bytes(file_bytes)
                            result = await asyncio.to_thread(
                                convert_file_to_markdown, tmp_path, max_chars=50_000
                            )
                            content += f"\n\n[Document: {attachment.filename}]\n\n{result.text_content}"
                            logger.debug("Discord: converted attachment {} ({} chars)", attachment.filename, result.original_size)
                        else:
                            content += f"\n\n[User sent file: {attachment.filename}]"
                    except ImportError:
                        content += f"\n\n[User sent file: {attachment.filename}]"
                    except Exception as exc:
                        logger.debug("Discord attachment conversion failed for {}: {}", attachment.filename, exc)
                        content += f"\n\n[User sent file: {attachment.filename}]"
                    finally:
                        if tmp_path is not None:
                            tmp_path.unlink(missing_ok=True)

            msg = InboundMessage(
                channel="discord",
                chat_id=str(message.channel.id),
                user_id=user_id,
                text=content,
                metadata={
                    "message_id": str(message.id),
                    "guild_id": str(message.guild.id) if message.guild else "",
                },
            )
            await bus.push_inbound(msg)

        self._task = asyncio.create_task(self._client.start(token), name="discord-bot")
        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=30)
        except TimeoutError as exc:
            raise RuntimeError(
                "Discord bot failed to connect within 30 seconds. "
                "Check bot token and network connectivity."
            ) from exc
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

    async def send_file(self, chat_id: str, file_path: str, caption: str = "") -> None:
        """Send a file to Discord as an attachment."""
        from pathlib import Path

        import discord

        if not self._client:
            logger.error("Discord: cannot send file, client not initialized")
            return

        path = Path(file_path)
        if not path.is_file():
            logger.error("Discord: file not found: {}", file_path)
            await self.send(chat_id, f"File not found: {file_path}")
            return

        channel = self._client.get_channel(int(chat_id))
        if not channel:
            try:
                channel = await self._client.fetch_channel(int(chat_id))
            except Exception as exc:
                logger.error("Discord: channel {} not found: {}", chat_id, exc)
                return

        try:
            discord_file = discord.File(path, filename=path.name)
            await channel.send(content=caption or None, file=discord_file)
            logger.info("Discord: sent file {} to channel {}", path.name, chat_id)
        except Exception as exc:
            logger.error("Discord: failed to send file {}: {}", file_path, exc)
