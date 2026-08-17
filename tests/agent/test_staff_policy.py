"""Tests for StaffPolicy manager and staff access restrictions."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.agent.staff_policy import StaffPolicy
from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import Config, StaffPolicyConfig


class DummyTool(Tool):
    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"Dummy {self._name}"

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs: Any) -> Any:
        return f"executed {self._name}"


def test_staff_policy_config_schema_and_aliases() -> None:
    cfg = StaffPolicyConfig()
    assert cfg.enabled is False
    assert cfg.unrestricted_users == []
    assert cfg.allowed_commands is None
    assert cfg.disabled_commands == []
    assert cfg.allowed_tools is None
    assert "exec" in cfg.disabled_tools
    assert "write_to_file" in cfg.disabled_tools
    assert "skill-creator" in cfg.disabled_skills

    # Test JSON alias deserialization
    raw_config = {
        "staffPolicy": {
            "enabled": True,
            "unrestrictedUsers": ["telegram:12345", "+15550199"],
            "allowedCommands": ["/help", "/status", "/guide"],
            "disabledCommands": ["/exec", "/reset"],
            "allowedTools": ["web_search", "image_generation"],
            "disabledTools": ["exec"],
            "allowedSkills": ["cron"],
            "disabledSkills": ["skill-creator"],
        }
    }
    parsed = Config.model_validate(raw_config)
    sp = parsed.staff_policy
    assert sp.enabled is True
    assert sp.unrestricted_users == ["telegram:12345", "+15550199"]
    assert sp.allowed_commands == ["/help", "/status", "/guide"]
    assert sp.disabled_commands == ["/exec", "/reset"]
    assert sp.allowed_tools == ["web_search", "image_generation"]
    assert sp.disabled_tools == ["exec"]
    assert sp.allowed_skills == ["cron"]
    assert sp.disabled_skills == ["skill-creator"]


def test_staff_policy_unrestricted_users_matching() -> None:
    policy = StaffPolicy(
        enabled=True,
        unrestricted_users=["12345", "telegram:67890", "+15550199"],
    )

    # Unrestricted users (developers/admins)
    assert policy.is_unrestricted("12345", channel="telegram") is True
    assert policy.is_unrestricted("telegram:12345") is True
    assert policy.is_unrestricted("67890", channel="telegram") is True
    # WhatsApp phone number and JID matching
    assert policy.is_unrestricted("15550199", channel="whatsapp") is True
    assert policy.is_unrestricted("+15550199", channel="whatsapp") is True
    assert policy.is_unrestricted("15550199@s.whatsapp.net", channel="whatsapp") is True
    assert policy.is_unrestricted("whatsapp:15550199@s.whatsapp.net") is True

    # Non-unrestricted users (staff users)
    assert policy.is_unrestricted("99999", channel="telegram") is False
    assert policy.is_unrestricted("99999|otheruser", channel="telegram") is False
    assert policy.is_unrestricted("+19999999", channel="whatsapp") is False


def test_staff_policy_command_filtering() -> None:
    policy = StaffPolicy(
        enabled=True,
        unrestricted_users=["dev_user"],
        allowed_commands=["/help", "/status", "/guide"],
        disabled_commands=["/exec"],
    )

    # Developer gets full command access
    assert policy.is_command_allowed("dev_user", "telegram", "/exec echo 1") is True
    assert policy.is_command_allowed("dev_user", "telegram", "/anything") is True

    # Staff user is restricted to allowed_commands and blocked from disabled_commands
    assert policy.is_command_allowed("staff_user", "telegram", "/help") is True
    assert policy.is_command_allowed("staff_user", "telegram", "/guide hi") is True
    assert policy.is_command_allowed("staff_user", "telegram", "/exec echo 1") is False
    assert policy.is_command_allowed("staff_user", "telegram", "/unknown") is False


def test_staff_policy_tool_filtering() -> None:
    policy = StaffPolicy(
        enabled=True,
        unrestricted_users=["dev_user"],
        disabled_tools=["exec", "write_to_file"],
    )

    reg = ToolRegistry()
    reg.register(DummyTool("exec"))
    reg.register(DummyTool("read_file"))
    reg.register(DummyTool("write_to_file"))
    reg.register(DummyTool("web_search"))

    # Developer gets all tools
    dev_tools = policy.filter_tools("dev_user", "telegram", reg)
    assert dev_tools.has("exec")
    assert dev_tools.has("write_to_file")
    assert dev_tools.has("read_file")

    # Staff gets filtered tools
    staff_tools = policy.filter_tools("staff_user", "telegram", reg)
    assert not staff_tools.has("exec")
    assert not staff_tools.has("write_to_file")
    assert staff_tools.has("read_file")
    assert staff_tools.has("web_search")


def test_staff_policy_skill_filtering() -> None:
    policy = StaffPolicy(
        enabled=True,
        unrestricted_users=["dev_user"],
        disabled_skills=["skill-creator"],
    )

    dev_disabled = policy.filter_disabled_skills("dev_user", "telegram", base_disabled=["cron"])
    assert "cron" in dev_disabled
    assert "skill-creator" not in dev_disabled

    staff_disabled = policy.filter_disabled_skills("staff_user", "telegram", base_disabled=["cron"])
    assert "cron" in staff_disabled
    assert "skill-creator" in staff_disabled


@pytest.mark.asyncio
async def test_agent_loop_inline_command_disallow(tmp_path: Path) -> None:
    bus = MessageBus()
    provider = SimpleNamespace(get_default_model=lambda: "dummy-model")

    staff_cfg = StaffPolicyConfig(
        enabled=True,
        unrestricted_users=["dev_user"],
        allowed_commands=["/guide"],
    )

    loop = AgentLoop(
        bus=bus,
        provider=provider,  # type: ignore[arg-type]
        workspace=tmp_path,
        staff_policy=staff_cfg,
    )

    outbound_messages: list[Any] = []

    async def fake_publish(msg: Any) -> None:
        outbound_messages.append(msg)

    bus.publish_outbound = fake_publish  # type: ignore[method-assign]

    msg = InboundMessage(
        channel="telegram",
        sender_id="staff_user",
        chat_id="chat_1",
        content="/restricted_cmd hello",
    )

    await loop._dispatch_command_inline(
        msg=msg,
        key="telegram:chat_1",
        raw="/restricted_cmd hello",
        dispatch_fn=lambda ctx: None,  # type: ignore[arg-type, return-value]
    )

    assert len(outbound_messages) == 1
    assert "restricted for staff users" in outbound_messages[0].content


@pytest.mark.asyncio
async def test_agent_loop_dispatch_command_disallow(tmp_path: Path) -> None:
    from nanobot.agent.loop import TurnContext

    bus = MessageBus()
    provider = SimpleNamespace(get_default_model=lambda: "dummy-model")

    staff_cfg = StaffPolicyConfig(
        enabled=True,
        unrestricted_users=["dev_user"],
        allowed_commands=["/help", "/status", "/guide"],
    )

    loop = AgentLoop(
        bus=bus,
        provider=provider,  # type: ignore[arg-type]
        workspace=tmp_path,
        staff_policy=staff_cfg,
    )

    msg = InboundMessage(
        channel="telegram",
        sender_id="staff_user",
        chat_id="chat_1",
        content="/dream",
    )

    ctx = TurnContext(
        msg=msg,
        session=SimpleNamespace(key="telegram:chat_1", metadata={}),  # type: ignore[arg-type]
        session_key="telegram:chat_1",
        turn_id="turn_1",
        runtime=SimpleNamespace(),  # type: ignore[arg-type]
        kind=SimpleNamespace(),  # type: ignore[arg-type]
        delivery=SimpleNamespace(route=SimpleNamespace(channel="telegram")),  # type: ignore[arg-type]
    )

    res = await loop._dispatch_command(ctx)
    assert res is True
    assert ctx.outbound is not None
    assert "restricted for staff users" in ctx.outbound.content


def test_staff_policy_validation_warnings() -> None:
    policy = StaffPolicy(
        enabled=True,
        allowed_tools=["web_serach"],  # typo: web_serach
        disabled_tools=["exec_typo"],  # typo: exec_typo
        allowed_commands=["/helpp"],  # typo: /helpp
        disabled_skills=["skill_typo"],  # typo: skill_typo
    )

    known_tools = {"exec", "read_file", "web_search"}
    known_commands = {"/help", "/status", "/guide"}
    known_skills = {"cron", "github", "skill-creator"}

    warnings = policy.validate_policy(
        registered_tools=known_tools,
        registered_commands=known_commands,
        registered_skills=known_skills,
    )
    assert len(warnings) == 4
    assert any("web_serach" in w for w in warnings)
    assert any("exec_typo" in w for w in warnings)
    assert any("/helpp" in w for w in warnings)
    assert any("skill_typo" in w for w in warnings)


def test_staff_policy_non_slash_text_not_command() -> None:
    policy = StaffPolicy(
        enabled=True,
        unrestricted_users=[],
        allowed_commands=["/help", "/status"],
    )

    # Non-slash strings (heartbeat prompts, system prompts, regular messages)
    assert policy.is_command_allowed("staff_user", "telegram", "[Your heartbeat task is...]") is True
    assert policy.is_command_allowed("staff_user", "telegram", "Hello assistant") is True
    assert policy.is_command_allowed("staff_user", "telegram", "[your prompt]") is True

    # Actual slash commands
    assert policy.is_command_allowed("staff_user", "telegram", "/help") is True
    assert policy.is_command_allowed("staff_user", "telegram", "/exec") is False

