"""Tests for /fallback command."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nanobot.bus.events import Address, InboundMessage
from nanobot.command.router import CommandContext


def _make_loop(provider_mock=None):
    """Create a minimal AgentLoop with mocked dependencies."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    provider = provider_mock or MagicMock()
    if isinstance(provider, MagicMock):
        provider.get_default_model.return_value = "test-model"
    workspace = MagicMock()
    workspace.__truediv__ = MagicMock(return_value=MagicMock())

    with (
        patch("nanobot.agent.loop.ContextBuilder"),
        patch("nanobot.agent.loop.SessionManager"),
        patch("nanobot.agent.loop.SubagentManager"),
        patch("nanobot.agent.loop.MemoryConsolidator"),
    ):
        loop = AgentLoop(bus=bus, provider=provider, workspace=workspace)
    return loop, bus


def _make_fallback_client(slots=None):
    """Create a FallbackClient with given slots."""
    from nanobot.providers.fallback import FallbackClient

    if slots is None:
        slots = [
            (MagicMock(), "claude-sonnet-4-20250514", "anthropic/sonnet", "UTC"),
            (MagicMock(), "gpt-4o", "openai/gpt4o", "UTC"),
            (MagicMock(), "gemini-2.0-flash", "google/flash", "UTC"),
        ]

    client = FallbackClient.__new__(FallbackClient)
    client._slots = slots
    client._active_index = 0
    client._reset_tasks = {}
    client.generation = MagicMock(max_tokens=8192, context_max=200000)
    client.get_default_model = MagicMock(return_value="test-model")
    return client


@pytest.mark.asyncio
async def test_cmd_fallback_no_args_shows_status():
    """Without argument, /fallback shows current provider chain and active slot."""
    from nanobot.command.builtin import cmd_fallback

    fallback = _make_fallback_client()
    fallback._active_index = 1
    loop, _bus = _make_loop(provider_mock=fallback)

    session = MagicMock()
    msg = InboundMessage(
        address=Address(channel="cli", segments=("user",)),
        sender_id="cli:user",
        content="/fallback",
    )
    ctx = CommandContext(
        msg=msg, session=session, key=msg.session_key, raw="/fallback", loop=loop, args=""
    )

    response = await cmd_fallback(ctx)

    assert response is not None
    assert "Provider: openai/gpt4o" in response.content
    assert "Active slot: 1" in response.content
    assert "[0] anthropic/sonnet (claude-sonnet-4-20250514)" in response.content
    assert "[1] openai/gpt4o (gpt-4o) <--" in response.content
    assert "[2] google/flash (gemini-2.0-flash)" in response.content


@pytest.mark.asyncio
async def test_cmd_fallback_set_valid_index():
    """With valid integer argument, /fallback sets the active slot."""
    from nanobot.command.builtin import cmd_fallback

    fallback = _make_fallback_client()
    fallback._active_index = 0
    loop, _bus = _make_loop(provider_mock=fallback)

    session = MagicMock()
    msg = InboundMessage(
        address=Address(channel="cli", segments=("user",)),
        sender_id="cli:user",
        content="/fallback 2",
    )
    ctx = CommandContext(
        msg=msg, session=session, key=msg.session_key, raw="/fallback 2", loop=loop, args=" 2"
    )

    response = await cmd_fallback(ctx)

    assert response is not None
    assert fallback._active_index == 2
    assert "Set provider to slot [2] google/flash (gemini-2.0-flash)" in response.content


@pytest.mark.asyncio
async def test_cmd_fallback_set_first_slot():
    """Setting to slot 0 resets to the first provider."""
    from nanobot.command.builtin import cmd_fallback

    fallback = _make_fallback_client()
    fallback._active_index = 2
    loop, _bus = _make_loop(provider_mock=fallback)

    session = MagicMock()
    msg = InboundMessage(
        address=Address(channel="cli", segments=("user",)),
        sender_id="cli:user",
        content="/fallback 0",
    )
    ctx = CommandContext(
        msg=msg, session=session, key=msg.session_key, raw="/fallback 0", loop=loop, args=" 0"
    )

    response = await cmd_fallback(ctx)

    assert response is not None
    assert fallback._active_index == 0
    assert (
        "Set provider to slot [0] anthropic/sonnet (claude-sonnet-4-20250514)" in response.content
    )


@pytest.mark.asyncio
async def test_cmd_fallback_invalid_index():
    """Out-of-range index returns an error."""
    from nanobot.command.builtin import cmd_fallback

    fallback = _make_fallback_client()
    loop, _bus = _make_loop(provider_mock=fallback)

    session = MagicMock()
    msg = InboundMessage(
        address=Address(channel="cli", segments=("user",)),
        sender_id="cli:user",
        content="/fallback 5",
    )
    ctx = CommandContext(
        msg=msg, session=session, key=msg.session_key, raw="/fallback 5", loop=loop, args=" 5"
    )

    response = await cmd_fallback(ctx)

    assert response is not None
    assert "Error: slot index must be 0-2, got 5" in response.content
    assert fallback._active_index == 0  # unchanged


