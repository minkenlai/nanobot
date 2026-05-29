from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.memory import MemoryStore


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
    result = await memory_store.consolidate(messages, mock_provider, "test-model")

    # Result should be False (it failed to consolidate)
    assert result is False
    # Memory file should NOT have been updated
    assert memory_store.read_long_term() == "Initial Fact"


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
    staging_content = memory_store.staging_file.read_text()
    assert "updated memory" in staging_content
