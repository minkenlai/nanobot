import pytest
from pydantic import ValidationError

from nanobot.config.schema import AgentDefaults, Config


def test_config_valid_minimal():
    """Test that a minimal valid config can be loaded."""
    data = {"agents": {"defaults": {"model": "gpt-4o", "workspace": "/tmp/nanobot"}}}
    cfg = Config.model_validate(data)
    assert cfg.agents.defaults.model == "gpt-4o"
    assert cfg.agents.defaults.workspace == "/tmp/nanobot"


def test_config_invalid_type():
    """Test that invalid types trigger ValidationError."""
    data = {"channels": {"send_max_retries": "not-an-int"}}
    with pytest.raises(ValidationError):
        Config.model_validate(data)


def test_config_range_validation():
    """Test that range constraints are enforced."""
    data = {
        "channels": {
            "send_max_retries": 11  # Max is 10
        }
    }
    with pytest.raises(ValidationError):
        Config.model_validate(data)


def test_agent_lazy_parsing():
    """Test that agents defined as dicts are lazily parsed into AgentDefaults."""
    data = {"agents": {"my_agent": {"model": "claude-3-sonnet", "temperature": 0.7}}}
    cfg = Config.model_validate(data)
    agent = cfg.agents.get_agent("my_agent")
    assert isinstance(agent, AgentDefaults)
    assert agent.model == "claude-3-sonnet"
    assert agent.temperature == 0.7


def test_config_env_override(monkeypatch):
    """Test that environment variables override file config."""
    # Set environment variable with prefix NANOBOT_
    # Nested: agents.defaults.model -> NANOBOT_AGENTS__DEFAULTS__MODEL
    monkeypatch.setenv("NANOBOT_AGENTS__DEFAULTS__MODEL", "env-model")

    # BaseSettings handles env vars on instantiation
    cfg_env = Config()
    assert cfg_env.agents.defaults.model == "env-model"