@pytest.mark.asyncio
async def test_cmd_fallback_negative_index():
    """Negative index returns an error."""
    from nanobot.command.builtin import cmd_fallback

    fallback = _make_fallback_client()
    loop, _bus = _make_loop(provider_mock=fallback)

    session = MagicMock()
    msg = InboundMessage(
        address=Address(channel="cli", segments=("user",)),
        sender_id="cli:user",
        content="/fallback -1",
    )
    ctx = CommandContext(
        msg=msg, session=session, key=msg.session_key, raw="/fallback -1", loop=loop, args=" -1"
    )

    response = await cmd_fallback(ctx)

    assert response is not None
    assert "Error: slot index must be 0-2, got -1" in response.content
    assert fallback._active_index == 0  # unchanged


@pytest.mark.asyncio
async def test_cmd_fallback_non_integer_arg():
    """Non-integer argument returns an error."""
    from nanobot.command.builtin import cmd_fallback

    fallback = _make_fallback_client()
    loop, _bus = _make_loop(provider_mock=fallback)

    session = MagicMock()
    msg = InboundMessage(
        address=Address(channel="cli", segments=("user",)),
        sender_id="cli:user",
        content="/fallback abc",
    )
    ctx = CommandContext(
        msg=msg, session=session, key=msg.session_key, raw="/fallback abc", loop=loop, args=" abc"
    )

    response = await cmd_fallback(ctx)

    assert response is not None
    assert "Error: expected integer, got 'abc'" in response.content
    assert fallback._active_index == 0  # unchanged


@pytest.mark.asyncio
async def test_cmd_fallback_not_fallback_client():
    """When provider is not a FallbackClient, returns an error."""
    from nanobot.command.builtin import cmd_fallback

    plain_provider = MagicMock()
    loop, _bus = _make_loop(provider_mock=plain_provider)

    session = MagicMock()
    msg = InboundMessage(
        address=Address(channel="cli", segments=("user",)),
        sender_id="cli:user",
        content="/fallback",
    )
    ctx = CommandContext(
        msg=msg, session=session, key=msg.session_key, raw="/fallback", loop=loop, args=""
    )

    response = await cmd_fallback(ctx)

    assert response is not None
    assert "Current provider is not a FallbackClient" in response.content


@pytest.mark.asyncio
async def test_cmd_fallback_no_loop():
    """When loop is None, returns an error."""
    from nanobot.command.builtin import cmd_fallback

    session = MagicMock()
    msg = InboundMessage(
        address=Address(channel="cli", segments=("user",)),
        sender_id="cli:user",
        content="/fallback",
    )
    ctx = CommandContext(
        msg=msg, session=session, key=msg.session_key, raw="/fallback", loop=None, args=""
    )

    response = await cmd_fallback(ctx)

    assert response is not None
    assert "Error: agent loop not available" in response.content


@pytest.mark.asyncio
async def test_cmd_fallback_pinned_profile_uses_registry():
    """With a pinned agent profile, /fallback targets the registry provider."""
    from nanobot.command.builtin import cmd_fallback

    loop_provider = _make_fallback_client()
    loop_provider._active_index = 0
    loop, _bus = _make_loop(provider_mock=loop_provider)

    registry_provider = _make_fallback_client()
    registry_provider._active_index = 2

    session = MagicMock()
    msg = InboundMessage(
        address=Address(channel="telegram", segments=("c1", "t1")),
        sender_id="tg:12345",
        content="/fallback",
        metadata={"agent_profile": "researcher"},
    )
    ctx = CommandContext(
        msg=msg, session=session, key=msg.session_key, raw="/fallback", loop=loop, args=""
    )

    with patch.object(loop.registry, "get_provider", return_value=registry_provider):
        response = await cmd_fallback(ctx)

    assert response is not None
    # Should show the registry provider's state (active_index=2), not loop's (active_index=0)
    assert "Provider: google/flash" in response.content
    assert "Active slot: 2" in response.content


@pytest.mark.asyncio
async def test_cmd_fallback_pinned_profile_sets_registry():
    """With a pinned profile, setting index only affects the registry provider."""
    from nanobot.command.builtin import cmd_fallback

    loop_provider = _make_fallback_client()
    loop_provider._active_index = 0
    loop, _bus = _make_loop(provider_mock=loop_provider)

    registry_provider = _make_fallback_client()
    registry_provider._active_index = 2

    session = MagicMock()
    msg = InboundMessage(
        address=Address(channel="telegram", segments=("c1", "t1")),
        sender_id="tg:12345",
        content="/fallback 1",
        metadata={"agent_profile": "researcher"},
    )
    ctx = CommandContext(
        msg=msg, session=session, key=msg.session_key, raw="/fallback 1", loop=loop, args=" 1"
    )

    with patch.object(loop.registry, "get_provider", return_value=registry_provider):
        response = await cmd_fallback(ctx)

    assert response is not None
    assert registry_provider._active_index == 1
    assert loop_provider._active_index == 0  # unchanged
    assert "Set provider to slot [1] openai/gpt4o (gpt-4o)" in response.content
