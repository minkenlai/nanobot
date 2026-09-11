"""Workspace-accessible session activity tracking for deterministic guard scripts."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from loguru import logger

if TYPE_CHECKING:
    from nanobot.bus.queue import MessageBus
    from nanobot.bus.runtime_events import UserInputAccepted

DEFAULT_ACTIVITY_FILENAME = "session_activity.json"
DEFAULT_ACTIVITY_WINDOW_MINUTES = 60


def _current_timestamp() -> datetime:
    return datetime.now().astimezone()


def load_session_activity(
    workspace: Path,
    filename: str = DEFAULT_ACTIVITY_FILENAME,
) -> dict[str, Any] | None:
    """Read and parse the workspace activity metadata file if it exists."""
    path = Path(workspace) / filename
    if not path.is_file():
        return None
    try:
        content = path.read_text(encoding="utf-8")
        parsed: object = json.loads(content)
        if isinstance(parsed, dict):
            return cast(dict[str, Any], parsed)
        return None
    except Exception as exc:
        logger.warning("Failed to read session activity metadata from {}: {}", path, exc)
        return None


class SessionActivityTracker:
    """Maintains lightweight session activity metadata in the workspace.

    Deterministic guard scripts (e.g. executed via HEARTBEAT.md or cron) running
    under workspace isolation policies can inspect this file to implement gated
    triggers and avoid unnecessary LLM wake-ups when no user activity occurred.
    """

    def __init__(
        self,
        workspace: Path,
        *,
        filename: str = DEFAULT_ACTIVITY_FILENAME,
        window_minutes: int = DEFAULT_ACTIVITY_WINDOW_MINUTES,
    ) -> None:
        self.workspace = Path(workspace).expanduser().resolve(strict=False)
        self.file_path = self.workspace / filename
        self.window_minutes = window_minutes
        self._active_sessions: dict[str, str] = {}
        self._last_activity_timestamp: str | None = None
        self._last_channel: str | None = None
        self._last_session_id: str | None = None
        self._load_existing()

    @property
    def last_activity_timestamp(self) -> str | None:
        return self._last_activity_timestamp

    @property
    def last_channel(self) -> str | None:
        return self._last_channel

    @property
    def last_session_id(self) -> str | None:
        return self._last_session_id

    @property
    def active_sessions(self) -> dict[str, str]:
        self._prune_expired()
        return dict(self._active_sessions)

    def _load_existing(self) -> None:
        """Load and prune existing activity file if present on startup."""
        data = load_session_activity(self.workspace, self.file_path.name)
        if not data:
            return
        self._last_activity_timestamp = (
            str(data["last_activity_timestamp"])
            if data.get("last_activity_timestamp")
            else None
        )
        self._last_channel = str(data["channel"]) if data.get("channel") else None
        self._last_session_id = str(data["session_id"]) if data.get("session_id") else None

        raw_active = cast(object, data.get("active_sessions"))
        if isinstance(raw_active, dict):
            dict_active = cast(dict[object, object], raw_active)
            self._active_sessions = {str(k): str(v) for k, v in dict_active.items()}
        elif isinstance(raw_active, list):
            fallback_ts = self._last_activity_timestamp or _current_timestamp().isoformat()
            list_active = cast(list[object], raw_active)
            self._active_sessions = {str(k): fallback_ts for k in list_active}

        self._prune_expired()

    def _prune_expired(self, ref_dt: datetime | None = None) -> None:
        """Prune active sessions older than window_minutes."""
        ref_time = ref_dt or _current_timestamp()
        max_age_seconds = self.window_minutes * 60
        expired: list[str] = []

        for session_id, ts_str in self._active_sessions.items():
            try:
                dt = datetime.fromisoformat(ts_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=ref_time.tzinfo)
                age = (ref_time - dt).total_seconds()
                if age >= max_age_seconds or age < -60:  # Also guard against large clock skew
                    expired.append(session_id)
            except Exception:
                expired.append(session_id)

        for key in expired:
            self._active_sessions.pop(key, None)

    def record_activity(
        self,
        *,
        channel: str,
        session_id: str,
        timestamp: datetime | None = None,
    ) -> dict[str, Any]:
        """Record user activity and atomically update the workspace metadata file."""
        now_dt = timestamp or _current_timestamp()
        ts_str = now_dt.isoformat()

        self._last_activity_timestamp = ts_str
        self._last_channel = channel
        self._last_session_id = session_id
        self._active_sessions[session_id] = ts_str

        self._prune_expired(now_dt)

        active_copy = dict(self._active_sessions)
        payload: dict[str, Any] = {
            "last_activity_timestamp": self._last_activity_timestamp,
            "channel": self._last_channel,
            "session_id": self._last_session_id,
            "window_minutes": self.window_minutes,
            "active_sessions": active_copy,
        }

        self._write_atomically(payload)
        return payload

    def _write_atomically(self, data: dict[str, Any]) -> None:
        """Atomically persist activity state to workspace file."""
        try:
            self.workspace.mkdir(parents=True, exist_ok=True)
            content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"

            tmp_path = self.file_path.with_suffix(
                f".tmp.{os.getpid()}.{time.time_ns()}"
            )
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.file_path)
        except Exception as exc:
            logger.warning(
                "Failed to write session activity metadata to {}: {}",
                self.file_path,
                exc,
            )

    async def on_user_input_accepted(self, event: UserInputAccepted) -> None:
        """MessageBus event handler for UserInputAccepted."""
        ctx = event.context
        self.record_activity(
            channel=ctx.channel,
            session_id=ctx.session_key,
        )

    def attach_to_bus(self, bus: MessageBus) -> None:
        """Subscribe to UserInputAccepted events on the given MessageBus."""
        from nanobot.bus.runtime_events import UserInputAccepted

        bus.subscribe(self.on_user_input_accepted, UserInputAccepted)
