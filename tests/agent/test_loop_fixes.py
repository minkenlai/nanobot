from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import Address, InboundMessage
from nanobot.bus.queue import MessageBus


@pytest.mark.asyncio
async def test_system_message_progress_signature(tmp_path):
    """Test that system message progress reporting doesn't raise TypeError."""
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation.max_tokens = 100

    # Mock chat_with_retry to return a tool call
    tool_call = MagicMock()
    tool_call.name = "test_tool"
    tool_call.arguments = {}
    tool_call.id = "call_1"
    tool_call.to_openai_tool_call.return_value = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "test_tool", "arguments": "{}"},
    }

    response = MagicMock()
    response.has_tool_calls = True
    response.tool_calls = [tool_call]
    response.usage = {}
    response.content = "Thinking..."
    response.reasoning_content = None
    response.thinking_blocks = None

    # First call returns tool call, second call returns finish
    response2 = MagicMock()
    response2.has_tool_calls = False
    response2.tool_calls = []
    response2.usage = {}
    response2.content = "Done"
    response2.finish_reason = "stop"
    response2.reasoning_content = None
    response2.thinking_blocks = None

    provider.chat_with_retry = AsyncMock(side_effect=[response, response2])

    loop = AgentLoop(bus, provider, tmp_path)

    # Create a system message
    msg = InboundMessage(
        address=Address("system", ("tg://123",)),
        sender_id="subagent",
        content="Subagent finished",
        metadata={"message_id": "999"},
    )

    # This should not raise TypeError when before_execute_tools calls _bus_progress
    await loop._process_message(msg)

    # Verify that progress was published to the bus
    outbound = []
    while not bus.outbound.empty():
        outbound.append(bus.outbound.get_nowait())

    assert any(m.metadata.get("_progress") and m.metadata.get("_tool_hint") for m in outbound)


@pytest.mark.asyncio
async def test_turn_end_signaled_on_none_response(tmp_path):
    """Test that _turn_end is signaled when agent returns None (e.g. after message tool)."""
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    loop = AgentLoop(bus, provider, tmp_path)

    # Mock _process_message to return None (simulating turn handled by message tool)
    loop._process_message = AsyncMock(return_value=None)

    msg = InboundMessage(address=Address("tg", ("123",)), sender_id="user", content="hello")

    # We need to run _dispatch to hit the logic that sends _turn_end
    await loop._dispatch(msg)

    # Verify _turn_end was sent
    msg_out = bus.outbound.get_nowait()
    assert msg_out.content == ""
    assert msg_out.metadata.get("_turn_end") is True
