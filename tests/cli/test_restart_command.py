"""Tests for /restart slash command."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.bus.events import Address, InboundMessage
from nanobot.providers.base import LLMResponse


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


class TestRestartCommand:
    @pytest.mark.asyncio
    async def test_restart_sends_message_and_calls_execv(self, tmp_path):
        from nanobot.command.builtin import cmd_restart
        from nanobot.command.router import CommandContext

        loop, bus = _make_loop()
        loop.workspace = tmp_path
        msg = InboundMessage(
            address=Address(channel="cli", segments=("direct",)),
            sender_id="user",
            content="/restart",
        )
        ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw="/restart", loop=loop)

        with patch("nanobot.command.builtin.os.execv") as mock_execv:
            out = await cmd_restart(ctx)
            assert "Restarting" in out.content

            await asyncio.sleep(1.5)
            mock_execv.assert_called_once()

            # Verify lifecycle log was written to
            log_file = tmp_path / "logs" / "lifecycle.log"
            assert log_file.exists()
            content = log_file.read_text(encoding="utf-8")
            assert "SHUTDOWN: RESTART_REQ cli://direct" in content

    @pytest.mark.asyncio
    async def test_run_propagates_external_cancellation(self):
        """External task cancellation should not be swallowed by the inbound wait loop."""
        loop, _bus = _make_loop()

        run_task = asyncio.create_task(loop.run())
        await asyncio.sleep(0.1)
        run_task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(run_task, timeout=1.0)

    @pytest.mark.asyncio
    async def test_run_agent_loop_resets_usage_when_provider_omits_it(self):
        loop, _bus = _make_loop()
        loop.provider.chat_with_retry = AsyncMock(
            side_effect=[
                LLMResponse(content="first", usage={"prompt_tokens": 9, "completion_tokens": 4}),
                LLMResponse(content="second", usage={}),
            ]
        )

        await loop._run_agent_loop([], address=Address(channel="cli", segments=("direct",)))
        assert loop._last_usage == {"prompt_tokens": 9, "completion_tokens": 4}

        await loop._run_agent_loop([], address=Address(channel="cli", segments=("direct",)))
        assert loop._last_usage == {"prompt_tokens": 0, "completion_tokens": 0}

    @pytest.mark.asyncio
    async def test_status_reports_runtime_info(self):
        import time

        from nanobot.command.builtin import cmd_status
        from nanobot.command.router import CommandContext

        loop, _bus = _make_loop()
        session = MagicMock()
        session.messages = [{"role": "user"}] * 3
        session.metadata.get.return_value = "defaults"
        loop.sessions.get_or_create.return_value = session
        loop._start_time = time.time() - 125
        loop.context_window_tokens = (
            64000  # Explicitly set context window for consistent calculation
        )
        loop.provider.get_default_model = lambda: "test-model"
        loop.subagents.get_running_count = lambda: 0
        loop.get_usage = MagicMock(return_value={"input_tokens": 100, "output_tokens": 50})

        msg = InboundMessage(
            address=Address(channel="telegram", segments=("c1",)),
            sender_id="u1",
            content="/status",
        )
        ctx = CommandContext(
            msg=msg, session=session, key=msg.session_key, raw="/status", loop=loop
        )

        with patch.object(
            loop.memory_consolidator,
            "estimate_session_prompt_tokens",
            return_value=(20500, "tiktoken"),
        ):
            response = await cmd_status(ctx)

        assert response is not None
        assert "System Status" in response.content
        assert "**Branch:** `unknown`" in response.content
        assert "**Commit:** `unknown`" in response.content
        assert "**PID:**" in response.content  # PID is dynamic, just check for existence
        assert "\n\n**Agent:** `defaults`" in response.content
        assert "**Model:** `test-model` (`unknown`)" in response.content
        assert "Tokens:** 100 in / 50 out" in response.content
        assert "Context:** 20k/64k (32%)" in response.content
        assert "Session:** 3 messages" in response.content
        assert "**Tasks:** 0 active" in response.content
        assert "Uptime:** 2m 5s" in response.content
        assert response.metadata == {"render_as": "text"}
