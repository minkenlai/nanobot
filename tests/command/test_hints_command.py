"""Tests for /hints slash command."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nanobot.bus.events import InboundMessage
from nanobot.channels.manager import ChannelManager
from nanobot.command.builtin import SESSION_TOOL_HINTS_METADATA_KEY, cmd_hints
from nanobot.command.router import CommandContext


@pytest.fixture
def mock_session() -> MagicMock:
    session = MagicMock()
    session.metadata = {}
    return session


@pytest.fixture
def mock_loop(mock_session: MagicMock) -> MagicMock:
    loop = MagicMock()
    loop.sessions.get_or_create.return_value = mock_session
    loop.channels_config.send_tool_hints = True
    return loop


@pytest.mark.asyncio
async def test_cmd_hints_on(mock_session: MagicMock, mock_loop: MagicMock) -> None:
    msg = InboundMessage(channel="telegram", chat_id="-10012345", content="/hints on", sender_id="user_1")
    ctx = CommandContext(
        msg=msg,
        session=mock_session,
        key="telegram:-10012345",
        raw="/hints on",
        args="on",
        loop=mock_loop,
    )

    res = await cmd_hints(ctx)
    assert res is not None
    assert mock_session.metadata.get(SESSION_TOOL_HINTS_METADATA_KEY) is True
    assert "Tool hints enabled" in res.content
    mock_loop.sessions.save.assert_called_with(mock_session)


@pytest.mark.asyncio
async def test_cmd_hints_off(mock_session: MagicMock, mock_loop: MagicMock) -> None:
    msg = InboundMessage(channel="telegram", chat_id="-10012345", content="/hints off", sender_id="user_1")
    ctx = CommandContext(
        msg=msg,
        session=mock_session,
        key="telegram:-10012345",
        raw="/hints off",
        args="off",
        loop=mock_loop,
    )

    res = await cmd_hints(ctx)
    assert res is not None
    assert mock_session.metadata.get(SESSION_TOOL_HINTS_METADATA_KEY) is False
    assert "Tool hints disabled" in res.content
    mock_loop.sessions.save.assert_called_with(mock_session)


@pytest.mark.asyncio
async def test_cmd_hints_reset(mock_session: MagicMock, mock_loop: MagicMock) -> None:
    mock_session.metadata[SESSION_TOOL_HINTS_METADATA_KEY] = False
    msg = InboundMessage(channel="telegram", chat_id="-10012345", content="/hints reset", sender_id="user_1")
    ctx = CommandContext(
        msg=msg,
        session=mock_session,
        key="telegram:-10012345",
        raw="/hints reset",
        args="reset",
        loop=mock_loop,
    )

    res = await cmd_hints(ctx)
    assert res is not None
    assert SESSION_TOOL_HINTS_METADATA_KEY not in mock_session.metadata
    assert "reset to default" in res.content
    mock_loop.sessions.save.assert_called_with(mock_session)


@pytest.mark.asyncio
async def test_cmd_hints_status_query(mock_session: MagicMock, mock_loop: MagicMock) -> None:
    mock_session.metadata[SESSION_TOOL_HINTS_METADATA_KEY] = True
    msg = InboundMessage(channel="telegram", chat_id="-10012345", content="/hints", sender_id="user_1")
    ctx = CommandContext(
        msg=msg,
        session=mock_session,
        key="telegram:-10012345",
        raw="/hints",
        args="",
        loop=mock_loop,
    )

    res = await cmd_hints(ctx)
    assert res is not None
    assert "Enabled" in res.content
    assert "/hints on" in res.content


def test_channel_manager_should_send_progress_respects_session_override() -> None:
    manager = MagicMock(spec=ChannelManager)
    # Use real method implementation
    manager.channels = {"telegram": MagicMock(send_tool_hints=False, send_progress=True)}
    manager._should_send_progress = ChannelManager._should_send_progress.__get__(manager, ChannelManager)

    # Without override -> uses channel default (False)
    assert manager._should_send_progress("telegram", tool_hint=True, msg_metadata={}) is False

    # With override send_tool_hints: True -> returns True
    assert manager._should_send_progress("telegram", tool_hint=True, msg_metadata={"send_tool_hints": True}) is True

    # With override send_tool_hints: False -> returns False
    assert manager._should_send_progress("telegram", tool_hint=True, msg_metadata={"send_tool_hints": False}) is False
