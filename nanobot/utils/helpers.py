"""Utility functions for nanobot."""

import base64
import hashlib
import json
import math
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import tiktoken


def strip_think(text: str) -> str:
    """Remove <think>…</think> blocks and any unclosed trailing <think> tag."""
    text = re.sub(r"<think>[\s\S]*?</think>", "", text)
    text = re.sub(r"<think>[\s\S]*$", "", text)
    return text.strip()


def detect_image_mime(data: bytes) -> str | None:
    """Detect image MIME type from magic bytes, ignoring file extension."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def build_image_content_blocks(
    raw: bytes, mime: str, path: str, label: str
) -> list[dict[str, Any]]:
    """Build native image blocks plus a short text label."""
    b64 = base64.b64encode(raw).decode()
    return [
        {
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{b64}"},
            "_meta": {"path": path},
        },
        {"type": "text", "text": label},
    ]


# ---------------------------------------------------------------------------
# Audio content helpers (Task 2.1 — internal schema extension)
# ---------------------------------------------------------------------------

_AUDIO_MIME_TYPES = frozenset(
    (
        "audio/ogg",
        "audio/mpeg",
        "audio/wav",
        "audio/flac",
        "audio/mp4",
        "audio/mp3",
        "audio/x-m4a",
        "audio/webm",
        "audio/aac",
    )
)


def build_audio_content_block(raw: bytes, mime: str, path: str = "") -> dict[str, Any]:
    """Build an internal audio content block.

    Schema (consistent with how ``image_url`` blocks are structured):

    .. code-block:: python

        {
            "type": "audio",
            "data": "data:<mime>;base64,<base64-payload>",
            "mime_type": "<mime>",
            "_meta": {"path": "<file_path>"},   # optional, stripped during sanitization
        }

    Args:
        raw: Raw audio bytes (e.g. ogg, mp3, wav).
        mime: MIME type (e.g. ``"audio/ogg"``).
        path: Optional file-system path for debug / audit trails.

    Returns:
        A single content block dict suitable for inclusion in a message's
        ``content`` list.
    """
    b64 = base64.b64encode(raw).decode()
    block: dict[str, Any] = {
        "type": "audio",
        "data": f"data:{mime};base64,{b64}",
        "mime_type": mime,
    }
    if path:
        block["_meta"] = {"path": path}
    return block


def has_audio_content(messages: list[dict[str, Any]]) -> bool:
    """Return ``True`` if any message in *messages* contains an audio block.

    Used by the routing logic (Phase 4) to decide whether to target an
    audio-capable model or fall back to the transcription pipeline.
    """
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "audio":
                    return True
    return False


def has_image_content(messages: list[dict[str, Any]]) -> bool:
    """Return ``True`` if any message in *messages* contains an image block."""
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "image_url":
                    return True
    return False


def has_multimodal_content(messages: list[dict[str, Any]]) -> bool:
    """Return ``True`` if any message contains audio or image blocks."""
    return has_image_content(messages) or has_audio_content(messages)


def _extract_text(message: Any) -> str:
    """Extract text content from a message, handling various content block types."""
    if isinstance(message, str):
        return message
    if not isinstance(message, dict):
        return str(message) if message else ""

    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif block.get("type") == "tool_result":
                    content_val = block.get("content", "")
                    if isinstance(content_val, list):
                        for sub_block in content_val:
                            if isinstance(sub_block, dict) and sub_block.get("type") == "text":
                                parts.append(sub_block.get("text", ""))
                    elif isinstance(content_val, str):
                        parts.append(content_val)
                elif block.get("type") == "tool_use":
                    parts.append(f"[tool: {block.get('name', '?')}]")
        return "\n".join(p for p in parts if p)
    return str(content) if content else ""


def ensure_dir(path: Path) -> Path:
    """Ensure directory exists, return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def timestamp() -> str:
    """Current ISO timestamp."""
    return datetime.now().isoformat()


def current_time_str(timezone: str | None = None) -> str:
    """Human-readable current time with weekday and UTC offset.

    When *timezone* is a valid IANA name (e.g. ``"Asia/Shanghai"``), the time
    is converted to that zone.  Otherwise falls back to the host local time.
    """
    from zoneinfo import ZoneInfo

    try:
        tz = ZoneInfo(timezone) if timezone else None
    except (KeyError, Exception):
        tz = None

    now = datetime.now(tz=tz) if tz else datetime.now().astimezone()
    offset = now.strftime("%z")
    offset_fmt = f"{offset[:3]}:{offset[3:]}" if len(offset) == 5 else offset
    tz_name = timezone or (time.strftime("%Z") or "UTC")
    return f"{now.strftime('%Y-%m-%d %H:%M (%A)')} ({tz_name}, UTC{offset_fmt})"


_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*]')


def safe_filename(name: str) -> str:
    """Replace unsafe path characters with underscores."""
    return _UNSAFE_CHARS.sub("_", name).strip()


