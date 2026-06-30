from unittest.mock import MagicMock

from nanobot.command.builtin import cmd_forget
from nanobot.session.manager import Session


async def test_cmd_forget_basic(tmp_path):
    # Setup
    mock_loop = MagicMock()
    mock_loop.sessions = MagicMock()

    # Mock session
    session = Session(key="test:forget")
    session.messages = [
        {"role": "user", "content": "m1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "m2"},
        {"role": "assistant", "content": "a2"},
        {"role": "user", "content": "m3"},
    ]
    session.last_consolidated = 2  # Marker after a1

    mock_loop.sessions.get_or_create.return_value = session

    # We mock CommandContext because it's usually in TYPE_CHECKING and hard to instantiate in tests
    ctx = MagicMock()
    ctx.loop = mock_loop
    ctx.session = session
    ctx.key = "test:forget"
    ctx.msg = MagicMock(address=MagicMock(channel="tg", sender_id="123"), sender_id="123")
    ctx.raw = "/forget"

    # Execute
    response = await cmd_forget(ctx)

    # Verify
    assert len(session.messages) == 2
    assert session.messages == [
        {"role": "user", "content": "m1"},
        {"role": "assistant", "content": "a1"},
    ]
    assert session.last_consolidated == 2
    assert "Forgot 3 messages" in response.content
    mock_loop.sessions.save.assert_called_with(session)


async def test_cmd_forget_already_at_marker():
    mock_loop = MagicMock()
    mock_loop.sessions = MagicMock()

    session = Session(key="test:forget_marker")
    session.messages = [
        {"role": "user", "content": "m1"},
    ]
    session.last_consolidated = 1

    mock_loop.sessions.get_or_create.return_value = session

    ctx = MagicMock()
    ctx.loop = mock_loop
    ctx.session = session
    ctx.key = "test:forget_marker"
    ctx.msg = MagicMock(address=MagicMock(channel="tg", sender_id="123"), sender_id="123")
    ctx.raw = "/forget"

    response = await cmd_forget(ctx)

    assert "Nothing to forget" in response.content
    assert len(session.messages) == 1


async def test_cmd_forget_marker_at_zero():
    mock_loop = MagicMock()
    mock_loop.sessions = MagicMock()

    session = Session(key="test:forget_zero")
    session.messages = [
        {"role": "user", "content": "m1"},
        {"role": "assistant", "content": "a1"},
    ]
    session.last_consolidated = 0

    mock_loop.sessions.get_or_create.return_value = session

    ctx = MagicMock()
    ctx.loop = mock_loop
    ctx.session = session
    ctx.key = "test:forget_zero"
    ctx.msg = MagicMock(address=MagicMock(channel="tg", sender_id="123"), sender_id="123")
    ctx.raw = "/forget"

    response = await cmd_forget(ctx)

    assert len(session.messages) == 0
    assert session.last_consolidated == 0
    assert "Forgot 2 messages" in response.content
