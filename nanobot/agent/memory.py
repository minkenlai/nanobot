"""Memory system for persistent agent memory."""

from __future__ import annotations

import asyncio
import json
import re
import weakref
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable
from uuid import uuid4

from loguru import logger

from nanobot.utils.helpers import (
    _extract_text,
    ensure_dir,
    estimate_message_tokens,
    estimate_prompt_tokens_chain,
)

if TYPE_CHECKING:
    from nanobot.providers.base import LLMClient
    from nanobot.session.manager import Session, SessionManager


_SAVE_MEMORY_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": "Save the memory consolidation result to persistent storage.",
            "parameters": {
                "type": "object",
                "properties": {
                    "history_entry": {
                        "type": "string",
                        "description": "A paragraph summarizing key events/decisions/topics. "
                        "Start with [YYYY-MM-DD HH:MM]. Include detail useful for grep search.",
                    },
                    "memory_update": {
                        "type": "string",
                        "description": "New facts, updates, or changes to be added to long-term memory. Use a bulleted list. Do NOT return the entire memory file.",
                    },
                },
                "required": ["history_entry", "memory_update"],
            },
        },
    }
]


def _ensure_text(value: Any) -> str:
    """Normalize tool-call payload values to text for file storage."""
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _normalize_save_memory_args(args: Any) -> dict[str, Any] | None:
    """Normalize provider tool-call arguments to the expected dict shape."""
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            # Salvage: find the first JSON object embedded in conversational text
            match = re.search(r"(\{.*?\})", args, re.DOTALL)
            if match:
                try:
                    args = json.loads(match.group(1))
                except json.JSONDecodeError:
                    pass
            if isinstance(args, str):
                return None
    if isinstance(args, list):
        return args[0] if args and isinstance(args[0], dict) else None
    return args if isinstance(args, dict) else None


_TOOL_CHOICE_ERROR_MARKERS = (
    "tool_choice",
    "toolchoice",
    "does not support",
    'should be ["none", "auto"]',
)


def _is_tool_choice_unsupported(content: str | None) -> bool:
    """Detect provider errors caused by forced tool_choice being unsupported."""
    text = (content or "").lower()
    return any(m in text for m in _TOOL_CHOICE_ERROR_MARKERS)


