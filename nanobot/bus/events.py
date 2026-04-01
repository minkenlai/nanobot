"""Event types for the message bus."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class Address:
    """Universal identifier for a conversation target."""

    channel: str  # e.g., 'tg', 'cli', 'discord'
    segments: tuple[str, ...] = field(default_factory=tuple)

    def to_uri(self) -> str:
        """Serialize to a URI string, e.g., 'tg://-1003434604734/12345'."""
        return f"{self.channel}://" + "/".join(self.segments)

    def __str__(self) -> str:
        return self.to_uri()

    @classmethod
    def from_uri(cls, uri: str) -> "Address":
        """Parse from a URI string or old-style colon string."""
        if "://" in uri:
            scheme, path = uri.split("://", 1)
            # Filter out empty segments caused by leading/trailing/double slashes
            segments = tuple(s for s in path.split("/") if s)
            return cls(channel=scheme, segments=segments)

        # Fallback for old-style 'telegram:chat_id:topic:thread_id'
        # or even just 'tg' with no segments
        parts = [p for p in uri.split(":") if p]
        if not parts:
            return cls(channel="unknown")

        channel = parts[0]
        # Map 'telegram' to 'tg' for brevity
        if channel == "telegram":
            channel = "tg"

        segments = tuple(p for p in parts[1:] if p.lower() != "topic")
        return cls(channel=channel, segments=segments)


@dataclass
class InboundMessage:
    """Message received from a chat channel."""

    address: Address
    sender_id: str  # User identifier
    content: str  # Message text
    timestamp: datetime = field(default_factory=datetime.now)
    media: list[str] = field(default_factory=list)  # Media URLs
    metadata: dict[str, Any] = field(default_factory=dict)  # Channel-specific data

    @property
    def channel(self) -> str:
        return self.address.channel

    @property
    def chat_id(self) -> str:
        return self.address.segments[0] if self.address.segments else ""

    @property
    def message_thread_id(self) -> int | None:
        if len(self.address.segments) > 1:
            try:
                return int(self.address.segments[1])
            except ValueError:
                return None
        return None

    @property
    def session_key(self) -> str:
        """Unique key for session identification."""
        # Use the new URI format as the session key
        return self.address.to_uri()


@dataclass
class OutboundMessage:
    """Message to send to a chat channel."""

    address: Address
    content: str
    reply_to: str | None = None
    media: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def channel(self) -> str:
        return self.address.channel

    @property
    def chat_id(self) -> str:
        return self.address.segments[0] if self.address.segments else ""

    @property
    def message_thread_id(self) -> int | None:
        if len(self.address.segments) > 1:
            try:
                return int(self.address.segments[1])
            except ValueError:
                return None
        return None
