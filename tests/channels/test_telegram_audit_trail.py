from unittest.mock import MagicMock

import pytest

from nanobot.bus.events import Address, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.telegram import TelegramChannel, TelegramConfig


class _FakeBot:
    def __init__(self):
        self.sent_messages = []
        self.edited_messages = []

    async def send_message(self, **kwargs):
        self.sent_messages.append(kwargs)
        # Return a mock message with a message_id
        msg = MagicMock()
        msg.message_id = len(self.sent_messages)
        return msg

    async def edit_message_text(self, **kwargs):
        self.edited_messages.append(kwargs)
        return True


@pytest.mark.asyncio
async def test_telegram_audit_trail_cumulative():
    config = TelegramConfig(enabled=True, token="fake:token", allow_from=["*"])
    channel = TelegramChannel(config, MessageBus())

    # Mock the Telegram Application and Bot
    mock_app = MagicMock()
    mock_app.bot = _FakeBot()
    channel._app = mock_app

    chat_id = "12345"

    # Step 1: First progress update (should send a new message)
    msg1 = OutboundMessage(
        address=Address(channel="telegram", segments=(chat_id,)),
        content="Step 1: Searching",
        metadata={"_progress": True, "_tool_hint": True},
    )
    await channel.send(msg1)

    assert len(mock_app.bot.sent_messages) == 1
    # The channel converts markdown to HTML
    sent_text = mock_app.bot.sent_messages[0]["text"]
    assert "⚙️ <code>Step 1: Searching</code>" in sent_text

    # Step 2: Second progress update (should edit the existing message)
    msg2 = OutboundMessage(
        address=Address(channel="telegram", segments=(chat_id,)),
        content="Step 2: Reading",
        metadata={"_progress": True, "_tool_hint": True},
    )
    await channel.send(msg2)

    assert len(mock_app.bot.edited_messages) == 1
    # Check that Step 1 is now "Done" and Step 2 is "Ongoing"
    edited_text = mock_app.bot.edited_messages[0]["text"]
    assert "✅ <code>Step 1: Searching</code>" in edited_text
    assert "⚙️ <code>Step 2: Reading</code>" in edited_text

    # Step 3: Final response (should finalize the audit trail)
    final_msg = OutboundMessage(
        address=Address(channel="telegram", segments=(chat_id,)),
        content="Final Answer",
        metadata={},
    )
    await channel.send(final_msg)

    # Finalize should have edited the message one last time
    assert len(mock_app.bot.edited_messages) == 2
    final_audit_text = mock_app.bot.edited_messages[1]["text"]
    assert "📋 <b>Audit Trail (Complete):</b>" in final_audit_text
    assert "✅ <code>Step 1: Searching</code>" in final_audit_text
    assert "✅ <code>Step 2: Reading</code>" in final_audit_text
    assert "⚙️" not in final_audit_text


@pytest.mark.asyncio
async def test_audit_trail_isolated_per_topic() -> None:
    """Concurrent topics in the same group must not share audit trail state.

    Before the fix, _progress_message_id and _progress_history were keyed by
    chat_id_str only, so two active topics in the same group would corrupt each
    other's state.  After the fix they are keyed by address.to_uri().
    """
    config = TelegramConfig(enabled=True, token="fake:token", allow_from=["*"])
    channel = TelegramChannel(config, MessageBus())

    mock_app = MagicMock()
    mock_app.bot = _FakeBot()
    channel._app = mock_app

    # Two different topics in the same group chat (chat_id="123")
    addr_topic1 = Address(channel="tg", segments=("123", "100"))
    addr_topic2 = Address(channel="tg", segments=("123", "200"))

    # Progress event for topic 1
    await channel.send(
        OutboundMessage(
            address=addr_topic1,
            content="Step in topic 1",
            metadata={"_progress": True, "_tool_hint": True},
        )
    )
    # Progress event for topic 2
    await channel.send(
        OutboundMessage(
            address=addr_topic2,
            content="Step in topic 2",
            metadata={"_progress": True, "_tool_hint": True},
        )
    )

    # Both topics must have sent their own separate audit trail messages.
    assert len(mock_app.bot.sent_messages) == 2
    assert "tg://123/100" in channel._progress_message_id
    assert "tg://123/200" in channel._progress_message_id

    # Topic 2's message must target thread 200, not thread 100.
    topic2_send = next(m for m in mock_app.bot.sent_messages if m.get("message_thread_id") == 200)
    assert topic2_send is not None

    # Finalise topic 1 — topic 2 must be unaffected.
    await channel.send(
        OutboundMessage(
            address=addr_topic1,
            content="Done",
            metadata={},
        )
    )

    assert "tg://123/100" not in channel._progress_message_id
    assert "tg://123/200" in channel._progress_message_id
