from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.channels.telegram import TelegramChannel


@pytest.mark.asyncio
async def test_audit_trail_rollover():
    mock_bot = AsyncMock()
    mock_app = MagicMock()
    mock_app.bot = mock_bot
    mock_bus = MagicMock()
    channel = TelegramChannel(mock_app, mock_bus)
    channel._app = mock_app

    address_uri = "tg://12345/678"
    from nanobot.bus.events import Address, OutboundMessage

    addr = Address(channel="tg", segments=("12345", "678"))

    # 1. Initial send
    mock_bot.send_message.return_value = MagicMock(message_id=100)
    msg1 = OutboundMessage(
        address=addr, content="Step 1", metadata={"_progress": True, "_tool_hint": True}
    )
    await channel._update_audit_trail(msg1)
    assert mock_bot.send_message.call_count == 1
    assert channel._progress_message_id[address_uri] == 100

    # 2. Normal update (edit)
    msg2 = OutboundMessage(
        address=addr, content="Step 2", metadata={"_progress": True, "_tool_hint": True}
    )
    await channel._update_audit_trail(msg2)
    assert mock_bot.edit_message_text.call_count == 1
    assert mock_bot.send_message.call_count == 1
    assert channel._progress_message_id[address_uri] == 100

    # 3. Long update (rollover)
    mock_bot.send_message.return_value = MagicMock(message_id=200)
    long_step = "A" * 4500
    msg_long = OutboundMessage(
        address=addr, content=long_step, metadata={"_progress": True, "_tool_hint": True}
    )
    await channel._update_audit_trail(msg_long)

    # Should have sent a new message (id 200)
    assert mock_bot.send_message.call_count == 2
    assert channel._progress_message_id[address_uri] == 200


@pytest.mark.asyncio
async def test_audit_trail_edit_failure_rollover():
    mock_bot = AsyncMock()
    mock_app = MagicMock()
    mock_app.bot = mock_bot
    mock_bus = MagicMock()
    channel = TelegramChannel(mock_app, mock_bus)
    channel._app = mock_app

    address_uri = "tg://12345/678"
    # Set an existing message ID
    channel._progress_message_id[address_uri] = 100

    # Mock edit_message_text to fail
    mock_bot.edit_message_text.side_effect = Exception("Message to edit not found")
    mock_bot.send_message.return_value = MagicMock(message_id=200)

    from nanobot.bus.events import Address, OutboundMessage

    addr = Address(channel="tg", segments=("12345", "678"))
    msg = OutboundMessage(
        address=addr, content="Step 1", metadata={"_progress": True, "_tool_hint": True}
    )

    await channel._update_audit_trail(msg)

    # Should have attempted edit, failed, and sent new message
    assert mock_bot.edit_message_text.call_count == 1
    assert mock_bot.send_message.call_count == 1
    assert channel._progress_message_id[address_uri] == 200
