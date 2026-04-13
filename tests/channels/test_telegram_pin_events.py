"""Tests for event-driven profile pin cache (pin/unpin and edit handlers)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

try:
    import telegram  # noqa: F401
except ImportError:
    pytest.skip(
        "Telegram dependencies not installed (python-telegram-bot)", allow_module_level=True
    )

from nanobot.bus.queue import MessageBus
from nanobot.channels.telegram import TelegramChannel, TelegramConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_channel() -> TelegramChannel:
    config = TelegramConfig(enabled=True, token="123:abc", allow_from=["*"])
    return TelegramChannel(config, MessageBus())


def _pin_update(
    chat_id: int = -100,
    thread_id: int | None = 5,
    pinned_text: str | None = None,
    pinned_message_id: int = 42,
) -> SimpleNamespace:
    """Simulate a StatusUpdate.PINNED_MESSAGE update."""
    if pinned_text is not None:
        pinned = SimpleNamespace(
            message_id=pinned_message_id,
            text=pinned_text,
            caption=None,
            message_thread_id=thread_id,
        )
    else:
        pinned = None

    message = SimpleNamespace(
        chat_id=chat_id,
        message_thread_id=thread_id,
        pinned_message=pinned,
    )
    return SimpleNamespace(message=message)


def _edit_update(
    chat_id: int = -100,
    thread_id: int | None = 5,
    message_id: int = 42,
    text: str = "",
) -> SimpleNamespace:
    """Simulate an EDITED_MESSAGE update."""
    edited = SimpleNamespace(
        chat_id=chat_id,
        message_thread_id=thread_id,
        message_id=message_id,
        text=text,
        caption=None,
    )
    return SimpleNamespace(edited_message=edited)


# ---------------------------------------------------------------------------
# _parse_profile_from_message
# ---------------------------------------------------------------------------


def test_parse_profile_matches_profile_key():
    ch = _make_channel()
    msg = SimpleNamespace(text="Profile: fast", caption=None)
    assert ch._parse_profile_from_message(msg) == "fast"


def test_parse_profile_matches_agent_key():
    ch = _make_channel()
    msg = SimpleNamespace(text="Agent: deep", caption=None)
    assert ch._parse_profile_from_message(msg) == "deep"


def test_parse_profile_case_insensitive():
    ch = _make_channel()
    msg = SimpleNamespace(text="PROFILE: BALANCED", caption=None)
    assert ch._parse_profile_from_message(msg) == "balanced"


def test_parse_profile_from_caption():
    ch = _make_channel()
    msg = SimpleNamespace(text=None, caption="Profile: nano")
    assert ch._parse_profile_from_message(msg) == "nano"


def test_parse_profile_returns_none_for_unrelated_text():
    ch = _make_channel()
    msg = SimpleNamespace(text="Hello world", caption=None)
    assert ch._parse_profile_from_message(msg) is None


# ---------------------------------------------------------------------------
# _on_pin_event
# ---------------------------------------------------------------------------


async def test_on_pin_event_valid_profile():
    ch = _make_channel()
    update = _pin_update(pinned_text="Profile: fast", pinned_message_id=42)
    await ch._on_pin_event(update, None)
    assert ch._topic_pins["-100:5"] == (42, "fast")


async def test_on_pin_event_non_profile_message():
    ch = _make_channel()
    update = _pin_update(pinned_text="Important announcement", pinned_message_id=7)
    await ch._on_pin_event(update, None)
    assert ch._topic_pins["-100:5"] == (7, None)


async def test_on_pin_event_unpin_clears_cache():
    ch = _make_channel()
    # Seed the cache first
    ch._topic_pins["-100:5"] = (42, "fast")
    update = _pin_update(pinned_text=None)  # pinned_message=None means unpin
    await ch._on_pin_event(update, None)
    assert "-100:5" not in ch._topic_pins


async def test_on_pin_event_ignores_non_topic_chats():
    """Pin events without a thread_id (non-forum chats) should be ignored."""
    ch = _make_channel()
    update = _pin_update(thread_id=None, pinned_text="Profile: deep")
    await ch._on_pin_event(update, None)
    assert ch._topic_pins == {}


async def test_on_pin_event_no_message_is_noop():
    ch = _make_channel()
    update = SimpleNamespace(message=None)
    await ch._on_pin_event(update, None)
    assert ch._topic_pins == {}


# ---------------------------------------------------------------------------
# _on_edited_message
# ---------------------------------------------------------------------------


async def test_on_edited_message_updates_pinned_profile():
    ch = _make_channel()
    ch._topic_pins["-100:5"] = (42, "fast")
    update = _edit_update(message_id=42, text="Profile: deep")
    await ch._on_edited_message(update, None)
    assert ch._topic_pins["-100:5"] == (42, "deep")


async def test_on_edited_message_clears_profile_if_text_changed():
    """Editing pinned message to non-profile text should set profile to None."""
    ch = _make_channel()
    ch._topic_pins["-100:5"] = (42, "fast")
    update = _edit_update(message_id=42, text="Just a note")
    await ch._on_edited_message(update, None)
    assert ch._topic_pins["-100:5"] == (42, None)


async def test_on_edited_message_ignores_non_pinned_message():
    ch = _make_channel()
    ch._topic_pins["-100:5"] = (42, "fast")
    # Edit a different message (id=99, not the pinned 42)
    update = _edit_update(message_id=99, text="Profile: deep")
    await ch._on_edited_message(update, None)
    assert ch._topic_pins["-100:5"] == (42, "fast")  # unchanged


async def test_on_edited_message_no_cache_entry_is_noop():
    ch = _make_channel()
    update = _edit_update(message_id=42, text="Profile: deep")
    await ch._on_edited_message(update, None)
    assert ch._topic_pins == {}


async def test_on_edited_message_ignores_non_topic_chats():
    ch = _make_channel()
    update = _edit_update(thread_id=None, message_id=42, text="Profile: fast")
    await ch._on_edited_message(update, None)
    assert ch._topic_pins == {}


async def test_on_edited_message_no_edited_message_is_noop():
    ch = _make_channel()
    update = SimpleNamespace(edited_message=None)
    await ch._on_edited_message(update, None)
    assert ch._topic_pins == {}


# ---------------------------------------------------------------------------
# _get_topic_profile_pin
# ---------------------------------------------------------------------------


async def test_get_topic_profile_pin_cache_hit_no_api_call():
    """Cache hit returns immediately without calling bot.get_chat."""
    ch = _make_channel()
    ch._topic_pins["-100:5"] = (42, "fast")
    ch._app = SimpleNamespace(bot=SimpleNamespace(get_chat=AsyncMock()))

    result = await ch._get_topic_profile_pin(-100, 5)

    assert result == "fast"
    ch._app.bot.get_chat.assert_not_called()


async def test_get_topic_profile_pin_cold_start_seeds_cache():
    """Cold start calls bot.get_chat, parses profile, seeds cache with message_id."""
    ch = _make_channel()
    pinned_msg = SimpleNamespace(
        message_id=42,
        text="Profile: balanced",
        caption=None,
        message_thread_id=5,
    )
    fake_chat = SimpleNamespace(pinned_message=pinned_msg)
    ch._app = SimpleNamespace(bot=SimpleNamespace(get_chat=AsyncMock(return_value=fake_chat)))

    result = await ch._get_topic_profile_pin(-100, 5)

    assert result == "balanced"
    assert ch._topic_pins["-100:5"] == (42, "balanced")
    ch._app.bot.get_chat.assert_called_once_with(-100)


async def test_get_topic_profile_pin_cold_start_no_pin():
    """Cold start with no pinned message caches (None, None) and returns None."""
    ch = _make_channel()
    fake_chat = SimpleNamespace(pinned_message=None)
    ch._app = SimpleNamespace(bot=SimpleNamespace(get_chat=AsyncMock(return_value=fake_chat)))

    result = await ch._get_topic_profile_pin(-100, 5)

    assert result is None
    assert ch._topic_pins["-100:5"] == (-1, None)


async def test_get_topic_profile_pin_cold_start_pin_in_different_topic():
    """Pin exists but belongs to a different topic — cache (-1, None) for this topic."""
    ch = _make_channel()
    pinned_msg = SimpleNamespace(
        message_id=42,
        text="Profile: fast",
        caption=None,
        message_thread_id=99,  # different topic
    )
    fake_chat = SimpleNamespace(pinned_message=pinned_msg)
    ch._app = SimpleNamespace(bot=SimpleNamespace(get_chat=AsyncMock(return_value=fake_chat)))

    result = await ch._get_topic_profile_pin(-100, 5)

    assert result is None
    assert ch._topic_pins["-100:5"] == (-1, None)


async def test_get_topic_profile_pin_lazy_fill_then_discover_native():
    """Lazy fill seeds with (None, None), which triggers a native pin lookup on next use."""
    ch = _make_channel()
    # 1. Simulate lazy fill (e.g. from _on_message)
    ch._topic_pins["-100:5"] = (None, None)

    # 2. Setup a native pin to be discovered
    pinned_msg = SimpleNamespace(
        message_id=42,
        text="Profile: fast",
        caption=None,
        message_thread_id=5,
    )
    fake_chat = SimpleNamespace(pinned_message=pinned_msg)
    ch._app = SimpleNamespace(bot=SimpleNamespace(get_chat=AsyncMock(return_value=fake_chat)))

    # 3. Call get_topic_profile_pin - it should NOT return None from cache, but call API
    result = await ch._get_topic_profile_pin(-100, 5)

    assert result == "fast"
    assert ch._topic_pins["-100:5"] == (42, "fast")
    ch._app.bot.get_chat.assert_called_once()
