"""Slack channel integration using slack-sdk Socket Mode.

Socket Mode eliminates the need for a public URL or ngrok — the bot
connects outbound to Slack's servers via WebSocket.

Requires: pip install grip[channels-slack]
Config:
  config.channels.slack.enabled = true
  config.channels.slack.token = "xoxb-BOT-TOKEN"
  config.channels.slack.extra.app_token = "xapp-APP-LEVEL-TOKEN"
"""

from __future__ import annotations

import asyncio
import contextlib

from loguru import logger

from grip.bus.events import InboundMessage
from grip.bus.queue import MessageBus
from grip.channels.base import BaseChannel
from grip.config.schema import ChannelEntry

SLACK_MAX_MESSAGE_LENGTH = 40000

_SLACK_COMMANDS = {
    "help": "List available commands",
    "new": "Start a fresh conversation",
    "status": "Show session info",
    "model": "Show or switch AI model",
    "clear": "Clear conversation history",
    "compact": "Summarize and compress history",
    "version": "Show grip version",
}


class SlackChannel(BaseChannel):
    """Slack bot channel using Socket Mode (no public URL needed)."""

    def __init__(self, config: ChannelEntry) -> None:
        super().__init__(config)
        self._socket_client = None
        self._web_client = None
        self._task: asyncio.Task | None = None

    @property
    def name(self) -> str:
        return "slack"

    async def start(self, bus: MessageBus) -> None:
        try:
            from slack_sdk.socket_mode.aiohttp import SocketModeClient
            from slack_sdk.web.async_client import AsyncWebClient
        except ImportError as exc:
            raise RuntimeError(
                "slack-sdk is required for Slack channel. "
                "Install with: uv pip install grip[channels-slack]"
            ) from exc

        self._bus = bus
        bus.subscribe_outbound(self._handle_outbound)

        bot_token = self._config.token.get_secret_value()
        app_token = self._config.extra.get("app_token", "")

        if not bot_token:
            raise ValueError("Slack bot token is required (config.channels.slack.token)")
        if not app_token:
            raise ValueError(
                "Slack app-level token is required for Socket Mode "
                "(config.channels.slack.extra.app_token)"
            )

        self._web_client = AsyncWebClient(token=bot_token)
        self._socket_client = SocketModeClient(
            app_token=app_token,
            web_client=self._web_client,
        )
        channel_ref = self

        async def on_event(client, req):
            """Handle incoming Socket Mode events."""
            if req.type == "events_api":
                event = req.payload.get("event", {})
                if event.get("type") == "message" and "subtype" not in event:
                    user_id = event.get("user", "")
                    if not channel_ref.is_allowed(user_id):
                        logger.warning("Slack: blocked message from non-allowed user {}", user_id)
                        await client.send_socket_mode_response({"envelope_id": req.envelope_id})
                        return

                    text = event.get("text", "").strip()
                    chat_id = event.get("channel", "")

                    if text.startswith(("!", "/")):
                        parts = text[1:].split(maxsplit=1)
                        command = parts[0].lower()
                        arg = parts[1] if len(parts) > 1 else ""
                        if command in _SLACK_COMMANDS:
                            cmd_msg = InboundMessage(
                                channel="slack",
                                chat_id=chat_id,
                                user_id=user_id,
                                text=f"/{command} {arg}".strip(),
                                metadata={
                                    "ts": event.get("ts", ""),
                                    "team": event.get("team", ""),
                                    "command": command,
                                    "arg": arg,
                                },
                            )
                            await bus.push_inbound(cmd_msg)
                            await client.send_socket_mode_response({"envelope_id": req.envelope_id})
                            return

                    # Auto-convert file shares to markdown
                    files = event.get("files", [])
                    if files:
                        import tempfile
                        from pathlib import Path

                        import httpx

                        for file_info in files:
                            fname = file_info.get("name", "unknown")
                            download_url = file_info.get("url_private_download", "")
                            ext = Path(fname).suffix.lower()
                            tmp_path = None
                            try:
                                from grip.tools.markitdown import (
                                    SUPPORTED_EXTENSIONS,
                                    convert_file_to_markdown,
                                )

                                if ext in SUPPORTED_EXTENSIONS and download_url:
                                    async with httpx.AsyncClient(timeout=30.0) as dl_client:
                                        resp = await dl_client.get(
                                            download_url,
                                            headers={"Authorization": f"Bearer {bot_token}"},
                                        )
                                        resp.raise_for_status()
                                        file_bytes = resp.content
                                    with tempfile.NamedTemporaryFile(
                                        suffix=ext, delete=False
                                    ) as tmp:
                                        tmp_path = Path(tmp.name)
                                    tmp_path.write_bytes(file_bytes)
                                    result = await asyncio.to_thread(
                                        convert_file_to_markdown, tmp_path, max_chars=50_000
                                    )
                                    text += f"\n\n[Document: {fname}]\n\n{result.text_content}"
                                    logger.debug(
                                        "Slack: converted file {} ({} chars)",
                                        fname,
                                        result.original_size,
                                    )
                                else:
                                    text += f"\n\n[User sent file: {fname}]"
                            except ImportError:
                                text += f"\n\n[User sent file: {fname}]"
                            except Exception as exc:
                                logger.debug("Slack file conversion failed for {}: {}", fname, exc)
                                text += f"\n\n[User sent file: {fname}]"
                            finally:
                                if tmp_path is not None:
                                    tmp_path.unlink(missing_ok=True)

                    msg = InboundMessage(
                        channel="slack",
                        chat_id=chat_id,
                        user_id=user_id,
                        text=text,
                        metadata={
                            "ts": event.get("ts", ""),
                            "team": event.get("team", ""),
                        },
                    )
                    await bus.push_inbound(msg)

                await client.send_socket_mode_response({"envelope_id": req.envelope_id})

        self._socket_client.socket_mode_request_listeners.append(on_event)
        self._task = asyncio.create_task(self._socket_client.connect(), name="slack-socket-mode")
        logger.info("Slack channel started (Socket Mode)")

    async def stop(self) -> None:
        if self._socket_client:
            await self._socket_client.close()
        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        logger.info("Slack channel stopped")

    async def send(self, chat_id: str, text: str, **kwargs) -> None:
        if not self._web_client:
            logger.error("Slack: cannot send, web client not initialized")
            return

        chunks = self.split_message(text, SLACK_MAX_MESSAGE_LENGTH)
        for chunk in chunks:
            await self._web_client.chat_postMessage(channel=chat_id, text=chunk)

    async def send_file(self, chat_id: str, file_path: str, caption: str = "") -> None:
        """Send a file to Slack using files_upload_v2."""
        from pathlib import Path

        if not self._web_client:
            logger.error("Slack: cannot send file, web client not initialized")
            return

        path = Path(file_path)
        if not path.is_file():
            logger.error("Slack: file not found: {}", file_path)
            await self.send(chat_id, f"File not found: {file_path}")
            return

        try:
            await self._web_client.files_upload_v2(
                channel=chat_id,
                file=str(path),
                filename=path.name,
                initial_comment=caption or "",
            )
            logger.info("Slack: sent file {} to channel {}", path.name, chat_id)
        except AttributeError:
            # Older slack-sdk versions without files_upload_v2
            try:
                await self._web_client.files_upload(
                    channels=chat_id,
                    file=str(path),
                    filename=path.name,
                    initial_comment=caption or "",
                )
                logger.info("Slack: sent file {} (v1 upload) to {}", path.name, chat_id)
            except Exception as exc:
                logger.error("Slack: failed to send file {}: {}", file_path, exc)
        except Exception as exc:
            logger.error("Slack: failed to send file {}: {}", file_path, exc)
