from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.memory import MemoryConsolidator, MemoryStore


@pytest.fixture
def mock_provider():
    provider = MagicMock()
    provider.chat_with_retry = AsyncMock()
    return provider


@pytest.fixture
def memory_store(tmp_path):
    return MemoryStore(tmp_path)


@pytest.mark.asyncio
async def test_memory_store_aborts_on_length_limit(memory_store, mock_provider):
    """Verify that consolidation aborts and doesn't write if finish_reason is 'length'."""
    # Setup: Existing memory
    memory_store.write_long_term("Initial Fact")

    # Mock a response that hit the token limit
    response = MagicMock()
    response.finish_reason = "length"
    response.has_tool_calls = False
    response.content = '{"history_entry": "truncated..."'  # Partial JSON
    mock_provider.chat_with_retry.return_value = response

    # Attempt consolidation
    messages = [{"role": "user", "content": "hello"}]
    result = await memory_store.consolidate(messages, mock_provider, "test-model", max_tokens=4096)

    # Result should be False (it failed to consolidate)
    assert result is False
    # Memory file should NOT have been updated
    assert memory_store.read_long_term() == "Initial Fact"


@pytest.mark.asyncio
async def test_memory_consolidator_uses_8k_budget(mock_provider, tmp_path):
    """Verify that the consolidator requests at least 8192 tokens."""
    sessions = MagicMock()

    consolidator = MemoryConsolidator(
        workspace=tmp_path,
        provider=mock_provider,
        model="test-model",
        sessions=sessions,
        context_window_tokens=32000,
        build_messages=lambda **kwargs: [],
        get_tool_definitions=lambda: [],
        max_completion_tokens=4096,  # Default is low
    )

    # Mock successful response
    response = MagicMock()
    response.finish_reason = "stop"
    response.has_tool_calls = True
    response.tool_calls = [
        MagicMock(arguments='{"history_entry": "test", "memory_update": "new fact"}')
    ]
    mock_provider.chat_with_retry.return_value = response

    await consolidator.consolidate_messages([{"role": "user", "content": "hi"}])

    # Check that max_tokens passed to provider was 8192
    _, kwargs = mock_provider.chat_with_retry.call_args
    assert kwargs["max_tokens"] == 8192


@pytest.mark.asyncio
async def test_memory_store_handles_raw_string_args(memory_store, mock_provider):
    """Verify hardening against providers that return tool args as a string instead of object."""
    response = MagicMock()
    response.finish_reason = "stop"
    response.has_tool_calls = False
    # Some providers return the JSON string directly in content when forced tool-call is used
    response.content = '{"history_entry": "grep entry", "memory_update": "updated memory"}'
    mock_provider.chat_with_retry.return_value = response

    result = await memory_store.consolidate(
        [{"role": "user", "content": "hi"}], mock_provider, "test-model"
    )

    assert result is True
    assert memory_store.read_long_term() == "updated memory"
