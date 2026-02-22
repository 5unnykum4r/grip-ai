"""Message bus event types for inter-component communication.

InboundMessage flows from channels into the agent loop.
OutboundMessage flows from the agent loop back to channels.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class InboundMessage:
    """A message arriving from a chat channel to be processed by the agent."""

    channel: str
    chat_id: str
    user_id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class OutboundMessage:
    """A message from the agent to be delivered to a chat channel.

    When file_path is set, the channel sends the file as an attachment
    (photo for images, document for everything else). The text field
    is used as a caption. When file_path is empty, only text is sent.
    """

    channel: str
    chat_id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    reply_to_message_id: str | None = None
    file_path: str = ""
