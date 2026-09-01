"""Tests for nanobot agent CLI model and preset options."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from nanobot.bus.events import OutboundMessage
from nanobot.cli.commands import app
from nanobot.config.schema import Config, ModelPresetConfig

runner = CliRunner()


def _fake_provider() -> MagicMock:
    provider = MagicMock()
    provider.model = "test-model"
    provider.close = AsyncMock(return_value=None)
    return provider


@pytest.fixture
def mock_agent_runtime(tmp_path):
    """Mock agent command dependencies for focused CLI tests."""
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "default-workspace")

    with (
        patch("nanobot.config.loader.load_config", return_value=config) as mock_load_config,
        patch("nanobot.config.loader.resolve_config_env_vars", side_effect=lambda c: c),
        patch("nanobot.cli.agent.sync_workspace_templates") as mock_sync_templates,
        patch("nanobot.providers.factory.make_provider", return_value=_fake_provider()),
        patch("nanobot.cli.terminal._print_agent_response") as mock_print_response,
        patch("nanobot.bus.queue.MessageBus"),
        patch("nanobot.cron.service.CronService"),
        patch("nanobot.cli.agent.AgentLoop.from_config") as mock_from_config,
    ):
        agent_loop = MagicMock()
        agent_loop.channels_config = None
        agent_loop.process_direct = AsyncMock(
            return_value=OutboundMessage(channel="cli", chat_id="direct", content="mock-response"),
        )
        agent_loop.aclose = AsyncMock(return_value=None)
        mock_from_config.return_value = agent_loop

        yield {
            "config": config,
            "load_config": mock_load_config,
            "sync_templates": mock_sync_templates,
            "from_config": mock_from_config,
            "agent_loop": agent_loop,
            "print_response": mock_print_response,
        }


def test_agent_help_shows_model_and_preset_options():
    result = runner.invoke(app, ["agent", "--help"])
    assert result.exit_code == 0
    assert "--model" in result.stdout
    assert "-M" in result.stdout
    assert "--preset" in result.stdout
    assert "-P" in result.stdout
    assert "Examples:" in result.stdout


def test_agent_overrides_model(mock_agent_runtime):
    result = runner.invoke(app, ["agent", "-m", "hello", "--model", "openai/gpt-4o"])

    assert result.exit_code == 0
    passed_config = mock_agent_runtime["from_config"].call_args.args[0]
    assert passed_config.agents.defaults.model == "openai/gpt-4o"
    assert passed_config.agents.defaults.model_preset is None


def test_agent_overrides_model_preset(mock_agent_runtime):
    config = mock_agent_runtime["config"]
    config.model_presets["fast"] = ModelPresetConfig(model="openai/gpt-4o-mini", provider="openai")

    result = runner.invoke(app, ["agent", "-m", "hello", "--preset", "fast"])

    assert result.exit_code == 0
    passed_config = mock_agent_runtime["from_config"].call_args.args[0]
    assert passed_config.agents.defaults.model_preset == "fast"


def test_agent_rejects_unknown_model_preset(mock_agent_runtime):
    result = runner.invoke(app, ["agent", "-m", "hello", "--preset", "nonexistent_preset"])

    assert result.exit_code != 0
    assert "Model preset 'nonexistent_preset' not found in configuration" in result.output
    mock_agent_runtime["from_config"].assert_not_called()
