from unittest.mock import MagicMock

from nanobot.agent.memory import MemoryConsolidator
from nanobot.providers.base import GenerationSettings


def test_memory_consolidator_respects_provider_context_max(tmp_path):
    """MemoryConsolidator should prioritize provider's context_max if available."""
    provider = MagicMock()
    provider.generation = GenerationSettings(context_max=2000000)

    mc = MemoryConsolidator(
        workspace=tmp_path,
        provider=provider,
        model="test",
        sessions=MagicMock(),
        build_messages=lambda *args, **kwargs: [],
        get_tool_definitions=lambda: [],
        context_window_tokens=100000,  # Default lower limit
    )

    assert mc.context_window_tokens == 2000000


def test_memory_consolidator_fallback_to_default_context_max(tmp_path):
    """MemoryConsolidator should fallback to default if provider context_max is None."""
    provider = MagicMock()
    provider.generation = GenerationSettings(context_max=None)

    mc = MemoryConsolidator(
        workspace=tmp_path,
        provider=provider,
        model="test",
        sessions=MagicMock(),
        build_messages=lambda *args, **kwargs: [],
        get_tool_definitions=lambda: [],
        context_window_tokens=100000,  # Default limit
    )

    assert mc.context_window_tokens == 100000
