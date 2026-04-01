import asyncio
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock
import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.providers.base import LLMResponse


@pytest.mark.asyncio
async def test_loop_error_logging_on_exception(tmp_path: Path):
    bus = AsyncMock()
    # Create an inbound message that will throw an error when processed
    inbound = InboundMessage(channel="cli", chat_id="test", content="hello", sender_id="user")

    # Let it run once, then we stop the loop to break out
    async def mock_consume():
        loop._running = False
        return inbound

    bus.consume_inbound = mock_consume

    provider = AsyncMock()
    provider.get_default_model.return_value = "test-model"

    loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")
    # Mock connect_mcp to avoid hangs
    loop._connect_mcp = AsyncMock()

    # Mock _process_message to raise an exception
    loop._process_message = AsyncMock(side_effect=ValueError("Test exception"))

    await loop.run()
    # Wait for the dispatched task to finish
    if loop._active_tasks:
        tasks = [t for tasks_list in loop._active_tasks.values() for t in tasks_list]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # Verify OutboundMessage was sent
    bus.publish_outbound.assert_called_once()
    outbound = bus.publish_outbound.call_args[0][0]
    assert outbound.channel == "cli"
    assert outbound.chat_id == "test"
    assert "System Error" in outbound.content
    assert "ValueError: Test exception" in outbound.content

    # Verify log file was created and contains traceback
    log_file = tmp_path / "logs" / "error.log"
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "Test exception" in content
    assert "ValueError" in content


@pytest.mark.asyncio
async def test_loop_error_logging_on_llm_error(tmp_path: Path):
    bus = AsyncMock()
    inbound = InboundMessage(channel="cli", chat_id="test", content="hello", sender_id="user")

    async def mock_consume():
        loop._running = False
        return inbound

    bus.consume_inbound = mock_consume

    provider = AsyncMock()
    provider.get_default_model.return_value = "test-model"
    provider.chat_with_retry = AsyncMock(
        return_value=LLMResponse(content="Rate limit", finish_reason="error")
    )
    provider.generation.max_tokens = 4096

    loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")
    loop._connect_mcp = AsyncMock()

    await loop.run()
    if loop._active_tasks:
        tasks = [t for tasks_list in loop._active_tasks.values() for t in tasks_list]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # The provider returning finish_reason="error" should raise RuntimeError
    # which gets caught by the top level loop and triggers error log.
    assert bus.publish_outbound.call_count >= 1

    # Find the error message
    calls = bus.publish_outbound.call_args_list
    error_outbound = None
    for call in calls:
        if "System Error" in call[0][0].content:
            error_outbound = call[0][0]
            break

    assert error_outbound is not None
    assert "RuntimeError: LLM Provider Error:" in error_outbound.content

    log_file = tmp_path / "logs" / "error.log"
    assert log_file.exists()
    assert "LLM Provider Error:" in log_file.read_text(encoding="utf-8")
