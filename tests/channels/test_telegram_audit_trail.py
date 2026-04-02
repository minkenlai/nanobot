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
        metadata={"_progress": True, "_tool_hint": True}
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
        metadata={"_progress": True, "_tool_hint": True}
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
        metadata={}
    )
    await channel.send(final_msg)

    # Finalize should have edited the message one last time
    assert len(mock_app.bot.edited_messages) == 2
    final_audit_text = mock_app.bot.edited_messages[1]["text"]
    assert "📋 <b>Audit Trail (Complete):</b>" in final_audit_text
    assert "✅ <code>Step 1: Searching</code>" in final_audit_text
    assert "✅ <code>Step 2: Reading</code>" in final_audit_text
    assert "⚙️" not in final_audit_text
