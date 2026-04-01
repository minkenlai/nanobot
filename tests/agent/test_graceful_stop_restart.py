import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import Address, InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.command import CommandContext
from nanobot.command.builtin import cmd_restart


@pytest.mark.asyncio
async def test_agent_loop_stop():
    """Verify that calling stop() breaks the loop."""
    bus = MessageBus()
    provider = MagicMock()
    workspace = Path("/tmp/nanobot_test")

    agent = AgentLoop(bus=bus, provider=provider, workspace=workspace)

    # Start the loop in a background task
    loop_task = asyncio.create_task(agent.run())

    # Give it a moment to start
    await asyncio.sleep(0.1)
    assert agent._running is True

    # Trigger stop
    agent.stop()

    # Wait for the loop to finish (should time out in 1s internally)
    await asyncio.wait_for(loop_task, timeout=2.0)
    assert agent._running is False


@pytest.mark.asyncio
async def test_restart_command_parsing():
    """Verify that /restart parses flags correctly without triggering on substrings."""
    mock_loop = MagicMock()
    mock_loop.workspace = Path("/tmp/nanobot_test")

    # 1. Normal restart (in-place)
    msg = InboundMessage(
        address=Address(channel="tg", segments=("123",)),
        sender_id="user123",
        content="/restart",
    )
    ctx = CommandContext(msg=msg, loop=mock_loop, raw="/restart", key="test", session=None)

    with patch("nanobot.command.builtin.asyncio.create_task"):
        resp = await cmd_restart(ctx)
        assert "in-place" in resp.content.lower()

    # 2. Full restart flag
    ctx.raw = "/restart --full"
    with patch("nanobot.command.builtin.asyncio.create_task"):
        resp = await cmd_restart(ctx)
        assert "full" in resp.content.lower()

    # 3. Short flag
    ctx.raw = "/restart -f"
    with patch("nanobot.command.builtin.asyncio.create_task"):
        resp = await cmd_restart(ctx)
        assert "full" in resp.content.lower()

    # 4. The "have-fun!" bug fix check
    ctx.raw = "/restart have-fun!"
    with patch("nanobot.command.builtin.asyncio.create_task"):
        resp = await cmd_restart(ctx)
        assert "in-place" in resp.content.lower()
        assert "full" not in resp.content.lower()
