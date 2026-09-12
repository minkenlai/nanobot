"""Tool for managing metadata-driven session context injection and protocol overrides."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool, ToolResult, tool_parameters
from nanobot.agent.tools.context import ToolContext
from nanobot.agent.tools.schema import StringSchema, tool_parameters_schema
from nanobot.session.metadata_store import SessionMetadataStore


@tool_parameters(
    tool_parameters_schema(
        action=StringSchema(
            "Action to perform: 'set' (create or update session metadata for chat_id), "
            "'get' (view metadata for chat_id), 'remove' (delete metadata for chat_id), "
            "or 'list' (list all configured chat session overrides)."
        ),
        chat_id=StringSchema(
            "Chat ID or session identifier (e.g. '-1004453403218' or 'telegram:-1004453403218'). "
            "Required for 'set', 'get', and 'remove'."
        ),
        label=StringSchema(
            "Human-readable label for this chat (e.g. 'Staff Group', 'VIP Support'). Used with 'set'."
        ),
        context_injection=StringSchema(
            "Session-specific behavioral instructions, silence protocols, or rules prepended to prompts. Used with 'set'."
        ),
        personality_override=StringSchema(
            "Tone, persona, or style instructions for this specific chat. Used with 'set'."
        ),
        required=["action"],
    )
)
class UpdateSessionMetadataTool(Tool):
    """Tool for managing per-session context injection and behavioral overrides in sessions_metadata.json."""

    @property
    def name(self) -> str:
        return "update_session_metadata"

    @property
    def description(self) -> str:
        return (
            "View, map, update, or remove session-specific behavioral context, group chat protocols, "
            "and personality overrides in sessions_metadata.json by chat ID. "
            "Use this tool to establish immediate situational awareness or group chat silence rules for specific chats."
        )

    def __init__(self, store: SessionMetadataStore | None = None, file_path: Path | str | None = None) -> None:
        if store is not None:
            self.store = store
        else:
            self.store = SessionMetadataStore(file_path)

    @classmethod
    def enabled(cls, ctx: ToolContext) -> bool:
        return True

    @classmethod
    def create(cls, ctx: ToolContext) -> Tool:
        config = getattr(ctx, "config", None)
        path = getattr(config, "sessions_metadata_path", None) if config else None
        return cls(file_path=path)

    async def execute(self, *args: Any, **kwargs: Any) -> ToolResult:
        action = str(kwargs.get("action", "")).strip().lower()
        chat_id = str(kwargs.get("chat_id", "")).strip()
        label = kwargs.get("label")
        context_injection = kwargs.get("context_injection")
        personality_override = kwargs.get("personality_override")

        if action in ("set", "update", "add"):
            if not chat_id:
                return ToolResult.error("chat_id is required when setting session metadata.")
            entry = self.store.set(
                chat_id,
                label=str(label) if label is not None else None,
                context_injection=str(context_injection) if context_injection is not None else None,
                personality_override=str(personality_override) if personality_override is not None else None,
            )
            return ToolResult(
                f"Successfully updated session metadata for chat '{chat_id}':\n"
                f"  Label               : {entry.label or '(none)'}\n"
                f"  Context Injection   : {entry.context_injection or '(none)'}\n"
                f"  Personality Override: {entry.personality_override or '(none)'}\n"
                f"  Stored in           : {self.store.file_path}"
            )

        if action in ("get", "show", "view"):
            if not chat_id:
                return ToolResult.error("chat_id is required when retrieving session metadata.")
            entry = self.store.get(chat_id)
            if not entry:
                return ToolResult(f"No session metadata found for chat '{chat_id}'.")
            return ToolResult(
                f"Session metadata for chat '{chat_id}':\n"
                f"  Label               : {entry.label or '(none)'}\n"
                f"  Context Injection   : {entry.context_injection or '(none)'}\n"
                f"  Personality Override: {entry.personality_override or '(none)'}"
            )

        if action in ("remove", "delete", "clear"):
            if not chat_id:
                return ToolResult.error("chat_id is required when removing session metadata.")
            deleted = self.store.delete(chat_id)
            if deleted:
                return ToolResult(f"Successfully removed session metadata for chat '{chat_id}'.")
            return ToolResult(f"No session metadata found to remove for chat '{chat_id}'.")

        if action in ("list", "all"):
            entries = self.store.list_all()
            if not entries:
                return ToolResult(f"No session metadata entries configured in {self.store.file_path}.")

            lines = [f"Configured Session Metadata ({len(entries)} chats in {self.store.file_path}):"]
            for cid, ent in entries.items():
                label_display = f" ({ent.label})" if ent.label else ""
                lines.append(f"• Chat ID: {cid}{label_display}")
                if ent.context_injection:
                    lines.append(f"    Injection  : {ent.context_injection}")
                if ent.personality_override:
                    lines.append(f"    Personality: {ent.personality_override}")
            return ToolResult("\n".join(lines))

        return ToolResult.error(f"Unknown action '{action}'. Supported actions: 'set', 'get', 'remove', 'list'.")
