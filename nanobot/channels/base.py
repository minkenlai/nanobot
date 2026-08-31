"""Base channel interface for chat platforms."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from loguru import logger

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.pairing import (
    PAIRING_CODE_META_KEY,
    format_pairing_reply,
    generate_code,
    is_approved,
)

_BOOL_CAMEL_ALIASES: dict[str, str] = {
    "ignore_connect_backlog": "ignoreConnectBacklog",
}
_INT_CAMEL_ALIASES: dict[str, str] = {
    "max_message_age_seconds": "maxMessageAgeSeconds",
}


class BaseChannel(ABC):
    """
    Abstract base class for chat channel implementations.

    Each channel (Telegram, Discord, etc.) should implement this interface
    to integrate with the nanobot message bus.
    """

    name: str = "base"
    display_name: str = "Base"
    send_progress: bool = True
    send_tool_hints: bool = True
    show_reasoning: bool = True
    staff_policy: Any = None

    def __init__(self, config: Any, bus: MessageBus):
        """
        Initialize the channel.

        Args:
            config: Channel-specific configuration.
            bus: The message bus for communication.
        """
        self.config = config
        self.logger = logger.bind(channel=self.name)
        self.bus = bus
        self._running = False
        self.max_message_age_seconds: int | None = self._extract_config_int(
            "max_message_age_seconds", default=300
        )
        self.ignore_connect_backlog: bool = self._extract_config_bool(
            "ignore_connect_backlog", default=True
        )
        self.connected_at: float | None = None

    def _extract_config_int(self, key: str, default: int | None) -> int | None:
        cfg = self.config
        camel = _INT_CAMEL_ALIASES.get(key, key)
        if isinstance(cfg, dict):
            cfg_dict = cast(dict[str, Any], cfg)
            if key in cfg_dict:
                val: Any = cfg_dict[key]
            elif camel in cfg_dict:
                val = cfg_dict[camel]
            else:
                return default
            if val is None:
                return None
            try:
                return int(val)
            except (ValueError, TypeError):
                return default
        if hasattr(cfg, key):
            val = getattr(cfg, key)
        elif hasattr(cfg, camel):
            val = getattr(cfg, camel)
        else:
            return default
        if val is None:
            return None
        try:
            return int(val)
        except (ValueError, TypeError):
            return default

    def _extract_config_bool(self, key: str, default: bool) -> bool:
        cfg = self.config
        camel = _BOOL_CAMEL_ALIASES.get(key, key)
        if isinstance(cfg, dict):
            cfg_dict = cast(dict[str, Any], cfg)
            if key in cfg_dict:
                val: Any = cfg_dict[key]
            elif camel in cfg_dict:
                val = cfg_dict[camel]
            else:
                return default
            return val if isinstance(val, bool) else default
        if hasattr(cfg, key):
            val = getattr(cfg, key)
        elif hasattr(cfg, camel):
            val = getattr(cfg, camel)
        else:
            return default
        return val if isinstance(val, bool) else default

    def mark_connected(self, connected_at: float | None = None) -> None:
        """Record connection time for connect-backlog filtering."""
        self.connected_at = time.time() if connected_at is None else float(connected_at)

    async def transcribe_audio(self, file_path: str | Path) -> str:
        """Transcribe an audio file via Whisper (OpenAI or Groq). Returns empty string on failure."""
        try:
            from nanobot.audio.transcription import (
                resolve_transcription_config,
                transcribe_audio_file,
            )
            from nanobot.config.loader import load_config

            return await transcribe_audio_file(file_path, resolve_transcription_config(load_config()))
        except Exception:
            self.logger.exception("Audio transcription failed")
            return ""

    async def login(self, force: bool = False) -> bool:
        """
        Perform channel-specific interactive login (e.g. QR code scan).

        Args:
            force: If True, ignore existing credentials and force re-authentication.

        Returns True if already authenticated or login succeeds.
        Override in subclasses that support interactive login.
        """
        return True

    @abstractmethod
    async def start(self) -> None:
        """
        Start the channel and begin listening for messages.

        This should be a long-running async task that:
        1. Connects to the chat platform
        2. Listens for incoming messages
        3. Forwards messages to the bus via _handle_message()
        """
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop the channel and clean up resources."""
        pass

    @abstractmethod
    async def send(self, msg: OutboundMessage) -> None:
        """
        Send a message through this channel.

        Args:
            msg: The message to send.

        Implementations should raise on delivery failure so the channel manager
        can apply any retry policy in one place.
        """
        pass

    def progress_transport_defaults(self) -> tuple[bool, bool] | None:
        """Return channel-owned defaults for progress and tool-hint messages.

        ``None`` keeps the global channel policy. Channels should override this
        only when their transport requires different defaults.
        """
        return None

    def should_retry_send_error(self, error: Exception) -> bool:
        """Return whether the channel manager may retry a failed delivery.

        Channels with protocol-level business errors can override this hook to
        prevent retries that cannot succeed until external state changes.
        Transport and unexpected errors remain retryable by default.
        """
        return True

    def start_error_message(self, error: Exception) -> str | None:
        """Return an actionable public message for a channel startup failure.

        Channel-specific exception handling stays in the owning channel. Returning
        ``None`` keeps the manager's generic fallback.
        """
        return None

    async def send_delta(
        self,
        chat_id: str,
        delta: str,
        metadata: dict[str, Any] | None = None,
        *,
        stream_id: str | None = None,
        stream_end: bool = False,
        resuming: bool = False,
        merge_next: bool = False,
    ) -> None:
        """Deliver a streaming text chunk.

        Override in subclasses to enable streaming. Implementations should
        raise on delivery failure so the channel manager can retry.

        Stateful implementations should key buffers by ``stream_id`` rather
        than only by ``chat_id`` when it is provided.

        ``merge_next`` marks a resumable provider boundary whose next text
        segment belongs to the same user-visible message.
        """
        pass

    async def send_reasoning_delta(
        self,
        chat_id: str,
        delta: str,
        metadata: dict[str, Any] | None = None,
        *,
        stream_id: str | None = None,
    ) -> None:
        """Stream a chunk of model reasoning/thinking content.

        Default is no-op. Channels with a native low-emphasis primitive
        (Slack context block, Telegram expandable blockquote, Discord
        subtext, WebUI italic bubble, ...) override to render reasoning
        as a subordinate trace that updates in place as the model thinks.

        Streaming contract mirrors :meth:`send_delta`: stateful implementations
        should key buffers by ``stream_id`` rather than only by ``chat_id``.
        """
        return

    async def send_reasoning_end(
        self,
        chat_id: str,
        metadata: dict[str, Any] | None = None,
        *,
        stream_id: str | None = None,
    ) -> None:
        """Mark the end of a reasoning stream segment.

        Default is no-op. Channels that buffer ``send_reasoning_delta``
        chunks for in-place updates use this signal to flush and freeze
        the rendered group; one-shot channels can ignore it entirely.
        """
        return

    async def send_file_edit_events(
        self,
        chat_id: str,
        edits: list[dict[str, Any]],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Deliver structured live file-edit events.

        Default is no-op. Channels with a rich activity surface can override
        this to render editing progress without receiving empty text messages.
        """
        return

    async def send_reasoning(self, msg: OutboundMessage) -> None:
        """Deliver a complete reasoning block.

        Default implementation reuses the streaming pair so plugins only
        need to override the delta/end methods. Equivalent to one delta
        with the full content followed immediately by an end marker —
        keeps a single rendering path for both streamed and one-shot
        reasoning (e.g. DeepSeek-R1's final-response ``reasoning_content``).
        """
        if not msg.content:
            return
        stream_id = getattr(msg.event, "stream_id", None)
        await self.send_reasoning_delta(
            msg.chat_id,
            msg.content,
            msg.metadata,
            stream_id=stream_id,
        )
        await self.send_reasoning_end(
            msg.chat_id,
            msg.metadata,
            stream_id=stream_id,
        )

    @property
    def supports_streaming(self) -> bool:
        """True when config enables streaming AND this subclass implements send_delta."""
        cfg = self.config
        config_mapping = cast(dict[str, Any], cfg) if isinstance(cfg, dict) else None
        streaming: Any = (
            config_mapping.get("streaming", False)
            if config_mapping is not None
            else getattr(cast(Any, cfg), "streaming", False)
        )
        return bool(streaming) and type(self).send_delta is not BaseChannel.send_delta

    def is_allowed(self, sender_id: str) -> bool:
        """Check sender permission: star > allowlist > pairing store > deny."""
        if isinstance(self.config, dict):
            config_mapping = cast(dict[str, Any], self.config)
            allow_list: Any = (
                config_mapping.get("allow_from") or config_mapping.get("allowFrom") or []
            )
        else:
            allow_list = getattr(self.config, "allow_from", None) or []
        if "*" in allow_list:
            return True
        # allowFrom entries are opaque tokens — must match exactly.
        if str(sender_id) in allow_list:
            return True
        if is_approved(self.name, str(sender_id)):
            return True
        return False

    def _normalize_message_timestamp(
        self,
        timestamp: datetime | float | int | str | None,
        metadata: dict[str, Any] | None,
    ) -> tuple[datetime, float | None]:
        """Normalize various timestamp representations to (datetime, epoch_seconds | None)."""
        raw_ts = timestamp
        if raw_ts is None and metadata:
            raw_ts = (
                metadata.get("timestamp")
                or metadata.get("server_timestamp")
                or metadata.get("create_time")
            )

        if raw_ts is None:
            return datetime.now(), None

        if isinstance(raw_ts, datetime):
            dt = raw_ts
            if dt.tzinfo is not None:
                epoch_sec = dt.timestamp()
            else:
                epoch_sec = dt.replace(tzinfo=timezone.utc).timestamp()
            return dt, epoch_sec

        if isinstance(raw_ts, (int, float)):
            val = float(raw_ts)
            if val <= 0:
                return datetime.now(), None
            epoch_sec = val / 1000.0 if val > 1e11 else val
            try:
                dt = datetime.fromtimestamp(epoch_sec, tz=timezone.utc)
            except (ValueError, OverflowError, OSError):
                return datetime.now(), None
            return dt, epoch_sec

        if isinstance(raw_ts, str):
            try:
                val = float(raw_ts)
                if val <= 0:
                    return datetime.now(), None
                epoch_sec = val / 1000.0 if val > 1e11 else val
                dt = datetime.fromtimestamp(epoch_sec, tz=timezone.utc)
                return dt, epoch_sec
            except ValueError:
                pass
            try:
                dt = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
                epoch_sec = dt.timestamp()
                return dt, epoch_sec
            except ValueError:
                pass

        return datetime.now(), None

    def _should_ignore_backlog(self, epoch_seconds: float | None, sender_id: str) -> bool:
        """Check if incoming message is backlogged/outdated based on channel policy."""
        if epoch_seconds is None or epoch_seconds <= 0:
            return False

        if (
            self.ignore_connect_backlog
            and self.connected_at is not None
            and self.connected_at > 0
            and epoch_seconds < self.connected_at
        ):
            self.logger.info(
                "Ignoring backlogged message from {}: timestamp {} is prior to connect time {}",
                sender_id,
                epoch_seconds,
                self.connected_at,
            )
            return True

        if (
            self.max_message_age_seconds is not None
            and self.max_message_age_seconds > 0
        ):
            age = time.time() - epoch_seconds
            if age > self.max_message_age_seconds:
                self.logger.info(
                    "Ignoring outdated message from {}: age {:.1f}s exceeds max_message_age_seconds ({}s)",
                    sender_id,
                    age,
                    self.max_message_age_seconds,
                )
                return True

        return False

    async def _handle_message(
        self,
        sender_id: str,
        chat_id: str,
        content: str,
        media: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        session_key: str | None = None,
        is_dm: bool = False,
        authorization_id: str | None = None,
        require_existing_session: bool = False,
        timestamp: datetime | float | int | str | None = None,
    ) -> None:
        """Handle a message after checking backlog freshness and authorization."""
        parsed_dt, epoch_seconds = self._normalize_message_timestamp(timestamp, metadata)
        if self._should_ignore_backlog(epoch_seconds, str(sender_id)):
            return

        permission_id = authorization_id if authorization_id is not None else sender_id
        if not self.is_allowed(permission_id):
            if is_dm:
                try:
                    code = generate_code(self.name, str(sender_id))
                except OSError:
                    # Transient pairing-store I/O failure: skip the pairing
                    # reply for this message rather than crash the handler.
                    self.logger.warning(
                        "Pairing store unavailable; dropping DM from {}", sender_id
                    )
                    return
                await self.send(
                    OutboundMessage(
                        channel=self.name,
                        chat_id=str(chat_id),
                        content=format_pairing_reply(code),
                        metadata={PAIRING_CODE_META_KEY: code},
                    )
                )
                self.logger.info(
                    "Sent pairing code {} to sender {} in chat {}",
                    code, sender_id, chat_id,
                )
            else:
                self.logger.warning(
                    "Access denied for sender {}. "
                    "Add them to allowFrom list in config to grant access.",
                    sender_id,
                )
            return

        meta = metadata or {}
        if self.supports_streaming:
            meta = {**meta, "_wants_stream": True}

        msg = InboundMessage(
            channel=self.name,
            sender_id=str(sender_id),
            chat_id=str(chat_id),
            content=content,
            timestamp=parsed_dt,
            media=media or [],
            metadata=meta,
            session_key_override=session_key,
            require_existing_session=require_existing_session,
        )

        await self.bus.publish_inbound(msg)

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        """Return default config for onboard. Override in plugins to auto-populate config.json."""
        return {"enabled": False}

    @classmethod
    def refresh_feature_metadata(
        cls,
        config_path: Path,
        *,
        instance_id: str = "default",
    ) -> bool:
        """Refresh persisted display metadata after an explicit settings action."""
        return False

    @property
    def is_running(self) -> bool:
        """Check if the channel is running."""
        return self._running
