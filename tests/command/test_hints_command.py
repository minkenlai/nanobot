"""Tests for /hints slash command."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

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


@pytest.mark.asyncio
async def test_turn_delivery_applies_session_metadata_to_events() -> None:
    from nanobot.agent.turn_delivery import TurnDelivery, TurnRoute
    from nanobot.bus.events import InboundMessage
    from nanobot.bus.outbound_events import ProgressEvent
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    published = []

    async def fake_publish_event(event, *, channel, chat_id, metadata=None):
        published.append({"event": event, "channel": channel, "chat_id": chat_id, "metadata": metadata})

    bus.publish_event = fake_publish_event

    msg = InboundMessage(channel="telegram", chat_id="123", content="hi", sender_id="user1", metadata={})
    delivery = TurnDelivery(
        bus=bus,
        runtime_event_publisher=MagicMock(),
        input_message=msg,
        session_key="telegram:123",
        route=TurnRoute(channel="telegram", chat_id="123", metadata={}, publish_lifecycle=True),
    )

    delivery.apply_session_metadata({"send_tool_hints": False})

    await delivery.events.publish(ProgressEvent(content="read foo", tool_hint=True))
    assert len(published) == 1
    assert published[0]["metadata"].get("send_tool_hints") is False


@pytest.mark.asyncio
async def test_agent_progress_hook_drops_bare_thought_progress() -> None:
    from nanobot.agent.hook import AgentHookContext
    from nanobot.agent.progress_hook import AgentProgressHook
    from nanobot.events import EventSink
    from nanobot.providers.base import LLMResponse, ToolCallRequest

    events = []

    async def fake_publish(event):
        events.append(event)

    sink = EventSink(publish=fake_publish)
    hook = AgentProgressHook(events=sink)

    context = AgentHookContext(
        iteration=1,
        messages=[],
        response=LLMResponse(content="thought", tool_calls=[ToolCallRequest(id="1", name="read_file", arguments={"path": "test.py"})]),
        tool_calls=[ToolCallRequest(id="1", name="read_file", arguments={"path": "test.py"})],
    )

    await hook.before_execute_tools(context)

    # Should only emit the tool_hint event, NOT a separate "thought" progress event
    assert len(events) == 1
    assert events[0].tool_hint is True
    assert events[0].content != "thought"


@pytest.mark.asyncio
async def test_agent_loop_restore_turn_applies_hints_override(tmp_path) -> None:
    from types import SimpleNamespace

    from nanobot.agent.loop import AgentLoop, TurnContext
    from nanobot.bus.events import InboundMessage
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    provider = SimpleNamespace(get_default_model=lambda: "dummy-model")
    loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path)

    session = loop.sessions.get_or_create("telegram:chat_1")
    session.metadata["send_tool_hints"] = False
    loop.sessions.save(session)

    mock_delivery = MagicMock()
    mock_delivery.started = AsyncMock()
    msg = InboundMessage(channel="telegram", chat_id="chat_1", sender_id="user_1", content="hello")
    ctx = TurnContext(
        msg=msg,
        session=None,
        session_key="telegram:chat_1",
        turn_id="turn_1",
        runtime=SimpleNamespace(),
        kind=SimpleNamespace(),
        delivery=mock_delivery,
    )

    await loop._restore_turn(ctx)
    mock_delivery.apply_session_metadata.assert_called_with(session.metadata)
