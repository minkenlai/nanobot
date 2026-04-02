"""Tests for modular channel aliases in ChannelManager."""

from unittest.mock import MagicMock

import pytest

from nanobot.bus.events import Address, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.channels.manager import ChannelManager
from nanobot.config.schema import Config


class AliasChannel(BaseChannel):
    """Mock channel with aliases."""

    name = "aliased"
    display_name = "Aliased Channel"
    aliases = ["al", "shortcut"]

    def __init__(self, config, bus):
        super().__init__(config, bus)
        self.send_mock = MagicMock()

    async def start(self):
        pass

    async def stop(self):
        pass

    async def send(self, msg):
        self.send_mock(msg)


class CollisionChannel(BaseChannel):
    """Mock channel with colliding alias."""

    name = "collider"
    display_name = "Collider Channel"
    aliases = ["al"]  # Collides with AliasChannel

    async def start(self):
        pass

    async def stop(self):
        pass

    async def send(self, msg):
        pass


@pytest.fixture
def bus():
    return MessageBus()


@pytest.fixture
def config():
    cfg = Config()
    # Mock discovery to return our test classes
    return cfg


def test_alias_registration(bus, config, monkeypatch):
    """Verify aliases are correctly registered from channel classes."""
    # Mock discovery to return our test names
    monkeypatch.setattr("nanobot.channels.registry.discover_channel_names", lambda: ["aliased"])
    monkeypatch.setattr("nanobot.channels.registry.discover_plugins", lambda: {})

    # Mock loading to return our test class
    mock_load = MagicMock(return_value=AliasChannel)
    monkeypatch.setattr("nanobot.channels.registry.load_channel_class", mock_load)

    # Mock config to have the channel enabled
    config.channels.aliased = {"enabled": True}

    manager = ChannelManager(config, bus)

    # Verify aliases are registered
    assert manager._aliases["al"] == "aliased"
    assert manager._aliases["shortcut"] == "aliased"
    assert manager.get_channel("al").name == "aliased"
    assert manager.get_channel("shortcut").name == "aliased"
    assert manager.get_channel("aliased").name == "aliased"


def test_alias_collision_warning(bus, config, monkeypatch):
    """Verify alias collisions are handled with a warning."""
    import io

    from loguru import logger

    # Capture loguru output
    log_capture = io.StringIO()
    sink_id = logger.add(log_capture, format="{message}")

    try:
        # Mock discovery for colliding names
        monkeypatch.setattr(
            "nanobot.channels.registry.discover_channel_names", lambda: ["aliased", "collider"]
        )
        monkeypatch.setattr("nanobot.channels.registry.discover_plugins", lambda: {})

        # Mock loading for both
        def mock_load(name):
            return AliasChannel if name == "aliased" else CollisionChannel

        monkeypatch.setattr("nanobot.channels.registry.load_channel_class", mock_load)

        config.channels.aliased = {"enabled": True}
        config.channels.collider = {"enabled": True}

        manager = ChannelManager(config, bus)

        # Check that we handled the collision (aliased vs collider)
        # Note: the exact winner depends on iteration order of the union set,
        # but the key is that a collision is detected and warned about.
        assert "al" in manager._aliases

        # Warning should be logged
        assert "already taken by" in log_capture.getvalue()
    finally:
        logger.remove(sink_id)


@pytest.mark.asyncio
async def test_outbound_dispatch_with_alias(bus, config, monkeypatch):
    """Verify outbound messages are correctly routed via aliases."""
    monkeypatch.setattr("nanobot.channels.registry.discover_channel_names", lambda: ["aliased"])
    monkeypatch.setattr("nanobot.channels.registry.discover_plugins", lambda: {})
    monkeypatch.setattr("nanobot.channels.registry.load_channel_class", lambda _: AliasChannel)

    config.channels.aliased = {"enabled": True}

    manager = ChannelManager(config, bus)
    channel = manager.get_channel("aliased")

    # Send message using alias 'al'
    msg = OutboundMessage(address=Address(channel="al", segments=("123",)), content="test content")

    # We manually trigger the dispatch logic for testing
    channel_name = manager._aliases.get(msg.channel, msg.channel)
    target_channel = manager.get_channel(channel_name)
    await target_channel.send(msg)

    channel.send_mock.assert_called_once_with(msg)
