"""Integration tests for /guide slash command and routing."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from nanobot.bus.events import InboundMessage
from nanobot.channels.telegram.runtime import (
    TelegramChannel,
    TelegramConfig,
    TelegramGuideBotConfig,
)
from nanobot.channels.whatsapp.runtime import WhatsAppConfig, WhatsAppRoutingConfig
from nanobot.command.builtin import (
    cmd_guide,
    register_builtin_commands,
)
from nanobot.command.router import CommandContext, CommandRouter
from nanobot.config.schema import ChannelsConfig


@pytest.mark.asyncio
async def test_cmd_guide_no_args_returns_usage() -> None:
    msg = InboundMessage(
        channel="telegram",
        sender_id="12345",
        chat_id="67890",
        content="/guide",
    )
    ctx = CommandContext(
        msg=msg,
        session=None,
        key="telegram:67890",
        raw="/guide",
        args="",
        loop=SimpleNamespace(channels_config=ChannelsConfig()),  # type: ignore[arg-type]
    )

    resp = await cmd_guide(ctx)
    assert resp is not None
    assert "Usage: /guide <prompt>" in resp.content


@pytest.mark.asyncio
async def test_cmd_guide_routes_to_custom_telegram_guide_url(monkeypatch: pytest.MonkeyPatch) -> None:
    received_requests: list[dict[str, Any]] = []

    class FakeResponse:
        def __init__(self) -> None:
            self.headers: dict[str, str] = {"content-type": "text/event-stream"}

        def raise_for_status(self) -> None:
            pass

        async def aiter_lines(self):
            yield 'data: {"choices":[{"delta":{"content":"Hello from Guide assistant node!"}}]}'
            yield "data: [DONE]"

    class FakeStreamContext:
        async def __aenter__(self) -> FakeResponse:
            return FakeResponse()

        async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
            pass

    class FakeAsyncClient:
        def __init__(self, timeout: float | None = None) -> None:
            pass

        async def __aenter__(self) -> FakeAsyncClient:
            return self

        async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
            pass

        def stream(self, method: str, url: str, json: Any = None, headers: Any = None) -> FakeStreamContext:
            received_requests.append({"method": method, "url": url, "json": json})
            return FakeStreamContext()

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    custom_url = "http://custom-guide-node:18791/v1/chat/completions"
    channels_cfg = ChannelsConfig(
        telegram=TelegramConfig(
            guide_bot=TelegramGuideBotConfig(
                enabled=True,
                guide_instance_url=custom_url,
                guide_model_name="custom-guide-model",
            )
        )
    )

    msg = InboundMessage(
        channel="telegram",
        sender_id="12345",
        chat_id="67890",
        content="/guide How do I set up?",
        metadata={"message_thread_id": 101},
    )
    ctx = CommandContext(
        msg=msg,
        session=None,
        key="telegram:67890",
        raw="/guide How do I set up?",
        args="How do I set up?",
        loop=SimpleNamespace(channels_config=channels_cfg),  # type: ignore[arg-type]
    )

    resp = await cmd_guide(ctx)
    assert resp is not None
    assert resp.content == "Hello from Guide assistant node!"
    assert resp.metadata.get("node_type") == "guide"
    assert resp.metadata.get("bot_identity") == "admin"

    assert len(received_requests) == 1
    assert received_requests[0]["url"] == custom_url
    assert received_requests[0]["json"]["model"] == "custom-guide-model"
    assert received_requests[0]["json"]["session_id"] == "telegram:guide:test:67890:topic:101"
    assert received_requests[0]["json"]["user"] == "telegram:12345"


@pytest.mark.asyncio
async def test_cmd_guide_routes_to_whatsapp_routing_url_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    received_requests: list[dict[str, Any]] = []

    class FakeResponse:
        def __init__(self) -> None:
            self.headers: dict[str, str] = {"content-type": "text/event-stream"}

        def raise_for_status(self) -> None:
            pass

        async def aiter_lines(self):
            yield 'data: {"choices":[{"delta":{"content":"WhatsApp Guide response"}}]}'
            yield "data: [DONE]"

    class FakeStreamContext:
        async def __aenter__(self) -> FakeResponse:
            return FakeResponse()

        async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
            pass

    class FakeAsyncClient:
        def __init__(self, timeout: float | None = None) -> None:
            pass

        async def __aenter__(self) -> FakeAsyncClient:
            return self

        async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
            pass

        def stream(self, method: str, url: str, json: Any = None, headers: Any = None) -> FakeStreamContext:
            received_requests.append({"method": method, "url": url, "json": json})
            return FakeStreamContext()

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    custom_url = "http://wa-guide-node:18791/v1/chat/completions"
    channels_cfg = ChannelsConfig(
        whatsapp=WhatsAppConfig(
            routing=WhatsAppRoutingConfig(
                enabled=True,
                guide_instance_url=custom_url,
            )
        )
    )

    msg = InboundMessage(
        channel="whatsapp",
        sender_id="+15550199",
        chat_id="12036304@g.us",
        content="/guide test wa",
    )
    ctx = CommandContext(
        msg=msg,
        session=None,
        key="whatsapp:12036304@g.us",
        raw="/guide test wa",
        args="test wa",
        loop=SimpleNamespace(channels_config=channels_cfg),  # type: ignore[arg-type]
    )

    resp = await cmd_guide(ctx)
    assert resp is not None
    assert resp.content == "WhatsApp Guide response"
    assert len(received_requests) == 1
    assert received_requests[0]["url"] == custom_url
    assert received_requests[0]["json"]["session_id"] == "whatsapp:guide:test:12036304@g.us"


def test_command_router_dispatch_integration() -> None:
    router = CommandRouter()
    register_builtin_commands(router)

    assert router.is_dispatchable_command("/guide")
    assert router.is_dispatchable_command("/guide How do I reset password?")
    assert router.is_dispatchable_command("/GUIDE test")


def test_telegram_bus_slash_command_regex_integration() -> None:
    pat = TelegramChannel.TELEGRAM_BUS_SLASH_COMMAND_RE
    assert pat.fullmatch("/guide")
    assert pat.fullmatch("/guide test prompt")
    assert pat.fullmatch("/guide@admin_bot test prompt")
