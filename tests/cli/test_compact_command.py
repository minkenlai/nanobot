"""Tests for /compact slash command."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.bus.events import Address, InboundMessage, OutboundMessage
from nanobot.session.manager import Session


def _make_loop():
    """Create a minimal AgentLoop with mocked dependencies."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    workspace = MagicMock()
    workspace.__truediv__ = MagicMock(return_value=MagicMock())

    with (
        patch("nanobot.agent.loop.ContextBuilder"),
        patch("nanobot.agent.loop.SessionManager"),
        patch("nanobot.agent.loop.SubagentManager"),
        patch("nanobot.agent.loop.MemoryConsolidator") as mock_consolidator,
    ):
        mock_consolidator.return_value.estimate_session_prompt_tokens.return_value = (0, "mock")
        loop = AgentLoop(bus=bus, provider=provider, workspace=workspace)
    return loop, bus


class TestCompactCommand:
    @pytest.mark.asyncio
    async def test_compact_default_keeps_5(self):
        """Default N=5 when no argument is provided."""
        from nanobot.command.builtin import cmd_compact
        from nanobot.command.router import CommandContext

        loop, _bus = _make_loop()
        session = Session(key="test-session")
        for i in range(20):
            session.add_message("user", f"msg{i}")
        session.last_consolidated = 0

        loop.sessions.get_or_create.return_value = session

        msg = InboundMessage(
            address=Address(channel="cli", segments=("direct",)),
            sender_id="user",
            content="/compact",
        )
        ctx = CommandContext(
            msg=msg, session=session, key=msg.session_key, raw="/compact", loop=loop
        )

        loop.memory_consolidator.archive_messages = AsyncMock()

        out = await cmd_compact(ctx)
        assert isinstance(out, OutboundMessage)
        assert "5" in out.content

        # Verify 15 messages were archived (20 - 5 = 15)
        loop.memory_consolidator.archive_messages.assert_called_once()
        archived = loop.memory_consolidator.archive_messages.call_args[0][0]
        assert len(archived) == 15
        assert session.last_consolidated == 15

    @pytest.mark.asyncio
    async def test_compact_positive_n(self):
        """Positive N argument keeps that many messages."""
        from nanobot.command.builtin import cmd_compact
        from nanobot.command.router import CommandContext

        loop, _bus = _make_loop()
        session = Session(key="test-session")
        for i in range(20):
            session.add_message("user", f"msg{i}")
        session.last_consolidated = 0

        loop.sessions.get_or_create.return_value = session

        msg = InboundMessage(
            address=Address(channel="cli", segments=("direct",)),
            sender_id="user",
            content="/compact 10",
        )
        ctx = CommandContext(
            msg=msg, session=session, key=msg.session_key, raw="/compact 10", loop=loop
        )

        loop.memory_consolidator.archive_messages = AsyncMock()

        out = await cmd_compact(ctx)
        assert isinstance(out, OutboundMessage)
        assert "10" in out.content

        archived = loop.memory_consolidator.archive_messages.call_args[0][0]
        assert len(archived) == 10  # 20 - 10 = 10
        assert session.last_consolidated == 10

    @pytest.mark.asyncio
    async def test_compact_negative_n_uses_absolute(self):
        """Negative N is treated as its absolute value."""
        from nanobot.command.builtin import cmd_compact
        from nanobot.command.router import CommandContext

        loop, _bus = _make_loop()
        session = Session(key="test-session")
        for i in range(20):
            session.add_message("user", f"msg{i}")
        session.last_consolidated = 0

        loop.sessions.get_or_create.return_value = session

        msg = InboundMessage(
            address=Address(channel="cli", segments=("direct",)),
            sender_id="user",
            content="/compact -10",
        )
        ctx = CommandContext(
            msg=msg, session=session, key=msg.session_key, raw="/compact -10", loop=loop
        )

        loop.memory_consolidator.archive_messages = AsyncMock()

        out = await cmd_compact(ctx)
        assert isinstance(out, OutboundMessage)
        assert "10" in out.content

        archived = loop.memory_consolidator.archive_messages.call_args[0][0]
        assert len(archived) == 10  # Same as positive 10
        assert session.last_consolidated == 10

    @pytest.mark.asyncio
    async def test_compact_nothing_to_summarize(self):
        """Returns a message when there's nothing to consolidate."""
        from nanobot.command.builtin import cmd_compact
        from nanobot.command.router import CommandContext

        loop, _bus = _make_loop()
        session = Session(key="test-session")
        for i in range(3):
            session.add_message("user", f"msg{i}")
        session.last_consolidated = 0

        loop.sessions.get_or_create.return_value = session

        msg = InboundMessage(
            address=Address(channel="cli", segments=("direct",)),
            sender_id="user",
            content="/compact 5",
        )
        ctx = CommandContext(
            msg=msg, session=session, key=msg.session_key, raw="/compact 5", loop=loop
        )

        loop.memory_consolidator.archive_messages = AsyncMock()

        out = await cmd_compact(ctx)
        assert isinstance(out, OutboundMessage)
        assert "Nothing to summarize" in out.content
        loop.memory_consolidator.archive_messages.assert_not_called()

    @pytest.mark.asyncio
    async def test_compact_invalid_n_falls_back_to_default(self):
        """Invalid N argument falls back to default of 5."""
        from nanobot.command.builtin import cmd_compact
        from nanobot.command.router import CommandContext

        loop, _bus = _make_loop()
        session = Session(key="test-session")
        for i in range(20):
            session.add_message("user", f"msg{i}")
        session.last_consolidated = 0

        loop.sessions.get_or_create.return_value = session

        msg = InboundMessage(
            address=Address(channel="cli", segments=("direct",)),
            sender_id="user",
            content="/compact abc",
        )
        ctx = CommandContext(
            msg=msg, session=session, key=msg.session_key, raw="/compact abc", loop=loop
        )

        loop.memory_consolidator.archive_messages = AsyncMock()

        out = await cmd_compact(ctx)
        assert isinstance(out, OutboundMessage)
        assert "5" in out.content

        archived = loop.memory_consolidator.archive_messages.call_args[0][0]
        assert len(archived) == 15  # 20 - 5 = 15 (default)
        assert session.last_consolidated == 15

    @pytest.mark.asyncio
    async def test_compact_respects_last_consolidated(self):
        """Only consolidates messages after last_consolidated."""
        from nanobot.command.builtin import cmd_compact
        from nanobot.command.router import CommandContext

        loop, _bus = _make_loop()
        session = Session(key="test-session")
        for i in range(20):
            session.add_message("user", f"msg{i}")
        session.last_consolidated = 10  # First 10 already consolidated

        loop.sessions.get_or_create.return_value = session

        msg = InboundMessage(
            address=Address(channel="cli", segments=("direct",)),
            sender_id="user",
            content="/compact 5",
        )
        ctx = CommandContext(
            msg=msg, session=session, key=msg.session_key, raw="/compact 5", loop=loop
        )

        loop.memory_consolidator.archive_messages = AsyncMock()

        out = await cmd_compact(ctx)
        assert isinstance(out, OutboundMessage)

        archived = loop.memory_consolidator.archive_messages.call_args[0][0]
        assert len(archived) == 5  # 20 - 5 = 15, then 15 - 10 = 5
        assert session.last_consolidated == 15
