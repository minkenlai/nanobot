"""Tests for the streaming threshold logic in TelegramChannel.send_delta.

The threshold logic defers the first `send_message` call until the accumulated
buffer is "meaningful":
  - length >= 60 chars, OR
  - contains a newline (\n), OR
  - contains a sentence terminator (. ! ?)

Once message_id is set, subsequent deltas go straight to edit_message_text.
"""

import pytest
from conftest import _FakeBot

from nanobot.bus.events import Address, OutboundMessage
from nanobot.channels.telegram import TelegramChannel


def _make_delta(content: str, address: Address, metadata: dict | None = None) -> OutboundMessage:
    md = {"_stream_id": "stream-1"}
    if metadata:
        md.update(metadata)
    return OutboundMessage(address=address, content=content, metadata=md)


@pytest.mark.asyncio
async def test_short_chunk_does_not_trigger_send(telegram_channel: TelegramChannel) -> None:
    """A very short initial chunk ('T') must NOT trigger send_message."""
    ch = telegram_channel
    address = Address(channel="tg", segments=("42",))
    delta = _make_delta("T", address)

    await ch.send_delta(delta)

    bot = ch._app.bot
    assert len(bot.sent_messages) == 0, "send_message should NOT have been called for short chunk"
    buf = ch._stream_bufs.get(address.to_uri())
    assert buf is not None
    assert buf.message_id is None, "message_id must still be None"
    assert buf.text == "T"


@pytest.mark.asyncio
async def test_chunk_reaching_length_threshold_triggers_send(
    telegram_channel: TelegramChannel,
) -> None:
    """A chunk reaching >= 60 chars MUST trigger the initial send_message."""
    ch = telegram_channel
    address = Address(channel="tg", segments=("42",))
    long_text = "A" * 60  # exactly 60 chars

    delta = _make_delta(long_text, address)

    await ch.send_delta(delta)

    bot = ch._app.bot
    assert len(bot.sent_messages) == 1, "send_message should have been called once"
    assert bot.sent_messages[0]["text"] == long_text

    buf = ch._stream_bufs.get(address.to_uri())
    assert buf is not None
    assert buf.message_id is not None, "message_id must be set after initial send"


@pytest.mark.asyncio
async def test_newline_triggers_send(telegram_channel: TelegramChannel) -> None:
    """A chunk containing a newline MUST trigger the initial send regardless of length."""
    ch = telegram_channel
    address = Address(channel="tg", segments=("42",))
    short_with_newline = "Hello\n"  # only 6 chars

    delta = _make_delta(short_with_newline, address)

    await ch.send_delta(delta)

    bot = ch._app.bot
    assert len(bot.sent_messages) == 1, "send_message should have been called for newline chunk"
    assert bot.sent_messages[0]["text"] == short_with_newline


@pytest.mark.asyncio
async def test_sentence_terminator_triggers_send(telegram_channel: TelegramChannel) -> None:
    """A chunk containing a sentence terminator (. ! ?) MUST trigger the initial send."""
    ch = telegram_channel
    address = Address(channel="tg", segments=("42",))

    for terminator, content in [
        (".", "Done."),
        ("!", "Wow!"),
        ("?", "Why?"),
    ]:
        # Fresh bot per sub-test
        ch._app.bot = _FakeBot()
        ch._stream_bufs.clear()

        delta = _make_delta(content, address)
        await ch.send_delta(delta)

        fresh_bot = ch._app.bot
        assert len(fresh_bot.sent_messages) == 1, (
            f"send_message should have been called for content ending with '{terminator}'"
        )
        assert fresh_bot.sent_messages[0]["text"] == content
        buf = ch._stream_bufs.get(address.to_uri())
        assert buf is not None
        assert buf.message_id is not None, f"message_id must be set for terminator '{terminator}'"


@pytest.mark.asyncio
async def test_subsequent_deltas_edit_after_initial_send(
    telegram_channel: TelegramChannel,
) -> None:
    """Once message_id is set, subsequent deltas should go through edit_message_text."""
    ch = telegram_channel
    address = Address(channel="tg", segments=("42",))

    # First delta: enough to trigger initial send (contains '.')
    delta1 = _make_delta("Hello.", address)
    await ch.send_delta(delta1)

    bot = ch._app.bot
    assert len(bot.sent_messages) == 1, "Initial send should happen once"

    # Second delta: more content, should NOT trigger another send_message
    delta2 = _make_delta(" World", address)
    await ch.send_delta(delta2)

    # After the second delta, the buffer should have accumulated "Hello. World"
    buf = ch._stream_bufs.get(address.to_uri())
    assert buf is not None
    assert buf.message_id is not None
    assert buf.text == "Hello. World", "Buffer should accumulate delta content"

    # send_message should still be called exactly once (no re-sends)
    assert len(bot.sent_messages) == 1, "No additional send_message calls for subsequent deltas"


@pytest.mark.asyncio
async def test_short_response_sent_on_stream_end(
    telegram_channel: TelegramChannel,
) -> None:
    """A short response that never hit the threshold MUST still be sent when the stream ends."""
    ch = telegram_channel
    address = Address(channel="tg", segments=("42",))

    # 1. Send a short fragment that doesn't trigger initial send
    delta1 = _make_delta("Hello", address)
    await ch.send_delta(delta1)

    bot = ch._app.bot
    assert len(bot.sent_messages) == 0, "Should not have sent yet (below threshold)"

    # 2. Send the stream end signal
    delta_end = _make_delta("", address, metadata={"_stream_end": True})
    await ch.send_delta(delta_end)

    # 3. Verify it was finally sent
    assert len(bot.sent_messages) == 1, "Short response must be sent on stream end"
    assert bot.sent_messages[0]["text"] == "Hello"