def split_message(content: str, max_len: int = 2000) -> list[str]:
    """
    Split content into chunks within max_len, preferring line breaks.

    Args:
        content: The text content to split.
        max_len: Maximum length per chunk (default 2000 for Discord compatibility).

    Returns:
        List of message chunks, each within max_len.
    """
    if not content:
        return []
    if len(content) <= max_len:
        return [content]
    chunks: list[str] = []
    while content:
        if len(content) <= max_len:
            chunks.append(content)
            break
        cut = content[:max_len]
        # Try to break at newline first, then space, then hard break
        pos = cut.rfind("\n")
        if pos <= 0:
            pos = cut.rfind(" ")
        if pos <= 0:
            pos = max_len
        chunks.append(content[:pos])
        content = content[pos:].lstrip()
    return chunks


def build_assistant_message(
    content: str | None,
    tool_calls: list[dict[str, Any]] | None = None,
    reasoning_content: str | None = None,
    thinking_blocks: list[dict] | None = None,
) -> dict[str, Any]:
    """Build a provider-safe assistant message with optional reasoning fields."""
    msg: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    if reasoning_content is not None:
        msg["reasoning_content"] = reasoning_content
    if thinking_blocks:
        msg["thinking_blocks"] = thinking_blocks
    return msg


def estimate_prompt_tokens(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> int:
    """Estimate prompt tokens with tiktoken.

    Counts all fields that providers send to the LLM: content, tool_calls,
    reasoning_content, tool_call_id, name, plus per-message framing overhead.
    """
    try:
        enc = tiktoken.get_encoding("cl100k_base")
        parts: list[str] = []
        for msg in messages:
            content = msg.get("content")
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        txt = part.get("text", "")
                        if txt:
                            parts.append(txt)

            tc = msg.get("tool_calls")
            if tc:
                parts.append(json.dumps(tc, ensure_ascii=False))

            rc = msg.get("reasoning_content")
            if isinstance(rc, str) and rc:
                parts.append(rc)

            for key in ("name", "tool_call_id"):
                value = msg.get(key)
                if isinstance(value, str) and value:
                    parts.append(value)

        if tools:
            parts.append(json.dumps(tools, ensure_ascii=False))

        per_message_overhead = len(messages) * 4
        return len(enc.encode("\n".join(parts))) + per_message_overhead
    except Exception:
        return 0


def estimate_message_tokens(message: dict[str, Any]) -> int:
    """Estimate prompt tokens contributed by one persisted message."""
    content = message.get("content")
    parts: list[str] = []
    if isinstance(content, str):
        parts.append(content)
    elif isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text = part.get("text", "")
                if text:
                    parts.append(text)
            else:
                parts.append(json.dumps(part, ensure_ascii=False))
    elif content is not None:
        parts.append(json.dumps(content, ensure_ascii=False))

    for key in ("name", "tool_call_id"):
        value = message.get(key)
        if isinstance(value, str) and value:
            parts.append(value)
    if message.get("tool_calls"):
        parts.append(json.dumps(message["tool_calls"], ensure_ascii=False))

    rc = message.get("reasoning_content")
    if isinstance(rc, str) and rc:
        parts.append(rc)

    payload = "\n".join(parts)
    if not payload:
        return 4
    try:
        enc = tiktoken.get_encoding("cl100k_base")
        return max(4, len(enc.encode(payload)) + 4)
    except Exception:
        return max(4, len(payload) // 4 + 4)


def estimate_prompt_tokens_chain(
    provider: Any,
    model: str | None,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> tuple[int, str]:
    """Estimate prompt tokens via provider counter first, then tiktoken fallback."""
    provider_counter = getattr(provider, "estimate_prompt_tokens", None)
    if callable(provider_counter):
        try:
            tokens, source = provider_counter(messages, tools, model)
            if isinstance(tokens, (int, float)) and tokens > 0:
                return int(tokens), str(source or "provider_counter")
        except Exception:
            pass

    estimated = estimate_prompt_tokens(messages, tools)
    if estimated > 0:
        return int(estimated), "tiktoken"
    return 0, "none"


# ---------------------------------------------------------------------------
# Prefix-Anchor calibration (Phase 3)
# ---------------------------------------------------------------------------


def calculate_base_hash(
    system_prompt: str,
    tools: list[dict[str, Any]] | None = None,
) -> str:
    """SHA-256 hash of the static base content (system prompt + tool definitions).

    Used as the "base anchor" to detect when the non-conversation portion
    of a prompt has changed between turns (e.g. system prompt refresh,
    tools added/removed).
    """
    payload = system_prompt
    if tools:
        payload += "\n\n---[TOOLS]---\n" + json.dumps(tools, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def calculate_history_hash(messages: list[dict[str, Any]]) -> str:
    """SHA-256 hash of the conversation history prefix (all but the last message).

    By excluding the newest message, this hash remains stable across turns
    when only a single message is appended, enabling incremental delta
    calculation in :func:`calculate_calibrated_prompt_tokens`.
    """
    prefix = messages[:-1]  # always hash all but the last message
    return hashlib.sha256(
        json.dumps(prefix, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def calculate_calibrated_prompt_tokens(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    ratio: float,
    *,
    current_base_hash: str,
    current_history_hash: str,
    prev_actual: int,
    prev_base_hash: str,
    prev_history_hash: str,
) -> int:
    """Calculate prompt token count using the Prefix-Anchor approach.

    If both the base content (system+tools) and the history hashes match
    the previous turn, we assume only new messages were appended and use
    incremental estimation scaled by the calibration ratio.
    Otherwise, we fall back to a full tiktoken estimate scaled by ratio.

    Args:
        messages: Complete message list including the current user message.
        tools: Tool definitions (if any).
        ratio: Calibration ratio (actual / estimated) from the model family.
        current_base_hash: SHA-256 of current system prompt + tools.
        current_history_hash: SHA-256 of current messages.
        prev_actual: Actual prompt tokens from the previous LLM call.
        prev_base_hash: Base hash from the previous turn.
        prev_history_hash: History hash from the previous turn.

    Returns:
        Calibrated prompt token estimate.
    """
    if (
        current_base_hash == prev_base_hash
        and current_history_hash == prev_history_hash
        and prev_actual > 0
    ):
        # Anchor match — incremental delta only.
        # Estimate tokens for just the newly appended messages
        # (everything after the prefix hashed by calculate_history_hash).
        new_messages = messages[-1:]
        incremental = estimate_prompt_tokens(new_messages, tools)
        return prev_actual + max(0, math.ceil(incremental * ratio))
    # Full estimate
    full = estimate_prompt_tokens(messages, tools)
    return int(full * ratio)


def build_status_content(
    *,
    version: str,
    model: str,
    start_time: float,
    last_usage: dict[str, int],
    context_window_tokens: int,
    session_msg_count: int,
    context_tokens_estimate: int,
) -> str:
    """Build a human-readable runtime status snapshot."""
    uptime_s = int(time.time() - start_time)
    uptime = (
        f"{uptime_s // 3600}h {(uptime_s % 3600) // 60}m"
        if uptime_s >= 3600
        else f"{uptime_s // 60}m {uptime_s % 60}s"
    )
    last_in = last_usage.get("prompt_tokens", 0)
    last_out = last_usage.get("completion_tokens", 0)
    ctx_total = max(context_window_tokens, 0)
    ctx_pct = int((context_tokens_estimate / ctx_total) * 100) if ctx_total > 0 else 0
    ctx_used_str = (
        f"{context_tokens_estimate // 1000}k"
        if context_tokens_estimate >= 1000
        else str(context_tokens_estimate)
    )
    ctx_total_str = f"{ctx_total // 1024}k" if ctx_total > 0 else "n/a"
    return "\n".join(
        [
            f"\U0001f408 nanobot v{version}",
            f"\U0001f9e0 Model: {model}",
            f"\U0001f4ca Tokens: {last_in} in / {last_out} out",
            f"\U0001f4da Context: {ctx_used_str}/{ctx_total_str} ({ctx_pct}%)",
            f"\U0001f4ac Session: {session_msg_count} messages",
            f"\u23f1 Uptime: {uptime}",
        ]
    )


def sync_workspace_templates(workspace: Path, silent: bool = False) -> list[str]:
    """Sync bundled templates to workspace. Only creates missing files."""
    from importlib.resources import files as pkg_files

    try:
        tpl = pkg_files("nanobot") / "templates"
    except Exception:
        return []
    if not tpl.is_dir():
        return []

    added: list[str] = []

    def _write(src, dest: Path):
        if dest.exists():
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(src.read_text(encoding="utf-8") if src else "", encoding="utf-8")
        added.append(str(dest.relative_to(workspace)))

    for item in tpl.iterdir():
        if item.name.endswith(".md") and not item.name.startswith("."):
            _write(item, workspace / item.name)
    _write(tpl / "memory" / "MEMORY.md", workspace / "memory" / "MEMORY.md")
    _write(None, workspace / "memory" / "HISTORY.md")
    (workspace / "skills").mkdir(exist_ok=True)

    if added and not silent:
        from rich.console import Console

        for name in added:
            Console().print(f"  [dim]Created {name}[/dim]")
    return added


def resolve_context_window(
    profile_limit: int | None,
    provider_max: int | None,
    fallback: int,
) -> int:
    """Resolve effective context window from profile limit and provider max.

    Models without a configured context_max are ignored, not treated as infinite.
    """
    if isinstance(provider_max, int) and profile_limit:
        return min(profile_limit, provider_max)
    elif profile_limit:
        return profile_limit
    elif isinstance(provider_max, int):
        return provider_max
    return fallback
