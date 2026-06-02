"""Tests for /status command with pinned profiles."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from nanobot.bus.events import Address, InboundMessage
from nanobot.command.router import CommandContext


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
        patch("nanobot.agent.loop.MemoryConsolidator"),
    ):
        loop = AgentLoop(bus=bus, provider=provider, workspace=workspace)
    return loop, bus


@pytest.mark.asyncio
async def test_cmd_status_pinned_profile_context_window():
    """Verify /status resolves context_window_tokens from the pinned profile."""
    from nanobot.command.builtin import cmd_status

    loop, _bus = _make_loop()

    # Set the loop's context_window_tokens to a stale value
    # (simulating that _apply_agent_profile hasn't run yet)
    loop.context_window_tokens = 64000

    # Configure a pinned profile with a different context window
    loop.config.agents = {
        "researcher": {
            "model": "claude-sonnet-4-20250514",
            "contextWindowTokens": 131072,
        }
    }

    session = MagicMock()
    session.messages = [{"role": "user"}] * 3
    session.metadata.get.return_value = "defaults"
    loop.sessions.get_or_create.return_value = session
    loop._start_time = time.time() - 125
    loop.provider.get_default_model = lambda: "test-model"
    loop.subagents.get_running_count = lambda: 0
    loop.get_usage = MagicMock(return_value={"input_tokens": 100, "output_tokens": 50})

    msg = InboundMessage(
        address=Address(channel="telegram", segments=("c1",)),
        sender_id="u1",
        content="/status",
        metadata={"agent_profile": "researcher"},
    )
    ctx = CommandContext(msg=msg, session=session, key=msg.session_key, raw="/status", loop=loop)

    # Mock the provider returned for the pinned profile
    mock_agent_provider = MagicMock()
    mock_agent_provider.get_default_model = lambda: "claude-sonnet-4-20250514"

    with (
        patch.object(
            loop.memory_consolidator,
            "estimate_session_prompt_tokens",
            return_value=(20500, "tiktoken"),
        ),
        patch.object(loop.registry, "get_provider", return_value=mock_agent_provider),
    ):
        response = await cmd_status(ctx)

    assert response is not None
    # Should use the pinned profile's context window (131072 -> 131k), not the stale 64k
    assert "Context:** 20k/131k (15%)" in response.content


@pytest.mark.asyncio
async def test_cmd_status_no_pinned_profile_uses_loop_default():
    """When no pinned profile, /status falls back to loop.context_window_tokens."""
    from nanobot.command.builtin import cmd_status

    loop, _bus = _make_loop()
    loop.context_window_tokens = 64000
    loop.config.agents = None

    session = MagicMock()
    session.messages = [{"role": "user"}] * 3
    session.metadata.get.return_value = "defaults"
    loop.sessions.get_or_create.return_value = session
    loop._start_time = time.time() - 125
    loop.provider.get_default_model = lambda: "test-model"
    loop.subagents.get_running_count = lambda: 0
    loop.get_usage = MagicMock(return_value={"input_tokens": 100, "output_tokens": 50})

    msg = InboundMessage(
        address=Address(channel="telegram", segments=("c1",)),
        sender_id="u1",
        content="/status",
    )
    ctx = CommandContext(msg=msg, session=session, key=msg.session_key, raw="/status", loop=loop)

    with patch.object(
        loop.memory_consolidator,
        "estimate_session_prompt_tokens",
        return_value=(20500, "tiktoken"),
    ):
        response = await cmd_status(ctx)

    assert response is not None
    # Should use the loop's context_window_tokens (64000 -> 64k)
    assert "Context:** 20k/64k (32%)" in response.content


@pytest.mark.asyncio
async def test_cmd_status_pinned_profile_falls_back_to_provider_max():
    """When profile has no contextWindowTokens, fall back to provider's context_max."""
    from nanobot.command.builtin import cmd_status

    loop, _bus = _make_loop()
    loop.context_window_tokens = 64000

    # Profile without explicit contextWindowTokens
    loop.config.agents = {
        "deep": {
            "model": "claude-opus-4-20250514",
        }
    }

    # Mock registry.get_runner to return a runner with provider context_max
    mock_runner = MagicMock()
    mock_runner.provider.generation.context_max = 200000
    loop.registry.get_runner = MagicMock(return_value=mock_runner)

    session = MagicMock()
    session.messages = [{"role": "user"}] * 3
    session.metadata.get.return_value = "defaults"
    loop.sessions.get_or_create.return_value = session
    loop._start_time = time.time() - 125
    loop.provider.get_default_model = lambda: "test-model"
    loop.subagents.get_running_count = lambda: 0
    loop.get_usage = MagicMock(return_value={"input_tokens": 100, "output_tokens": 50})

    msg = InboundMessage(
        address=Address(channel="telegram", segments=("c1",)),
        sender_id="u1",
        content="/status",
        metadata={"agent_profile": "deep"},
    )
    ctx = CommandContext(msg=msg, session=session, key=msg.session_key, raw="/status", loop=loop)

    mock_agent_provider = MagicMock()
    mock_agent_provider.get_default_model = lambda: "claude-opus-4-20250514"

    with (
        patch.object(
            loop.memory_consolidator,
            "estimate_session_prompt_tokens",
            return_value=(20500, "tiktoken"),
        ),
        patch.object(loop.registry, "get_provider", return_value=mock_agent_provider),
    ):
        response = await cmd_status(ctx)

    assert response is not None
    # Should fall back to provider's context_max (200000 -> 200k)
    assert "Context:** 20k/200k (10%)" in response.content
