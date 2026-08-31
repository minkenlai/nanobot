import time

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.channels.manager import ChannelManager
from nanobot.config.schema import ChannelsConfig, Config


class _DummyChannel(BaseChannel):
    name = "dummy"

    def __init__(self, config, bus):
        super().__init__(config, bus)
        self.sent: list[OutboundMessage] = []

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def send(self, msg: OutboundMessage) -> None:
        self.sent.append(msg)


def test_channels_config_defaults() -> None:
    cfg = ChannelsConfig()
    assert cfg.max_message_age_seconds == 300
    assert cfg.ignore_connect_backlog is True


def test_channel_manager_resolves_backlog_config() -> None:
    config = Config()
    config.channels.max_message_age_seconds = 450
    config.channels.ignore_connect_backlog = True

    bus = MessageBus()
    mgr = ChannelManager(config, bus)

    # Channel with no overrides inherits global channels config
    ch1 = mgr._build_channel("ch1", _DummyChannel, {"enabled": True})
    assert ch1.max_message_age_seconds == 450
    assert ch1.ignore_connect_backlog is True

    # Channel with snake_case override
    ch2 = mgr._build_channel(
        "ch2",
        _DummyChannel,
        {"enabled": True, "max_message_age_seconds": 60, "ignore_connect_backlog": False},
    )
    assert ch2.max_message_age_seconds == 60
    assert ch2.ignore_connect_backlog is False

    # Channel with camelCase override
    ch3 = mgr._build_channel(
        "ch3",
        _DummyChannel,
        {"enabled": True, "maxMessageAgeSeconds": 120, "ignoreConnectBacklog": False},
    )
    assert ch3.max_message_age_seconds == 120
    assert ch3.ignore_connect_backlog is False

    # Channel with None (disabled)
    ch4 = mgr._build_channel(
        "ch4",
        _DummyChannel,
        {"enabled": True, "max_message_age_seconds": None},
    )
    assert ch4.max_message_age_seconds is None


@pytest.mark.asyncio
async def test_channel_manager_start_marks_connected() -> None:
    config = Config()
    bus = MessageBus()
    mgr = ChannelManager(config, bus)

    ch = _DummyChannel({"enabled": True}, bus)
    assert ch.connected_at is None

    t0 = time.time()
    await mgr._start_channel("dummy", ch)
    assert ch.connected_at is not None
    assert ch.connected_at >= t0


@pytest.mark.asyncio
async def test_backlog_filtering_integration() -> None:
    bus = MessageBus()
    channel = _DummyChannel(
        {"allowFrom": ["*"], "max_message_age_seconds": 100, "ignore_connect_backlog": True},
        bus,
    )
    t_connect = time.time()
    channel.mark_connected(t_connect)

    # 1. Message from before connect (backlog) -> dropped
    await channel._handle_message(
        sender_id="user1",
        chat_id="chat1",
        content="backlog message",
        timestamp=t_connect - 20,
    )
    assert bus.inbound_size == 0

    # 2. Message older than 100s -> dropped
    await channel._handle_message(
        sender_id="user1",
        chat_id="chat1",
        content="outdated message",
        timestamp=time.time() - 200,
    )
    assert bus.inbound_size == 0

    # 3. Fresh message after connect -> accepted
    fresh_time = time.time()
    await channel._handle_message(
        sender_id="user1",
        chat_id="chat1",
        content="valid message",
        timestamp=fresh_time,
    )
    assert bus.inbound_size == 1
    msg = await bus.consume_inbound()
    assert msg.content == "valid message"
    assert msg.sender_id == "user1"
