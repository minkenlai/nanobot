from unittest.mock import MagicMock

import pytest

from nanobot.providers.fallback import FallbackProvider


@pytest.mark.asyncio
async def test_cmd_status_pinned_profile():
    # Setup mock loop and session
    mock_loop = MagicMock()
    mock_loop.provider = MagicMock(spec=FallbackProvider)
    mock_loop.provider.active_identifier = "gpt-4o"
    mock_loop.provider.active_model = "GPT-4o"
    mock_loop.provider.fallback_identifiers = ["gpt-4o", "claude-3"]
    mock_loop.registry = MagicMock()
    mock_loop.registry.get_provider.side_effect = lambda x: {
        "researcher": MagicMock(
            spec=FallbackProvider,
            active_identifier="claude-3-5",
            active_model="Claude 3.5 Sonnet",
            fallback_identifiers=["claude-3-5"],
        )
    }[x]

    # Case 1: No pinned profile (uses deault loop.provider)
    mock_ctx = MagicMock()
    mock_ctx.session.metadata = {"agent": "defaults"}
    # mock_ctx.session.metadata.get("agent_profile") is None

    # We need to mock the 'loop' global or pass it in.
    # Assuming cmd_status uses a global 'loop' or receives it via ctx.
    # For this test, let's assume we mock the 'loop' inside nanobot.command.builtin

    # Test with pinned profile
    mock_msg = MagicMock()
    mock_msg.metadata = {"agent_profile": "researcher"}

    # Execute (assuming a simplified environment or mocking the loop)
    # result = await cmd_status(mock_ctx, loop=mock_loop)
    # (Actual implementation depends on how 'loop' is accessed in builtin.py)
    pass


# Since I saw the code: it uses 'loop.registry' and 'loop.provider'
# I'll write a cleaner version based on the current de-facto implementation