class MemoryStore:
    """Two-layer memory: MEMORY.md (long-term facts) + HISTORY.md (grep-searchable log)."""

    _MAX_FAILURES_BEFORE_RAW_ARCHIVE = 3

    def __init__(self, workspace: Path):
        self.memory_dir = ensure_dir(workspace / "memory")
        self.memory_file = self.memory_dir / "MEMORY.md"
        self.history_file = self.memory_dir / "HISTORY.md"
        self.staging_file = self.memory_dir / "STAGING.md"
        self.recovery_dir = ensure_dir(self.memory_dir / "recovery")
        self._consecutive_failures = 0

    def read_long_term(self) -> str:
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8")
        return ""

    def write_long_term(self, content: str) -> None:
        self.memory_file.write_text(content, encoding="utf-8")

    def append_history(self, entry: str) -> None:
        with open(self.history_file, "a", encoding="utf-8") as f:
            f.write(entry.rstrip() + "\n\n")

    def get_memory_context(self) -> str:
        long_term = self.read_long_term()
        return f"## Long-term Memory\n{long_term}" if long_term else ""

    @staticmethod
    def _format_messages(messages: list[dict]) -> str:
        lines = []
        for message in messages:
            text = _extract_text(message)
            if not text:
                continue
            tools = (
                f" [tools: {', '.join(message['tools_used'])}]" if message.get("tools_used") else ""
            )
            lines.append(
                f"[{message.get('timestamp', '?')[:16]}] {message['role'].upper()}{tools}: {text}"
            )
        return "\n".join(lines)

    async def consolidate(
        self,
        messages: list[dict],
        provider: LLMClient,
        model: str,
    ) -> bool:
        """Consolidate the provided message chunk into MEMORY.md + HISTORY.md."""
        if not messages:
            return True

        current_memory = self.read_long_term()
        prompt = f"""Process this conversation and call the save_memory tool with your consolidation.

## Current Long-term Memory
{current_memory or "(empty)"}

## Conversation to Process
{self._format_messages(messages)}"""

        chat_messages = [
            {
                "role": "system",
                "content": "You are a memory consolidation agent. Call the save_memory tool with your consolidation of the conversation.",
            },
            {"role": "user", "content": prompt},
        ]

        try:
            forced = {"type": "function", "function": {"name": "save_memory"}}
            response = await provider.chat_with_retry(
                messages=chat_messages,
                tools=_SAVE_MEMORY_TOOL,
                model=model,
                tool_choice=forced,
            )

            if response.finish_reason == "error" and _is_tool_choice_unsupported(response.content):
                logger.warning("Forced tool_choice unsupported, retrying with auto")
                response = await provider.chat_with_retry(
                    messages=chat_messages,
                    tools=_SAVE_MEMORY_TOOL,
                    model=model,
                    tool_choice="auto",
                )

            if response.finish_reason == "length":
                logger.error(
                    "Memory consolidation TRUNCATED (finish_reason=length). "
                    "MEMORY.md update or history_entry was too long for the max_tokens limit ({}). "
                    "Aborting to avoid corrupting memory files.",
                    provider.generation.max_tokens,
                )
                return self._fail_or_raw_archive(messages)

            if not response.has_tool_calls:
                # Last ditch effort: try to parse the content as a tool-call arguments string
                if response.content:
                    args = _normalize_save_memory_args(response.content)
                    if not args:
                        return self._fail_or_raw_archive(messages)
                else:
                    return self._fail_or_raw_archive(messages)
            else:
                args = _normalize_save_memory_args(response.tool_calls[0].arguments)

            if args is None:
                logger.warning("Memory consolidation: unexpected save_memory arguments")
                return self._fail_or_raw_archive(messages)

            if (
                "history_entry" not in args
                or "memory_update" not in args
                or args["history_entry"] is None
                or args["memory_update"] is None
            ):
                logger.warning("Memory consolidation: save_memory payload missing required fields")
                return self._fail_or_raw_archive(messages)

            entry = _ensure_text(args["history_entry"]).strip()
            update = _ensure_text(args["memory_update"])

            if not entry:
                logger.warning("Memory consolidation: history_entry is empty")
                return self._fail_or_raw_archive(messages)

            self.append_history(entry)
            if update != current_memory:
                # Instead of overwriting MEMORY.md, we append these updates to STAGING.md
                # to be processed by the memory-synthesize skill later.
                staging_path = self.memory_dir / "STAGING.md"
                with open(staging_path, "a", encoding="utf-8") as f:
                    f.write(f"\n## Consolidation Update: {datetime.now().isoformat()}\n{update}\n")
                logger.info("Memory updates staged to STAGING.md")

            self._consecutive_failures = 0
            logger.info("Memory consolidation done for {} messages", len(messages))
            return True
        except Exception:
            logger.exception("Memory consolidation failed")
            return self._fail_or_raw_archive(messages)

    def _fail_or_raw_archive(self, messages: list[dict]) -> bool:
        """Increment failure count; after threshold, raw-archive messages and return True."""
        self._consecutive_failures += 1
        if self._consecutive_failures < self._MAX_FAILURES_BEFORE_RAW_ARCHIVE:
            return False
        self._raw_archive(messages)
        self._consecutive_failures = 0
        return True

    def _raw_archive(self, messages: list[dict]) -> None:
        """Fallback: dump raw messages to a recovery sidecar file."""
        ts = datetime.now()
        file_ts = ts.strftime("%Y%H%M%S")
        recovery_file = self.recovery_dir / f"recovery_{file_ts}_{uuid4().hex[:8]}.json"
        recovery_file.write_text(
            json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.warning(
            "Memory consolidation degraded: raw-archived %d messages to %s",
            len(messages),
            recovery_file.name,
        )
        hist_ts = ts.strftime("%Y-%m-%d %H:%M")
        self.append_history(
            f"[{hist_ts}] [RAW] {len(messages)} messages archived to recovery sidecar: {recovery_file.name}"
        )


class MemoryConsolidator:
    """Owns consolidation policy, locking, and session offset updates."""

    _MAX_CONSOLIDATION_ROUNDS = 5
    _SAFETY_BUFFER = 1024  # extra headroom for tokenizer estimation drift

    def __init__(
        self,
        workspace: Path,
        provider: LLMClient,
        model: str,
        sessions: SessionManager,
        context_window_tokens: int,
        build_messages: Callable[..., list[dict[str, Any]]],
        get_tool_definitions: Callable[[], list[dict[str, Any]]],
        max_completion_tokens: int = 4096,
    ):
        self.store = MemoryStore(workspace)
        self.provider = provider
        self.model = model
        self.sessions = sessions

        # Override context_window_tokens with provider's max if available
        provider_context_max = (
            getattr(provider.generation, "context_max", None)
            if hasattr(provider, "generation")
            else None
        )
        self.context_window_tokens = (
            provider_context_max if provider_context_max is not None else context_window_tokens
        )

        self.max_completion_tokens = max_completion_tokens
        self._build_messages = build_messages
        self._get_tool_definitions = get_tool_definitions
        self._locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()

    def get_lock(self, session_key: str) -> asyncio.Lock:
        """Return the shared consolidation lock for one session."""
        return self._locks.setdefault(session_key, asyncio.Lock())

    async def consolidate_messages(self, messages: list[dict[str, object]]) -> bool:
        """Archive a selected message chunk into persistent memory."""
        return await self.store.consolidate(messages, self.provider, self.model)

    def pick_consolidation_boundary(
        self,
        session: Session,
        tokens_to_remove: int,
    ) -> tuple[int, int] | None:
        """Pick a user-turn boundary that removes enough old prompt tokens."""
        start = session.last_consolidated
        if start >= len(session.messages) or tokens_to_remove <= 0:
            return None

        removed_tokens = 0
        last_boundary: tuple[int, int] | None = None
        for idx in range(start, len(session.messages)):
            message = session.messages[idx]
            if idx > start and message.get("role") == "user":
                last_boundary = (idx, removed_tokens)
                if removed_tokens >= tokens_to_remove:
                    return last_boundary
            removed_tokens += estimate_message_tokens(message)

        return last_boundary

    def estimate_session_prompt_tokens(self, session: Session) -> tuple[int, str]:
        """Estimate current prompt size for the normal session history view."""
        history = session.get_history(max_messages=0)
        from nanobot.bus.events import Address

        try:
            addr = Address.from_uri(session.key)
            channel = addr.channel
            chat_id = addr.segments[0] if addr.segments else None
        except Exception:
            channel, chat_id = None, None
        probe_messages = self._build_messages(
            history=history,
            current_message="[token-probe]",
            channel=channel,
            chat_id=chat_id,
        )
        return estimate_prompt_tokens_chain(
            self.provider,
            self.model,
            probe_messages,
            self._get_tool_definitions(),
        )

    async def archive_messages(self, messages: list[dict[str, object]]) -> bool:
        """Archive messages with guaranteed persistence (retries until raw-dump fallback)."""
        if not messages:
            return True
        for _ in range(self.store._MAX_FAILURES_BEFORE_RAW_ARCHIVE):
            if await self.consolidate_messages(messages):
                return True
        return True

    async def maybe_consolidate_by_tokens(
        self, session: Session, context_window_tokens: int
    ) -> None:
        """Archive old messages until prompt fits within safe budget.

        context_window_tokens is the *chat session's* context ceiling (from the
        active agent profile), used to calculate consolidation thresholds and
        how much history to keep.  This is distinct from the consolidator's own
        provider context limit, which constrains how much the consolidator can
        process in a single LLM call.
        """
        if not session.messages or context_window_tokens <= 0:
            return

        lock = self.get_lock(session.key)
        async with lock:
            budget = context_window_tokens - self.max_completion_tokens - self._SAFETY_BUFFER
            target = budget // 2
            estimated, source = self.estimate_session_prompt_tokens(session)
            if estimated <= 0:
                return
            if estimated < budget:
                return

            for round_num in range(self._MAX_CONSOLIDATION_ROUNDS):
                if estimated <= target:
                    return

                boundary = self.pick_consolidation_boundary(session, max(1, estimated - target))
                if boundary is None:
                    return

                end_idx = boundary[0]
                chunk = session.messages[session.last_consolidated : end_idx]
                if not chunk:
                    return

                if not await self.consolidate_messages(chunk):
                    return
                session.last_consolidated = end_idx
                self.sessions.save(session)

                estimated, source = self.estimate_session_prompt_tokens(session)
                if estimated <= 0:
                    return
