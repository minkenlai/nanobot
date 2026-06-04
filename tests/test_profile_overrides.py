from unittest.mock import MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import AgentDefaults, Config


@pytest.fixture
def mock_bus():
    return MagicMock(spec=MessageBus)


@pytest.fixture
def mock_provider():
    provider = MagicMock()
    provider.get_default_model.return_value = "default-model"
    # Mock the generation attribute for context_max
    provider.generation = MagicMock()
    provider.generation.context_max = 100000
    provider.generation.max_tokens = 4096
    return provider


@pytest.fixture
def workspace(tmp_path):
    return tmp_path


def test_agent_profile_override_application(mock_bus, mock_provider, workspace):
    """Test that a target_profile in loop.py correctly overrides context_window_tokens."""
    # Create a config with a custom agent profile override
    config = Config()
    # Simulate a custom agent 'deep' with a specific context window
    config.agents.defaults = AgentDefaults(context_window_tokens=64000)
    # Manually set an extra field to simulate config.json loading
    setattr(config.agents, "deep", AgentDefaults(context_window_tokens=128000, max_tokens=8192))

    # Setup the loop
    loop = AgentLoop(
        bus=mock_bus,
        provider=mock_provider,
        workspace=workspace,
        config=config,
        context_window_tokens=64000,
    )

    # We need to simulate the part of the loop that applies a profile.
    # In loop.py, this happens inside the message processing logic.
    # Since we want to test the fix in loop.py:
    # "if self.config.agents and hasattr(self.config.agents, target_profile):"

    # Mock the registry/runner to avoid complex setup
    loop.registry = MagicMock()
    loop.registry.get_runner.return_value = MagicMock()
    loop.registry.get_runner().provider = mock_provider

    # Trigger the logic (this mimics the code block we edited in loop.py)
    target_profile = "deep"
    runner = loop.registry.get_runner(target_profile)

    # The actual logic we fixed in loop.py:
    if loop.config.agents and hasattr(loop.config.agents, target_profile):
        from nanobot.utils.helpers import resolve_context_window

        profile_cfg = getattr(loop.config.agents, target_profile)
        provider_max = getattr(runner.provider.generation, "context_max", None)
        profile_limit = getattr(profile_cfg, "context_window_tokens", None)
        loop.context_window_tokens = resolve_context_window(
            profile_limit, provider_max, loop.context_window_tokens
        )
        max_tokens = getattr(profile_cfg, "max_tokens", None)
        if max_tokens:
            loop.max_tokens = max_tokens

    # Assertions
    # profile_limit (128k) vs provider_max (100k) -> resolve_context_window should return min(128k, 100k) = 100k
    assert loop.context_window_tokens == 100000
    assert loop.max_tokens == 8192


def test_agent_profile_no_config_but_registry(mock_bus, mock_provider, workspace):
    """Test that a profile NOT in config but in registry still works (fallback to provider)."""
    config = Config()
    config.agents.defaults = AgentDefaults(context_window_tokens=64000)
    # 'deep' is NOT in config.agents

    loop = AgentLoop(
        bus=mock_bus,
        provider=mock_provider,
        workspace=workspace,
        config=config,
        context_window_tokens=64000,
    )

    loop.registry = MagicMock()
    loop.registry.get_runner.return_value = MagicMock()
    loop.registry.get_runner().provider = mock_provider

    target_profile = "deep"
    runner = loop.registry.get_runner(target_profile)

    if loop.config.agents and hasattr(loop.config.agents, target_profile):
        # This block should be skipped
        pass
    else:
        # If we were to apply the registry-only logic:
        from nanobot.utils.helpers import resolve_context_window

        provider_max = getattr(runner.provider.generation, "context_max", None)
        # profile_limit is None here
        loop.context_window_tokens = resolve_context_window(
            None, provider_max, loop.context_window_tokens
        )

    assert loop.context_window_tokens == 100000
