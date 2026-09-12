"""Metadata-driven session context store for dynamic prompt overrides."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, cast

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from nanobot.config.paths import get_config_path


class SessionMetadataEntry(BaseModel):
    """Behavioral overrides and context injection for a specific session/chat."""

    model_config = ConfigDict(extra="ignore")

    label: str = Field(default="", description="Human-readable label for the session (e.g. 'Staff Group').")
    context_injection: str = Field(
        default="",
        description="Specific behavioral/protocol instructions to prepend to the session prompt.",
    )
    personality_override: str = Field(
        default="",
        description="Tone and personality guidance for this session.",
    )


class SessionMetadataStore:
    """Persistent store for chat-specific behavioral overrides (sessions_metadata.json)."""

    def __init__(self, file_path: Path | str | None = None) -> None:
        if file_path:
            self.file_path = Path(file_path).expanduser().resolve()
        else:
            self.file_path = (get_config_path().parent / "sessions_metadata.json").resolve()

    def _load_raw(self) -> dict[str, Any]:
        if not self.file_path.exists():
            return {}
        try:
            data = json.loads(self.file_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return cast(dict[str, Any], data)
        except Exception:
            logger.warning("Failed to parse session metadata from {}: corrupt or invalid JSON", self.file_path)
        return {}

    def load(self) -> dict[str, SessionMetadataEntry]:
        """Load all session metadata entries from disk."""
        raw = self._load_raw()
        entries: dict[str, SessionMetadataEntry] = {}
        for key, value in raw.items():
            if isinstance(value, dict):
                try:
                    entries[str(key).strip()] = SessionMetadataEntry.model_validate(value)
                except Exception:
                    logger.warning("Skipping invalid session metadata entry for key: {}", key)
        return entries

    def get(self, chat_id: str | None) -> SessionMetadataEntry | None:
        """Lookup session metadata for a chat ID (supports channel-prefixed or bare IDs)."""
        if not chat_id:
            return None
        target = str(chat_id).strip()
        if not target:
            return None

        entries = self.load()
        # 1. Exact match
        if target in entries:
            return entries[target]

        # 2. If target has channel prefix (e.g. 'telegram:-100123'), try bare chat_id
        if ":" in target:
            bare_id = target.split(":", 1)[1]
            if bare_id in entries:
                return entries[bare_id]

        # 3. If target is bare chat_id, check if any entry has '<channel>:<chat_id>'
        for key, entry in entries.items():
            if ":" in key and key.split(":", 1)[1] == target:
                return entry

        return None

    def set(
        self,
        chat_id: str,
        *,
        label: str | None = None,
        context_injection: str | None = None,
        personality_override: str | None = None,
    ) -> SessionMetadataEntry:
        """Create or update session metadata for a chat ID and atomically persist."""
        target = str(chat_id).strip()
        if not target:
            raise ValueError("chat_id must not be empty")

        entries = self.load()
        existing = entries.get(target)

        new_label = label if label is not None else (existing.label if existing else "")
        new_injection = (
            context_injection if context_injection is not None else (existing.context_injection if existing else "")
        )
        new_personality = (
            personality_override
            if personality_override is not None
            else (existing.personality_override if existing else "")
        )

        entry = SessionMetadataEntry(
            label=new_label,
            context_injection=new_injection,
            personality_override=new_personality,
        )
        entries[target] = entry
        self._save_atomic(entries)
        return entry

    def delete(self, chat_id: str) -> bool:
        """Delete session metadata for a chat ID and atomically persist."""
        target = str(chat_id).strip()
        if not target:
            return False

        entries = self.load()
        matched_key: str | None = None
        if target in entries:
            matched_key = target
        elif ":" in target:
            bare = target.split(":", 1)[1]
            if bare in entries:
                matched_key = bare
        else:
            for k in entries:
                if ":" in k and k.split(":", 1)[1] == target:
                    matched_key = k
                    break

        if matched_key and matched_key in entries:
            del entries[matched_key]
            self._save_atomic(entries)
            return True
        return False

    def list_all(self) -> dict[str, SessionMetadataEntry]:
        """Return a mapping of all configured chat IDs to entries."""
        return self.load()

    def format_injection(self, chat_id: str | None) -> str | None:
        """Format the session context injection string for prompt assembly."""
        entry = self.get(chat_id)
        if not entry:
            return None

        parts: list[str] = []
        if entry.label.strip():
            parts.append(f"[Session Context: {entry.label.strip()}]")
        if entry.context_injection.strip():
            parts.append(entry.context_injection.strip())
        if entry.personality_override.strip():
            parts.append(f"Personality: {entry.personality_override.strip()}")

        if not parts:
            return None
        return "\n\n".join(parts)

    def _save_atomic(self, entries: dict[str, SessionMetadataEntry]) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        dump_data = {
            k: {
                "label": v.label,
                "context_injection": v.context_injection,
                "personality_override": v.personality_override,
            }
            for k, v in entries.items()
        }
        serialized = json.dumps(dump_data, indent=2, ensure_ascii=False) + "\n"

        temp_fd, temp_path = tempfile.mkstemp(dir=self.file_path.parent, prefix="sessions_metadata_", suffix=".tmp")
        try:
            with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                f.write(serialized)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, self.file_path)
        except Exception:
            if os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except Exception:
                    pass
            raise
