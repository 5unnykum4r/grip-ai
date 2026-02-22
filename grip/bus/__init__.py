"""Message bus for channel <-> agent communication."""

from grip.bus.events import InboundMessage, OutboundMessage
from grip.bus.queue import MessageBus

__all__ = ["InboundMessage", "MessageBus", "OutboundMessage"]
